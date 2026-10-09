"""The repository seed/key policy — one rule, read by both execution modes.

Issue #35: a workflow that reads one entity and creates another could not
succeed under any seed. `cli` seeded EVERY declared entity, so the create always
hit an "already exists" conflict; with an empty repository the read found nothing
instead. Two failures, no seed in between.

Two rules fix that, and both live here so mode A (interp.py) and mode B
(backend.py, Wave 2) compute them from the same input rather than one copying the
other's answer — the arrangement `differential.py::_derive_skip_from_payload`
already uses for the Presence-guard skip flag (issue #12).

  SEED RULE — role-based, and ORDER-AWARE within the role. The default seed
  populates exactly the entities the workflow READS first (`read`; `query` is
  narrowed out, see `seeded_entities`). An entity it only creates starts empty,
  so the create inserts instead of conflicting — and so does an entity created
  BEFORE its first read (issue #174): it is excluded even though a later call
  reads it, because the create's own insert is what that later read then finds.
  Reachability is structural: a RepositoryCall nested under a Guard counts,
  because a guard's truth depends on the payload and mode B derives its outcome
  statically (RFC-0004 §Execution modes, the four observables).

  KEY RULE — a row lives under "<entity_id>#<payload id or '-'>". The identity
  field is the key, never a hash of the whole payload: two legitimately identical
  creates must stay two creates. This mirrors the CacheAccess key that
  interp.py already derives as `payload.get("id", "-")`.

Why the key is scoped by entity: `interp.sample_payload` synthesises a FLAT dict
merging every field of every entity, so with two entities that both declare `id`
a single value serves both. Scoping is what keeps their rows apart.

The single-key invariant this produces: one run has one payload, so every call
against entity E addresses the same key, and each entity's table holds at most
one row. That is what lets mode B answer "does this create conflict?" from the
document alone — E conflicts iff it is seeded, or an earlier call in
`repository_calls` already created it. No interpreter state, no runtime channel.

RFC-0052 (issue #175) relaxes this per entity: a `by <ref>` read/update/delete
addresses the ref's value instead, and mode B refuses any workflow that uses one.

Imports nothing from `interp`, `backend`, or `cli`: mode B imports this module,
and a cycle would break the build.
"""
from .lexer import PAYLOAD_NAMESPACE

READ_OPS = ("read", "query")


def binding_name(entity_node):
    """The name a read entity is bound under in the execution scope (RFC-0012 §G12.2).

    The declared name, camelCased: `Product` -> `product`, `OrderItem` ->
    `orderItem`. Derived from `name`, never from the node id: `derive_segments`
    splits a multi-word declaration into dotted id segments (`entity.order.item`),
    and a dotted string is not the single `CamelName` the grammar's binding
    position accepts.

    Lives here rather than in `interp` because both execution modes need it —
    mode A to bind at run time, mode B's host to project the same names from the
    seed rule — and this module is the one both already read.
    """
    name = entity_node.get("name") or ""
    return name[:1].lower() + name[1:]


def repository_calls(document, workflow_id):
    """Every RepositoryCall reachable from `workflow_id`, in declared order.

    Returns a list of (entity_id, operation). Guard/Concurrency/Pipeline children
    are walked unconditionally — this reports what the workflow *can* touch, which
    is a property of the document, not of any one payload.
    """
    nodes = {n["id"]: n for n in document["nodes"]}
    workflow = nodes.get(workflow_id)
    if workflow is None or workflow["kind"] != "Workflow":
        # A dangling workflow id is the caller's to report (the CLI already does);
        # answering "no calls" keeps this a total function over the document.
        return []

    calls = []

    def walk(ids):
        for node_id in ids:
            node = nodes.get(node_id)
            if node is None:
                continue
            if node["kind"] == "WorkflowStep":
                for child_id in node.get("children", []):
                    child = nodes.get(child_id)
                    if child is not None and child["kind"] == "RepositoryCall":
                        calls.append((child["entity"], child["operation"]))
            else:
                # Guard, Concurrency, Pipeline — containers that hold steps.
                walk(node.get("children", []))

    walk(workflow.get("children", []))
    return calls


