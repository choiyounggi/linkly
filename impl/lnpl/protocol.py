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
        for node in proposal["nodes"]:
            for ref in node.get("children", []):
                if ref not in {n["id"] for n in merged["nodes"]}:
                    raise RpcError("ir_invalid",
                                   "applying %s would leave a dangling reference to %s"
                                   % (node["id"], ref))
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
        allowed = ROLES[role]["propose"]
        for node in fragment["nodes"]:
            kind = node.get("kind")
            if kind not in allowed:
                raise RpcError("ir_invalid",
                               "role %s may not propose %s nodes" % (role, kind))

        pid = "prop-%04d" % (len(self.proposals) + 1)
        review = self._m_agent_dispatch({"role": "Reviewer",
                                         "objective": "review %s" % pid,
                                         "deadline_ms": params.get("deadline_ms", 30000)})
        self.proposals[pid] = {"id": pid, "role": role, "state": "pending",
                               "nodes": fragment["nodes"],
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
