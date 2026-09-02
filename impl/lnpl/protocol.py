"""Agent protocol — RFC-0006, JSON-RPC 2.0 over an in-process transport.

The eight methods RFC-0006 fixes:

    agent.card       agent.dispatch   agent.report
    ir.get           ir.propose
    kb.route         kb.load          kb.verify

Three properties this implementation holds to, because they are the ones that
stop being true first when a protocol is implemented casually:

1. **`ir.propose` never mutates.** It records a proposal and returns a review task.
   Application happens only after a Reviewer's `agent.report` approves it. There is
   no ninth method for approval — the decision travels as a report payload.
2. **Idempotency is real.** `agent.dispatch` and `ir.propose` require an
   `idempotency_key`; a replay returns the *stored first response*, and the same key
   with different params is an error rather than a silent overwrite.
3. **Errors are typed and lossy on purpose.** `internal` never carries a traceback
   or a path. Every error says whether it is retryable, so a caller does not have to
   guess from the message.
"""

import copy
import json

JSONRPC = "2.0"

# type -> (code, retryable). Codes -32001..-32012 sit in the implementation-defined
# server range JSON-RPC 2.0 reserves (-32099..-32000).
ERRORS = {
    "ir_invalid": (-32602, False),
    "kb_version_conflict": (-32001, False),
    "agent_timeout": (-32002, True),
    "proposal_rejected": (-32003, False),
    "idempotency_in_flight": (-32010, True),
    "idempotency_mismatch": (-32011, False),
    "overloaded": (-32012, True),
    "ambiguous_step": (-32013, False),
    "internal": (-32603, False),
}

# Envelope-layer reserved codes, for reference in errors we surface unchanged.
RESERVED = {"parse_error": -32700, "invalid_request": -32600,
            "method_not_found": -32601, "invalid_params": -32602,
            "internal_error": -32603}

TASK_STATES = ("submitted", "working", "input-required",
               "completed", "failed", "canceled")

# Which IR node categories each role may propose (RFC-0006 role table).
DECLARATION = {"Entity", "Service", "Workflow", "Event", "Capability"}
BEHAVIOR = {"BusinessRule", "Validation", "WorkflowStep", "Pipeline",
            "Concurrency", "Guard"}
EFFECT = {"NetworkCall", "RepositoryCall", "CacheAccess", "Transaction",
          "Authorization", "EventEmit"}
CONSTRAINT = {"Policy", "Security", "Performance"}

ROLES = {
    "Planner": {"propose": set(), "approve": False},
    "Architect": {"propose": DECLARATION | BEHAVIOR, "approve": False},
    "Coder": {"propose": BEHAVIOR | EFFECT, "approve": False},
    "Reviewer": {"propose": set(), "approve": True},
    "Tester": {"propose": BEHAVIOR, "approve": False},
    "PerformanceAnalyzer": {"propose": CONSTRAINT, "approve": False},
    "SecurityAuditor": {"propose": CONSTRAINT | EFFECT, "approve": False},
    "RefactoringAgent": {"propose": BEHAVIOR | EFFECT, "approve": False},
    "ReleaseAgent": {"propose": set(), "approve": False},
}


class RpcError(Exception):
    """A structured protocol error (RFC-0006 §Errors)."""

    def __init__(self, type_name, message, details=None):
        if type_name not in ERRORS:
            raise ValueError("unknown error type %r" % type_name)
        code, retryable = ERRORS[type_name]
        super().__init__(message)
        self.type = type_name
        self.code = code
        self.retryable = retryable
        self.message = message
        self.details = details or {}

    def to_error(self):
        err = {"code": self.code, "type": self.type, "message": self.message,
               "retryable": self.retryable}
        if self.details:
            err["details"] = self.details
        return err


# RFC-0001 §구조 규칙 5 lists the named (non-owning) reference fields. `target` is
# deliberately absent: the compiler also writes field paths ("entity.user.email")
# and the literal "unspecified" there (lower.py), so treating it as a node
# reference would reject the compiler's own output. Recorded in
# docs/CONSISTENCY-CHECK.md rather than silently diverging.
NAMED_REF_FIELDS = ("requires", "constraints", "entity", "event")

