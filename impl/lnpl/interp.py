"""IR interpreter — execution mode A (RFC-0004 §Execution modes, plan.md D14).

Purpose is clarity, not speed: this is the executable form of the specification
(the WebAssembly reference-interpreter convention). It executes a Semantic IR
document against in-memory fake capabilities and emits the observable signals
RFC-0003 requires — a span per step, a correlation id, per-step duration, and
Password masking.

What is enforced here (RFC-0003 §Policy Enforcement):
  timeout  — a workflow deadline; steps consume it, exceeding it fails the run
  retry    — re-runs a failed step, only when its effects are idempotent
  cache    — the CacheAccess TTL budget; a hit skips the origin read
  response — an SLO, measured and reported, never enforced
  rollback — compensation at Transaction boundaries (no Transaction in Phase 1)
"""

from .condition import PAYLOAD_NAMESPACE
from .diagnostics import Diagnostics
from .drivers import DriverError
from .refinements import BASE_CATEGORY
from .repo_policy import binding_name, row_key
from .types import SEMANTIC_TYPES

IDEMPOTENT_OPS = {
    ("RepositoryCall", "read"), ("RepositoryCall", "query"),
    ("RepositoryCall", "delete"), ("RepositoryCall", "update"),
    ("CacheAccess", "get"), ("CacheAccess", "set"), ("CacheAccess", "invalidate"),
}

# The absolute bound on how many times one step may run, initial attempt included
# (RFC-0003 §Policy Enforcement). 100 is 20x the largest `retry` declared anywhere
# in this repo (5) and far above the 2-3 attempts a real retry budget uses, so no
# valid configuration reaches it — but it is finite, which is the point.
MAX_STEP_ATTEMPTS = 100

MASKED_TYPES = ("Password",)
MASK = "***"


class RunError(Exception):
    """Raised when execution violates a runtime contract."""


class Clock:
    """Injected monotonic clock in milliseconds — deterministic in tests."""

    def __init__(self, step_cost_ms=5):
        self.now = 0
        self.step_cost_ms = step_cost_ms

    def advance(self, ms=None):
        self.now += self.step_cost_ms if ms is None else ms
        return self.now


class FakeRepository:
    """Stands in for a `postgres` capability: one keyed table per entity."""

    def __init__(self, rows=None):
        # {entity_id: {row_key: row}} — copied per instance because `create` now
        # writes into the table, and aliasing the caller's seed dict would carry
        # one run's writes into the next (issue #35).
        #
        # The copy goes one level deeper than issue #35 needed: RFC-0015's `set`
        # writes INTO a row, and a read binds the stored dict itself, so with a
        # shallow copy the caller's seed row would be the object the assignment
        # mutates. Two runs over one seed would then see each other's deduction.
        self.rows = {entity_id: {key: dict(row) if isinstance(row, dict) else row
                                 for key, row in table.items()}
                     for entity_id, table in (rows or {}).items()}
        self.calls = []

    def execute(self, entity_id, operation, key):
        self.calls.append((entity_id, operation))
        table = self.rows.setdefault(entity_id, {})
        if operation in ("read", "query"):
            return table.get(key)
        if operation == "create":
            if key in table:
                # A duplicate create conflicts. This matters beyond realism: without a
                # non-idempotent operation that can fail, the rule "do not retry a
                # non-idempotent effect" cannot be tested at all. The conflict is per
                # (entity, key), not per entity: that is what lets a workflow read one
                # entity and create another (issue #35) while creating the same key
                # twice still fails, keeping the retry rule testable.
                raise RunError("repository create conflicts: %s already exists" % entity_id)
            table[key] = {"id": key}
        return {"affected": 1}

    def query(self, entity_id):
        """Every row for `entity_id`, row_key ascending — never `None`, empty
        list when the table has none (RFC-0025 §5: an empty RowSet, not an
        absent one). Sorted rather than `dict.values()`: insertion order and
        row_key order can differ, and `SqliteRepositoryDriver.query` orders by
        `ORDER BY row_key`, so this has to sort the same way to agree with it
        (RFC-0025 §7 — the contract suite's reverse-insertion-order case is
        what a plain `dict.values()` here would fail).
        """
        table = self.rows.get(entity_id, {})
        return [row for _key, row in sorted(table.items())]

    # -- RepositoryDriver contract (drivers.py) ----------------------------
    # This class is the contract's reference implementation, so the three
    # methods below exist to make that explicit rather than to add behaviour:
    # seeding is what the constructor already does, and the other two are
    # genuinely nothing here. A real driver has to work for its answers.

    def seed(self, rows):
        """Insert only where absent — the constructor's job, done later.

        `setdefault` at both levels is what makes a re-seed non-destructive:
        a row an earlier run wrote stays as it was found, which is the property
        that lets one seed rule serve a store that persists.
        """
        for entity_id, table in (rows or {}).items():
            target = self.rows.setdefault(entity_id, {})
            for key, row in table.items():
                target.setdefault(key, dict(row) if isinstance(row, dict) else row)

    def persist(self, entity_id, key, row):
        """Nothing to do: a read binds the dict this table holds, so a write
        through the binding has already landed."""
        return None

    def close(self):
        return None


class FakeCache:
    """Stands in for a `redis` capability. TTL is the Performance budget."""

    def __init__(self, clock):
        self.clock = clock
        self.store = {}       # key -> (value, expires_at_ms)
        self.hits = 0
        self.misses = 0

    def get(self, key):
        entry = self.store.get(key)
        if entry is None or entry[1] <= self.clock.now:
            self.misses += 1
            return None
        self.hits += 1
        return entry[0]

    def set(self, key, value, ttl_ms):
        if ttl_ms is None:
            raise RunError("CacheAccess set without a TTL budget "
                           "(RFC-0003 requires every cache key to carry a TTL)")
        self.store[key] = (value, self.clock.now + ttl_ms)

    def invalidate(self, key):
        self.store.pop(key, None)

    def close(self):
        """The CacheDriver contract's release hook. In-memory, so nothing."""
        return None


class Span:
    __slots__ = ("name", "kind", "start_ms", "end_ms", "attrs", "children")

    def __init__(self, name, kind, start_ms):
        self.name = name
        self.kind = kind
        self.start_ms = start_ms
        self.end_ms: "int | None" = None
        self.attrs = {}
        self.children = []

    @property
    def duration_ms(self):
        return None if self.end_ms is None else self.end_ms - self.start_ms

    def to_dict(self):
        return {"name": self.name, "kind": self.kind, "duration_ms": self.duration_ms,
                "attrs": self.attrs,
                "children": [c.to_dict() for c in self.children]}


