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
  parallel — a `parallel` block's steps run on a block-scoped
             ThreadPoolExecutor, fail-fast, capped at the declared value
             (issue #108)
"""

import hashlib
import json
import threading
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait

from .condition import PAYLOAD_NAMESPACE, guard_condition_text, parse_value
from .diagnostics import Diagnostics
from .drivers import (ConflictError, DEFAULT_NETWORK_TIMEOUT_MS, DriverError,
                      FakeNetworkDriver)
from .refinements import BASE_CATEGORY
from .repo_policy import apply_predicate, binding_name, row_key
from .tracecontext import format_traceparent, new_span_id
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
    """Injected monotonic clock in milliseconds — deterministic in tests.

    The **virtual** binding (RFC-0003 §Execution Model/Clock, RFC-0029
    Updates): process-local, starts at 0, advances only via `advance()`. This
    is the default for every execution path (`run`, `spec`, `diff`) and its
    values/ordering are a regression boundary — `lnpl diff` and the spec
    goldens are only valid on this binding. See `RealClock` for the other.
    """

    def __init__(self, step_cost_ms=5):
        self.now = 0
        self.step_cost_ms = step_cost_ms

    def advance(self, ms=None):
        self.now += self.step_cost_ms if ms is None else ms
        return self.now


class RealClock:
    """The **real** binding (`--clock real`, RFC-0003 §Execution Model/Clock,
    RFC-0029 Updates): `now` reads a monotonic wall-clock, so it advances on
    its own between calls. `advance()` is a no-op — nothing to fast-forward.

    First consumer: `CacheAccess` TTL (issue #100) — binding a cache entry's
    expiry to actual elapsed time is what a persistent cache driver needs
    (`docs/backends.md` §5, `CacheDriver`'s docstring). Never used by `spec`/
    `diff`: both stay on the virtual binding, since a non-deterministic clock
    cannot produce a repeatable comparison.
    """

    @property
    def now(self):
        return time.monotonic_ns() // 1_000_000

    def advance(self, ms=None):
        return self.now


# The closed table of clock selectors `--clock` accepts.
CLOCKS = ("virtual", "real")


def open_clock(spec):
    """`--clock`'s value -> a Clock instance, or None for the default virtual
    binding.

    `None` means "the Interpreter builds its own virtual `Clock()`", which
    keeps the untouched path byte-identical to what it was before this issue
    — the same shape as `drivers.open_repository`/`open_network`. The lookup
    is a closed table with a defined miss.
    """
    if spec == "virtual":
        return None
    if spec == "real":
        return RealClock()
    raise ValueError("unknown clock %r (accepted: %s)"
                     % (spec, ", ".join(CLOCKS)))


class FakeRepository:
    """Stands in for a `postgres` capability: one keyed table per entity."""

    # issue #116, D5: this reference implementation pushes a `list where`
    # predicate/order/limit down into its own `query()` (in-memory, via
    # `repo_policy.apply_predicate`) rather than relying on the interpreter's
    # over-fetch-then-filter fallback — the same "opt in by declaring the
    # attribute" idiom `testing.RepositoryDriverTCK` already uses for the
    # optimistic-version conflict (`observed_version`).
    supports_predicate = True

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
        # issue #120: the `begin()` snapshot, or `None` between transactions.
        self._snapshot = None

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
                # issue #113, D2: called directly (as this class's own
                # unit tests do), this stays a bare `RunError` -- `FakeRepository`
                # is not a `RepositoryDriver`, so it never raises `DriverError`
                # for `run_workflow` to translate. `failure_kind` rides as an
                # attribute on the instance instead, read by `run_workflow`
                # below the same way `__cause__` is read for a real driver's
                # `ConflictError`.
                conflict = RunError(
                    "repository create conflicts: %s already exists" % entity_id)
                conflict.failure_kind = "conflict"
                raise conflict
            table[key] = {"id": key}
        return {"affected": 1}

    def query(self, entity_id, predicate=None, order=None, limit=None):
        """Every row for `entity_id`, row_key ascending — never `None`, empty
        list when the table has none (RFC-0025 §5: an empty RowSet, not an
        absent one). Sorted rather than `dict.values()`: insertion order and
        row_key order can differ, and `SqliteRepositoryDriver.query` orders by
        `ORDER BY row_key`, so this has to sort the same way to agree with it
        (RFC-0025 §7 — the contract suite's reverse-insertion-order case is
        what a plain `dict.values()` here would fail).

        `predicate`/`order`/`limit` (issue #116, D5) default to `None` —
        the pre-#116 call shape, byte-identical in behaviour — and, when
        given, are applied by `repo_policy.apply_predicate` over this same
        row_key-ordered list, never a second sort strategy.
        """
        table = self.rows.get(entity_id, {})
        rows = [row for _key, row in sorted(table.items())]
        if predicate is None and order is None and limit is None:
            return rows
        return apply_predicate(rows, predicate, order, limit)

    def query_sorted(self, entity_id, field):
        """Every row for `entity_id`, ordered by `field` ascending, row_key
        the tiebreaker (issue #99, D7 — `SqliteRepositoryDriver.query_sorted`
        pushed to SQL via `json_extract`; the Fake sorts in memory, over the
        same `(field value, row_key)` pair, so the two backends agree).
        """
        table = self.rows.get(entity_id, {})
        return [row for _key, row in
               sorted(table.items(), key=lambda kv: (kv[1].get(field), kv[0]))]

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
        """Write `row` into the table under `key`.

        For the read-then-`set` path this is a no-op in effect: `row` IS the
        dict `self.rows[entity_id][key]` already holds (a read binds that
        exact object), so reassigning the same reference changes nothing.
        For `create`'s payload-seeding (issue #97 / RFC-0012 Updates), `row`
        is a freshly built dict never yet in the table — a genuine write is
        what makes the Fake agree with `SqliteRepositoryDriver.persist`
        (drivers.py), which always writes what it is given.
        """
        self.rows.setdefault(entity_id, {})[key] = row

    def record_emission(self, emission):
        """Nothing to persist — the Fake has no store that outlives the run
        (issue #102: outbox persistence is a `SqliteRepositoryDriver`
        contract, the same asymmetry `persist`'s own docstring states)."""
        return None

    def begin(self):
        """Snapshot `self.rows` so a later `rollback()` can restore it
        (issue #120, RFC-0032 enforced). The copy goes two dict levels deep,
        matching the constructor's own copy: RFC-0015's `set` mutates a read
        row's dict in place and a read binds that exact object, so a
        shallow (one-level) snapshot would share the row dict with the live
        table and "restore" a value that was mutated right along with it.

        Rejects a nested call — a re-snapshot while one is already open
        would make "the matching `begin()`" ambiguous, and silently drop
        whatever `rollback()` was supposed to undo."""
        if self._snapshot is not None:
            raise RunError("begin() called while a transaction is already open")
        self._snapshot = {entity_id: {key: dict(row) if isinstance(row, dict) else row
                                      for key, row in table.items()}
                          for entity_id, table in self.rows.items()}

    def commit(self):
        """Discard the snapshot — the writes since `begin()` stay."""
        self._snapshot = None

    def rollback(self):
        """Restore `self.rows` from the `begin()` snapshot, discarding
        every write made since. A no-op, not an error, when there is no
        snapshot: `FakeRepository` is also driven directly (its own unit
        tests, `--backend fake` without a wrapping `run_workflow`), and
        those callers never open a transaction to begin with."""
        if self._snapshot is None:
            return
        self.rows = self._snapshot
        self._snapshot = None

    def read_outbox(self, event, after_seq=0):
        """Nothing to tail — same asymmetry `record_emission` states: with
        no persisted emission, there is nothing an SSE subscriber (issue
        #103) could ever be shown."""
        return []

    def close(self):
        return None


class FakeCache:
    """Stands in for a `redis` capability. TTL is the Performance budget.

    TTL is judged entirely through whichever `Clock` this is constructed
    with — `get`/`set` never read a wall clock directly. A store-backed
    `CacheDriver` may follow the same clock-comparison shape, or delegate TTL
    to the store's own native expiry instead (`CacheDriver`'s docstring).
    """

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
        # issue #107: `None` by default — a non-HTTP run (`lnpl run`) never
        # sets these, so its `to_dict()` stays byte-identical to before this
        # issue. `LnplWsgiApp` populates them once per request (D3:
        # correlation_id stays the separate, pre-existing run identifier;
        # these are the distributed-trace identity linked on the same record).
        self.trace_id = None
        self.span_id = None
        self.trace_link = None
        self.tracestate = None
        # r1-F1: trace-flags (D6 — preserved when propagated, "01" when we
        # mint a fresh trace of our own). Outbound-injection-only, like
        # tracestate: never surfaced in `to_dict()`.
        self.flags = None

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
        out = {"correlation_id": self.correlation_id,
               "span": self.root.to_dict() if self.root else None,
               "metrics": [{"name": n, "labels": label, "value": v} for n, label, v in self.metrics],
               "logs": self.logs}
        # issue #107: keys added only when set, so a non-HTTP run's
        # to_dict() (trace_id/span_id/trace_link/tracestate all `None`)
        # stays byte-identical to the pre-#107 golden output.
        if self.trace_id is not None:
            out["trace_id"] = self.trace_id
        if self.span_id is not None:
            out["span_id"] = self.span_id
        if self.trace_link is not None:
            out["links"] = self.trace_link
        # D10: tracestate is a vendor extension with PII risk — never surfaced
        # in to_dict(), even when set.
        return out


class _CreatedRow(dict):
    """A row from `create <Entity> as <name>` (issue #97 / RFC-0012 Updates).

    `bindings` keys it under the author's chosen `as` name, not the entity's
    default binding name, so `Interpreter._entity_id_for_binding` (built
    from `repo_policy.binding_name`) cannot resolve it there — the entity id
    rides on the row itself instead, the same way `drivers._VersionedRow`
    carries `observed_version` invisibly to every user-facing surface
    (payload, response, wire).
    """

    def __init__(self, data, entity_id):
        super().__init__(data)
        self.entity_id = entity_id


class _ParallelGroup:
    """Marks one `Concurrency` block for `run_workflow`'s main loop (issue
    #108 D1). `_flatten_items` yields this instead of recursing into the
    block's children the way it still does for `Pipeline` — running them is
    not "get the next id," it is "run this whole scope on its own executor,"
    which needs `rowsets`/`deadline`/the run's constraints, none of which
    this generator carries. `parallel` cannot nest and cannot be guarded
    (RFC-0002's grammar), so `step_ids` are always plain WorkflowStep ids,
    never another block.
    """
    __slots__ = ("node_id", "step_ids")

    def __init__(self, node_id, step_ids):
        self.node_id = node_id
        self.step_ids = step_ids


def _flatten_items(nodes, ids, interp, result, root, con, payload, bindings):
    """Yield the WorkflowStep ids to execute, applying Guard/Concurrency/Pipeline.

    RFC-0003 evaluation semantics for the Guard kind:
      when   — evaluate the condition once; skip the guarded item if it is false
      until  — run the guarded item until the condition holds (deadline-bounded)
      repeat — run the guarded item `count` times
    Pipeline expands to its children in declared order: this interpreter is
    single-threaded by design for everything but `parallel` (mode A), and
    RFC-0004 requires only *observable* equivalence with mode B, which does
    not include scheduler shape. `Concurrency` (issue #108) is different: its
    children genuinely run concurrently, so this generator does not descend
    into it at all — it yields a `_ParallelGroup` marker instead (see there).
    """
    for node_id in ids:
        node = nodes[node_id]
        kind = node["kind"]
        if kind == "WorkflowStep":
            yield node_id
        elif kind == "Concurrency":
            yield _ParallelGroup(node_id, node.get("children", []))
        elif kind == "Pipeline":
            for inner in _flatten_items(nodes, node.get("children", []), interp,
                                        result, root, con, payload, bindings):
                yield inner
        elif kind == "Guard":
            mode = node["mode"]
            inner_ids = node.get("children", [])
            if mode == "when":
                alternatives = node.get("alternatives")
                if not alternatives:
                    if not _condition_holds(node.get("condition"), payload, bindings,
                                            caller=interp.caller):
                        # Issue #83: a second, pure re-evaluation just to collect the
                        # per-term values (RFC-0014 D3-D4 addendum). Kept OUT of the
                        # line above on purpose: that line is a mutation_check.py
                        # anchor, and re-evaluating here instead of threading a
                        # collector through the control-flow call leaves it byte-
                        # identical.
                        raw_evals = []
                        _condition_holds(node.get("condition"), payload, bindings,
                                         collector=raw_evals, caller=interp.caller)
                        result["skipped"].append(_skip_record(
                            nodes, node,
                            evaluations=[_masked_evaluation(interp, e) for e in raw_evals]))
                        interp.trace.log("INFO", "guard skipped the guarded item",
                                         guard=node_id, condition=node.get("condition"))
                        continue
                else:
                    # RFC-0028 §Reference-level Specification/4: evaluate the
                    # condition AND every alternative — no short-circuit, same
                    # reasoning `And` already uses (pure terms, and the trace
                    # must show every alternative's value).
                    texts = [node.get("condition")] + list(alternatives)
                    raw_evals = []
                    holds_per_text = []
                    for text in texts:
                        term_evals = []
                        holds_per_text.append(_condition_holds(
                            text, payload, bindings, collector=term_evals,
                            caller=interp.caller))
                        raw_evals.extend(term_evals)
                    if not any(holds_per_text):
                        result["skipped"].append(_skip_record(
                            nodes, node,
                            evaluations=[_masked_evaluation(interp, e) for e in raw_evals]))
                        interp.trace.log(
                            "INFO", "guard skipped the guarded item",
                            guard=node_id,
                            condition=guard_condition_text(
                                node.get("condition"), alternatives))
                        continue
                    fired = next(i for i, h in enumerate(holds_per_text) if h)
                    if fired > 0:
                        interp.trace.log(
                            "INFO", "guard alternative matched", guard=node_id,
                            condition=alternatives[fired - 1])
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
                while not _condition_holds(node.get("condition"), payload, bindings,
                                           caller=interp.caller):
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
                                     collector=raw_evals, caller=interp.caller)
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

    `condition` (RFC-0028 §Reference-level Specification/4): the primary
    condition text, or — when the guard has `alternatives` — the SSOT-joined
    text `guard_condition_text` builds. Mode B's `restore_skips` calls the
    same function, so the two modes cannot independently drift on the join.
    """
    return {"guard": node["id"],
            "mode": node["mode"],
            "condition": guard_condition_text(node.get("condition"),
                                              node.get("alternatives")),
            "steps": _guarded_step_names(nodes, node.get("children", [])),
            "rounds": rounds,
            "evaluations": evaluations if evaluations is not None else []}


CALLER_NAMESPACE = "caller"


def caller_view(claims):
    """Derive the read-only `caller` scope from verified token claims (issue
    #119 A-2/A-3, D2/D3).

    `claims` is `None` when the route carries no verified token (no
    `token_provider` configured, or the route does not require auth) — the
    whole scope is then `None`, distinct from a dict whose fields are merely
    absent. `subject`/`role` are singular by design (D2): no `caller.roles`,
    no `contains` operator.

    Role resolution (D3): `role` (a string claim) wins outright when present,
    valid or not — a malformed `role` claim does not fall back to `roles`.
    Only when `role` is absent does `roles` apply, and only when it is a
    list of exactly one string; zero, two-or-more, or wrong-typed elements
    resolve to no role. Ambiguous is treated as absent, never as a guess.
    """
    if claims is None:
        return None
    subject = claims.get("sub")
    if "role" in claims:
        raw_role = claims["role"]
        role = raw_role if isinstance(raw_role, str) else None
    else:
        roles = claims.get("roles")
        if (isinstance(roles, list) and len(roles) == 1
                and isinstance(roles[0], str)):
            role = roles[0]
        else:
            role = None
    return {"subject": subject, "role": role}


def resolve_reference(name, payload, bindings, caller=None):
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

    `caller` (issue #119, optional, default `None`): the read-only scope
    `caller_view` derived from this run's verified claims. `caller.subject`/
    `caller.role` resolve the same way `input.*` does — a reserved namespace
    checked before the general `bindings` lookup, never a bound row.
    """
    if "." not in name:
        return payload.get(name)
    binding, _, field = name.partition(".")
    if binding == CALLER_NAMESPACE:
        return None if caller is None else caller.get(field)
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


def _resolve_predicate_value(value, payload, bindings, caller=None):
    """A `list where` term's right-side `Value` -> the concrete value a
    driver compares a stored field against (issue #116, D5).

    `caller` (issue #119) threads through to `resolve_reference` exactly as
    every other resolver here does, so `list where` can name `caller.
    subject`/`caller.role` on its right side (`_Scope.resolve_field`
    already accepts it at compile time) without it silently resolving to
    `None` — and matching nothing — at run time.

    Deliberately NOT `eval_value`: that function encodes an instant-shaped
    string operand to epoch-milliseconds (RFC-0016), which would compare a
    `DateTime` field's raw STORED string (`SqliteRepositoryDriver.query`
    reads it via `json_extract`, unencoded — the same representation
    `query_sorted`'s existing `ORDER BY json_extract(...)` already compares
    raw, issue #99 D7) against an encoded int — a type mismatch on one side
    only. Resolving both sides in their stored representation keeps a
    predicate/order comparison consistent with `query_sorted`'s established
    precedent, and needs no int64-bounds enforcement (RFC-0015's own reason
    for that check): mode B never compiles a `list where` predicate at all
    (RFC-0025 §10 — RowSet values are outside its four observation
    classes), so there is no compiled path for this arithmetic to disagree
    with.
    """
    from .condition import Arith, Lit, Ref

    if isinstance(value, Lit):
        return value.value
    if isinstance(value, Ref):
        return resolve_reference(value.name, payload, bindings, caller)
    if isinstance(value, Arith):
        left = _resolve_predicate_value(value.left, payload, bindings, caller)
        right = _resolve_predicate_value(value.right, payload, bindings, caller)
        if left is None or right is None:
            return None
        if value.op == '+':
            return left + right
        if value.op == '-':
            return left - right
        if value.op == '*':
            return left * right
        # '/' — RFC-0028 §1: truncating toward zero, matching `eval_value`.
        if right == 0:
            raise RunError("division by zero in a `list where` predicate")
        quotient, _ = divmod(abs(left), abs(right))
        return -quotient if (left < 0) != (right < 0) else quotient
    raise RunError("unknown predicate value type: %r" % (value,))


def _condition_holds(condition, payload, bindings, collector=None, caller=None,
                      money_fields=None):
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

    `money_fields` (RFC-0044 §3, optional, default `None`): a predicate
    `ref -> bool` — only `spec._expect_result` passes one, so guard evaluation
    (`when`/`until`) never does and RFC-0044 §3's "MoneyLiteral never appears
    in an Operand position" stays true for guards. When given, and `condition`
    is exactly `<ref> <op> <value>` with `<value>` MoneyLiteral-shaped
    (`money.parse_money_literal`) and `money_fields(ref)` true, this evaluates
    the comparison directly — `==`/`!=` as structural wire-dict equality
    (RFC-0044 §3's exact-scale rule makes the two sides' normal form agree);
    any other comparator raises `RunError`, since RFC-0044 §5's order
    evaluator's only caller is RFC-0045's sum/avg/min/max, not `expect
    result`. `MoneyLiteral` is not in `condition.py`'s `Value` grammar at all
    (RFC-0044 §3), so this must run BEFORE `parse_condition` below, which
    would otherwise raise `ConditionError` on the literal token. Every other
    shape (a non-money ref, a non-money-literal-shaped value, no `money_fields`
    at all) falls through unchanged to the existing path.
    """
    if condition is None:
        return True

    if money_fields is not None:
        from . import money
        from .lexer import COMPARATORS

        tokens = condition.split()
        if len(tokens) == 3 and tokens[1] in COMPARATORS and money_fields(tokens[0]):
            ref, op, value_token = tokens
            try:
                parsed = money.parse_money_literal(value_token)
            except money.MoneyError as exc:
                raise RunError(str(exc))
            if parsed is not None:
                if op not in ("==", "!="):
                    raise RunError(
                        "Money order comparisons (%s) are not supported in "
                        "`expect result` — only sum/avg/min/max evaluate "
                        "Money order (RFC-0044 §5); use == or != instead." % op)
                actual = resolve_reference(ref, payload, bindings, caller)
                return (actual == parsed) if op == "==" else (actual != parsed)

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
        raw = resolve_reference(cond.field, payload, bindings, caller)
        holds = (raw is not None) if cond.kind == "exists" else (raw is None)
        if collector is not None:
            collector.append({"ref": cond.field, "value": raw, "op": cond.kind,
                              "expected": None, "holds": holds})
        return holds

    if isinstance(cond, Comparison):
        return _comparison_holds(cond, condition, payload, bindings, collector, caller)

    if isinstance(cond, And):
        # Every term is evaluated, not short-circuited: the terms are pure, so
        # the result is the same, and a value fault in a later term must surface
        # in both modes rather than depending on where the run stopped reading.
        results = [_comparison_holds(term, condition, payload, bindings, collector, caller)
                   for term in cond.terms]
        return all(results)

    raise RunError(f"Unknown condition type: {type(cond)}")


def _comparison_holds(cmp_node, condition, payload, bindings, collector=None, caller=None):
    """One `Comparison` against this scope. Unresolved reference -> False.

    `collector` (issue #83): see `_condition_holds`. `ref` is the left
    operand's normalized text (`_value_text` — a bare `Ref` renders as its own
    dotted name), and `value`/`expected` are the left/right operands as
    evaluated here, unmasked (`_masked_evaluation` in `_flatten_items` masks a
    sensitive one before it reaches a skip record).
    """
    left = eval_value(cmp_node.left, condition, payload, bindings, caller)
    right = eval_value(cmp_node.right, condition, payload, bindings, caller)
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


def eval_value(value, condition, payload, bindings, caller=None):
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
        raw = resolve_reference(value.name, payload, bindings, caller)
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
        left = eval_value(value.left, condition, payload, bindings, caller)
        right = eval_value(value.right, condition, payload, bindings, caller)
        if left is None or right is None:
            return None
        if value.op == '+':
            result = left + right
        elif value.op == '-':
            result = left - right
        elif value.op == '*':
            result = left * right
        else:  # '/' — RFC-0028 §1: truncating (toward zero), not Python floor
            if right == 0:
                raise RunError(
                    "division by zero: %s (in %r)"
                    % (_value_text(value), condition))
            # Integer-only (no float: an i64 magnitude exceeds float64's exact
            # range) truncation toward zero, matching mode B's `arith.divsi`.
            quotient, _ = divmod(abs(left), abs(right))
            result = -quotient if (left < 0) != (right < 0) else quotient
        if result < INT64_MIN or result > INT64_MAX:
            raise RunError(
                "value out of the 64-bit range: %s = %d (in %r)"
                % (_value_text(value), result, condition))
        return result
    raise RunError(f"Unknown value type: {type(value)}")


def eval_aggregate(agg, expression, rowsets, agg_field_type=None):
    """A parsed `Aggregate` -> int/str/dict (RFC-0025 §5, RFC-0045 §3-§5,
    RFC-0047 §Reference-level Specification/3).

    An absent or empty RowSet binding sums/counts to 0 — not None, not a
    fault. That covers two cases identically: this workflow never `list`ed
    the entity at all (the `aggregation-orphaned-list` warning's case,
    RFC-0025 §4), and it did, but the store had no rows for it. Both are
    "nothing to aggregate," and RFC-0025's own decision is that neither is an
    error — a report with no links is a normal state, not an exception.
    `avg`/`min`/`max` have no such identity element (RFC-0045 §3/§4): an
    empty RowSet fails with `avg-of-empty-rowset` / `min-max-of-empty-rowset`.

    A row that IS present but cannot supply the aggregated field is different:
    the field's declared type is checked at compile time (RFC-0025 §3,
    RFC-0045 §2), but a driver can still hand back a row that was never
    written with it (a plain `create` writes only `id` —
    `interp.FakeRepository.execute`). That is the same fault an unresolved
    `Value` reference already is in an assignment (`eval_value` returning
    None -> `RunError`), so it raises here too rather than silently treating
    one row as 0 and the rest as data.

    For any NON-EMPTY RowSet this still dispatches on each row value's own
    Python shape: `dict` -> Money (RFC-0044 §1's `{"amount", "currency"}`),
    `str` -> DateTime (RFC-0016 §2's stored instant text), plain `int`/`bool`
    -> Integer. `lower.py`'s static rejection (RFC-0045 §2) already limits
    which shape a legal program's rows can carry, so this is safe whenever
    there is at least one row to inspect — `agg_field_type` is not consulted
    there.

    Load-bearing decision (RFC-0047, previously recorded on the blackboard as
    open): a Money field's declared type CANNOT be recovered from an EMPTY
    RowSet's rows, since there are none to inspect. `agg_field_type` is
    `lower.py`'s `_check_aggregate`-computed base type, carried on the
    `Assignment` IR node (RFC-0047 §1/§2) and forwarded here by `_run_effect`
    as an optional keyword — the signature is unchanged for every existing
    positional caller. When the RowSet is empty, `func == "sum"`, and
    `agg_field_type == "Money"`, the result is RFC-0045 §5's
    `{"amount": "0", "currency": null}` instead of plain integer `0`. An IR
    document compiled before RFC-0047 (no `agg_field_type` key, so this
    parameter stays `None`) keeps the old plain-`0` result — a deliberate
    backward-compatibility floor, not a bug: language semantics are fixed by
    RFC-0047, but an already-compiled artifact only observes them after
    recompilation.
    """
    binding = agg.ref.namespace or agg.ref.name
    rows = rowsets.get(binding) or []
    if agg.func == "count":
        return len(rows)

    field = agg.ref.field
    values = []
    for row in rows:
        if not isinstance(row, dict) or field not in row:
            raise RunError(
                "aggregate %r: a row in the %r RowSet has no %r field"
                % (expression, binding, field))
        values.append(row[field])

    if agg.func in ("sum", "avg"):
        return _eval_sum_avg(agg.func, values, field, expression,
                             agg_field_type=agg_field_type)
    return _eval_minmax(agg.func, values, field, expression)


def _money_run_error(expression, err):
    return RunError("aggregate %r: %s — %s" % (expression, err.code, err.message))


def _decode_money(minor, currency):
    """The inverse of `money.encode_money` — a minor-unit int + currency back
    to the `{"amount", "currency"}` wire shape (RFC-0044 §1)."""
    from . import money
    exp = money.exponent(currency)
    sign = "-" if minor < 0 else ""
    digits = str(abs(minor))
    if exp:
        digits = digits.rjust(exp + 1, "0")
        amount = digits[:-exp] + "." + digits[-exp:]
    else:
        amount = digits
    return {"amount": sign + amount, "currency": currency}


def _eval_sum_avg(func, values, field, expression, agg_field_type=None):
    """RFC-0045 §3/§5: `sum`/`avg` over Integer or Money row values.

    RFC-0047 §3: an empty `sum` over a Money field returns the Money-shaped
    zero (`agg_field_type` is the only place this parameter is consulted —
    every other branch below is byte-for-byte RFC-0045's original rule)."""
    from . import money

    if func == "avg" and not values:
        raise RunError(
            "aggregate %r: avg-of-empty-rowset — averaging %r needs at "
            "least one row" % (expression, field))
    if not values:
        if func == "sum" and agg_field_type == "Money":
            return {"amount": "0", "currency": None}
        return 0

    if isinstance(values[0], dict):
        pairs = []
        for value in values:
            if not isinstance(value, dict) or "amount" not in value \
                    or "currency" not in value:
                raise RunError(
                    "aggregate %r: cannot %s non-Money %s=%r"
                    % (expression, func, field, value))
            try:
                pairs.append(money.encode_money(value["amount"], value["currency"]))
            except money.MoneyError as e:
                raise _money_run_error(expression, e)
        total_pair = pairs[0]
        for pair in pairs[1:]:
            try:
                total_pair = money.add(total_pair, pair)
            except money.MoneyError as e:
                raise _money_run_error(expression, e)
        minor, currency = total_pair
        minor = _checked(minor, field, expression)
        if func == "avg":
            minor = money.avg_round(minor, len(values))
        return _decode_money(minor, currency)

    total = 0
    for value in values:
        if isinstance(value, bool):
            value = 1 if value else 0
        elif not isinstance(value, int):
            raise RunError(
                "aggregate %r: cannot %s non-numeric %s=%r"
                % (expression, func, field, value))
        total = _checked(total + value, field, expression)
    if func == "sum":
        return total
    return money.avg_round(total, len(values))


def _eval_minmax(func, values, field, expression):
    """RFC-0045 §4: `min`/`max` over Integer, DateTime, or Money row values.
    Comparison uses each type's encoded ordering key; the returned value is
    always the untouched row value that won (D10 — a DateTime `min` must not
    surface an epoch-ms integer, breaking the field's wire shape)."""
    if not values:
        raise RunError(
            "aggregate %r: min-max-of-empty-rowset — `%s %s` needs at "
            "least one row" % (expression, func, field))
    first = values[0]
    if isinstance(first, dict):
        return _minmax_money(func, values, field, expression)
    if isinstance(first, str):
        return _minmax_datetime(func, values, field, expression)
    return _minmax_integer(func, values, field, expression)


def _minmax_integer(func, values, field, expression):
    def key_of(value):
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, int):
            return value
        raise RunError(
            "aggregate %r: cannot compare non-numeric %s=%r"
            % (expression, field, value))

    best = values[0]
    best_key = key_of(best)
    for value in values[1:]:
        key = key_of(value)
        if (key < best_key) if func == "min" else (key > best_key):
            best, best_key = value, key
    return best


def _minmax_datetime(func, values, field, expression):
    from .condition import ConditionError, encode_instant

    def key_of(value):
        if not isinstance(value, str):
            raise RunError(
                "aggregate %r: cannot compare non-DateTime %s=%r"
                % (expression, field, value))
        try:
            return encode_instant(value, field)
        except ConditionError as e:
            raise RunError("%s (in aggregate %r)" % (e, expression))

    best = values[0]
    best_key = key_of(best)
    for value in values[1:]:
        key = key_of(value)
        if (key < best_key) if func == "min" else (key > best_key):
            best, best_key = value, key
    return best


def _minmax_money(func, values, field, expression):
    from . import money

    def encode(value):
        if not isinstance(value, dict) or "amount" not in value \
                or "currency" not in value:
            raise RunError(
                "aggregate %r: cannot compare non-Money %s=%r"
                % (expression, field, value))
        try:
            return money.encode_money(value["amount"], value["currency"])
        except money.MoneyError as e:
            raise _money_run_error(expression, e)

    best = values[0]
    best_pair = encode(best)
    for value in values[1:]:
        pair = encode(value)
        try:
            cmp = money.compare(pair, best_pair)
        except money.MoneyError as e:
            raise _money_run_error(expression, e)
        if (cmp < 0) if func == "min" else (cmp > 0):
            best, best_pair = value, pair
    return best


def eval_format(fmt, payload, bindings, caller=None):
    """A parsed `FormatCall` -> str, or None when an argument reference
    resolves to nothing (issue #94) — the same "unresolved reference"
    contract `eval_value` uses for a `Value`, so the caller's existing
    None -> RunError translation covers this RHS kind too.

    Substitution is a plain, sequential `{}` replace — not `str.format`,
    which would also interpret `{name}`/`{0}` and accept a template wider
    than the positional-only grammar `condition.parse_format` already
    enforces (issue #94, D1: no named fields, no padding, no precision).
    """
    parts = []
    for ref in fmt.args:
        raw = resolve_reference(ref.name, payload, bindings, caller)
        if raw is None:
            return None
        parts.append(str(raw))
    out = fmt.template
    for part in parts:
        out = out.replace("{}", part, 1)
    return out


def _checked(number, name, condition):
    from .condition import INT64_MAX, INT64_MIN
    if number < INT64_MIN or number > INT64_MAX:
        raise RunError("value out of the 64-bit range: %s = %d (in %r)"
                       % (name, number, condition))
    return number


def _value_text(value):
    from .condition import value_to_string
    return value_to_string(value)


SCHEMA_GEN_KEY = "_schema_gen"


def schema_generation(entity_node):
    """sha256 12-hex digest of `entity_node`'s declared, non-derived (name,
    type) field pairs, sorted (issue #147). Deterministic and timestamp-free
    — `provenance.py`'s own digest precedent (no build-host/wall-clock
    identifiers, only the compiled shape), narrowed to one entity's fields
    rather than the whole document. A `derived` field is excluded: it is
    never persisted (see `row_shape_mismatches`), so it cannot be part of a
    stored row's shape.
    """
    fields = sorted((f["name"], f["type"]) for f in entity_node.get("fields", [])
                    if not f.get("derived"))
    encoded = json.dumps(fields, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def strip_schema_gen(row):
    """Drop the `_schema_gen` reserved key before a stored row reaches any
    observable surface (issue #147 D3): a binding, a RowSet, a `respond`, an
    HTTP response. The key is a storage-layer implementation detail the
    `RepositoryDriver` SPI itself never knows about — every driver stores and
    returns it like any other payload key — so every caller that reads a row
    back from a repository is the one responsible for stripping it here.

    Mutates `row` in place and returns it, rather than rebuilding a plain
    `dict` — `SqliteRepositoryDriver._read`'s result carries an
    `observed_version` attribute (`_VersionedRow`) that `persist()`'s
    optimistic lock (issue #92) and `wsgi.py`'s ETag (issue #113 D12) both
    read afterward; rebuilding would silently drop it.
    """
    if isinstance(row, dict):
        row.pop(SCHEMA_GEN_KEY, None)
    return row


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


def _note_values(interp, refs, payload, bindings):
    """A `note`'s `refs` -> resolved values, in template order (issue #111,
    D4). Each is resolved through `resolve_reference` — the ONE resolver
    every other reader uses — then masked through the same `mask_payload`
    chokepoint `_masked_evaluation` applies to a guard's collected values
    (issue #43: no second masking rule for this channel either). An
    unresolved reference (no such binding, no such field) is `None`, not a
    fault — this is an observability channel, and it must not be able to
    fail a run over a stale reference.
    """
    values = []
    for ref in refs:
        raw = resolve_reference(ref, payload, bindings, interp.caller)
        if raw is None or "." not in ref:
            values.append(raw)
            continue
        binding, _, field = ref.partition(".")
        if binding == PAYLOAD_NAMESPACE:
            values.append(raw)
            continue
        entity_id = interp._entity_id_for_binding(binding)
        if entity_id is None:
            values.append(raw)
            continue
        entity_view = interp._entity_view(interp.nodes[entity_id])
        masked = mask_payload({field: raw}, entity_view)
        values.append(masked[field])
    return values


class Interpreter:
    def __init__(self, document, clock=None, repo_rows=None,
                 correlation_id="cid-0001", *, repository=None, cache=None,
                 network=None, claims=None):
        """`repository`/`cache`/`network` bind the declared capabilities to a
        real backend (issue #25, #64); with none given, this builds exactly
        the in-memory set it always did.

        All three are keyword-only, after a bare `*`. The four positional
        parameters keep their order and meaning, so none of the existing call
        sites changes — and a stale positional call cannot silently bind a
        driver to `correlation_id`, which is the failure a middle insertion
        would have caused at every one of them.

        `claims` (issue #119, keyword-only, default `None`): the verified
        bearer token claims this request carried, or `None` when the route
        has no token_provider/auth requirement. Derived once into
        `self.caller` via `caller_view` — guards and assignments read
        `caller.subject`/`caller.role` through the same resolver `input.*`
        uses, never the raw claims dict.
        """
        self.doc = document
        self.nodes = {n["id"]: n for n in document["nodes"]}
        self.refinements = refinement_index(document)
        self.clock = clock or Clock()
        self.caller = caller_view(claims)
        if repository is None:
            self.repo = FakeRepository(repo_rows)
        else:
            # The seed rule is the store's, not the Fake's: a real driver gets
            # the same rows and inserts only what is absent, so a row an
            # earlier run left behind survives this one's seeding.
            self.repo = repository
            self.repo.seed(repo_rows or {})
        self.cache = cache if cache is not None else FakeCache(self.clock)
        # RFC-0027 §1: no stub table by default — every unstubbed target gets
        # the deterministic (200, {}) FakeNetworkDriver already answers.
        self.network = network if network is not None else FakeNetworkDriver()
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
               "cache_ttl_ms": None, "response_slo_ms": None, "mechanisms": [],
               # issue #108 D2-r1: the declared cap, or `None` when `parallel`
               # is bare (or absent) — `_run_parallel_block` falls back to
               # the block's own step count in that case, since it is the
               # one place that knows how many steps a given block has.
               "parallel_cap": None}
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
                    elif rule["name"] == "parallel":
                        out["parallel_cap"] = rule.get("value")
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
        masked = {}
        for name, row in bindings.items():
            view = views.get(name)
            if view is None:
                # issue #97 / RFC-0012 Updates: `name` may be a `create ...
                # as <name>` binding — its row DOES have a declared Entity
                # shape (unlike a NetworkCall result), just not under this
                # entity's own binding name, so `views.get(name)` misses it.
                # Without this, a Password field seeded from the payload
                # would leave this chokepoint unmasked.
                entity_id = getattr(row, "entity_id", None)
                entity_node = self.nodes.get(entity_id) if entity_id else None
                if entity_node is not None:
                    view = self._entity_view(entity_node)
            masked[name] = mask_payload(row, view)
        return masked

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
        # issue #96: refs from every `Response` node a step that actually ran
        # (not one a guard skipped, not one that failed) owns, in program
        # order. Collected here rather than by a second walk of the document
        # after the fact, so a guard that never fired contributes nothing —
        # the same rule every other Effect gets from this loop.
        response_refs = []
        # issue #111, D4: same collection shape as `response_refs`, but
        # resolved to VALUES immediately rather than deferred to end-of-run
        # — a `note` is a span annotation, a snapshot of `bindings` at the
        # point it ran, not a final-state read like `respond`'s FieldMask.
        # Resolving it here (right after `_run_step` returns for the SAME
        # step, before any later step can mutate the same row) is what
        # keeps that snapshot honest.
        notes = []
        # issue #79, RFC-0032: one transaction per execution, not per step.
        # `begin()` opens it before the first step; exactly one of
        # `commit()`/`rollback()` below closes it before this method
        # returns or re-raises. A `RunError` escaping the loop itself (e.g.
        # a guard condition `_flatten_items` cannot evaluate) never reaches
        # the per-step `except` below, so it is caught here too — otherwise
        # that path would leave the transaction open.
        self.repo.begin()
        try:
            for item_id in _flatten_items(self.nodes, wf.get("children", []), self,
                                         result, root, con, payload, bindings):
                if isinstance(item_id, _ParallelGroup):
                    # issue #108 D1: a whole scope, not a single step — see
                    # `_run_parallel_block`. It does its own fail-fast
                    # short-circuiting internally; this loop only needs to
                    # stop pulling further items once it has.
                    self._run_parallel_block(item_id, wf["name"], result, root,
                                             con, payload, bindings, rowsets,
                                             deadline, response_refs, notes)
                    if result["status"] == "failed":
                        break
                    continue
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
                                        # issue #111, D5: `Annotation` is not
                                        # an Effect (issue #96's `Response`
                                        # precedent) — `spec.py`'s `effects
                                        # <N>` count must not see a `note`
                                        # any differently than it saw a
                                        # `respond` before this feature.
                                        "effects": [self.nodes[c]["kind"]
                                                    for c in step.get("children", [])
                                                    if self.nodes[c]["kind"] != "Annotation"]})
                if last_error is None:
                    for child_id in step.get("children", []):
                        child = self.nodes[child_id]
                        if child["kind"] == "Response":
                            response_refs.extend(child["refs"])
                        elif child["kind"] == "Annotation":
                            notes.append({"template": child["template"],
                                         "values": _note_values(
                                             self, child["refs"], payload, bindings)})
                if last_error is not None:
                    result["status"] = "failed"
                    result["failed_step"] = step["name"]
                    result["failure_reason"] = str(last_error)
                    # issue #113, D2: `map_result` (wsgi.py) sees only this dict,
                    # never the exception — so the failure's TYPE has to ride
                    # along as a field, not be re-derived by matching against
                    # `failure_reason`'s wording (that is M6's mistake, issue
                    # #113/#128 forbid repeating it). Two carriers, one per
                    # raise site: `__cause__` is the original `DriverError` a
                    # real driver's `raise RunError(...) from exc` chained
                    # (currently only ever a `ConflictError`); `failure_kind`
                    # is the attribute a bare `RunError` carries when raised
                    # directly — `FakeRepository`'s create-conflict (D2) and
                    # `_run_step`'s deadline-exhausted raise (issue #128) both
                    # set it. Neither carrier is present on a failure this
                    # feature does not know about.
                    if isinstance(last_error.__cause__, ConflictError):
                        result["failure_kind"] = "conflict"
                    else:
                        kind = getattr(last_error, "failure_kind", None)
                        if kind is not None:
                            result["failure_kind"] = kind
                    self.trace.log("ERROR", "step failed",
                                   step=step["name"], reason=str(last_error))
                    break
                if deadline is not None and self.clock.now > deadline:
                    result["status"] = "failed"
                    result["failed_step"] = step["name"]
                    result["failure_reason"] = ("deadline exceeded after step %r"
                                                % step["name"])
                    result["failure_kind"] = "deadline"
                    self.trace.log("ERROR", "deadline exceeded",
                                   step=step["name"], deadline_ms=con["timeout_ms"])
                    break
        except RunError:
            self.repo.rollback()
            raise
        if result["status"] == "completed":
            self.repo.commit()
        else:
            self.repo.rollback()
            if con["rollback"]:
                self.trace.log(
                    "INFO", "rollback: execution boundary rolled back, "
                            "writes made during this run are discarded")

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
        # issue #96, D3/D4: additive and non-destructive — a workflow with no
        # `respond` (no refs collected) gets no `response` key at all, so its
        # `result` is unchanged from before this feature existed. Built from
        # `result["bindings"]`, i.e. AFTER the masking chokepoint, per RFC-0003
        # §Observability — no second masking rule for this channel either.
        if result["status"] == "completed" and response_refs:
            response = {}
            for ref in response_refs:
                binding, _, field = ref.partition(".")
                response.setdefault(binding, {})[field] = \
                    result["bindings"][binding][field]
            result["response"] = response
        # issue #102, D5: additive and non-destructive, the same `response`
        # precedent (issue #96) — a run that never emits gets no `emissions`
        # key at all, so it stays byte-identical to before this feature
        # existed. Unlike `response` this is NOT gated on `status ==
        # "completed"`: `spec.py`'s `emitted` assertion already reads
        # `self.outbox` unconditionally (RFC-0003 — the synchronous part of
        # `emit` ends at registering the publish, before whatever runs
        # after it), and this clause is that same surface on the JSON
        # result, so the two must not disagree about what a failed run
        # still registered.
        if self.outbox:
            result["emissions"] = list(self.outbox)
        # issue #111, D4: same `emissions` precedent — additive, and NOT
        # gated on `status == "completed"`. A `note` is exactly the
        # observability channel a failed run needs most (the issue's own
        # motivation: domain context for a failure the trace cannot show),
        # so a step that ran and noted something before a LATER step failed
        # must not lose that note.
        if notes:
            result["notes"] = notes
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

    def _run_step(self, step, span, con, payload, deadline, bindings, rowsets,
                 lock=None):
        # issue #108 D4: `lock` is `None` on every pre-#108 call site (the
        # sequential main loop) and this method is then byte-identical to
        # before — the `if lock is not None` guards below are no-ops. Only
        # `_run_parallel_block` passes a real `threading.RLock`, held for
        # everything here EXCEPT the one place D4 carves out
        # (`_run_effect`'s NetworkCall branch, below) — repository/cache
        # calls and every `bindings`/`rowsets` mutation stay serialized.
        if lock is not None:
            lock.acquire()
        try:
            if deadline is not None and self.clock.now >= deadline:
                exhausted = RunError("deadline exhausted before step %r" % step["name"])
                exhausted.failure_kind = "deadline"
                raise exhausted
            for child_id in step.get("children", []):
                effect = self.nodes[child_id]
                self._run_effect(effect, span, con, payload, bindings, rowsets,
                                 deadline, lock=lock)
            self.clock.advance()
        finally:
            if lock is not None:
                lock.release()

    def _run_effect(self, effect, span, con, payload, bindings, rowsets,
                    deadline=None, lock=None):
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
            from .condition import Aggregate, FormatCall, parse_value_or_aggregate
            rhs = parse_value_or_aggregate(effect["expression"])
            if isinstance(rhs, Aggregate):
                # RFC-0025 §5: sums/counts the RowSet, never a "resolves to
                # nothing" — an absent or empty RowSet is 0, not a fault.
                # RFC-0047 §3: `agg_field_type` is absent on a non-aggregate
                # or `count` Assignment, and on any Assignment compiled
                # before RFC-0047 — `.get()` yields `None` in all three
                # cases, which `eval_aggregate` treats as "no Money-zero
                # special case, fall back to the RFC-0045 behavior."
                value = eval_aggregate(rhs, effect["expression"], rowsets,
                                       agg_field_type=effect.get("agg_field_type"))
            elif isinstance(rhs, FormatCall):
                value = eval_format(rhs, payload, bindings, self.caller)
            else:
                value = eval_value(rhs, effect["expression"], payload, bindings, self.caller)
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
                # issue #97 / RFC-0012 Updates: `binding` may be a `create
                # ... as <name>` result — a namespace `_entity_id_for_binding`
                # cannot see (it is built from entities' OWN binding names,
                # not from author-chosen `as` names) — so the entity id rides
                # on the row itself instead (`_CreatedRow.entity_id`).
                entity_id = getattr(row, "entity_id", None)
            if entity_id is None:
                raise RunError(
                    "assignment target %r names no declared entity, so the "
                    "write has no row to address" % target)
            entity_node = self.nodes.get(entity_id)
            stamped = entity_node is not None and not isinstance(self.repo, FakeRepository)
            if stamped:
                # issue #147 D2/D3: mutate `row` in place rather than
                # `dict(row, ...)` — a real driver's read binds a
                # `_VersionedRow`, and a plain-dict copy would silently drop
                # its `observed_version`, turning every conditional UPDATE
                # into an unconditional one (issue #92's optimistic lock).
                # Reverted in `finally`, so the stamp never becomes an
                # observable field of a live run. `FakeRepository` is
                # skipped — it has no cross-run identity for a "schema
                # generation" to track, and its own contract tests assert a
                # stored row's exact content.
                row[SCHEMA_GEN_KEY] = schema_generation(entity_node)
            try:
                self.repo.persist(entity_id, row_key(entity_id, payload), row)
            except DriverError as exc:
                raise RunError(str(exc)) from exc
            finally:
                if stamped:
                    row.pop(SCHEMA_GEN_KEY, None)
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
            #
            # issue #116, D5: `predicate`/`order`/`limit` all `None` (no
            # `where`/`order by`/`limit` clause) is the unchanged call —
            # `self.repo.query(effect["entity"])`, one positional argument,
            # byte-identical to the pre-#116 shape (this issue's constraint).
            # Only when one of the three is present does the driver's
            # `supports_predicate` opt-in decide whether it is pushed down
            # or applied here, over an over-fetched row_count (D5's "core
            # over-receives, then post-processes" fallback).
            predicate = None
            if effect.get("predicate"):
                predicate = [(term["field"], term["op"],
                             _resolve_predicate_value(
                                 parse_value(term["value"]), payload, bindings,
                                 self.caller))
                            for term in effect["predicate"]]
            order = ((effect["order"]["field"], effect["order"]["desc"])
                    if effect.get("order") else None)
            limit = effect.get("limit")
            try:
                if predicate is None and order is None and limit is None:
                    rows = self.repo.query(effect["entity"])
                elif getattr(self.repo, "supports_predicate", False):
                    rows = self.repo.query(effect["entity"], predicate=predicate,
                                          order=order, limit=limit)
                else:
                    rows = self.repo.query(effect["entity"])
                    rows = apply_predicate(rows, predicate, order, limit)
                    self.trace.log("INFO", "predicate-not-pushed-down",
                                   entity=effect["entity"])
            except DriverError as exc:
                raise RunError(str(exc)) from exc
            # issue #147 D3: never expose the storage-layer stamp through a
            # RowSet — `list`'s only observable surface for stored rows.
            rows = [strip_schema_gen(r) for r in rows]
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
            # issue #147 D3: never expose the storage-layer stamp through a
            # `read` binding — the row's only observable surface here.
            row = strip_schema_gen(row)
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
                    # issue #85: a schema change that ran ahead of a
                    # backfill is otherwise silent — the row simply reads
                    # back wrong-shaped. Warn (never block: RFC-0021's
                    # "does editing the program remove it" says warning
                    # here means "editing the *data* removes it").
                    for mismatch in row_shape_mismatches(
                            entity_node, row, self.refinements):
                        self.diagnostics.add(
                            code="stored-row-shape-mismatch",
                            where=effect["id"], subject=entity_node["name"],
                            message=(
                                "stored row is missing declared field %r "
                                "(expected %s)"
                                % (mismatch["field"], mismatch["expected_type"])
                                if mismatch["kind"] == "missing" else
                                "stored row field %r does not match its "
                                "declared type %s"
                                % (mismatch["field"], mismatch["expected_type"])),
                            line=self.nodes[effect["id"]].get("line"))
            if effect["operation"] == "read" and row is None:
                self.clock.advance(1)
                child.end_ms = self.clock.now
                raise RunError("repository read found no row for %s" % effect["entity"])
            if effect["operation"] == "create":
                # issue #97 / RFC-0012 Updates: payload seeding — same-named,
                # non-derived fields copy into the row created above,
                # regardless of `as` ("뼈대 행" fix, issue #97 §3). `as`
                # additionally binds the seeded row into `bindings` so a
                # later `set`/`format`/`respond` can address it, the same
                # scope a `read` binding gets (RFC-0027 §2 notation reused).
                created_key = row_key(effect["entity"], payload)
                entity_node = self.nodes.get(effect["entity"])
                seeded = {"id": created_key}
                if entity_node is not None:
                    for field in entity_node.get("fields", []):
                        if field.get("derived"):
                            continue
                        fname = field["name"]
                        if fname in payload:
                            seeded[fname] = payload[fname]
                if len(seeded) > 1:
                    # issue #147 D2/D3: `FakeRepository` is skipped (see the
                    # Assignment branch above for why); `seeded` is mutated
                    # in place and reverted in `finally` — it is what
                    # `bindings[effect["result"]]` exposes below, and the
                    # stamp must never reach that surface.
                    stamped = (entity_node is not None
                              and not isinstance(self.repo, FakeRepository))
                    if stamped:
                        seeded[SCHEMA_GEN_KEY] = schema_generation(entity_node)
                    try:
                        self.repo.persist(effect["entity"], created_key, seeded)
                    except DriverError as exc:
                        raise RunError(str(exc)) from exc
                    finally:
                        if stamped:
                            seeded.pop(SCHEMA_GEN_KEY, None)
                if effect.get("result"):
                    bindings[effect["result"]] = _CreatedRow(seeded, effect["entity"])
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
            # RFC-0027 §3: the driver is invoked whether or not the call is
            # bound — this is what makes NetworkCall a real outbound call
            # rather than the trace-only simulation it was before this RFC.
            # `as`-less calls still observe nothing new (§ below), which is
            # what keeps the unbound path byte-identical to the pre-RFC-0027
            # no-op (backward compatibility, golden silence).
            remaining_ms = ((deadline - self.clock.now) if deadline is not None
                            else DEFAULT_NETWORK_TIMEOUT_MS)
            # issue #107, D6/D11: trace-id is invariant for this run;
            # parent-id becomes THIS step's span id, so a downstream service
            # sees the call site, not the workflow root. A non-HTTP run
            # (`lnpl run`) never populates `self.trace.trace_id` (it stays
            # `None`), so no header is sent there — only `LnplWsgiApp`
            # requests carry one.
            trace_id = self.trace.trace_id
            trace_headers = None
            if trace_id is not None:
                span_id = child.attrs.get("span_id")
                if span_id is None:
                    span_id = new_span_id()
                    child.attrs["span_id"] = span_id
                # r1-F1/D6: propagate the flags _resolve_trace_context
                # already decided (inherited on adoption, "01" when we
                # minted the trace ourselves) rather than defaulting here.
                flags = self.trace.flags or "01"
                trace_headers = {"traceparent": format_traceparent(trace_id, span_id, flags)}
                if self.trace.tracestate is not None:
                    trace_headers["tracestate"] = self.trace.tracestate
            # issue #109, D6: `with <ref>...` path arguments are resolved to
            # their bound values here — the same `resolve_reference` every
            # other RHS in this method reads through — and handed to the
            # driver RAW; the driver (which alone knows the declared `path`
            # template) does the `{}` substitution and the percent-encoding
            # (`drivers._assemble_path`), so both `NetworkDriver`
            # implementations escape identically.
            path_args = None
            if effect.get("path_args"):
                path_args = []
                for ref in effect["path_args"]:
                    value = resolve_reference(ref, payload, bindings, self.caller)
                    if value is None:
                        raise RunError(
                            "NetworkCall %r: `with` reference %r resolved to "
                            "nothing" % (effect["id"], ref))
                    path_args.append(value)
            # issue #108 D4: the ONE point in a locked step where the lock
            # is dropped — the whole reason a `parallel` block is faster is
            # that N of these can be in flight while their threads hold no
            # lock at all. `_run_step`'s own `finally` still releases once
            # more when this method returns; reacquiring here first keeps
            # that release balanced (and every mutation below — `child.attrs`,
            # `bindings` — happens with the lock held again).
            if lock is not None:
                lock.release()
            try:
                status, body, _headers = self.network.call(
                    effect["target"], payload, remaining_ms, trace_headers,
                    path_args=path_args)
            except DriverError as exc:
                if effect.get("result"):
                    # RFC-0027 §3, D3: a bound call's transport failure is a
                    # value the guard can branch on, not a run failure.
                    status, body = 0, {}
                else:
                    # The fifth `DriverError`->`RunError` translation site
                    # (Assignment's persist, RepositoryCall's query/execute,
                    # CacheAccess, and this one) — an observation-only step
                    # must not silently swallow a real failure (RFC-0027 §3).
                    raise RunError(str(exc)) from exc
            finally:
                if lock is not None:
                    lock.acquire()
            child.attrs["target"] = effect.get("target")
            if effect.get("result"):
                child.attrs["status"] = status
                # RFC-0027 §2/§4: flattened — `status` plus the body's
                # top-level keys in one dict, since `Reference` (RFC-0012
                # §G12.1) reads at most two segments (`<name>.<field>`) and
                # cannot express `<name>.body.<key>`. `status` wins any key
                # collision with the body.
                bound = dict(body) if isinstance(body, dict) else {}
                bound["status"] = status
                bindings[effect["result"]] = bound
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
            # issue #102: persisted before the in-memory outbox sees it, so a
            # driver fault here (translated to RunError below, the same as
            # every other repo call) never leaves an emission counted in
            # `self.outbox`/`result["emissions"]` that the durable store does
            # not actually have.
            try:
                self.repo.record_emission(emission)
            except DriverError as exc:
                raise RunError(str(exc)) from exc
            self.outbox.append(emission)
            child.attrs["event"] = event_ref
            child.attrs["emission_id"] = emission["emission_id"]
            self.trace.log("INFO", "event publish registered",
                           event=event_ref, emission_id=emission["emission_id"])
        elif kind == "Response":
            # issue #96: declarative — `run_workflow` reads `effect["refs"]`
            # off this step and assembles `result["response"]` from
            # `bindings` after the run completes. Nothing to evaluate here;
            # this branch exists only so the step's effect walk does not
            # treat an unrecognized kind as unimplemented (the `else` below).
            pass
        elif kind == "Annotation":
            # issue #111, D4: declarative, the same `Response` precedent —
            # `run_workflow` resolves `effect["refs"]`/`effect["template"]`
            # into `result["notes"]` right after this step returns (while
            # `bindings` still holds THIS step's values, not a later step's
            # overwrite), which is why nothing runs here.
            pass
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

    # ---- issue #108: `parallel` block execution ----------------------------

    def _execute_step_with_retry(self, step, workflow_name, con, payload,
                                 deadline, bindings, rowsets, lock,
                                 cancel_event):
        """Run one step to completion under its retry policy; never raises —
        returns `(span, entry, error, response_ext, notes_ext)`, `error`
        being the final `RunError` or `None`. `_run_parallel_block`'s
        per-step worker (only caller): the sequential main loop keeps its
        own, separate inline copy of this same shape rather than calling
        here, so that loop's behaviour for a workflow with no `parallel`
        block is provably untouched by this method's existence (issue #108
        DoD 7).

        `span`'s start/end are real wall-clock milliseconds, not the virtual
        `self.clock` every other span uses — D6's reason: sibling spans that
        share one incrementing counter can never show overlap, and overlap
        IS the evidence a `parallel` block actually ran concurrently.
        `self.clock` itself still advances normally (under `lock`) for
        deadline/backoff bookkeeping — only the SPAN timestamps are real time.
        """
        span = Span(step["name"], "WorkflowStep", _wall_clock_ms())
        attempts = 0
        last_error = None
        while True:
            attempts += 1
            if attempts > 1 and cancel_event.is_set():
                # D3/D7: a sibling's failure stops the NEXT retry attempt,
                # never the one already in flight (a thread cannot be
                # stopped mid-attempt, only kept from starting another).
                break
            try:
                self._run_step(step, span, con, payload, deadline, bindings,
                               rowsets, lock=lock)
                last_error = None
                break
            except RunError as exc:
                last_error = exc
                if not self._retryable(step, con, attempts, deadline):
                    break
                with lock:
                    self.trace.log("WARN", "step retry", step=step["name"],
                                   attempt=attempts, reason=str(exc))
                    self.clock.advance(_backoff_ms(attempts))
        span.end_ms = _wall_clock_ms()
        response_ext, notes_ext = [], []
        with lock:
            span.attrs["attempts"] = attempts
            self.trace.metric("step.duration_ms",
                              {"workflow": workflow_name, "step": step["name"]},
                              span.duration_ms)
            entry = {"step": step["name"], "attempts": attempts,
                     "duration_ms": span.duration_ms,
                     "effects": [self.nodes[c]["kind"]
                                for c in step.get("children", [])
                                if self.nodes[c]["kind"] != "Annotation"]}
            if last_error is None:
                for child_id in step.get("children", []):
                    child = self.nodes[child_id]
                    if child["kind"] == "Response":
                        response_ext.extend(child["refs"])
                    elif child["kind"] == "Annotation":
                        notes_ext.append({"template": child["template"],
                                          "values": _note_values(
                                              self, child["refs"], payload, bindings)})
            else:
                self.trace.log("ERROR", "step failed", step=step["name"],
                               reason=str(last_error))
        return span, entry, last_error, response_ext, notes_ext

    def _run_parallel_block(self, group, workflow_name, result, root, con,
                            payload, bindings, rowsets, deadline,
                            response_refs, notes):
        """issue #108 D1-D4/D6/D7: run one `parallel` block's steps
        concurrently on a block-scoped `ThreadPoolExecutor` — created and
        shut down within this call, so no task from this block outlives it
        either way (structural concurrency; the block IS the scope).

        Fail-fast (D3): every step is submitted, then `wait(FIRST_EXCEPTION)`
        returns as soon as one raises. That step's failure cancels every
        future that has not started yet (`Future.cancel()` — a no-op once a
        thread has actually begun) and sets `cancel_event` so any step still
        retrying stops after its current attempt. Whatever was already in
        flight is still joined before this method returns — nothing survives
        it, success or failure.

        Declared-order reporting (D6): steps are appended to `root.children`/
        `result["steps"]` in the block's WRITTEN order, not completion order,
        once every future is settled — the same shape `spec.py`'s `steps <N>`
        already expects from the sequential path. A step whose future was
        cancelled before it ever started contributes nothing, exactly like a
        step after a sequential failure never running (D6). `failed_step` is
        whichever failed step's span started EARLIEST in real time — the
        branch that actually triggered the cancellation, when more than one
        step fails independently.
        """
        step_ids = group.step_ids
        steps = [self.nodes[sid] for sid in step_ids]
        cap = con["parallel_cap"] or len(steps)
        lock = threading.RLock()
        cancel_event = threading.Event()
        outcomes = {}

        def worker(step):
            outcome = self._execute_step_with_retry(
                step, workflow_name, con, payload, deadline, bindings,
                rowsets, lock, cancel_event)
            outcomes[step["id"]] = outcome
            error = outcome[2]
            if error is not None:
                raise error

        with ThreadPoolExecutor(max_workers=cap) as pool:
            futures = {pool.submit(worker, step): step for step in steps}
            done, pending = wait(futures, return_when=FIRST_EXCEPTION)
            if any(fut.exception() is not None for fut in done):
                cancel_event.set()
                for fut in pending:
                    fut.cancel()
            # `pool`'s own `__exit__` (`shutdown(wait=True)`) blocks here
            # until every future that DID start has actually finished —
            # cancelling a pending one only stops it from starting.

        failed_step_name = None
        failed_error = None
        earliest_failure_start = None
        for step in steps:
            outcome = outcomes.get(step["id"])
            if outcome is None:
                continue   # cancelled before it ever started — no record
            span, entry, error, response_ext, notes_ext = outcome
            root.children.append(span)
            result["steps"].append(entry)
            if error is None:
                response_refs.extend(response_ext)
                notes.extend(notes_ext)
            elif earliest_failure_start is None or span.start_ms < earliest_failure_start:
                earliest_failure_start = span.start_ms
                failed_step_name = step["name"]
                failed_error = error

        if failed_error is not None:
            result["status"] = "failed"
            result["failed_step"] = failed_step_name
            result["failure_reason"] = str(failed_error)
            if isinstance(failed_error.__cause__, ConflictError):
                result["failure_kind"] = "conflict"
            else:
                kind = getattr(failed_error, "failure_kind", None)
                if kind is not None:
                    result["failure_kind"] = kind
        elif (deadline is not None and outcomes and self.clock.now > deadline):
            # Parity with the sequential loop's own post-step check
            # (`run_workflow`, "deadline exceeded after step %r") — every
            # step here succeeded on its own, but this block's steps'
            # combined virtual-clock cost (each `_run_step` still calls
            # `self.clock.advance()` under `lock`, same as sequential; the
            # SUM is order-independent even though which thread advances it
            # when is not) pushed the run past its `policy timeout`
            # deadline. Reported against the last DECLARED step, matching
            # D6's declared-order framing — there is no single "the step
            # that did it" once steps ran concurrently.
            last_step = steps[-1]
            result["status"] = "failed"
            result["failed_step"] = last_step["name"]
            result["failure_reason"] = ("deadline exceeded after step %r"
                                        % last_step["name"])
            result["failure_kind"] = "deadline"
            self.trace.log("ERROR", "deadline exceeded", step=last_step["name"],
                           deadline_ms=con["timeout_ms"])


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

    A `derived` field (issue #95) is excluded from the "must be present" half
    of this check and rejected outright if the payload supplies it anyway — it
    is server-computed, so the client sending one is mass-assignment, not a
    completed form.
    """
    rule = effect.get("rule")
    if rule == "semantic-types":
        target = effect.get("target")
        entity = nodes.get(target)
        if entity is None or entity.get("kind") != "Entity":
            raise RunError("validation references undeclared entity %r"
                           % target)
        for field in entity.get("fields", []):
            if field.get("derived"):
                # issue #95: server-computed, so the payload must not name it
                # at all — the trust-boundary inversion the brief's own
                # `Order{total, placedAt}` regression reports.
                if field["name"] in payload:
                    raise RunError(
                        "field %r is derived (server-computed) and must not "
                        "be supplied in the payload" % field["name"])
                continue
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


def row_shape_mismatches(entity_node, row, refinements):
    """`entity_node`'s declared fields vs. a stored `row` (issue #85).

    Reuses `check_semantic_type` — the same judgement `validate_effect`
    already applies to a payload — rather than a second type rule. A
    `derived` field is skipped: it is never persisted (issue #95's `create`
    branch does not seed one, and `derived-never-assigned` forbids a
    workflow from ever `set`ting one), so its absence from a stored row is
    the normal shape, not a mismatch.

    Returns a list of `{"field", "expected_type", "kind"}` dicts, `kind` one
    of `"missing"` / `"type"` — never the stored value itself (D2): a caller
    building a diagnostic or a JSON report from this list cannot leak one by
    accident, because there is nothing here to leak.
    """
    mismatches = []
    for field in entity_node.get("fields", []):
        if field.get("derived"):
            continue
        name = field["name"]
        if name not in row:
            mismatches.append({"field": name, "expected_type": field["type"],
                               "kind": "missing"})
            continue
        try:
            check_semantic_type(field["type"], row[name], name, refinements)
        except RunError:
            mismatches.append({"field": name, "expected_type": field["type"],
                               "kind": "type"})
    return mismatches


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
            if field.get("derived"):
                # issue #95: the client can never send this, so the default
                # fixture must not manufacture a value for it either — doing
                # so would make every derived-field entity fail its own
                # default-payload validation forever.
                continue
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


def _wall_clock_ms():
    """Real elapsed time in milliseconds — issue #108 D6's exception to the
    virtual `Clock` every other span timestamp uses. `time.monotonic()`, not
    `time.time()`: immune to a system clock adjustment landing mid-run, and
    every sibling span within one process shares the same base regardless,
    which is all overlap detection needs. Integer milliseconds, matching the
    virtual `Clock`'s own type — every other span-timestamp consumer already
    assumes `int`."""
    return int(time.monotonic() * 1000)