# Every field that can carry a node reference. `set(...)` is not decoration —
# NAMED_REF_FIELDS is a tuple, and `{"children"} | NAMED_REF_FIELDS` is a TypeError.
REFERENCE_KEYS = {"children"} | set(NAMED_REF_FIELDS)

# RFC-0001 §노드 카탈로그's *children 허용* column, which RFC-0004 §S2 calls
# invariant V5. Nothing else in this implementation enforces it — `_structure_fault`
# covers V2/V3/V4 and the schema types `children` as an unrestricted id array — so
# without this table RFC-0010's attachment exception would let a role write a
# `WorkflowStep` into an `Entity`. Enforcing V5 document-wide is a larger change
# (recorded in docs/CONSISTENCY-CHECK.md); this gates `attach` only.
CHILDREN_ALLOWED = {
    "Entity": {"Validation"},
    "Service": {"Workflow", "Pipeline", "BusinessRule"},
    "Workflow": {"WorkflowStep", "Guard", "Concurrency", "Pipeline"},
    "Event": set(),
    "Capability": set(),
    "BusinessRule": set(),
    "Validation": set(),
    "WorkflowStep": {"Validation", "BusinessRule", "NetworkCall", "RepositoryCall",
                     "CacheAccess", "Transaction", "Authorization", "EventEmit",
                     "Concurrency", "Pipeline"},
    "Guard": {"WorkflowStep", "Concurrency", "Pipeline"},
    "Pipeline": {"WorkflowStep"},
    "Concurrency": {"WorkflowStep"},
    "NetworkCall": set(),
    "RepositoryCall": set(),
    "CacheAccess": set(),
    "Transaction": {"RepositoryCall", "NetworkCall", "CacheAccess", "EventEmit",
                    "BusinessRule", "Validation"},
    "Authorization": set(),
    "EventEmit": set(),
    "Policy": set(),
    "Security": set(),
    "Performance": set(),
}


def attachments(intent):
    """`{parent id: {child ids}}` from an intent's `attach` list.

    Shape errors are `ir_invalid` rather than a TypeError deep in a gate, and the
    message names `intent` so a caller can tell this from a node problem.
    """
    return _intent_entries(intent, "attach", ("parent", "child"),
                           lambda e: (e["parent"], e["child"]))


def moves(intent):
    """`{(from id, node id): to id}` from an intent's `move` list."""
    return _intent_entries(intent, "move", ("node", "from", "to"),
                           lambda e: ((e["from"], e["node"]), e["to"]))


def _intent_entries(intent, key, required, pair):
    if intent is None:
        intent = {}
    if not isinstance(intent, dict):
        raise RpcError("ir_invalid", "intent must be an object, got %r"
                       % type(intent).__name__)
    raw = intent.get(key) or []
    if not isinstance(raw, list):
        raise RpcError("ir_invalid", "intent.%s must be an array" % key)
    out = {}
    for entry in raw:
        if not isinstance(entry, dict) or any(
                not isinstance(entry.get(field), str) for field in required):
            raise RpcError("ir_invalid",
                           "each intent.%s entry needs string %s"
                           % (key, ", ".join(required)))
        left, right = pair(entry)
        if key == "attach":
            out.setdefault(left, set()).add(right)
        else:
            out[left] = right
    return out


def _comparable(node):
    """A node's fields that a reference-only edit may not touch.

    Reference fields are excluded because condition (d) checks those per field.
    `meta.origin` is excluded because RFC-0010 *requires* the edit to set it, and a
    node that had no `meta` at all would otherwise fail condition (c) for obeying
    that requirement. The rest of `meta` — `source` in particular — is compared, so
    provenance cannot be rewritten under cover of an attachment.
    """
    out = {k: v for k, v in node.items() if k not in REFERENCE_KEYS and k != "meta"}
    meta = node.get("meta")
    if isinstance(meta, dict):
        rest = {k: v for k, v in meta.items() if k != "origin"}
        # A `meta` holding nothing but the required origin is equivalent to no
        # `meta` at all — otherwise obeying condition (e) on a node that had none
        # would itself violate condition (c).
        if rest:
            out["meta"] = rest
    elif meta is not None:
        out["meta"] = meta
    return out