class Trace:
    def __init__(self, correlation_id):
        self.correlation_id = correlation_id
        self.root: "Span | None" = None
        self.logs = []
        self.metrics = []      # (name, labels, value)

    def log(self, level, message, **fields):
        self.logs.append({"level": level, "message": message,
                          "correlation_id": self.correlation_id, **fields})

    def metric(self, name, labels, value):
        # RFC-0003 label allowlist — reject unbounded-cardinality labels here so
        # a violation surfaces at the source rather than in a metrics backend.
        allowed = {"module", "service", "workflow", "step", "kind"}
        extra = set(labels) - allowed
        if extra:
            raise RunError("metric label(s) outside the allowlist: %s" % sorted(extra))
        self.metrics.append((name, labels, value))

    def to_dict(self):
        return {"correlation_id": self.correlation_id,
                "span": self.root.to_dict() if self.root else None,
                "metrics": [{"name": n, "labels": l, "value": v} for n, l, v in self.metrics],
                "logs": self.logs}


def _flatten_items(nodes, ids, interp, result, root, con, payload, bindings):
    """Yield the WorkflowStep ids to execute, applying Guard/Concurrency/Pipeline.

    RFC-0003 evaluation semantics for the Guard kind:
      when   — evaluate the condition once; skip the guarded item if it is false
      until  — run the guarded item until the condition holds (deadline-bounded)
      repeat — run the guarded item `count` times
    Concurrency and Pipeline both expand to their children in declared order: this
    interpreter is single-threaded by design (mode A), and RFC-0004 requires only
    *observable* equivalence with mode B, which does not include scheduler shape.
    """
    for node_id in ids:
        node = nodes[node_id]
        kind = node["kind"]
        if kind == "WorkflowStep":
            yield node_id
        elif kind in ("Concurrency", "Pipeline"):
            for inner in _flatten_items(nodes, node.get("children", []), interp,
                                        result, root, con, payload, bindings):
                yield inner
        elif kind == "Guard":
            mode = node["mode"]
            inner_ids = node.get("children", [])
            if mode == "when":
                if not _condition_holds(node.get("condition"), payload, bindings):
                    # Issue #83: a second, pure re-evaluation just to collect the
                    # per-term values (RFC-0014 D3-D4 addendum). Kept OUT of the
                    # line above on purpose: that line is a mutation_check.py
                    # anchor, and re-evaluating here instead of threading a
                    # collector through the control-flow call leaves it byte-
                    # identical.
                    raw_evals = []
                    _condition_holds(node.get("condition"), payload, bindings,
                                     collector=raw_evals)
                    result["skipped"].append(_skip_record(
                        nodes, node,
                        evaluations=[_masked_evaluation(interp, e) for e in raw_evals]))
                    interp.trace.log("INFO", "guard skipped the guarded item",
                                     guard=node_id, condition=node.get("condition"))
                    continue
                for inner in _flatten_items(nodes, inner_ids, interp, result, root,
                                            con, payload, bindings):
                    yield inner
            elif mode == "repeat":
                for _ in range(int(node["count"])):
                    for inner in _flatten_items(nodes, inner_ids, interp, result,
                                                root, con, payload, bindings):
                        yield inner
            elif mode == "until":
                # RFC-0003 §Guard: bounded loop with two stop conditions.
                # Both apply always: (1) deadline if timeout declared, (2) round cap.
                # Whichever hits first causes termination; reason is logged separately.
                rounds = 0
                deadline = None if con["timeout_ms"] is None else interp.clock.now + con["timeout_ms"]
                while not _condition_holds(node.get("condition"), payload, bindings):
                    # Check both boundaries before iteration
                    if deadline is not None and interp.clock.now >= deadline:
                        interp.trace.log("WARN", "until loop hit deadline",
                                         guard=node_id, rounds=rounds, reason="deadline")
                        break
                    if rounds >= _UNTIL_ROUND_CAP:
                        interp.trace.log("WARN", "until loop hit round cap",
                                         guard=node_id, rounds=rounds, reason="round_cap")
                        break
                    rounds += 1
                    for inner in _flatten_items(nodes, inner_ids, interp, result,
                                                root, con, payload, bindings):
                        yield inner
                if rounds == 0:
                    # Issue #44 (t4 F-9): `when` recorded its skip and a
                    # zero-round `until` recorded nothing, so "declared and did
                    # not run" had two shapes — one observable, one silent. The
                    # two paths are the same fact, so they get the same record.
                    # A loop that ran at least one round skipped nothing.
                    # Issue #83: the condition is pure (no side effect on
                    # payload/bindings), so re-evaluating it here to collect
                    # evaluations does not change what already decided rounds==0.
                    raw_evals = []
                    _condition_holds(node.get("condition"), payload, bindings,
                                     collector=raw_evals)
                    result["skipped"].append(_skip_record(
                        nodes, node, rounds=0,
                        evaluations=[_masked_evaluation(interp, e) for e in raw_evals]))
                    interp.trace.log("INFO", "guard skipped the guarded item",
                                     guard=node_id, condition=node.get("condition"),
                                     rounds=0)
            else:
                raise RunError("unknown guard mode %r" % mode)
        else:
            raise RunError("workflow body cannot contain %s" % kind)


_UNTIL_ROUND_CAP = 16


def _guarded_step_names(nodes, ids):
    """The WorkflowStep names a guard's subtree holds, in declared order.

    `_flatten_items` never descends into a subtree it skips, so what did NOT run
    has to be collected separately. Names rather than node ids: mode B's output
    carries only `step <index> <name>`, so a manifest keyed on ids is something
    the compiled mode cannot produce, and the two modes could never be compared
    on it (issue #44).
    """
    out = []
    for node_id in ids:
        node = nodes.get(node_id)
        if node is None:
            continue
        if node["kind"] == "WorkflowStep":
            out.append(node["name"])
        elif node["kind"] in ("Concurrency", "Pipeline", "Guard"):
            out.extend(_guarded_step_names(nodes, node.get("children", [])))
    return out


def _skip_record(nodes, node, rounds=None, evaluations=None):
    """One `result["skipped"]` entry — the record shape issue #44 defines.

    `rounds` is None for `when` (it evaluates once) and 0 for an `until` that
    never entered its body. `guard` is mode A's own node id: useful for a
    debugger, and deliberately excluded from the mode A/B comparison, which is
    keyed on the fields both modes can observe.

    `evaluations` (issue #83, RFC-0014 D3-D4 addendum) is additive only — the
    five keys above are unchanged. It is a list of already-masked
    `{"ref", "value", "op", "expected", "holds"}` entries, one per
    Presence/Comparison term the condition evaluated (`_condition_holds`'s
    `collector`). Like `guard`, it names something mode B cannot produce, so
    `differential._normalise_skips` — an ALLOW-list of exactly
    `{mode, condition, step, rounds}` — excludes it the same way it already
    excludes `guard`, with no change needed there.
    """
    return {"guard": node["id"],
            "mode": node["mode"],
            "condition": node.get("condition"),
            "steps": _guarded_step_names(nodes, node.get("children", [])),
            "rounds": rounds,
            "evaluations": evaluations if evaluations is not None else []}


