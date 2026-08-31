"""`lnpl migrate` — issue #147, expand-contract's "migrate" step.

Backfills ONE field on every row of one declared entity that is currently
missing it (expand semantics: an existing value is never overwritten), then
re-stamps `_schema_gen` (interp.py's write-side schema-generation stamp,
issue #147 D2) on every row it actually changes. Never touches
`lnpl_rows`/`lnpl_outbox` DDL — `_schema_gen`, like the backfilled field
itself, lives inside the payload.

See docs/migration.md for the expand/migrate/contract procedure this
command is one step of.
"""

from .drivers import DriverError
from .interp import (RunError, SCHEMA_GEN_KEY, check_semantic_type,
                     refinement_index, schema_generation)
from .repo_policy import row_key


class MigrateError(Exception):
    """A migrate request refused before writing anything — an undeclared
    entity, an undeclared or `derived` field, or a `--set` value that fails
    its field's declared type (RFC-0001) — this repo's "does not guess,
    refuses" rule (issue #147 D5). Also raised, after a `rollback()`, for a
    `DriverError` the store itself reports mid-batch.
    """


def _qualified_name(node):
    """`billing.Order` when the node carries a namespace, else `Order`.

    Same spelling `openapi._schema_name` puts in `components/schemas`, so the
    name a user reads out of a generated spec is the name `--entity` accepts.
    """
    return ("%s.%s" % (node["namespace"], node["name"])
            if node.get("namespace") else node["name"])


def _resolve_entity(doc, name):
    """Find the entity `--entity` names, or refuse if the name is ambiguous.

    RFC-0033 makes "same short name, different namespace" a legal *non*-
    collision, and `lnpl migrate` takes a directory, so a bare `Order` can
    name two different entities at once (`billing.Order`, `shipping.Order`).
    Matching on `node["name"]` alone and returning the first hit silently
    backfilled whichever happened to be declared first — a write to the wrong
    entity's rows, with no error and no log line, and the second entity was
    not reachable under any spelling.

    So accept the qualified name too, and when a bare name matches more than
    one entity, refuse and list the candidates rather than pick one: issue
    #147 D5's "does not guess, refuses" rule, the same rule `MigrateError`
    above already states. A bare name that matches exactly one entity still
    resolves — an unqualified single-namespace or pre-RFC-0033 layout behaves
    exactly as before.

    Returns `None` when nothing matches; the caller reports that as an
    undeclared entity.
    """
    entities = [n for n in doc.get("nodes", []) if n["kind"] == "Entity"]
    exact = [n for n in entities if _qualified_name(n) == name]
    if len(exact) > 1:
        # `namespace + "." + name` is a plain concatenation, and nothing in the
        # parser constrains either half against a literal dot, so two distinct
        # entities can share one qualified spelling (namespace `a.b` + `C`, and
        # namespace `a` + `b.C`). They have distinct ids, so the compiler is
        # right not to reject them -- but no `--entity` string can tell them
        # apart, and picking one would be the same silent wrong-entity write
        # this function exists to prevent. Refuse and name the ids.
        raise MigrateError(
            "entity name %r is ambiguous — %s share that qualified name; "
            "rename one so it can be addressed" % (name, ", ".join(sorted(
                n["id"] for n in exact))))
    if exact:
        return exact[0]
    bare = [n for n in entities if n["name"] == name]
    if len(bare) > 1:
        raise MigrateError(
            "entity name %r is ambiguous across namespaces (%s) — name one "
            "of them exactly" % (name, ", ".join(sorted(
                _qualified_name(n) for n in bare))))
    return bare[0] if bare else None


def _resolve_field(entity_node, name):
    for field in entity_node.get("fields", []):
        if field["name"] == name and not field.get("derived"):
            return field
    return None


def _resolve_base(type_name, refinements):
    refinement = refinements.get(type_name)
    return refinement["base"] if refinement is not None else type_name