def reference_only_edit(proposed, existing, declared_children, child_kinds=None):
    """Is `proposed` a replacement of `existing` that only adds `declared_children`?

    RFC-0010 lets a role edit a node outside its rights for exactly one purpose:
    attaching something it authored in the same proposal. That is safe only when the
    edit does nothing else, so all of it holds or none of it does.

    The reference comparison is **per field and order-preserving**. A set comparison
    passes two things it must not: reversing `children` (whose order is execution
    order, RFC-0001 rule 3), and moving a reference from `constraints` into
    `children` — set-identical, while the interpreter reads `constraints` for retry,
    timeout and rollback, so the declared policy silently stops applying.

    RFC-0010 §Methods/ir.propose allows `constraints` field for Constraint-kind
    children (Policy, Security, Performance), with same per-field order-preserving
    rule as `children`.
    """
    if existing is None:
        return False
    if proposed.get("kind") != existing.get("kind"):
        return False

    if _comparable(proposed) != _comparable(existing):
        return False

    for field in REFERENCE_KEYS:
        before, after = existing.get(field), proposed.get(field)
        # Only `children` may take the declared additions (RFC-0010 default).
        # RFC-0010 also allows `constraints` field for Constraint-kind children
        # when child_kinds are provided.
        if field == "children":
            allowed_new = declared_children
        elif field == "constraints" and child_kinds:
            # Allow constraints field only for Constraint-kind children
            constraint_kinds = {"Policy", "Security", "Performance"}
            constraint_refs = {ref for ref in declared_children
                             if child_kinds.get(ref) in constraint_kinds}
            allowed_new = constraint_refs
        else:
            allowed_new = ()

        if isinstance(after, list):
            remaining = [ref for ref in after if ref not in allowed_new]
            if remaining != list(before or []):
                return False
        elif after != before:
            return False
    return True


def node_references(node):
    """Every node id this node points at — owning (`children`) and named (rule 5).

    One function so both gates that enforce rule 6 (the Reviewer's judgment and
    `ir.apply`) ask the same question. When they asked different questions, a
    reference dropped from `constraints` slipped past both.
    """
    refs = list(node.get("children", []))
    for field in NAMED_REF_FIELDS:
        value = node.get(field)
        if isinstance(value, list):
            refs.extend(v for v in value if isinstance(v, str))
        elif isinstance(value, str):
            refs.append(value)
    source = node.get("source")
    if isinstance(source, dict) and isinstance(source.get("ref"), str):
        refs.append(source["ref"])
    return refs


# Node kinds that may legitimately have no owner. RFC-0001 rule 2 allows only
# Declaration nodes to be entry (top-level) nodes; rule 5 exempts Constraint
# nodes, which are never owned via `children` and are reached through the
# `constraints` field instead. Everything else must have exactly one owner.
DECLARATION_KINDS = frozenset({"Entity", "Service", "Workflow", "Event", "Capability"})
CONSTRAINT_KINDS = frozenset({"Policy", "Security", "Performance"})
ENTRY_KINDS = DECLARATION_KINDS | CONSTRAINT_KINDS