def resolve_reference(name, payload, bindings):
    """Resolve a condition/expectation `Reference` to a value (RFC-0012 §G12.1).

    Bare `stock` names an input payload field; qualified `product.stock` names a
    field of the row bound when that entity was read. The two forms never fall
    back to each other — the split is by grammar, not by precedence (§G12.3), so
    a program written before RFC-0012 resolves exactly as it did.

    Returns None for anything unresolved: no such binding, no such field, no such
    payload key. An unresolved reference is an expected outcome the caller
    branches on, not a fault, so it is a return value rather than an exception.

    This is the ONE resolver. `_condition_holds` (guards) and `spec._expect_result`
    (assertions) both call it, which is what makes "guards and expect share one
    scope" a property of the code rather than a claim in a document.
    """
    if "." not in name:
        return payload.get(name)
    binding, _, field = name.partition(".")
    if binding == PAYLOAD_NAMESPACE:
        # RFC-0015 §G15.2: `input.<field>` is the explicit spelling of the bare
        # form. It exists because the natural way to name an input field is the
        # entity it belongs to (`payment.amount`), and that spelling means "a row
        # this workflow read" — a workflow that only validates its input reads
        # nothing, so the guard could not be written at all (t2 F-1).
        return payload.get(field)
    row = bindings.get(binding)
    if not isinstance(row, dict):
        return None
    return row.get(field)


def _condition_holds(condition, payload, bindings, collector=None):
    """Mode A condition evaluation: Presence + Comparison.

    RFC-0008: evaluates parsed conditions (Presence and Comparison).
    Invalid conditions are rejected at parse time, so runtime sees only valid forms.

    RFC-0012: `bindings` is the execution scope — the rows read so far, keyed by
    `repo_policy.binding_name`. It is a required argument rather than a defaulted
    one on purpose: a call site that forgot it would silently evaluate every
    qualified reference as absent, which is issue #37 reappearing as a false
    negative instead of a crash.

    `collector` (issue #83, optional, default `None`): when a caller passes a
    list, each Presence/Comparison term evaluated appends one raw (unmasked)
    `{"ref", "value", "op", "expected", "holds"}` entry to it — the trace guard
    skips carry as `evaluations`. `None` collects nothing, so every existing
    call site (`differential.py`, `spec.py`, the tests) is unaffected.
    """
    if condition is None:
        return True

    # Import here to avoid circular dependency
    from .condition import (And, Comparison, ConditionError, Presence,
                            parse_condition)

    try:
        cond = parse_condition(condition)
    except ConditionError as e:
        raise RunError(f"Invalid condition: {e}")

    if cond is None:
        return True

    if isinstance(cond, Presence):
        raw = resolve_reference(cond.field, payload, bindings)
        holds = (raw is not None) if cond.kind == "exists" else (raw is None)
        if collector is not None:
            collector.append({"ref": cond.field, "value": raw, "op": cond.kind,
                              "expected": None, "holds": holds})
        return holds

    if isinstance(cond, Comparison):
        return _comparison_holds(cond, condition, payload, bindings, collector)

    if isinstance(cond, And):
        # Every term is evaluated, not short-circuited: the terms are pure, so
        # the result is the same, and a value fault in a later term must surface
        # in both modes rather than depending on where the run stopped reading.
        results = [_comparison_holds(term, condition, payload, bindings, collector)
                   for term in cond.terms]
        return all(results)

    raise RunError(f"Unknown condition type: {type(cond)}")


def _comparison_holds(cmp_node, condition, payload, bindings, collector=None):
    """One `Comparison` against this scope. Unresolved reference -> False.

    `collector` (issue #83): see `_condition_holds`. `ref` is the left
    operand's normalized text (`_value_text` — a bare `Ref` renders as its own
    dotted name), and `value`/`expected` are the left/right operands as
    evaluated here, unmasked (`_masked_evaluation` in `_flatten_items` masks a
    sensitive one before it reaches a skip record).
    """
    left = eval_value(cmp_node.left, condition, payload, bindings)
    right = eval_value(cmp_node.right, condition, payload, bindings)
    op = cmp_node.op
    if left is None or right is None:
        # A reference that names nothing behaves as it did before RFC-0015:
        # `null < X`, `null == X` and the rest are all false, on either side.
        holds = False
    elif op == '<':
        holds = left < right
    elif op == '<=':
        holds = left <= right
    elif op == '>':
        holds = left > right
    elif op == '>=':
        holds = left >= right
    elif op == '==':
        holds = left == right
    elif op == '!=':
        holds = left != right
    else:
        raise RunError(f"Unknown comparator {op!r}")
    if collector is not None:
        collector.append({"ref": _value_text(cmp_node.left), "value": left,
                          "op": op, "expected": right, "holds": holds})
    return holds


def eval_value(value, condition, payload, bindings):
    """A parsed `Value` -> int, or None when a reference resolves to nothing.

    RFC-0015 fixes the domain at signed 64-bit — the width mode B compiles to —
    so a program whose arithmetic would wrap in the compiled path fails in both
    modes instead of disagreeing. The failure is issue #48's class (`RunError` ->
    `failed`, rc=1), not a new one.
    """
    from .condition import (Arith, ConditionError, INT64_MAX, INT64_MIN, Lit,
                            Ref, encode_instant, is_instant_text,
                            looks_like_instant)

    if isinstance(value, Lit):
        return value.value
    if isinstance(value, Ref):
        raw = resolve_reference(value.name, payload, bindings)
        if raw is None:
            return None
        if isinstance(raw, bool):
            # bool is an int in Python, and 0/1 is what mode B's i64 carries.
            return 1 if raw else 0
        if isinstance(raw, int):
            return _checked(raw, value.name, condition)
        if isinstance(raw, str):
            # RFC-0016: a DateTime is compared as UTC epoch-milliseconds. The
            # same encoder runs in mode B (`backend.encode_condition_value`), so
            # both modes read one instant from one string.
            if is_instant_text(raw) or looks_like_instant(raw):
                try:
                    return _checked(encode_instant(raw, value.name), value.name,
                                    condition)
                except ConditionError as e:
                    # A zoneless or malformed timestamp is a value fault, which
                    # is issue #48's class (`RunError` -> failed, rc=1) — not a
                    # new result class, and not the `Cannot compare non-numeric`
                    # message, which would name the wrong problem.
                    raise RunError(f"{e} (in condition {condition!r})")
            try:
                return _checked(int(raw), value.name, condition)
            except ValueError:
                pass
        raise RunError(f"Cannot compare non-numeric {value.name}={raw!r} "
                       f"in condition {condition!r}")
    if isinstance(value, Arith):
        left = eval_value(value.left, condition, payload, bindings)
        right = eval_value(value.right, condition, payload, bindings)
        if left is None or right is None:
            return None
        result = left + right if value.op == '+' else left - right
        if result < INT64_MIN or result > INT64_MAX:
            raise RunError(
                "value out of the 64-bit range: %s = %d (in %r)"
                % (_value_text(value), result, condition))
        return result
    raise RunError(f"Unknown value type: {type(value)}")