def _coerce(field, raw, refinements):
    """`raw` (a `--set NAME=VALUE` string) -> a value of `field`'s declared
    type, or `MigrateError` (issue #147 D5). Parsing is by the field's base
    (`Boolean` -> true/false, `Integer` -> int, everything else stays a
    string — composite types have no Phase 1 rule to parse against either,
    `types.py`'s own docstring), then `check_semantic_type` applies the full
    declared type's rule, refinement facets included.
    """
    base = _resolve_base(field["type"], refinements)
    if base == "Boolean":
        lowered = raw.strip().lower()
        if lowered not in ("true", "false"):
            raise MigrateError(
                "--set %s: %r is not a valid Boolean (use true/false)"
                % (field["name"], raw))
        value = lowered == "true"
    elif base == "Integer":
        try:
            value = int(raw)
        except ValueError:
            raise MigrateError(
                "--set %s: %r is not a valid Integer" % (field["name"], raw))
    else:
        value = raw
    try:
        check_semantic_type(field["type"], value, field["name"], refinements)
    except RunError as exc:
        raise MigrateError("--set %s: %s" % (field["name"], exc)) from exc
    return value


def run_migration(doc, repository, entity_name, field_name, raw_value, dry_run=False):
    """Backfill `field_name` = `raw_value` onto every row of `entity_name`
    that lacks it. Returns `{"scanned", "updated", "skipped"}` — `scanned`
    is every row of the entity, `updated` the ones missing the field
    (written, unless `dry_run`), `skipped` the ones that already had it
    (expand semantics: never overwritten) or that a concurrent writer
    claimed first. Every write in one transaction (issue #147 D4); a
    `DriverError` mid-batch rolls the whole batch back.

    Review r1 F1: the initial `query()` scan below is a snapshot, taken
    before any transaction opens — a live server (docs/migration.md's
    expand step runs while old and new code both serve traffic) can write
    to a scanned row before this function gets to it. Persisting a
    `dict(scanned_row)` copy would silently discard that write. Instead,
    each candidate is re-read one at a time with `execute(..., "read", ...)`
    — the same call `Interpreter`'s own `read`/`set` path uses — immediately
    before its own `persist()`, inside the single migrate transaction. That
    re-read returns a `_VersionedRow`, and it is mutated IN PLACE (never
    `dict(current)`, which would build a plain dict and silently drop
    `observed_version` — the exact `_VersionedRow`-copy mistake this same
    issue's write-side stamp injection made and fixed in `interp.py`, caught
    here on a second re-audit, not by inspection). Only because
    `observed_version` survives does `persist()`'s existing optimistic lock
    (issue #92) actually engage for this write: a fresh concurrent write
    that landed before this re-read survives (the write below applies ON
    TOP of it, since `current` IS that fresh row); one landing in the
    microscopic gap between this re-read and this persist instead makes the
    conditional UPDATE affect zero rows, so `persist()` raises
    `DriverError` — failing the whole batch loudly rather than losing data
    quietly.
    """
    entity_node = _resolve_entity(doc, entity_name)
    if entity_node is None:
        raise MigrateError("no declared entity named %r" % entity_name)
    field = _resolve_field(entity_node, field_name)
    if field is None:
        raise MigrateError(
            "entity %r has no settable field named %r"
            % (entity_name, field_name))
    refinements = refinement_index(doc)
    value = _coerce(field, raw_value, refinements)
    entity_id = entity_node["id"]
    try:
        rows = repository.query(entity_id)
    except DriverError as exc:
        raise MigrateError(str(exc)) from exc
    scanned = len(rows)
    candidates = [row for row in rows if field_name not in row]
    skipped = scanned - len(candidates)
    if dry_run or not candidates:
        return {"scanned": scanned, "updated": len(candidates), "skipped": skipped}
    repository.begin()
    updated = 0
    try:
        for row in candidates:
            key = row_key(entity_id, row)
            current = repository.execute(entity_id, "read", key)
            if current is None or field_name in current:
                # Raced since the scan: deleted, or another writer already
                # set this field first (expand semantics: still never
                # overwritten).
                skipped += 1
                continue
            current[field_name] = value
            current[SCHEMA_GEN_KEY] = schema_generation(entity_node)
            repository.persist(entity_id, key, current)
            updated += 1
    except DriverError as exc:
        repository.rollback()
        raise MigrateError(str(exc)) from exc
    repository.commit()
    return {"scanned": scanned, "updated": updated, "skipped": skipped}
