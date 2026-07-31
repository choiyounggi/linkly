"""The RFC-0006 Examples cycle — ROADMAP Phase 3's completion criterion."""

import json
import os
import unittest

from lnpl.agents import Coder, Planner, Reviewer, run_cycle
from lnpl.kb import KnowledgeBase
from lnpl.protocol import RpcError, Server

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN_STEPS = ["validate input", "authenticate", "cache user",
                "generate token", "audit login", "return token"]


def golden():
    with open(os.path.join(REPO, "examples", "login.lir.json"), encoding="utf-8") as fh:
        return json.load(fh)


class TestCycle(unittest.TestCase):
    def setUp(self):
        self.doc = golden()
        self.server, self.transcript = run_cycle(
            self.doc, KnowledgeBase(), "Login", GOLDEN_STEPS)

    def test_every_step_is_dispatched_and_reported(self):
        self.assertEqual([r["step"] for r in self.transcript], GOLDEN_STEPS)
        self.assertTrue(all(t.state in ("completed", "input-required", "failed")
                            for t in self.server.tasks.values()))

    def test_the_jwt_step_routes_loads_pins_proposes_and_is_approved(self):
        rec = next(r for r in self.transcript if r["step"] == "generate token")
        self.assertEqual(rec["doc_id"], "security-jwt-issuance")
        self.assertEqual(rec["kb_version"], "0.1.0")
        self.assertTrue(rec["proposal_id"])
        self.assertEqual(rec["review_state"], "completed")
        self.assertEqual(rec["applied"], ["wf.login.step.4",
                                          "wf.login.step.4.authz"])

    def test_the_cycle_uses_the_whole_method_surface(self):
        used = {m for m, _p in self.server.log}
        for m in ("agent.card", "agent.dispatch", "agent.report",
                  "ir.propose", "kb.route", "kb.load", "kb.verify"):
            self.assertIn(m, used)

    def test_the_applied_effect_is_owned_by_its_step(self):
        nodes = {n["id"]: n for n in self.server.doc["nodes"]}
        self.assertIn("wf.login.step.4.authz",
                      nodes["wf.login.step.4"]["children"])

    def test_no_node_ends_up_orphaned(self):
        nodes = self.server.doc["nodes"]
        owned = set()
        for n in nodes:
            owned.update(n.get("children", []))
        entry_kinds = {"Entity", "Service", "Event", "Capability",
                       "Policy", "Security", "Performance"}
        orphans = [n["id"] for n in nodes
                   if n["kind"] not in entry_kinds and n["id"] not in owned]
        self.assertEqual(orphans, [])

    def test_the_applied_node_records_its_provenance(self):
        node = next(n for n in self.server.doc["nodes"]
                    if n["id"] == "wf.login.step.4.authz")
        self.assertEqual(node["meta"]["origin"], "agent:Coder")
        self.assertIn("security-jwt-issuance@0.1.0", node["meta"]["source"])

    def test_only_the_issuance_step_gains_an_authorization(self):
        authz = [n["id"] for n in self.server.doc["nodes"]
                 if n["kind"] == "Authorization"]
        self.assertEqual(authz, ["wf.login.step.4.authz"])


class TestCoderRestraint(unittest.TestCase):
    """The Coder emits what the KB prescribes, and stops when it prescribes nothing."""

    def setUp(self):
        self.server = Server(golden(), KnowledgeBase())
        self.coder = Coder(self.server)
        self.planner = Planner(self.server)

    def _task(self, step):
        return self.server.call("agent.dispatch", role="Coder",
                                objective="implement %s" % step,
                                deadline_ms=1000, idempotency_key="t-%s" % step)

    def test_an_unrouted_step_proposes_nothing(self):
        rec = self.coder.implement(self._task("validate input"), "validate input")
        self.assertIsNone(rec["doc_id"])
        self.assertIsNone(rec["proposal_id"])
        self.assertEqual(len(self.server.proposals), 0)

    def test_a_routed_step_without_a_prescription_proposes_nothing(self):
        rec = self.coder.implement(self._task("authenticate"), "authenticate")
        self.assertEqual(rec["doc_id"], "patterns-repository-call")
        self.assertIsNone(rec["proposal_id"])

    def test_planner_holds_no_propose_rights(self):
        card = self.server.call("agent.card", role="Planner")
        self.assertEqual(card["ir_access"]["propose"], [])

    def test_planner_dispatch_is_idempotent_across_replans(self):
        first = self.planner.plan("Login", GOLDEN_STEPS)
        second = self.planner.plan("Login", GOLDEN_STEPS)
        self.assertEqual([t["task"]["task_id"] for t in first],
                         [t["task"]["task_id"] for t in second])


class TestRejectionPath(unittest.TestCase):
    def test_a_rejected_proposal_leaves_the_document_unchanged(self):
        doc = golden()
        server = Server(doc, KnowledgeBase())
        coder, reviewer = Coder(server), Reviewer(server)
        task = server.call("agent.dispatch", role="Coder", objective="x",
                           deadline_ms=1000, idempotency_key="rj")
        rec = coder.implement(task, "generate token")
        before = len(server.doc["nodes"])
        with self.assertRaises(RpcError) as ctx:
            reviewer.decide(rec["review_task_id"], rec["proposal_id"],
                            approve=False, reason="not now")
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertEqual(len(server.doc["nodes"]), before)
        self.assertEqual(server.applied, [])


class TestSchemaGate(unittest.TestCase):
    def test_a_proposal_that_breaks_the_schema_is_refused_at_apply_time(self):
        def reject_all(_document):
            raise RuntimeError("schema says no")

        server = Server(golden(), KnowledgeBase(), schema_validator=reject_all)
        coder = Coder(server)
        task = server.call("agent.dispatch", role="Coder", objective="x",
                           deadline_ms=1000, idempotency_key="sg")
        rec = coder.implement(task, "generate token")
        before = len(server.doc["nodes"])
        with self.assertRaises(RpcError) as ctx:
            Reviewer(server).decide(rec["review_task_id"], rec["proposal_id"])
        self.assertEqual(ctx.exception.type, "ir_invalid")
        self.assertIn("fails validation", str(ctx.exception))
        self.assertEqual(len(server.doc["nodes"]), before)


if __name__ == "__main__":
    unittest.main()
