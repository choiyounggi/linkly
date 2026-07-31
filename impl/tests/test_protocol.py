"""Agent protocol — RFC-0006: methods, errors, idempotency, task lifecycle."""

import json
import os
import unittest

from lnpl.kb import KnowledgeBase
from lnpl.protocol import ERRORS, RpcError, Server

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_golden():
    with open(os.path.join(REPO, "examples", "login.lir.json"), encoding="utf-8") as fh:
        return json.load(fh)


def server():
    return Server(load_golden(), KnowledgeBase())


AUTHZ = {"kind": "Authorization", "id": "wf.login.step.4.authz",
         "requirement": "verified jwt"}


def fragment(nodes=None):
    return {"module": "login", "nodes": nodes or [AUTHZ]}


class TestMethodSurface(unittest.TestCase):
    def setUp(self):
        self.s = server()

    def test_all_eight_methods_are_reachable(self):
        card = self.s.call("agent.card", role="Coder")
        self.assertEqual(len(card["methods"]), 8)
        for m in card["methods"]:
            handler = getattr(self.s, "_m_" + m.replace(".", "_"), None)
            self.assertIsNotNone(handler, m)

    def test_unknown_method_returns_the_reserved_code(self):
        resp = self.s.handle({"jsonrpc": "2.0", "id": 1, "method": "agent.nope"})
        self.assertEqual(resp["error"]["code"], -32601)

    def test_wrong_jsonrpc_version_is_rejected(self):
        resp = self.s.handle({"jsonrpc": "1.0", "id": 1, "method": "ir.get"})
        self.assertIn("error", resp)

    def test_agent_card_reports_role_specific_propose_rights(self):
        self.assertEqual(self.s.call("agent.card", role="Planner")["ir_access"]["propose"], [])
        self.assertTrue(self.s.call("agent.card", role="Coder")["ir_access"]["propose"])
        self.assertTrue(self.s.call("agent.card", role="Reviewer")["approve"])

    def test_ir_get_returns_a_node_and_errors_on_a_missing_one(self):
        self.assertEqual(self.s.call("ir.get", node_id="wf.login")["node"]["kind"],
                         "Workflow")
        with self.assertRaises(RpcError):
            self.s.call("ir.get", node_id="wf.nope")


class TestErrorContract(unittest.TestCase):
    def test_every_error_type_carries_a_code_and_a_retryable_flag(self):
        for name, (code, retryable) in ERRORS.items():
            self.assertIsInstance(code, int, name)
            self.assertIsInstance(retryable, bool, name)

    def test_implementation_defined_codes_stay_in_the_reserved_server_range(self):
        for name, (code, _r) in ERRORS.items():
            if code in (-32602, -32603):
                continue        # envelope-layer reserved codes, reused deliberately
            self.assertTrue(-32099 <= code <= -32000, "%s -> %d" % (name, code))

    def test_timeouts_are_retryable_and_rejections_are_not(self):
        self.assertTrue(ERRORS["agent_timeout"][1])
        self.assertFalse(ERRORS["proposal_rejected"][1])
        self.assertFalse(ERRORS["kb_version_conflict"][1])

    def test_internal_errors_do_not_leak_details(self):
        s = server()
        # Force an unexpected exception inside a handler.
        s.kb = None
        resp = s.handle({"jsonrpc": "2.0", "id": 1, "method": "kb.route",
                         "params": {"task_description": "x"}})
        self.assertEqual(resp["error"]["message"], "internal error")
        self.assertNotIn("Traceback", json.dumps(resp))
        self.assertNotIn(REPO, json.dumps(resp))


class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.s = server()

    def test_dispatch_requires_a_key(self):
        with self.assertRaises(RpcError) as ctx:
            self.s.call("agent.dispatch", role="Coder", objective="x", deadline_ms=1000)
        self.assertIn("idempotency_key", str(ctx.exception))

    def test_dispatch_requires_a_deadline(self):
        with self.assertRaises(RpcError) as ctx:
            self.s.call("agent.dispatch", role="Coder", objective="x",
                        idempotency_key="k")
        self.assertIn("deadline_ms", str(ctx.exception))

    def test_replay_returns_the_stored_first_response(self):
        a = self.s.call("agent.dispatch", role="Coder", objective="x",
                        deadline_ms=1000, idempotency_key="k1")
        b = self.s.call("agent.dispatch", role="Coder", objective="x",
                        deadline_ms=1000, idempotency_key="k1")
        self.assertEqual(a, b)
        self.assertEqual(len(self.s.tasks), 1, "replay created a second task")

    def test_same_key_with_different_params_is_an_error(self):
        self.s.call("agent.dispatch", role="Coder", objective="x",
                    deadline_ms=1000, idempotency_key="k2")
        with self.assertRaises(RpcError) as ctx:
            self.s.call("agent.dispatch", role="Coder", objective="different",
                        deadline_ms=1000, idempotency_key="k2")
        self.assertEqual(ctx.exception.type, "idempotency_mismatch")
        self.assertFalse(ctx.exception.retryable)