def eval_aggregate(agg, expression, rowsets):
    """A parsed `Aggregate` -> int, always (RFC-0025 §5).

    An absent or empty RowSet binding sums/counts to 0 — not None, not a
    fault. That covers two cases identically: this workflow never `list`ed
    the entity at all (the `aggregation-orphaned-list` warning's case,
    RFC-0025 §4), and it did, but the store had no rows for it. Both are
    "nothing to aggregate," and RFC-0025's own decision is that neither is an
    error — a report with no links is a normal state, not an exception.

    A row that IS present but cannot supply the summed field is different: the
    field's declared type is checked at compile time (RFC-0025 §3), but a
    driver can still hand back a row that was never written with it (a plain
    `create` writes only `id` — `interp.FakeRepository.execute`). That is the
    same fault an unresolved `Value` reference already is in an assignment
    (`eval_value` returning None -> `RunError`), so it raises here too rather
    than silently treating one row as 0 and the rest as data.
    """
    binding = agg.ref.namespace or agg.ref.name
    rows = rowsets.get(binding) or []
    if agg.func == "count":
        return len(rows)
    field = agg.ref.field
    total = 0
    for row in rows:
        if not isinstance(row, dict) or field not in row:
            raise RunError(
                "aggregate %r: a row in the %r RowSet has no %r field"
                % (expression, binding, field))
        value = row[field]
        if isinstance(value, bool):
            value = 1 if value else 0
        elif not isinstance(value, int):
            raise RunError(
                "aggregate %r: cannot sum non-numeric %s=%r"
                % (expression, field, value))
        total = _checked(total + value, field, expression)
    return total


def _checked(number, name, condition):
    from .condition import INT64_MAX, INT64_MIN
    if number < INT64_MIN or number > INT64_MAX:
        raise RunError("value out of the 64-bit range: %s = %d (in %r)"
                       % (name, number, condition))
    return number


def _value_text(value):
    from .condition import value_to_string
    return value_to_string(value)


def mask_payload(payload, entity_node):
    """Replace values whose declared semantic type is masked (RFC-0003 §Observability).

    A field's declared type is resolved to its 18-type `base` first, so
    `refine ApiKey of Password` inherits Password's masking obligation: a
    refinement strengthens its base and cannot shed the base's obligations. The
    list of masked names is never extended — a second hardcoded name would break
    again for the next refinement someone writes. Entity nodes that carry no
    resolved `base` (a hand-built node, or one from outside the interpreter) fall
    back to the declared type, which is the pre-refinement behavior.
    """
    if not isinstance(payload, dict) or entity_node is None:
        return payload
    masked_names = {f["name"] for f in entity_node.get("fields", [])
                    if f.get("base", f.get("type")) in MASKED_TYPES}
    return {k: (MASK if k in masked_names else v) for k, v in payload.items()}


def _masked_evaluation(interp, entry):
    """One collected evaluation entry (issue #83, D3), masked through the same
    `mask_payload` chokepoint every other outbound channel uses — no second
    masking rule. `ref` naming a bound entity's sensitive field gets its
    `value` replaced; a bare reference or an `input.*` one names no entity
    (RFC-0012 §G12.1) and is returned unchanged, as is a ref this document has
    no such entity/field for.
    """
    ref = entry["ref"]
    if "." not in ref:
        return entry
    binding, _, field = ref.partition(".")
    if binding == PAYLOAD_NAMESPACE:
        return entry
    entity_id = interp._entity_id_for_binding(binding)
    if entity_id is None:
        return entry
    entity_view = interp._entity_view(interp.nodes[entity_id])
    masked = mask_payload({field: entry["value"]}, entity_view)
    return dict(entry, value=masked[field])