def lookup_key_source(document, workflow_id, entity_id):
    """issue #175 / RFC-0052 §4: the `lookup` ref of `entity_id`'s FIRST
    `read` reachable from `workflow_id`, in declared order, or `None` (no
    `by` on that read, or the entity is never read).

    Same reachability walk as `repository_calls`, kept separate so that
    function's `(entity_id, operation)` shape — and its five callers — stay
    unchanged for a value only the seed rule needs.
    """
    nodes = {n["id"]: n for n in document["nodes"]}
    workflow = nodes.get(workflow_id)
    if workflow is None or workflow["kind"] != "Workflow":
        return None

    def first_read(ids):
        for node_id in ids:
            node = nodes.get(node_id)
            if node is None:
                continue
            if node["kind"] == "WorkflowStep":
                for child_id in node.get("children", []):
                    child = nodes.get(child_id)
                    if (child is not None and child["kind"] == "RepositoryCall"
                            and child["entity"] == entity_id
                            and child["operation"] == "read"):
                        return child
            else:
                found = first_read(node.get("children", []))
                if found is not None:
                    return found
        return None

    read = first_read(workflow.get("children", []))
    return read.get("lookup") if read is not None else None


def event_emissions(document, workflow_id):
    """Every event id an `emit`/`publish` step inside `workflow_id` names, in
    declared order (issue #103). Same reachability walk `repository_calls`
    already runs for `RepositoryCall` — an `EventEmit` sits under a
    `WorkflowStep` the exact same way, so `serve.build_routes` can derive
    "which service owns this event" from what a service's workflows actually
    emit, the same structural-not-declared rule D1 in `build_routes`'s own
    docstring already uses for get-single entity ownership.
    """
    nodes = {n["id"]: n for n in document["nodes"]}
    workflow = nodes.get(workflow_id)
    if workflow is None or workflow["kind"] != "Workflow":
        return []

    events = []

    def walk(ids):
        for node_id in ids:
            node = nodes.get(node_id)
            if node is None:
                continue
            if node["kind"] == "WorkflowStep":
                for child_id in node.get("children", []):
                    child = nodes.get(child_id)
                    if child is not None and child["kind"] == "EventEmit":
                        events.append(child["event"])
            else:
                walk(node.get("children", []))

    walk(workflow.get("children", []))
    return events


def seeded_entities(document, workflow_id):
    """The entity ids the default seed populates — those the workflow `read`s
    BEFORE it creates them.

    Order-aware (issue #174): an entity's FIRST `read` or `create` call, in
    document order, decides its seed membership. First-`read` seeds (a later
    `create` against it is then the reachable conflict `TestReadThenCreate`
    pins); first-`create` does NOT seed, even when the same entity is read
    later in the same workflow — seeding it would make that create collide
    with a row the workflow itself was about to insert, and the create's own
    insert is what the later read finds instead. `query` never counts as
    either kind of first operation, so it neither seeds nor suppresses.

    `operation == "read"` only, not `READ_OPS` (`read`+`query`) — narrowed by
    RFC-0025 §5. The original reason `query` was ever in this set was to keep
    the SAME single-row invariant `read` needs (so a later read finds
    something rather than failing "no row for entity"); `list`(`query`) has
    no analogous failure to avoid — an empty RowSet is a normal 0-row result,
    not an error (RFC-0025 §5) — so auto-seeding it produces exactly the
    wrong default: a single field-less row (a copy of the payload, missing
    whatever field an aggregate sums) where the correct default is nothing.
    """
    first_op = {}
    for entity_id, operation in repository_calls(document, workflow_id):
        if operation in ("read", "create"):
            first_op.setdefault(entity_id, operation)
    return {entity_id for entity_id, operation in first_op.items()
            if operation == "read"}


def row_key(entity_id, payload):
    """The deterministic key a row lives under, scoped to the entity.

    Same (entity_id, payload) always yields the same key. A payload with no `id`
    falls back to the "-" sentinel, exactly as the CacheAccess key does.
    """
    return "%s#%s" % (entity_id, payload.get("id", "-"))


