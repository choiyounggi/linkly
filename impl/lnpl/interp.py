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

IDEMPOTENT_OPS = {
    ("RepositoryCall", "read"), ("RepositoryCall", "query"),
    ("RepositoryCall", "delete"), ("RepositoryCall", "update"),
    ("CacheAccess", "get"), ("CacheAccess", "set"), ("CacheAccess", "invalidate"),
}

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
    """Stands in for a `postgres` capability."""

    def __init__(self, rows=None):
        self.rows = rows or {}
        self.calls = []

    def execute(self, entity_id, operation):
        self.calls.append((entity_id, operation))
        if operation in ("read", "query"):
            return self.rows.get(entity_id)
        return {"affected": 1}


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


def _flatten_items(nodes, ids, interp, result, root, con, payload):
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
                                        result, root, con, payload):
                yield inner
        elif kind == "Guard":
            mode = node["mode"]
            inner_ids = node.get("children", [])
            if mode == "when":
                if not _condition_holds(node.get("condition"), payload):
                    result["skipped"].append(node_id)
                    interp.trace.log("INFO", "guard skipped the guarded item",
                                     guard=node_id, condition=node.get("condition"))
                    continue
                for inner in _flatten_items(nodes, inner_ids, interp, result, root,
                                            con, payload):
                    yield inner
            elif mode == "repeat":
                for _ in range(int(node["count"])):
                    for inner in _flatten_items(nodes, inner_ids, interp, result,
                                                root, con, payload):
                        yield inner
            elif mode == "until":
                # A bounded loop: the workflow deadline is the only stop condition
                # the interpreter can rely on, so `until` runs at most once per
                # remaining budget slice and reports when it gave up.
                rounds = 0
                while not _condition_holds(node.get("condition"), payload):
                    rounds += 1
                    for inner in _flatten_items(nodes, inner_ids, interp, result,
                                                root, con, payload):
                        yield inner
                    if con["timeout_ms"] is None or rounds >= _UNTIL_ROUND_CAP:
                        interp.trace.log("WARN", "until loop hit its round cap",
                                         guard=node_id, rounds=rounds)
                        break
            else:
                raise RunError("unknown guard mode %r" % mode)
        else:
            raise RunError("workflow body cannot contain %s" % kind)


_UNTIL_ROUND_CAP = 16


def _condition_holds(condition, payload):
    """Phase 1 condition evaluation: `<field> missing` / `<field> exists`.

    Anything else is rejected rather than guessed — RFC-0002 Open Questions 2
    still owns the general condition grammar.
    """
    if condition is None:
        return True
    tokens = condition.split()
    if len(tokens) == 2 and tokens[1] in ("missing", "exists"):
        present = payload.get(tokens[0]) is not None
        return present if tokens[1] == "exists" else not present
    raise RunError("Phase 1 evaluates only `<field> missing|exists` conditions, "
                   "got %r (RFC-0002 Open Questions 2)" % condition)


def mask_payload(payload, entity_node):
    """Replace values whose declared semantic type is masked (RFC-0003 §Observability)."""
    if not isinstance(payload, dict) or entity_node is None:
        return payload
    masked_names = {f["name"] for f in entity_node.get("fields", [])
                    if f.get("type") in MASKED_TYPES}
    return {k: (MASK if k in masked_names else v) for k, v in payload.items()}