class Interpreter:
    def __init__(self, document, clock=None, repo_rows=None,
                 correlation_id="cid-0001", *, repository=None, cache=None):
        """`repository`/`cache` bind the declared capabilities to a real
        backend (issue #25); with neither, this builds exactly the in-memory
        pair it always did.

        Both are keyword-only, after a bare `*`. The four positional
        parameters keep their order and meaning, so none of the existing call
        sites changes — and a stale positional call cannot silently bind a
        driver to `correlation_id`, which is the failure a middle insertion
        would have caused at every one of them.
        """
        self.doc = document
        self.nodes = {n["id"]: n for n in document["nodes"]}
        self.refinements = refinement_index(document)
        self.clock = clock or Clock()
        if repository is None:
            self.repo = FakeRepository(repo_rows)
        else:
            # The seed rule is the store's, not the Fake's: a real driver gets
            # the same rows and inserts only what is absent, so a row an
            # earlier run left behind survives this one's seeding.
            self.repo = repository
            self.repo.seed(repo_rows or {})
        self.cache = cache if cache is not None else FakeCache(self.clock)
        self._entity_by_binding = None
        self.trace = Trace(correlation_id)
        # Registered event publications. RFC-0003 leaves the *mechanism* open
        # (§Open Questions 3 — transactional outbox or otherwise); the contract it
        # fixes is at-least-once with a dedupable id, which is what this records.
        self.outbox = []
        # Runtime diagnostics (issue #38). Deliberately not `trace.log`: mode A/B
        # equivalence covers log levels (docs/ROADMAP.md Phase 2) and mode B
        # cannot produce these, so routing them through the trace would make the
        # two modes disagree about a signal the contract says must match.
        self.diagnostics = Diagnostics()

    def _entity_id_for_binding(self, binding):
        """The Entity a bound name came from, or None.

        `repo_policy.binding_name` is the one place that decides what a read
        binds a row under, so the reverse lookup is built from it rather than
        from a second rule that could drift. Built once per run and cached:
        the map is a property of the document, not of the step.

        None is a legitimate answer — a name bound by something other than a
        repository read has no row to flush — and the Fake ignores the call
        either way, so the default path cannot change behaviour here.
        """
        if self._entity_by_binding is None:
            self._entity_by_binding = {
                binding_name(node): node["id"]
                for node in self.doc["nodes"] if node["kind"] == "Entity"}
        return self._entity_by_binding.get(binding)

    # ---- constraint lookup -------------------------------------------------
    def _service_for(self, workflow_id):
        for n in self.doc["nodes"]:
            if n["kind"] == "Service" and workflow_id in n.get("children", []):
                return n
        return None

    def _constraints(self, service):
        out = {"retry": 0, "timeout_ms": None, "rollback": False,
               "cache_ttl_ms": None, "response_slo_ms": None, "mechanisms": []}
        if service is None:
            return out
        for cid in service.get("constraints", []):
            node = self.nodes.get(cid)
            if node is None:
                raise RunError("dangling constraint reference %r" % cid)
            if node["kind"] == "Policy":
                for rule in node.get("rules", []):
                    if rule["name"] == "retry":
                        out["retry"] = int(rule["value"])
                    elif rule["name"] == "timeout":
                        out["timeout_ms"] = _duration_ms(rule["value"])
                    elif rule["name"] == "rollback":
                        out["rollback"] = True
            elif node["kind"] == "Security":
                out["mechanisms"] = list(node.get("mechanisms", []))
            elif node["kind"] == "Performance":
                for b in node.get("budgets", []):
                    if b["metric"] == "cache":
                        out["cache_ttl_ms"] = _duration_ms(b["value"])
                    elif b["metric"] == "response":
                        out["response_slo_ms"] = _duration_ms(str(b["value"]).lstrip("<>="))
        return out

    def _entity_node(self):
        """The Entity in scope, as an observability view: every field carries the
        18-type `base` its declared type resolves to, so masking honours a
        refinement of `Password` without each call site having to know the
        document.

        RFC-0003 §Observability requires exactly one masking chokepoint and calls
        per-call-site masking a contract violation — the call site that forgets
        is the leak. Resolving the base here rather than at each
        `mask_payload(...)` covers both sinks (the workflow-start log and the
        outbox emission) with one change. `type` is left untouched — this view
        is for masking only; validation resolves its own entity from
        `Validation.target` (issue #48).
        """
        for n in self.doc["nodes"]:
            if n["kind"] == "Entity":
                return self._entity_view(n)
        return None

    def _entity_view(self, node):
        """`node` as an observability view — each field carries its resolved
        18-type `base`, so masking honours refinements (see `_entity_node`)."""
        fields = [dict(f, base=self.refinements.get(f.get("type"), {})
                       .get("base", f.get("type")))
                  for f in node.get("fields", [])]
        return dict(node, fields=fields)

    def _masked_bindings(self, bindings):
        """A masked COPY of the execution scope for the result channel (issue
        #43). The scope itself stays raw — guards evaluate real values
        (RFC-0012) — but `result` leaves the process, and RFC-0003
        §Observability puts every outbound channel behind the one
        `mask_payload` chokepoint. Each binding is masked by ITS entity's
        fields, since a bound row only ever holds that entity's columns.
        """
        views = {binding_name(n): self._entity_view(n)
                 for n in self.doc["nodes"] if n["kind"] == "Entity"}
        return {name: mask_payload(row, views.get(name))
                for name, row in bindings.items()}

    # ---- execution ---------------------------------------------------------
    def run_workflow(self, workflow_id, payload=None):
        wf = self.nodes.get(workflow_id)
        if wf is None or wf["kind"] != "Workflow":
            raise RunError("no such workflow: %r" % workflow_id)
        service = self._service_for(workflow_id)
        con = self._constraints(service)
        payload = payload or {}

        root = Span(wf["name"], "Workflow", self.clock.now)
        self.trace.root = root
        deadline = None if con["timeout_ms"] is None else self.clock.now + con["timeout_ms"]
        entity = self._entity_node()
        self.trace.log("INFO", "workflow start",
                       workflow=wf["name"], payload=mask_payload(payload, entity))

        result = {"status": "completed", "steps": [], "failed_step": None,
                  "skipped": [], "failure_reason": None}
        # RFC-0012 §G12.2: the execution scope, created per run and threaded
        # through as an argument. Not an attribute of `self`: `run_workflow` can
        # be called twice on one Interpreter, and a shared map would carry the
        # first run's rows into the second — the same aliasing `FakeRepository`
        # copies its seed to avoid (issue #35).
        bindings = {}
        # RFC-0025 §5: a SEPARATE namespace for RowSet bindings (`list`), so an
        # entity can carry a single-row binding and a RowSet binding at once
        # without one overwriting the other. Guard conditions never read this —
        # `Aggregate` is not a `Value` (RFC-0025 §2) — so only step execution
        # needs it; `_flatten_items` (guard evaluation) does not.
        rowsets = {}
        for item_id in _flatten_items(self.nodes, wf.get("children", []), self, result,
                                     root, con, payload, bindings):
            step = self.nodes[item_id]
            span = Span(step["name"], "WorkflowStep", self.clock.now)
            root.children.append(span)
            attempts = 0
            last_error = None
            while True:
                attempts += 1
                try:
                    self._run_step(step, span, con, payload, deadline, bindings,
                                   rowsets)
                    last_error = None
                    break
                except RunError as exc:
                    last_error = exc
                    if not self._retryable(step, con, attempts, deadline):
                        break
                    self.trace.log("WARN", "step retry",
                                   step=step["name"], attempt=attempts, reason=str(exc))
                    self.clock.advance(_backoff_ms(attempts))
            span.end_ms = self.clock.now
            span.attrs["attempts"] = attempts
            self.trace.metric("step.duration_ms",
                              {"workflow": wf["name"], "step": step["name"]},
                              span.duration_ms)
            result["steps"].append({"step": step["name"], "attempts": attempts,
                                    "duration_ms": span.duration_ms,
                                    "effects": [self.nodes[c]["kind"]
                                                for c in step.get("children", [])]})
            if last_error is not None:
                result["status"] = "failed"
                result["failed_step"] = step["name"]
                result["failure_reason"] = str(last_error)
                self.trace.log("ERROR", "step failed",
                               step=step["name"], reason=str(last_error))
                if con["rollback"]:
                    self.trace.log("INFO", "rollback: no Transaction boundary in scope, "
                                          "nothing to compensate")
                break
            if deadline is not None and self.clock.now > deadline:
                result["status"] = "failed"
                result["failed_step"] = step["name"]
                result["failure_reason"] = ("deadline exceeded after step %r"
                                            % step["name"])
                self.trace.log("ERROR", "deadline exceeded",
                               step=step["name"], deadline_ms=con["timeout_ms"])
                break

        # Issue #44 (t1 F-5, t2 F-6): the run completed, but not all of what the
        # program declared actually happened. `status` stays `completed` — a
        # guard doing its job is not a failure, and a cache-hit skip is a normal
        # optimisation — so the fact travels on the channel built for "declared,
        # and here is what the runtime really did with it" instead. That also
        # puts it behind `--strict`, which is the only way a caller reading just
        # the exit code could ever have seen it (issue #45's gate).
        for record in result["skipped"]:
            self.diagnostics.add(
                code="guard-skipped-steps",
                where=record["guard"],
                subject=record["condition"] or "(unconditional)",
                message="the `%s` guard did not run %s; the workflow still "
                        "reports completed, so a caller reading only the status "
                        "cannot tell this run from one that ran every step"
                        % (record["mode"],
                           ", ".join(record["steps"]) or "(no step)"),
                # RFC-0024 (issue #82 line= migration): same precedent as
                # `authorization-not-verified` below — the Guard node's own
                # lowering already recorded a line, so this reads it rather
                # than re-deriving one.
                line=self.nodes[record["guard"]].get("line"))

        root.end_ms = self.clock.now
        total = root.duration_ms
        result["bindings"] = self._masked_bindings(bindings)
        result["duration_ms"] = total
        result["correlation_id"] = self.trace.correlation_id
        if con["response_slo_ms"] is not None:
            result["slo_ms"] = con["response_slo_ms"]
            result["slo_met"] = total <= con["response_slo_ms"]
            if not result["slo_met"]:
                self.trace.log("WARN", "response SLO exceeded (measured, not enforced)",
                               measured_ms=total, slo_ms=con["response_slo_ms"])
        self.trace.metric("workflow.duration_ms", {"workflow": wf["name"]}, total)
        return result

    def _run_step(self, step, span, con, payload, deadline, bindings, rowsets):
        if deadline is not None and self.clock.now >= deadline:
            raise RunError("deadline exhausted before step %r" % step["name"])
        for child_id in step.get("children", []):
            effect = self.nodes[child_id]
            self._run_effect(effect, span, con, payload, bindings, rowsets)
        self.clock.advance()

    def _run_effect(self, effect, span, con, payload, bindings, rowsets):
        kind = effect["kind"]
        child = Span(effect["id"].rsplit(".", 1)[-1], kind, self.clock.now)
        span.children.append(child)

        if kind == "Assignment":
            # RFC-0015. The bound row IS the stored row (a `read` binds the dict
            # the table holds), so writing through the binding is what makes the
            # deduction observable to `rows`/`result` assertions rather than only
            # to the trace. The effect is recorded either way: a silent update is
            # the failure mode issue #38 named, one level down.
            target = effect["target"]
            binding, _, field = target.partition(".")
            row = bindings.get(binding)
            if not isinstance(row, dict):
                raise RunError(
                    "assignment target %r names no bound row — %s was never read"
                    % (target, binding))
            from .condition import Aggregate, parse_value_or_aggregate
            rhs = parse_value_or_aggregate(effect["expression"])
            if isinstance(rhs, Aggregate):
                # RFC-0025 §5: sums/counts the RowSet, never a "resolves to
                # nothing" — an absent or empty RowSet is 0, not a fault.
                value = eval_aggregate(rhs, effect["expression"], rowsets)
            else:
                value = eval_value(rhs, effect["expression"], payload, bindings)
            if value is None:
                raise RunError(
                    "assignment %r cannot be evaluated: a reference in %r "
                    "resolves to nothing" % (target, effect["expression"]))
            row[field] = value
            # The write above lands in the dict the read bound. For the Fake
            # that dict IS the stored row and this is a no-op; for a real store
            # it is a detached copy, and without this flush the assignment
            # would be visible for the rest of the run and gone afterwards —
            # a silent update, which is the failure mode one level down from
            # the one issue #38 named.
            # Not a silent skip when the binding names no entity. The compiler
            # already refuses `set input.x` ("not state") and an assignment to
            # an entity the workflow never reads ("never reads it"), so a
            # binding with no entity behind it means the document did not come
            # from the compiler. Skipping the flush there would drop the write
            # on a real store and keep it on the Fake — the two backends would
            # disagree, silently, on exactly the operation this flush exists
            # for.
            entity_id = self._entity_id_for_binding(binding)
            if entity_id is None:
                raise RunError(
                    "assignment target %r names no declared entity, so the "
                    "write has no row to address" % target)
            try:
                self.repo.persist(entity_id, row_key(entity_id, payload), row)
            except DriverError as exc:
                raise RunError(str(exc)) from exc
            child.attrs["target"] = target
            child.attrs["value"] = value
            self.trace.log("INFO", "assignment applied",
                           target=target, value=value)
        elif kind == "Validation":
            self._validate(effect, payload)
        elif kind == "RepositoryCall" and effect["operation"] == "query":
            # RFC-0025 §5/§7: a RowSet, not a row. `execute`'s single-key
            # contract cannot express "every row," so `list` calls the
            # driver's own `query(entity_id)` instead — a different method,
            # not a branch of `execute` (which still answers `operation
            # in ("read", "query")` the old, unused way, for D5's
            # unchanged-signature reason: RFC-0025 §7 kept `execute` as no
            # call site had to be enumerated).
            try:
                rows = self.repo.query(effect["entity"])
            except DriverError as exc:
                raise RunError(str(exc)) from exc
            child.attrs["row_count"] = len(rows)
            entity_node = self.nodes.get(effect["entity"])
            if entity_node is not None:
                # RFC-0012 §G12.2 (RFC-0025 §5): a SEPARATE namespace from
                # `bindings` — last write wins, same rule, different scope.
                rowsets[binding_name(entity_node)] = rows
        elif kind == "RepositoryCall":
            # One of two places a driver fault is translated. A DriverError
            # becomes a RunError with its message and cause intact, so a real
            # backend's failure is an ordinary failed run — the same status and
            # the same rc a Fake failure produces — instead of a traceback.
            try:
                row = self.repo.execute(effect["entity"], effect["operation"],
                                        row_key(effect["entity"], payload))
            except DriverError as exc:
                raise RunError(str(exc)) from exc
            child.attrs["found"] = row is not None
            if effect["operation"] == "read" and isinstance(row, dict):
                # RFC-0012 §G12.2: a completed read binds its row into the
                # execution scope, last write wins. Only reads bind — create /
                # update / delete answer with an affected-row count, so there is
                # no row content to name. `query` no longer reaches this branch
                # at all (RFC-0025 §6.1/§6.2 — it binds a RowSet above instead
                # of a row, so it must not satisfy a single-row reference).
                entity_node = self.nodes.get(effect["entity"])
                if entity_node is not None:
                    bindings[binding_name(entity_node)] = row
            if effect["operation"] == "read" and row is None:
                self.clock.advance(1)
                child.end_ms = self.clock.now
                raise RunError("repository read found no row for %s" % effect["entity"])
        elif kind == "CacheAccess":
            key = effect["key"].replace("{id}", str(payload.get("id", "-")))
            try:
                if effect["operation"] == "set":
                    self.cache.set(key, payload, con["cache_ttl_ms"])
                    child.attrs["ttl_ms"] = con["cache_ttl_ms"]
                elif effect["operation"] == "get":
                    child.attrs["hit"] = self.cache.get(key) is not None
                else:
                    self.cache.invalidate(key)
            except DriverError as exc:
                raise RunError(str(exc)) from exc
        elif kind == "Authorization":
            child.attrs["requirement"] = effect.get("requirement")
            # Recording the requirement is all Phase 1 does with it. The step
            # then succeeds, which reads exactly like an authorization that
            # passed — issue #38's sharpest edge, so it leaves a diagnostic.
            self.diagnostics.add(
                code="authorization-not-verified",
                where=effect["id"], subject=effect.get("requirement") or "unspecified",
                message="the authorization requirement is recorded on the trace "
                        "and never checked; this step cannot deny anything",
                # RFC-0024: the runtime has no source text in hand, only the IR —
                # so it reads the line lowering already recorded on this Effect
                # node, rather than re-deriving one.
                line=self.nodes[effect["id"]].get("line"))
        elif kind == "NetworkCall":
            child.attrs["target"] = effect.get("target")
        elif kind == "EventEmit":
            # RFC-0003: the step's synchronous part ends at *registering* the
            # publish. Delivery is at-least-once, so every emission carries a
            # unique id the consumer can dedupe on. The payload crosses a declared
            # transfer boundary, so it is copied out of the arena — and masked,
            # because an event leaves the process.
            event_ref = effect.get("event")
            if event_ref is None:
                raise RunError("EventEmit has no event reference")
            if event_ref not in self.nodes:
                raise RunError("EventEmit references undeclared event %r" % event_ref)
            emission = {"emission_id": "%s#%d" % (effect["id"], len(self.outbox) + 1),
                        "event": event_ref,
                        "payload": mask_payload(payload, self._entity_node())}
            self.outbox.append(emission)
            child.attrs["event"] = event_ref
            child.attrs["emission_id"] = emission["emission_id"]
            self.trace.log("INFO", "event publish registered",
                           event=event_ref, emission_id=emission["emission_id"])
        else:
            raise RunError("Phase 1 interpreter does not execute %s" % kind)

        self.clock.advance(1)
        child.end_ms = self.clock.now

    def _validate(self, effect, payload):
        validate_effect(self.nodes, effect, payload, self.refinements)

    def _retryable(self, step, con, attempts, deadline=None):
        # RFC-0003: an absolute ceiling, written without reference to `con["retry"]`
        # on purpose. A retry loop whose only bound is the declared budget stops
        # being a failure and becomes an infinite loop the moment that budget stops
        # applying (kb/antipatterns/antipatterns-unbounded-retry.md), and the
        # deadline below cannot stand in for it — it is `None` whenever the owning
        # service declares no `timeout`. No valid configuration reaches this.
        # `>=`, not `>`: `attempts` is the run just finished, so refusing at
        # `MAX_STEP_ATTEMPTS` is what makes it the total, initial attempt included.
        if attempts >= MAX_STEP_ATTEMPTS:
            return False
        if attempts > con["retry"]:
            return False
        # RFC-0003: every retry must fit inside the workflow deadline's remaining
        # time. Without this the retry budget is the only bound, so a runtime that
        # lost its attempt cap would spin forever instead of failing.
        if deadline is not None and self.clock.now + _backoff_ms(attempts) >= deadline:
            return False
        for child_id in step.get("children", []):
            eff = self.nodes[child_id]
            key = (eff["kind"], eff.get("operation"))
            if eff["kind"] in ("RepositoryCall", "CacheAccess") and key not in IDEMPOTENT_OPS:
                return False
            if eff["kind"] in ("NetworkCall", "EventEmit"):
                return False
        return True