def default_rows(document, workflow_id, payload):
    """The seeded store: {entity_id: {row_key: row}} for each read entity.

    The row is a copy of the payload — the caller's dict must not become shared
    mutable state once `create` starts writing into these tables.

    issue #175 / RFC-0052 §4: when an entity's first read is
    `by input.<field>`, its row lives under that field's value instead of the
    payload `id` — the key that read will address. Every other lookup (bare,
    `caller.*`, a bound or network-result ref) is not payload-derivable here
    and keeps the payload-id key. A payload without that field seeds no row
    for the entity at all.
    """
    rows = {}
    for entity_id in seeded_entities(document, workflow_id):
        source = lookup_key_source(document, workflow_id, entity_id)
        if source is not None and source.startswith(PAYLOAD_NAMESPACE + "."):
            value = payload.get(source.partition(".")[2])
            if value is None:
                # No value, no key: the read fails with its named RunError
                # anyway, and an `entity#None` row would outlive that failed
                # run in a persistent store — so seed nothing for it.
                continue
            key = row_key(entity_id, {"id": value})
        else:
            key = row_key(entity_id, payload)
        rows[entity_id] = {key: dict(payload)}
    return rows


def seed_bindings(document, workflow_id, payload, seeded=None):
    """The execution scope the seed rule implies (RFC-0012 §G12.6).

    Mode A builds its scope by binding what each read actually returned. Mode B's
    module models no repository state, so its host has to answer the same question
    from the document: under the SEED RULE above, a seeded entity's row is a copy
    of the payload, so reading it binds a row equal to the payload.

    `seeded` is the run's seed condition — `None` for the default role-based
    policy, `frozenset()` for `--no-row`. With no seed nothing binds, which is
    also what mode A observes: the read finds no row and the step fails before any
    guard is reached.

    This is a projection of the same rule `default_rows` materialises, not a
    reading of mode A's store — keeping mode B independent of how `FakeRepository`
    happens to lay rows out, exactly as `seeded` itself does.
    """
    entities = (seeded_entities(document, workflow_id) if seeded is None
                else set(seeded))
    nodes = {n["id"]: n for n in document["nodes"]}
    scope = {}
    for entity_id in entities:
        node = nodes.get(entity_id)
        if node is not None:
            scope[binding_name(node)] = dict(payload)
    return scope


# issue #116, D4/D5: comparator symbol -> a pure two-argument test. Shared
# by `apply_predicate` below, so a term's `op` is judged the same way
# wherever a driver does not push the predicate down to its own store.
_PREDICATE_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


def _row_matches(row, predicate):
    """One row against every conjunction term (issue #116, D4) — `None` on
    either side never matches, the same "unresolved -> false" rule a guard
    comparison already applies (`interp._comparison_holds`), so a `list
    where` referencing an unset `input.<field>` yields an empty RowSet
    rather than raising.
    """
    for field, op, value in predicate:
        actual = row.get(field)
        if actual is None or value is None:
            return False
        if not _PREDICATE_OPS[op](actual, value):
            return False
    return True


def apply_predicate(rows, predicate=None, order=None, limit=None):
    """Filter/sort/limit an already row_key-ordered row list in Python
    (issue #116, D5/D6) — the ONE place this semantics is written, shared by
    `interp.FakeRepository.query`'s native implementation and
    `interp.Interpreter`'s fallback for a driver that does not declare
    `supports_predicate` (over-fetch, then filter here), so the two paths
    can never silently disagree on what a predicate/order/limit means.

    `rows` must already be in row_key-ascending order (every `RepositoryDriver.
    query` caller's contract) — `sorted()` below is stable, so that order
    survives as the tiebreak for equal `order` values regardless of `desc`
    (Python's documented stable-sort guarantee: `reverse=True` does not
    reverse ties).
    """
    if predicate:
        rows = [row for row in rows if _row_matches(row, predicate)]
    if order is not None:
        field, desc = order
        # RFC-0053 §9: a row lacking the field (or holding null) sorts last,
        # ascending and descending alike, keeping row_key order among them.
        present = [r for r in rows if r.get(field) is not None]
        missing = [r for r in rows if r.get(field) is None]
        present = sorted(present, key=lambda row: row.get(field), reverse=desc)
        rows = present + missing
    if limit is not None:
        rows = rows[:limit]
    return rows
