"""The repository seed/key policy — one rule, read by both execution modes.

Issue #35: a workflow that reads one entity and creates another could not
succeed under any seed. `cli` seeded EVERY declared entity, so the create always
hit an "already exists" conflict; with an empty repository the read found nothing
instead. Two failures, no seed in between.

Two rules fix that, and both live here so mode A (interp.py) and mode B
(backend.py, Wave 2) compute them from the same input rather than one copying the
other's answer — the arrangement `differential.py::_derive_skip_from_payload`
already uses for the Presence-guard skip flag (issue #12).

  SEED RULE — role-based. The default seed populates exactly the entities the
  workflow READS (`read`/`query`). An entity it only creates starts empty, so the
  create inserts instead of conflicting. Reachability is structural: a
  RepositoryCall nested under a Guard counts, because a guard's truth depends on
  the payload and mode B derives its outcome statically (RFC-0004 §Execution
  modes, the four observables).

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

Imports nothing from `interp`, `backend`, or `cli`: mode B imports this module,
and a cycle would break the build.
"""

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


def seeded_entities(document, workflow_id):
    """The entity ids the default seed populates — those the workflow reads."""
    return {entity_id for entity_id, operation in repository_calls(document, workflow_id)
            if operation in READ_OPS}


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
    """
    return {entity_id: {row_key(entity_id, payload): dict(payload)}
            for entity_id in seeded_entities(document, workflow_id)}


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