def validate_effect(nodes, effect, payload, refinements):
    """Raise `RunError` iff a `Validation` effect rejects `payload` (RFC-0001).

    Module-level, not a method: this single judgement is what "validated" means
    in BOTH execution modes — the interpreter calls it per attempt, and mode B's
    static derivation (`backend._validation_fails`) calls it at build time, so
    the two cannot drift apart (issue #48).

    For `rule == "semantic-types"` the entity is the one `Validation.target`
    names, never a positional default: `validate order` in a multi-entity
    document must check Order's facets, not whichever Entity the document
    happens to declare first (issue #48, qa t1 F-6/S4). `lower` always writes an
    Entity node id here, so a miss means the IR bypassed the compiler — fail
    closed, like 부록 A.7 ⓐ upstream.
    """
    rule = effect.get("rule")
    if rule == "semantic-types":
        target = effect.get("target")
        entity = nodes.get(target)
        if entity is None or entity.get("kind") != "Entity":
            raise RunError("validation references undeclared entity %r"
                           % target)
        for field in entity.get("fields", []):
            if field["name"] not in payload:
                raise RunError("missing required field %r" % field["name"])
            check_semantic_type(field["type"], payload[field["name"]],
                                field["name"], refinements)
    else:
        field_name = effect["target"].rsplit(".", 1)[-1]
        if field_name not in payload:
            raise RunError("missing required field %r" % field_name)
        check_semantic_type(rule, payload[field_name], field_name, refinements)