class Interpreter:
    def __init__(self, document, clock=None, repo_rows=None, correlation_id="cid-0001"):
        self.doc = document
        self.nodes = {n["id"]: n for n in document["nodes"]}
        self.clock = clock or Clock()
        self.repo = FakeRepository(repo_rows)
        self.cache = FakeCache(self.clock)
        self.trace = Trace(correlation_id)

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
        for n in self.doc["nodes"]:
            if n["kind"] == "Entity":
                return n
        return None

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
                  "skipped": []}
        for item_id in _flatten_items(self.nodes, wf.get("children", []), self, result,
                                     root, con, payload):
            step = self.nodes[item_id]
            span = Span(step["name"], "WorkflowStep", self.clock.now)
            root.children.append(span)
            attempts = 0
            last_error = None
            while True:
                attempts += 1
                try:
                    self._run_step(step, span, con, payload, deadline)
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
                                    "duration_ms": span.duration_ms})
            if last_error is not None:
                result["status"] = "failed"
                result["failed_step"] = step["name"]
                self.trace.log("ERROR", "step failed",
                               step=step["name"], reason=str(last_error))
                if con["rollback"]:
                    self.trace.log("INFO", "rollback: no Transaction boundary in scope, "
                                          "nothing to compensate")
                break
            if deadline is not None and self.clock.now > deadline:
                result["status"] = "failed"
                result["failed_step"] = step["name"]
                self.trace.log("ERROR", "deadline exceeded",
                               step=step["name"], deadline_ms=con["timeout_ms"])
                break

        root.end_ms = self.clock.now
        total = root.duration_ms
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

    def _run_step(self, step, span, con, payload, deadline):
        if deadline is not None and self.clock.now >= deadline:
            raise RunError("deadline exhausted before step %r" % step["name"])
        for child_id in step.get("children", []):
            effect = self.nodes[child_id]
            self._run_effect(effect, span, con, payload)
        self.clock.advance()

    def _run_effect(self, effect, span, con, payload):
        kind = effect["kind"]
        child = Span(effect["id"].rsplit(".", 1)[-1], kind, self.clock.now)
        span.children.append(child)

        if kind == "Validation":
            self._validate(effect, payload)
        elif kind == "RepositoryCall":
            row = self.repo.execute(effect["entity"], effect["operation"])
            child.attrs["found"] = row is not None
            if effect["operation"] == "read" and row is None:
                self.clock.advance(1)
                child.end_ms = self.clock.now
                raise RunError("repository read found no row for %s" % effect["entity"])
        elif kind == "CacheAccess":
            key = effect["key"].replace("{id}", str(payload.get("id", "-")))
            if effect["operation"] == "set":
                self.cache.set(key, payload, con["cache_ttl_ms"])
                child.attrs["ttl_ms"] = con["cache_ttl_ms"]
            elif effect["operation"] == "get":
                child.attrs["hit"] = self.cache.get(key) is not None
            else:
                self.cache.invalidate(key)
        elif kind == "Authorization":
            child.attrs["requirement"] = effect.get("requirement")
        elif kind == "NetworkCall":
            child.attrs["target"] = effect.get("target")
        else:
            raise RunError("Phase 1 interpreter does not execute %s" % kind)

        self.clock.advance(1)
        child.end_ms = self.clock.now

    def _validate(self, effect, payload):
        entity = self._entity_node()
        rule = effect.get("rule")
        if rule == "semantic-types":
            if entity is None:
                raise RunError("validation has no entity in scope")
            for field in entity.get("fields", []):
                if field["name"] not in payload:
                    raise RunError("missing required field %r" % field["name"])
                check_semantic_type(field["type"], payload[field["name"]], field["name"])
        else:
            field_name = effect["target"].rsplit(".", 1)[-1]
            if field_name not in payload:
                raise RunError("missing required field %r" % field_name)
            check_semantic_type(rule, payload[field_name], field_name)

    def _retryable(self, step, con, attempts, deadline=None):
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


def check_semantic_type(type_name, value, field_name):
    """Built-in validation rules for the semantic types Phase 1 covers."""
    import re
    if type_name in ("semantic-types",):
        return
    if value is None:
        raise RunError("field %r is null" % field_name)
    if type_name == "UUID":
        if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                        r"[0-9a-f]{4}-[0-9a-f]{12}$", str(value), re.I):
            raise RunError("field %r is not a canonical UUID" % field_name)
    elif type_name == "Email":
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(value)):
            raise RunError("field %r is not a valid email address" % field_name)
    elif type_name == "Password":
        if not str(value):
            raise RunError("field %r is empty" % field_name)
    elif type_name == "DateTime":
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(value)):
            raise RunError("field %r is not an RFC 3339 timestamp" % field_name)
    elif type_name == "Text":
        if not isinstance(value, str):
            raise RunError("field %r is not text" % field_name)
    elif type_name == "Integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise RunError("field %r is not an integer" % field_name)
    elif type_name == "Boolean":
        if not isinstance(value, bool):
            raise RunError("field %r is not a boolean" % field_name)
    # Types without a Phase 1 rule pass through; RFC-0001 owns the full table.


def _duration_ms(text):
    for unit, mult in (("ms", 1), ("s", 1000), ("m", 60000)):
        if str(text).endswith(unit):
            head = str(text)[: -len(unit)]
            if head.isdigit():
                return int(head) * mult
    raise RunError("not a duration: %r" % text)


def _backoff_ms(attempt):
    """Capped exponential backoff. Deterministic: jitter is a runtime concern
    and would make the reference interpreter non-reproducible."""
    return min(100 * (2 ** (attempt - 1)), 1000)
