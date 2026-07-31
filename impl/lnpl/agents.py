"""Two agents doing the RFC-0006 Examples round trip (ROADMAP Phase 3).

The cycle RFC-0006 describes, and what each leg actually does here:

    Planner   receives an intent, decomposes it, and dispatches the work
    Coder     routes the step to the KB, loads the document, pins its version,
              and proposes the IR fragment that document tells it to produce
    Reviewer  approves, which is the only way a proposal reaches the document

The Coder is the interesting one: it does not decide *what* to emit from its own
knowledge. It asks the KB, and if the KB has nothing to say it **stops** rather
than inventing an Effect — the same rule the compiler's verb lexicon follows.
"""

from .protocol import RpcError, Server


class Planner:
    """Turns an intent into dispatched work. Proposes nothing (RFC-0006 role table)."""

    role = "Planner"

    def __init__(self, server):
        self.server = server

    def plan(self, intent, steps, deadline_ms=30000):
        """Dispatch one task per step; returns the task descriptors."""
        card = self.server.call("agent.card", role=self.role)
        if card["ir_access"]["propose"]:
            raise RpcError("internal", "Planner must not hold propose rights")
        tasks = []
        for i, step in enumerate(steps, start=1):
            task = self.server.call(
                "agent.dispatch", role="Coder",
                objective="implement step %r of %r" % (step, intent),
                deadline_ms=deadline_ms,
                idempotency_key="plan-%s-%d" % (_slug(intent), i))
            tasks.append({"task": task, "step": step})
        return tasks


class Coder:
    """Routes a step to the KB, then proposes the IR the KB prescribes."""

    role = "Coder"

    def __init__(self, server):
        self.server = server

    def implement(self, task, step, deadline_ms=30000):
        """One leg of the cycle. Returns a record of what it did and why."""
        routed = self.server.call("kb.route", task_description=step)["doc_ids"]
        if not routed:
            # The KB has nothing for this step. Stopping is the correct outcome:
            # an agent that invents an Effect here is the synthesis route this
            # platform rejected.
            self.server.call("agent.report", task_id=task["task_id"],
                             state="completed",
                             payload={"step": step, "kb": [], "proposed": None,
                                      "reason": "no KB guidance; nothing proposed"})
            return {"step": step, "doc_id": None, "proposal_id": None}

        doc_id = routed[0]
        doc = self.server.call("kb.load", doc_id=doc_id)["document"]
        # Pin the version we reasoned against, so a later drift is detectable.
        self.server.call("kb.verify", doc_id=doc_id, version=doc["version"])

        fragment = self._fragment_for(step, doc)
        if fragment is None:
            self.server.call("agent.report", task_id=task["task_id"],
                             state="completed",
                             payload={"step": step, "kb": [doc_id], "proposed": None,
                                      "reason": "KB guidance carries no IR prescription"})
            return {"step": step, "doc_id": doc_id, "proposal_id": None}

        proposal = self.server.call(
            "ir.propose", role=self.role, ir_fragment=fragment,
            deadline_ms=deadline_ms,
            idempotency_key="coder-%s" % _slug(step))
        self.server.call("agent.report", task_id=task["task_id"],
                         state="input-required",
                         payload={"step": step, "kb": [doc_id],
                                  "proposed": proposal["proposal_id"],
                                  "awaiting": proposal["review_task_id"]})
        return {"step": step, "doc_id": doc_id,
                "proposal_id": proposal["proposal_id"],
                "review_task_id": proposal["review_task_id"],
                "kb_version": doc["version"]}

    # The mapping from KB guidance to an IR fragment. Deliberately tiny and
    # explicit: the Coder emits only what a document prescribes, and only kinds
    # its role may propose.
    def _fragment_for(self, step, doc):
        if doc["id"] != "security-jwt-issuance":
            return None
        # The jwt guidance prescribes an Authorization gate on *issuance*. Routing
        # is lexical, so it also matches steps that merely mention a token; the
        # prescription is narrowed by the step's verb, which the grammar guarantees
        # is the first token.
        if step.split()[0] != "generate":
            return None
        node = self._step_node_for(step)
        if node is None:
            return None
        authz_id = "%s.authz" % node["id"]
        # The Effect must be *owned* by its step, or it is unreachable in the flat
        # node table: propose the updated parent alongside the new child.
        parent = dict(node)
        parent["children"] = list(node.get("children", [])) + [authz_id]
        return {"module": self.server.doc["module"],
                "nodes": [parent,
                          {"kind": "Authorization",
                           "id": authz_id,
                           "requirement": "verified jwt",
                           "meta": {"origin": "agent:Coder",
                                    "source": "kb:%s@%s" % (doc["id"], doc["version"])}}]}

    def _step_node_for(self, step):
        for node in self.server.doc["nodes"]:
            if node["kind"] == "WorkflowStep" and node.get("name") == step:
                return node
        return None


class Reviewer:
    """Approves or rejects. The only role with approve rights."""

    role = "Reviewer"

    def __init__(self, server):
        self.server = server

    def decide(self, review_task_id, proposal_id, approve=True, reason=""):
        payload = {"proposal_id": proposal_id,
                   "decision": "approved" if approve else "rejected",
                   "reason": reason}
        return self.server.call("agent.report", task_id=review_task_id,
                                payload=payload)


def run_cycle(document, knowledge_base, intent, steps, schema_validator=None):
    """The full RFC-0006 Examples cycle. Returns (server, transcript)."""
    server = Server(document, knowledge_base, schema_validator=schema_validator)
    planner, coder, reviewer = Planner(server), Coder(server), Reviewer(server)

    transcript = []
    for item in planner.plan(intent, steps):
        record = coder.implement(item["task"], item["step"])
        transcript.append(record)
        if record["proposal_id"]:
            approved = reviewer.decide(record["review_task_id"],
                                       record["proposal_id"], approve=True)
            record["review_state"] = approved["state"]
            record["applied"] = approved["result"]["applied_nodes"]
    return server, transcript


def _slug(text):
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower())