def refinement_index(document):
    """Every `Refinement` node in `document`, keyed by the name a field's `type`
    (or a `Validation.rule`) spells — RFC-0001 부록 A.6.1 resolution order ②.

    This is the ONLY source of refinements at runtime. `refinements.PRESETS` is
    deliberately not consulted: a built-in preset a field uses is already emitted
    into the document as a structurally identical node (A.6.4 emit-on-use), while
    a user-declared `refine` exists ONLY here — reading the preset table would
    silently skip every user declaration, which is the class of bug issue #31
    exists to eliminate.

    The returned dicts are the document's own objects, not copies; callers treat
    them as read-only.
    """
    return {n["name"]: {"base": n["base"], "facets": n["facets"]}
            for n in document.get("nodes", []) if n["kind"] == "Refinement"}


def _check_facets(base, facets, value, field_name, type_name):
    """Apply a refinement's facets on top of its base's own rule (부록 A.6.3).

    `pattern` is applied with `re.search`: JSON Schema defines `pattern` as an
    unanchored ECMA-262 partial match, and the OpenAPI projection of these same
    facets must accept exactly what this accepts. The three built-in presets
    carry their own `^...$`, so anchoring only ever matters for a user pattern.
    (`types.SEMANTIC_TYPES`'s own base rules keep `re.match` — a different
    registry with a different owner.)

    Numeric facets compare as `decimal.Decimal`, never `float`: `Decimal` is
    serialized as a string and float coercion would round the comparison.
    """
    import decimal
    import re
    if "enum" in facets:
        # `True == 1` in Python, so an unguarded membership test would let a
        # boolean satisfy `enum 1`. `Integer`'s base rule excludes bool for the
        # same reason; the facet layer holds the same line.
        if isinstance(value, bool) or value not in facets["enum"]:
            raise RunError("field %r is not one of %s's enum values %r"
                           % (field_name, type_name, facets["enum"]))
    category = BASE_CATEGORY[base]
    if category == "text":
        text = str(value)
        if "minLength" in facets and len(text) < facets["minLength"]:
            raise RunError("field %r is shorter than %s's minLength %d (%d)"
                           % (field_name, type_name, facets["minLength"], len(text)))
        if "maxLength" in facets and len(text) > facets["maxLength"]:
            raise RunError("field %r is longer than %s's maxLength %d (%d)"
                           % (field_name, type_name, facets["maxLength"], len(text)))
        if "pattern" in facets and not re.search(facets["pattern"], text):
            raise RunError("field %r does not match %s's pattern %r"
                           % (field_name, type_name, facets["pattern"]))
    elif category == "numeric":
        for name in ("min", "max"):
            if name not in facets:
                continue
            try:
                number = decimal.Decimal(str(value))
            except (decimal.InvalidOperation, ValueError):
                raise RunError("field %r is not a number, so %s's %s cannot be "
                               "applied" % (field_name, type_name, name))
            limit = decimal.Decimal(str(facets[name]))
            if number < limit if name == "min" else number > limit:
                raise RunError("field %r violates %s's %s %s"
                               % (field_name, type_name, name, facets[name]))
    # `boolean` and `composite` admit no facets at all (A.6.3), so there is
    # nothing to apply and no branch to write.