class TestProposalIsTwoStage(unittest.TestCase):
    def setUp(self):
        self.s = server()
        self.before = len(self.s.doc["nodes"])

    def _propose(self, nodes=None, role="Coder"):
        return self.s.call("ir.propose", role=role, ir_fragment=fragment(nodes),
                           deadline_ms=1000, idempotency_key="p-%s" % role)

    def test_propose_does_not_mutate_the_document(self):
        out = self._propose()
        self.assertEqual(out["state"], "pending")
        self.assertEqual(len(self.s.doc["nodes"]), self.before)

    def test_approval_applies_the_nodes(self):
        out = self._propose()
        task = self.s.call("agent.report", task_id=out["review_task_id"],
                           payload={"proposal_id": out["proposal_id"],
                                    "decision": "approved"})
        self.assertEqual(task["state"], "completed")
        self.assertEqual(len(self.s.doc["nodes"]), self.before + 1)

    def test_rejection_leaves_the_document_untouched(self):
        out = self._propose()
        with self.assertRaises(RpcError) as ctx:
            self.s.call("agent.report", task_id=out["review_task_id"],
                        payload={"proposal_id": out["proposal_id"],
                                 "decision": "rejected", "reason": "no"})
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertEqual(len(self.s.doc["nodes"]), self.before)

    def test_a_role_without_approve_rights_cannot_approve(self):
        out = self._propose()
        # Re-purpose the review task to a non-approving role.
        self.s.tasks[out["review_task_id"]].role = "Coder"
        with self.assertRaises(RpcError):
            self.s.call("agent.report", task_id=out["review_task_id"],
                        payload={"proposal_id": out["proposal_id"],
                                 "decision": "approved"})
        self.assertEqual(len(self.s.doc["nodes"]), self.before)

    def test_a_role_may_not_propose_a_kind_outside_its_rights(self):
        with self.assertRaises(RpcError) as ctx:
            self.s.call("ir.propose", role="Planner", ir_fragment=fragment(),
                        deadline_ms=1000, idempotency_key="pp")
        self.assertIn("may not propose", str(ctx.exception))

    def test_module_mismatch_is_rejected(self):
        with self.assertRaises(RpcError) as ctx:
            self.s.call("ir.propose", role="Coder",
                        ir_fragment={"module": "other", "nodes": [AUTHZ]},
                        deadline_ms=1000, idempotency_key="pm")
        self.assertIn("does not match", str(ctx.exception))

    def test_a_dangling_child_reference_is_refused_at_apply_time(self):
        bad = {"kind": "WorkflowStep", "id": "wf.login.step.9",
               "name": "ghost step", "children": ["wf.login.step.9.nope"]}
        out = self._propose([bad])
        with self.assertRaises(RpcError) as ctx:
            self.s.call("agent.report", task_id=out["review_task_id"],
                        payload={"proposal_id": out["proposal_id"],
                                 "decision": "approved"})
        self.assertIn("dangling", str(ctx.exception))

    def test_double_decision_on_one_proposal_is_refused(self):
        out = self._propose()
        self.s.call("agent.report", task_id=out["review_task_id"],
                    payload={"proposal_id": out["proposal_id"],
                             "decision": "approved"})
        with self.assertRaises(RpcError):
            self.s.call("agent.report", task_id=out["review_task_id"],
                        payload={"proposal_id": out["proposal_id"],
                                 "decision": "approved"})


class TestTaskLifecycle(unittest.TestCase):
    def setUp(self):
        self.s = server()

    def test_a_task_starts_submitted_and_records_its_history(self):
        t = self.s.call("agent.dispatch", role="Coder", objective="x",
                        deadline_ms=1000, idempotency_key="t1")
        self.assertEqual(t["state"], "submitted")
        done = self.s.call("agent.report", task_id=t["task_id"], state="completed",
                           payload={})
        self.assertEqual(done["history"], ["submitted", "working", "completed"])

    def test_input_required_is_a_reachable_non_terminal_state(self):
        t = self.s.call("agent.dispatch", role="Coder", objective="x",
                        deadline_ms=1000, idempotency_key="t2")
        mid = self.s.call("agent.report", task_id=t["task_id"],
                          state="input-required", payload={})
        self.assertEqual(mid["state"], "input-required")

    def test_a_terminal_task_cannot_transition_again(self):
        t = self.s.call("agent.dispatch", role="Coder", objective="x",
                        deadline_ms=1000, idempotency_key="t3")
        self.s.call("agent.report", task_id=t["task_id"], state="completed", payload={})
        with self.assertRaises(RpcError):
            self.s.call("agent.report", task_id=t["task_id"], state="failed", payload={})


class TestKbOverTheWire(unittest.TestCase):
    def setUp(self):
        self.s = server()

    def test_kb_route_matches_rfc_0005_signature(self):
        out = self.s.call("kb.route", task_description="generate token")
        self.assertEqual(out["doc_ids"][0], "security-jwt-issuance")

    def test_kb_load_returns_the_document(self):
        doc = self.s.call("kb.load", doc_id="security-jwt-issuance")["document"]
        self.assertEqual(doc["version"], "0.1.0")

    def test_kb_verify_conflict_is_typed_and_not_retryable(self):
        with self.assertRaises(RpcError) as ctx:
            self.s.call("kb.verify", doc_id="security-jwt-issuance", version="9.9.9")
        self.assertEqual(ctx.exception.type, "kb_version_conflict")
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("re-route", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