def _ownership_cycle(merged):
    """One cycle in the `children` graph as a list of ids, or [] if acyclic.

    RFC-0001 rule 4. Checking only for a node that lists itself catches 1-cycles
    and nothing longer: two new nodes owning each other each have an owner, so
    every per-node check passes while the pair is unreachable from any entry node.
    """
    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(merged, white)
    for root in sorted(merged):
        if colour[root] != white:
            continue
        colour[root] = grey
        path = [root]
        stack = [(root, iter(merged[root].get("children", [])))]
        while stack:
            node_id, kids = stack[-1]
            descended = False
            for kid in kids:
                if kid not in merged:
                    continue              # rule 6 reports dangling separately
                if colour[kid] == grey:
                    return path[path.index(kid):] + [kid]
                if colour[kid] == white:
                    colour[kid] = grey
                    path.append(kid)
                    stack.append((kid, iter(merged[kid].get("children", []))))
                    descended = True
                    break
            if not descended:
                colour[node_id] = black
                stack.pop()
                path.pop()
    return []


def _structure_fault(merged):
    """The first RFC-0001 structure-rule violation in a merged document, or None.

    Rules 2 (one owner, and only Declaration/Constraint nodes may be unowned),
    4 (acyclic ownership), 6 (every reference resolves), and invariants V1 (id
    uniqueness) and V5 (kind-specific children allowance per RFC-0004 §S2) are
    checked over the *whole* merged document, not just the proposed nodes — a
    proposal changes meaning by what it detaches as much as by what it adds.

    Lives here in the protocol layer, not the Reviewer, because BOTH gates that
    reach merge must run it: the Reviewer's `_assess` and the server's `_apply`
    (the approval-override path). Enforcing it in only one leaves the other able
    to write a document that violates the invariants (issue #15).
    """
    # V1: id uniqueness (RFC-0004 invariant V1)
    all_ids = [n["id"] for n in merged.values()]
    repeated = sorted({i for i in set(all_ids) if all_ids.count(i) > 1})
    if repeated:
        return ("id_unique: node id(s) %s appear more than once in the document "
                "(RFC-0001 공통 필드, RFC-0004 V1)" % ", ".join(repeated))

    dangling = sorted({ref for node in merged.values()
                       for ref in node_references(node) if ref not in merged})
    if dangling:
        return ("dangling: unresolved reference(s) %s — every owning and named "
                "reference must resolve in the same document (RFC-0001 rule 6)"
                % ", ".join(dangling))

    owners = {}
    contested = []
    for node in sorted(merged.values(), key=lambda n: n["id"]):
        for ref in node.get("children", []):
            if ref in owners:
                contested.append("%s (owned by %s and %s)" % (ref, owners[ref], node["id"]))
            else:
                owners[ref] = node["id"]
    if contested:
        return ("ownership: %s — a node may appear in at most one `children` list "
                "(RFC-0001 rule 2)" % ", ".join(sorted(contested)))

    orphans = sorted(n["id"] for n in merged.values()
                     if n["kind"] not in ENTRY_KINDS and n["id"] not in owners)
    if orphans:
        return ("orphan: nothing owns %s — only Declaration and Constraint nodes "
                "may be unowned (RFC-0001 rules 2, 5)" % ", ".join(orphans))

    cycle = _ownership_cycle(merged)
    if cycle:
        return ("cycle: ownership loops through %s — the `children` graph must be "
                "acyclic (RFC-0001 rule 4)" % " -> ".join(cycle))

    # V5: kind-specific children allowance (RFC-0004 invariant V5)
    for node in merged.values():
        parent_kind = node.get("kind")
        for child_id in node.get("children", []):
            child = merged.get(child_id)
            if child is None:
                continue  # dangling check above already caught this
            child_kind = child.get("kind")
            if child_kind and child_kind not in CHILDREN_ALLOWED.get(parent_kind, set()):
                return ("v5_children: a %s may not own a %s (RFC-0001 §노드 카탈로그 "
                        "children 허용; RFC-0004 §S2 V5): %s under %s"
                        % (parent_kind, child_kind, child_id, node["id"]))

    # Guard cardinality: exactly one child (RFC-0001 Guard row, "피가드 항목 1개")
    for node in merged.values():
        if node.get("kind") == "Guard":
            children_count = len(node.get("children", []))
            if children_count != 1:
                return ("guard_cardinality: Guard %s has %d children; exactly 1 required "
                        "(RFC-0001 §노드 카탈로그 Guard row)"
                        % (node["id"], children_count))

    return None