def check_semantic_type(type_name, value, field_name, refinements=None):
    """Validate a value against its semantic type's rule (RFC-0001).

    The rule is data on `types.SEMANTIC_TYPES[type_name]["check"]`; this applies
    it. When `type_name` names a `Refinement` in `refinements` (built by
    `refinement_index(document)`), the value must satisfy the base type's own
    rule AND every facet — a refinement strengthens its base, it never replaces
    it (부록 A.6.2).

    A name that is neither a base type nor a refinement in this document still
    passes: resolving `fields[].type` is the compiler's boundary, and it raises
    `LowerError` for a name that resolves to nothing (부록 A.7 ⓐ). Re-deciding
    that here would duplicate a check that already failed closed upstream.
    RFC-0001 owns the full table.
    """
    import re
    if type_name == "semantic-types":
        return
    if value is None:
        raise RunError("field %r is null" % field_name)
    refinement = None if refinements is None else refinements.get(type_name)
    if refinement is not None:
        # `base` is one of the 18 by construction (A.6.2 forbids refining a
        # refinement), so the recursive call needs no index of its own.
        check_semantic_type(refinement["base"], value, field_name)
        _check_facets(refinement["base"], refinement["facets"], value,
                      field_name, type_name)
        return
    spec = SEMANTIC_TYPES.get(type_name)
    if spec is None:
        return
    rule = spec["check"]
    if rule is None:
        return
    if rule[0] == "pattern":
        flags = re.I if rule[2] else 0
        if not re.match(rule[1], str(value), flags):
            raise RunError("field %r is not a valid %s" % (field_name, type_name))
    elif rule[0] == "py":
        pytype = rule[1]
        if not isinstance(value, pytype) or (pytype is int and isinstance(value, bool)):
            raise RunError("field %r is not a valid %s" % (field_name, type_name))
    elif rule[0] == "nonempty":
        if not str(value):
            raise RunError("field %r is empty" % field_name)


# The default-fixture sample per semantic type, projected from the one registry
# (issue #23/#24). Each value is a valid instance of its type, so a derived
# fixture passes `check_semantic_type`.
SAMPLE_VALUES = {name: spec["sample"] for name, spec in SEMANTIC_TYPES.items()}


# Shapes none of the 18 bases exhibits as a top-level sample. This list grows by
# SHAPE, never by refinement name — keying it on a name would make the built-in
# presets privileged, which 부록 A.6.4 forbids. Every entry goes through
# `check_semantic_type` before it is used, exactly like every other candidate, so
# an entry that fits nothing simply never wins.
EXTRA_TEXT_SAMPLES = ("https://example.com/a",)


def sample_for_type(type_name, refinements=None):
    """A valid sample value for a field of `type_name`, or None if none can be
    derived (RFC-0001 부록 A.6).

    For a refinement this PROPOSES candidates and VERIFIES each one, in this
    order: the base's own sample, the first `enum` member, the numeric bound, a
    length-adjusted derivation of the base sample, the registry's other string
    samples, then EXTRA_TEXT_SAMPLES. The first candidate that passes
    `check_semantic_type` wins. Deriving a string that satisfies an arbitrary
    regex is not decidable, so this never inverts a pattern — it proposes and
    checks. When nothing passes, the caller gets None and skips the field: an
    absent value is recoverable, while a value that fails its own validation
    turns a fixture into a false green.

    Returns None for "no sample" — test it with `is None`, because `{}`, `0` and
    `False` are all legitimate sample values.
    """
    refinement = None if refinements is None else refinements.get(type_name)
    if refinement is None:
        return SAMPLE_VALUES.get(type_name)
    base = refinement["base"]
    facets = refinement["facets"]
    base_sample = SAMPLE_VALUES.get(base)
    candidates = [base_sample]
    if "enum" in facets:
        candidates.append(facets["enum"][0])
    category = BASE_CATEGORY[base]
    if category == "numeric":
        for name in ("min", "max"):
            if name in facets:
                # `Decimal`'s own sample is a string, so a Decimal-based
                # refinement keeps that shape instead of turning into a number.
                candidates.append(str(facets[name])
                                  if isinstance(base_sample, str)
                                  else facets[name])
    elif category == "text" and isinstance(base_sample, str):
        unit = base_sample or "x"
        if "minLength" in facets and len(base_sample) < facets["minLength"]:
            candidates.append(unit * -(-facets["minLength"] // len(unit)))
        if "maxLength" in facets and len(base_sample) > facets["maxLength"]:
            candidates.append(base_sample[:facets["maxLength"]])
        candidates.extend(v for v in SAMPLE_VALUES.values()
                          if isinstance(v, str))
        candidates.extend(EXTRA_TEXT_SAMPLES)
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            check_semantic_type(type_name, candidate, "sample", refinements)
        except RunError:
            continue
        return candidate
    return None


def sample_payload(entities, refinements=None):
    """Synthesize a default input fixture covering every field of `entities`.

    The value for each field comes from `sample_for_type`. With `refinements`
    (from `refinement_index(document)`) a refinement-typed field gets a value
    too, derived against its facets and verified against its own type before it
    is used; a field no valid value can be derived for is left out, and the
    caller can still override with an explicit payload. Replaces the hardcoded
    login payload so `run`/`diff` work for any module (issue #23, #31).
    """
    payload = {}
    for entity in entities:
        for field in entity.get("fields", []):
            value = sample_for_type(field["type"], refinements)
            if value is not None:
                payload[field["name"]] = value
    return payload


def _duration_ms(text):
    """`3s` -> 3000, from the one unit table in `lexer` (RFC-0016)."""
    from .lexer import duration_ms_or_none
    try:
        value = duration_ms_or_none(str(text))
    except OverflowError as e:
        raise RunError(str(e))
    if value is None:
        raise RunError("not a duration: %r" % text)
    return value


def _backoff_ms(attempt):
    """Capped exponential backoff. Deterministic: jitter is a runtime concern
    and would make the reference interpreter non-reproducible."""
    return min(100 * (2 ** (attempt - 1)), 1000)