class Task:
    """A dispatched unit of work with the A2A-style state machine."""

    def __init__(self, task_id, role, objective):
        self.id = task_id
        self.role = role
        self.objective = objective
        self.state = "submitted"
        self.history = ["submitted"]
        self.result = None

    def transition(self, state):
        if state not in TASK_STATES:
            raise RpcError("internal", "unknown task state")
        terminal = ("completed", "failed", "canceled")
        if self.state in terminal:
            raise RpcError("internal",
                           "task %s is already terminal (%s)" % (self.id, self.state))
        self.state = state
        self.history.append(state)

    def to_dict(self):
        return {"task_id": self.id, "role": self.role, "state": self.state,
                "objective": self.objective, "history": list(self.history),
                "result": self.result}


class Server:
    """In-process JSON-RPC server holding the IR document and the KB."""

    def __init__(self, document, knowledge_base, schema_validator=None):
        self.doc = copy.deepcopy(document)
        self.kb = knowledge_base
        self.validate = schema_validator      # callable(document) -> None, or None
        self.tasks = {}
        self.proposals = {}
        self.applied = []                     # proposal ids applied, in order
        self._idem = {}                       # key -> (params_fingerprint, response)
        self._seq = 0
        self.log = []                         # every (method, params) for inspection

    # ---- transport ------------------------------------------------------
    def handle(self, request):
        """Take a JSON-RPC request dict, return a response dict."""
        rid = request.get("id")
        if request.get("jsonrpc") != JSONRPC:
            return self._err(rid, RpcError("internal", "jsonrpc must be \"2.0\""))
        method = request.get("method")
        params = request.get("params") or {}
        handler = getattr(self, "_m_" + method.replace(".", "_"), None) if method else None
        if handler is None:
            return {"jsonrpc": JSONRPC, "id": rid,
                    "error": {"code": RESERVED["method_not_found"],
                              "message": "method not found: %r" % method,
                              "retryable": False}}
        self.log.append((method, params))
        try:
            if method in ("agent.dispatch", "ir.propose"):
                return self._idempotent(rid, method, params, handler)
            return {"jsonrpc": JSONRPC, "id": rid, "result": handler(params)}
        except RpcError as exc:
            return self._err(rid, exc)
        except Exception:
            # Deliberately lossy: RFC-0006 forbids leaking internals.
            return self._err(rid, RpcError("internal", "internal error"))

    def call(self, method, **params):
        """Convenience wrapper: raises RpcError instead of returning an error dict."""
        self._seq += 1
        resp = self.handle({"jsonrpc": JSONRPC, "id": self._seq,
                            "method": method, "params": params})
        if "error" in resp:
            err = resp["error"]
            if err.get("type"):
                raise RpcError(err["type"], err["message"], err.get("details"))
            raise RpcError("internal", err["message"])
        return resp["result"]

    def _err(self, rid, exc):
        return {"jsonrpc": JSONRPC, "id": rid, "error": exc.to_error()}

    def _idempotent(self, rid, method, params, handler):
        key = params.get("idempotency_key")
        if not key:
            raise RpcError("ir_invalid",
                           "%s requires an idempotency_key (RFC-0006 §Reliability)"
                           % method)
        fingerprint = json.dumps({k: v for k, v in params.items()
                                  if k != "idempotency_key"},
                                 sort_keys=True, ensure_ascii=False)
        stored = self._idem.get(key)
        if stored is not None:
            prev_fp, prev_resp = stored
            if prev_fp != fingerprint:
                raise RpcError("idempotency_mismatch",
                               "idempotency key reused with different params",
                               {"key": key})
            return {"jsonrpc": JSONRPC, "id": rid, "result": prev_resp}
        result = handler(params)
        self._idem[key] = (fingerprint, result)
        return {"jsonrpc": JSONRPC, "id": rid, "result": result}

    # ---- methods --------------------------------------------------------
    def _m_agent_card(self, params):
        role = params.get("role")
        if role not in ROLES:
            raise RpcError("ir_invalid", "unknown role %r" % role)
        spec = ROLES[role]
        return {"role": role,
                "ir_access": {"read": ["Declaration", "Behavior", "Effect",
                                       "Constraint"],
                              "propose": sorted(spec["propose"])},
                "approve": spec["approve"],
                "methods": ["agent.card", "agent.dispatch", "agent.report",
                            "ir.get", "ir.propose",
                            "kb.route", "kb.load", "kb.verify"],
                "protocol": {"jsonrpc": JSONRPC, "streaming": "sse"},
                "version": "0.1.0"}

    def _m_agent_dispatch(self, params):
        role = params.get("role")
        objective = params.get("objective")
        if role not in ROLES:
            raise RpcError("ir_invalid", "unknown role %r" % role)
        if not objective:
            raise RpcError("ir_invalid", "dispatch needs an objective")
        if params.get("deadline_ms") is None:
            raise RpcError("ir_invalid",
                           "dispatch needs a deadline_ms (RFC-0006 §Reliability: "
                           "every call carries a deadline)")
        task_id = "task-%04d" % (len(self.tasks) + 1)
        self.tasks[task_id] = Task(task_id, role, objective)
        return self.tasks[task_id].to_dict()

    def _m_agent_report(self, params):
        task_id = params.get("task_id")
        task = self.tasks.get(task_id)
        if task is None:
            raise RpcError("ir_invalid", "unknown task %r" % task_id)
        payload = params.get("payload") or {}

        # A Reviewer decision on a proposal is a report payload, not a 9th method.
        if "proposal_id" in payload:
            return self._decide(task, payload)

        state = params.get("state", "completed")
        if task.state == "submitted":
            task.transition("working")
        task.transition(state)
        task.result = payload
        return task.to_dict()

    def _decide(self, task, payload):
        pid = payload["proposal_id"]
        proposal = self.proposals.get(pid)
        if proposal is None:
            raise RpcError("ir_invalid", "unknown proposal %r" % pid)
        if not ROLES[task.role]["approve"]:
            raise RpcError("proposal_rejected",
                           "role %s may not approve proposals" % task.role)
        decision = payload.get("decision")
        if decision not in ("approved", "rejected"):
            raise RpcError("ir_invalid", "decision must be approved|rejected")
        if proposal["state"] != "pending":
            raise RpcError("ir_invalid",
                           "proposal %s is already %s" % (pid, proposal["state"]))
        if task.state == "submitted":
            task.transition("working")

        if decision == "rejected":
            proposal["state"] = "rejected"
            task.transition("failed")
            task.result = {"proposal_id": pid, "decision": "rejected",
                           "reason": payload.get("reason", "")}
            raise RpcError("proposal_rejected",
                           payload.get("reason") or "proposal rejected",
                           {"proposal_id": pid})

        self._apply(proposal)
        proposal["state"] = "approved"
        task.transition("completed")
        task.result = {"proposal_id": pid, "decision": "approved",
                       "reason": payload.get("reason", ""),
                       "applied_nodes": [n["id"] for n in proposal["nodes"]]}
        return task.to_dict()

    def _apply(self, proposal):
        existing = {n["id"] for n in self.doc["nodes"]}
        merged = copy.deepcopy(self.doc)
        for node in proposal["nodes"]:
            if node["id"] in existing:
                merged["nodes"] = [node if n["id"] == node["id"] else n
                                   for n in merged["nodes"]]
            else:
                merged["nodes"].append(node)
        merged_ids = {n["id"] for n in merged["nodes"]}
        for node in proposal["nodes"]:
            for ref in node_references(node):
                if ref not in merged_ids:
                    raise RpcError("ir_invalid",
                                   "applying %s would leave a dangling reference to %s"
                                   % (node["id"], ref))
        # RFC-0004 §S2 invariants (V1 id-uniqueness, V5 children allowance),
        # RFC-0001 ownership/cycle rules and Guard cardinality apply to EVERY path
        # that reaches merge — including this approval-override path, not just the
        # Reviewer's assessment (issue #15). Run them over the whole merged
        # document before it becomes authoritative.
        fault = _structure_fault({n["id"]: n for n in merged["nodes"]})
        if fault is not None:
            raise RpcError("ir_invalid", "merged IR violates a structure rule: %s" % fault)
        if self.validate is not None:
            try:
                self.validate(merged)
            except Exception as exc:
                raise RpcError("ir_invalid", "merged IR fails validation: %s" % exc)
        self.doc = merged
        self.applied.append(proposal["id"])

    def _m_ir_get(self, params):
        node_id = params.get("node_id")
        if node_id is None:
            return {"lir_version": self.doc["lir_version"],
                    "module": self.doc["module"],
                    "node_ids": [n["id"] for n in self.doc["nodes"]]}
        for node in self.doc["nodes"]:
            if node["id"] == node_id:
                return {"node": node}
        raise RpcError("ir_invalid", "no such node %r" % node_id)

    def _m_ir_propose(self, params):
        role = params.get("role")
        if role not in ROLES:
            raise RpcError("ir_invalid", "unknown role %r" % role)
        fragment = params.get("ir_fragment")
        if not isinstance(fragment, dict) or "nodes" not in fragment:
            raise RpcError("ir_invalid", "ir_fragment must carry a `nodes` array")
        if fragment.get("module") not in (None, self.doc["module"]):
            raise RpcError("ir_invalid",
                           "fragment module %r does not match %r"
                           % (fragment.get("module"), self.doc["module"]))

        # RFC-0006 §Methods/ir.propose: kb_pins is required.
        # It lists the KB documents this proposal grounds on, or [] if none.
        kb_pins = params.get("kb_pins")
        if kb_pins is None:
            raise RpcError("ir_invalid",
                           "ir.propose requires kb_pins parameter — a list of "
                           "{doc_id, version} objects, or [] if no KB docs used "
                           "(RFC-0006 §Methods/ir.propose)")
        if not isinstance(kb_pins, list):
            raise RpcError("ir_invalid",
                           "kb_pins must be an array, got %s" % type(kb_pins).__name__)
        for pin in kb_pins:
            if not isinstance(pin, dict):
                raise RpcError("ir_invalid",
                               "each kb_pins entry must be an object {doc_id, version}")
            if not isinstance(pin.get("doc_id"), str) or not pin.get("doc_id"):
                raise RpcError("ir_invalid",
                               "kb_pins entry missing or empty doc_id (must be non-empty string)")
            if not isinstance(pin.get("version"), str) or not pin.get("version"):
                raise RpcError("ir_invalid",
                               "kb_pins entry missing or empty version (must be non-empty string)")
        # One node per id. `Reviewer._assess` merges with last-wins while `_apply`
        # appends every unseen id, so a fragment naming an id twice would put two
        # nodes with that id into the document and the reviewer would only have seen
        # one of them. RFC-0001's V1 (id uniqueness) is otherwise unenforced.
        ids = [n.get("id") for n in fragment["nodes"] if isinstance(n, dict)]
        repeated = sorted({i for i in ids if i is not None and ids.count(i) > 1})
        if repeated:
            raise RpcError("ir_invalid",
                           "ir_fragment names %s more than once — one node per id "
                           "(RFC-0001 §구조 규칙, id 유일)" % ", ".join(repeated))

        intent = params.get("intent") or {}
        attach_map = attachments(intent)
        moves(intent)          # shape-validate here so a bad move fails at propose

        allowed = ROLES[role]["propose"]
        by_id = {n["id"]: n for n in self.doc["nodes"]}

        # Validate the declarations before the rights loop consults them, so an
        # unauthored child or an illegal parent/child pairing reports itself rather
        # than surfacing as the generic "may not propose X" from the loop below.
        proposed_by_id = {n["id"]: n for n in fragment["nodes"] if "id" in n}
        authored = set(proposed_by_id) - set(by_id)
        constraint_kinds = {"Policy", "Security", "Performance"}
        for parent, children in attach_map.items():
            parent_kind = (proposed_by_id.get(parent)
                           or by_id.get(parent) or {}).get("kind")
            if not isinstance(parent_kind, str):
                raise RpcError("ir_invalid",
                               "intent.attach names parent %s, which is neither in "
                               "the fragment nor in the document" % parent)
            for child in sorted(children):
                if child not in authored:
                    raise RpcError(
                        "ir_invalid",
                        "intent.attach names %s, which this proposal did not "
                        "author — a proposal may attach only a node it wrote in "
                        "the same fragment (RFC-0010)" % child)
                child_kind = proposed_by_id.get(child, {}).get("kind")
                # RFC-0010 §Methods/ir.propose: allow constraints field for
                # Constraint-kind children (Policy, Security, Performance).
                # Otherwise, child must be in CHILDREN_ALLOWED for parent.
                if child_kind in constraint_kinds:
                    # Constraint attachment is allowed; will be validated via
                    # reference_only_edit when processing the parent node edit.
                    continue
                if child_kind not in CHILDREN_ALLOWED.get(parent_kind, set()):
                    raise RpcError(
                        "ir_invalid",
                        "a %s may not own a %s (RFC-0001 §노드 카탈로그 children "
                        "허용; RFC-0004 §S2 V5): intent.attach puts %s under %s"
                        % (parent_kind, child_kind, child, parent))

        # Map declared children to their kinds for reference_only_edit validation
        declared_kinds = {n["id"]: n.get("kind") for n in fragment["nodes"]
                         if "id" in n}

        for node in fragment["nodes"]:
            kind = node.get("kind")
            if kind in allowed:
                continue
            # RFC-0010: a node outside this role's rights is permitted for
            # attachment only, and only when the edit adds the declared children
            # and does nothing else.
            declared = attach_map.get(node.get("id"), set())
            if declared and reference_only_edit(node, by_id.get(node.get("id")),
                                                declared, declared_kinds):
                origin = (node.get("meta") or {}).get("origin") or ""
                if not origin.startswith("agent:"):
                    raise RpcError(
                        "ir_invalid",
                        "%s is edited outside %s's rights, so it must record "
                        "`meta.origin` as `agent:<role>` — otherwise the merged "
                        "document keeps no trace that a role reached outside its "
                        "rights (RFC-0010)" % (node.get("id"), role))
                continue
            raise RpcError("ir_invalid",
                           "role %s may not propose %s nodes" % (role, kind))


        pid = "prop-%04d" % (len(self.proposals) + 1)
        review = self._m_agent_dispatch({"role": "Reviewer",
                                         "objective": "review %s" % pid,
                                         "deadline_ms": params.get("deadline_ms", 30000)})
        self.proposals[pid] = {"id": pid, "role": role, "state": "pending",
                               "nodes": fragment["nodes"], "intent": intent,
                               "review_task_id": review["task_id"]}
        return {"proposal_id": pid, "state": "pending",
                "review_task_id": review["task_id"]}

    # ---- kb.* — the transport form of RFC-0005's interface --------------
    def _m_kb_route(self, params):
        desc = params.get("task_description")
        if not desc:
            raise RpcError("ir_invalid", "kb.route needs a task_description")
        return {"doc_ids": self.kb.route(desc)}

    def _m_kb_load(self, params):
        doc_id = params.get("doc_id")
        try:
            return {"document": self.kb.load(doc_id)}
        except Exception as exc:
            raise RpcError("ir_invalid", str(exc))

    def _m_kb_verify(self, params):
        doc_id, version = params.get("doc_id"), params.get("version")
        ok = self.kb.verify(doc_id, version)
        if not ok:
            raise RpcError("kb_version_conflict",
                           "document %r is not at version %r — re-route from "
                           "kb.route rather than retrying this call"
                           % (doc_id, version),
                           {"doc_id": doc_id, "expected": version})
        return {"ok": True}
