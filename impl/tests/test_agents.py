"""The RFC-0006 Examples cycle — ROADMAP Phase 3's completion criterion."""

import json
import os
import unittest

from lnpl.agents import (Architect, Coder, PerformanceAnalyzer, Planner,
                         RefactoringAgent, ReleaseAgent, Reviewer, SecurityAuditor,
                         Tester, run_cycle)
from lnpl.lower import derive_id
from lnpl.spec import EXPECTATIONS, run_manifest
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


class TestReviewerJudgment(unittest.TestCase):
    """The Reviewer decides for itself. A reviewer that only echoes its caller
    turns the two-stage approval `ir.propose` buys into a rubber stamp."""

    def setUp(self):
        self.server = Server(golden(), KnowledgeBase())
        self.reviewer = Reviewer(self.server)

    def _propose(self, nodes, role="Coder"):
        return self.server.call("ir.propose", role=role,
                                ir_fragment={"module": "login", "nodes": nodes},
                                deadline_ms=1000,
                                idempotency_key="k-%d" % len(self.server.proposals))

    def _good_pair(self):
        """A well-formed proposal: a new Effect plus the parent that owns it."""
        step = next(n for n in self.server.doc["nodes"]
                    if n["id"] == "wf.login.step.4")
        parent = dict(step)
        parent["children"] = list(step.get("children", [])) + ["wf.login.step.4.authz"]
        child = {"kind": "Authorization", "id": "wf.login.step.4.authz",
                 "requirement": "verified jwt",
                 "meta": {"origin": "agent:Coder", "source": "kb:security-jwt-issuance@0.1.0"}}
        return [parent, child]

    def test_a_well_formed_proposal_is_approved_without_being_told_to(self):
        out = self._propose(self._good_pair())
        task = self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertEqual(task["state"], "completed")
        self.assertEqual(task["result"]["decision"], "approved")

    def test_it_rejects_a_node_with_no_provenance(self):
        nodes = self._good_pair()
        del nodes[1]["meta"]
        out = self._propose(nodes)
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertIn("provenance", str(ctx.exception))

    def test_it_rejects_an_orphaned_effect(self):
        # The child alone: nothing owns it, so it is unreachable in the flat table.
        out = self._propose([self._good_pair()[1]])
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertIn("orphan", str(ctx.exception))

    def test_it_rejects_a_dangling_reference(self):
        nodes = self._good_pair()
        nodes[0]["children"] = nodes[0]["children"] + ["wf.login.step.4.ghost"]
        out = self._propose(nodes)
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        # The type matters: the apply-time guard also says "dangling", so asserting
        # the substring alone passes even when the reviewer never looked.
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("dangling: unresolved reference", str(ctx.exception))

    def test_it_rejects_a_removal_expressed_as_an_edit(self):
        # Replacing an existing step with empty children detaches the effect it
        # owned. Nothing is "added", so a check that only looked at new nodes would
        # approve a silent removal.
        step = next(n for n in self.server.doc["nodes"]
                    if n["id"] == "wf.login.step.2")
        stripped = dict(step)
        stripped["children"] = []
        out = self._propose([stripped])
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("wf.login.step.2.repo", str(ctx.exception))

    def test_it_rejects_a_node_that_claims_to_own_itself(self):
        child = self._good_pair()[1]
        child["children"] = [child["id"]]
        out = self._propose([child])
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("cycle", str(ctx.exception))

    def test_it_rejects_two_new_nodes_that_own_each_other(self):
        # A 2-cycle with no root: each node has an owner, so an "is anyone's child?"
        # check waves it through while the pair stays unreachable from every entry
        # node. RFC-0001 rule 4 forbids it by naming the whole graph, not one hop.
        meta = {"origin": "agent:Coder", "source": "kb:security-jwt-issuance@0.1.0"}
        a = {"kind": "Concurrency", "id": "wf.login.step.4.a", "name": "a",
             "children": ["wf.login.step.4.b"], "meta": meta}
        b = {"kind": "Concurrency", "id": "wf.login.step.4.b", "name": "b",
             "children": ["wf.login.step.4.a"], "meta": meta}
        out = self._propose([a, b])
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("cycle", str(ctx.exception))

    def test_it_rejects_a_constraint_removal_expressed_as_an_edit(self):
        # `constraints` is where the runtime reads retry/timeout/rollback and the
        # security mechanisms (interp.py). Dropping one is a removal that changes
        # behaviour, and the Constraint node stays in the document — so an
        # ownership check cannot see it. Only the "no dropped references" rule can.
        svc = next(n for n in self.server.doc["nodes"] if n["id"] == "svc.login")
        stripped = dict(svc)
        stripped["constraints"] = [c for c in svc["constraints"] if c != "security.login"]
        out = self._propose([stripped], role="Architect")
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("security.login", str(ctx.exception))

    def test_it_rejects_a_dangling_constraint_reference(self):
        # RFC-0001 rule 6 covers named references too, not just `children`.
        svc = next(n for n in self.server.doc["nodes"] if n["id"] == "svc.login")
        edited = dict(svc)
        edited["constraints"] = list(svc["constraints"]) + ["security.ghost"]
        out = self._propose([edited], role="Architect")
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("security.ghost", str(ctx.exception))

    def test_it_rejects_a_kind_swap_under_the_same_id(self):
        # Same id, different kind = the old node removed and a new one put in its
        # place. `ir.propose` cannot express the removal half.
        step = next(n for n in self.server.doc["nodes"]
                    if n["id"] == "wf.login.step.2.repo")
        swapped = dict(step)
        swapped["kind"] = "CacheAccess"
        out = self._propose([swapped])
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("kind", str(ctx.exception))

    def test_it_rejects_stealing_a_child_that_already_has_an_owner(self):
        # Two owners for one node breaks RFC-0001 rule 2, and silently moves a step
        # into a second parent's execution order.
        step = next(n for n in self.server.doc["nodes"] if n["id"] == "wf.login.step.4")
        thief = dict(step)
        thief["children"] = list(step.get("children", [])) + ["wf.login.step.2.repo"]
        out = self._propose([thief])
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("wf.login.step.2.repo", str(ctx.exception))

    def test_it_rejects_a_made_up_provenance_string(self):
        nodes = self._good_pair()
        nodes[1]["meta"] = {"origin": "agent:Coder", "source": "i made it up"}
        out = self._propose(nodes)
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertIn("provenance", str(ctx.exception))

    def test_it_rejects_an_unknown_provenance_scheme_even_when_the_tail_resolves(self):
        # This isolates the *form* rule from the *resolves* rule. "XX:entity.user"
        # has a tail that resolves in the document, so a reviewer that only asked
        # "does it resolve?" would approve it — and the resolver itself assumes the
        # form (it slices off three characters), so a scheme it does not know would
        # be interpreted as an ir: reference. Only `kb:` and `ir:` are provenance.
        nodes = self._good_pair()
        nodes[1]["meta"] = {"origin": "agent:Coder", "source": "XX:entity.user"}
        out = self._propose(nodes)
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("provenance", str(ctx.exception))

    def test_it_rejects_provenance_that_only_looks_right(self):
        # Well-formed and pointing at nothing. The KB and the document are both in
        # reach, so "it matches the regex" is not enough to call it a basis.
        for source in ("kb:totally-made-up-doc@9.9.9", "ir:wf.does.not.exist"):
            nodes = self._good_pair()
            nodes[1]["meta"] = {"origin": "agent:Coder", "source": source}
            out = self._propose(nodes)
            with self.assertRaises(RpcError) as ctx:
                self.reviewer.decide(out["review_task_id"], out["proposal_id"])
            self.assertEqual(ctx.exception.type, "proposal_rejected")
            self.assertIn("provenance", str(ctx.exception))

    def test_it_rejects_a_kb_provenance_pinned_to_the_wrong_version(self):
        nodes = self._good_pair()
        nodes[1]["meta"] = {"origin": "agent:Coder",
                            "source": "kb:security-jwt-issuance@9.9.9"}
        out = self._propose(nodes)
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertIn("provenance", str(ctx.exception))

    def test_it_rejects_a_kind_outside_the_proposers_rights(self):
        # Tester may propose Behavior only; an Effect is outside its rights. The
        # protocol blocks this at propose time, so plant it directly to prove the
        # reviewer is a second, independent gate.
        out = self._propose(self._good_pair())
        self.server.proposals[out["proposal_id"]]["role"] = "Tester"
        with self.assertRaises(RpcError) as ctx:
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertIn("rights", str(ctx.exception))

    def test_it_rejects_what_the_schema_would_refuse(self):
        def reject(_doc):
            raise RuntimeError("schema says no")
        server = Server(golden(), KnowledgeBase(), schema_validator=reject)
        reviewer = Reviewer(server)
        step = next(n for n in server.doc["nodes"] if n["id"] == "wf.login.step.4")
        parent = dict(step)
        parent["children"] = ["wf.login.step.4.authz"]
        child = {"kind": "Authorization", "id": "wf.login.step.4.authz",
                 "requirement": "x",
                 "meta": {"origin": "agent:Coder",
                          "source": "kb:security-jwt-issuance@0.1.0"}}
        out = server.call("ir.propose", role="Coder",
                          ir_fragment={"module": "login", "nodes": [parent, child]},
                          deadline_ms=1000, idempotency_key="s1")
        with self.assertRaises(RpcError) as ctx:
            reviewer.decide(out["review_task_id"], out["proposal_id"])
        # `ir.apply` reports schema failures too ("merged IR fails validation"), so
        # the substring alone passes even if the reviewer never ran the validator.
        # The type is what proves the rejection came from review.
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("schema: merged document would be invalid", str(ctx.exception))

    def test_an_explicit_override_is_honoured_and_recorded(self):
        nodes = self._good_pair()
        del nodes[1]["meta"]          # would be rejected on its own judgment
        out = self._propose(nodes)
        task = self.reviewer.decide(out["review_task_id"], out["proposal_id"],
                                    approve=True, reason="accepted knowingly")
        self.assertEqual(task["result"]["decision"], "approved")
        self.assertIn("override", task["result"]["reason"])

    def test_assessment_does_not_mutate_the_document(self):
        before = [dict(n) for n in self.server.doc["nodes"]]
        out = self._propose([self._good_pair()[1]])     # will be rejected
        with self.assertRaises(RpcError):
            self.reviewer.decide(out["review_task_id"], out["proposal_id"])
        self.assertEqual(self.server.doc["nodes"], before)


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
    def test_a_proposal_that_breaks_the_schema_is_caught_at_review_time(self):
        # The Reviewer now assesses before approving, so a schema problem is
        # reported as a rejection with a reason rather than surfacing later as an
        # apply-time fault. Either way the document must be untouched.
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
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("schema", str(ctx.exception))
        self.assertEqual(len(server.doc["nodes"]), before)
        self.assertEqual(server.applied, [])

    def test_an_override_still_reaches_the_apply_time_guard(self):
        # The reviewer is a second gate, not a replacement for the first: forcing
        # approval past its judgment must still hit the apply-time validation.
        def reject_all(_document):
            raise RuntimeError("schema says no")

        server = Server(golden(), KnowledgeBase(), schema_validator=reject_all)
        coder = Coder(server)
        task = server.call("agent.dispatch", role="Coder", objective="x",
                           deadline_ms=1000, idempotency_key="sg2")
        rec = coder.implement(task, "generate token")
        with self.assertRaises(RpcError) as ctx:
            Reviewer(server).decide(rec["review_task_id"], rec["proposal_id"],
                                    approve=True, reason="forced")
        self.assertEqual(ctx.exception.type, "ir_invalid")
        self.assertEqual(server.applied, [])


SPEC_FIXTURE = {
    "entity": {"name": "Order", "fields": [{"name": "id", "type": "UUID"},
                                           {"name": "total", "type": "Money"}]},
    "service": {"name": "OrderService"},
    "workflow": {"name": "Checkout", "steps": ["validate input", "create order"]},
}


def _task(server, role, key):
    return server.call("agent.dispatch", role=role, objective="t",
                       deadline_ms=1000, idempotency_key=key)


EMPTY_DOC = {"lir_version": "0.1", "module": "orders", "nodes": []}


class TestArchitect(unittest.TestCase):
    """Architect originates a program, so it starts from an empty module.

    Running it against the golden module would add a second Service, and
    `lower.py` makes a multi-service module with no `database` clause a compile
    error — a test that asserted approval there would enshrine a document the
    compiler refuses to emit.
    """

    def setUp(self):
        self.server = Server(EMPTY_DOC, KnowledgeBase())
        self.arch = Architect(self.server)

    def test_a_complete_spec_yields_declaration_nodes_that_the_reviewer_accepts(self):
        rec = self.arch.design(_task(self.server, "Architect", "a1"), SPEC_FIXTURE)
        self.assertIn("entity.order", rec["node_ids"])
        self.assertIn("svc.order", rec["node_ids"])
        self.assertIn("wf.checkout", rec["node_ids"])
        task = Reviewer(self.server).decide(rec["review_task_id"], rec["proposal_id"])
        self.assertEqual(task["result"]["decision"], "approved", task["result"]["reason"])

    def test_an_incomplete_spec_proposes_nothing_and_cites_a_clause(self):
        spec = dict(SPEC_FIXTURE)
        del spec["workflow"]
        rec = self.arch.design(_task(self.server, "Architect", "a2"), spec)
        self.assertIsNone(rec["proposal_id"])
        self.assertIn("RFC-0006", rec["clause"])
        self.assertEqual(len(self.server.proposals), 0)

    def test_ids_come_from_the_shared_derivation_rule(self):
        rec = self.arch.design(_task(self.server, "Architect", "a3"), SPEC_FIXTURE)
        self.assertIn(derive_id("OrderService", "Service"), rec["node_ids"])
        self.assertIn(derive_id("Checkout", "Workflow"), rec["node_ids"])

    def test_it_proposes_no_kind_outside_its_rights(self):
        rec = self.arch.design(_task(self.server, "Architect", "a4"), SPEC_FIXTURE)
        allowed = set(self.server.call("agent.card", role="Architect")["ir_access"]["propose"])
        kinds = {n["kind"] for n in self.server.proposals[rec["proposal_id"]]["nodes"]}
        self.assertTrue(kinds <= allowed, kinds - allowed)


class TestSecurityAuditor(unittest.TestCase):
    def test_the_golden_is_clean_because_it_already_declares_security(self):
        server = Server(golden(), KnowledgeBase())
        rec = SecurityAuditor(server).audit(_task(server, "SecurityAuditor", "s1"))
        self.assertIsNone(rec["proposal_id"])
        self.assertIn("already declares Security", rec["reason"])

    def test_a_service_reading_secrets_without_security_gets_a_finding(self):
        doc = golden()
        for node in doc["nodes"]:
            if node["kind"] == "Service":
                node["constraints"] = [c for c in node["constraints"]
                                       if not c.startswith("security.")]
        doc["nodes"] = [n for n in doc["nodes"] if n["kind"] != "Security"]
        server = Server(doc, KnowledgeBase())
        rec = SecurityAuditor(server).audit(_task(server, "SecurityAuditor", "s2"))
        self.assertTrue(rec["proposal_id"])
        task = Reviewer(server).decide(rec["review_task_id"], rec["proposal_id"])
        self.assertEqual(task["result"]["decision"], "approved", task["result"]["reason"])
        self.assertIn("security.login", [n["id"] for n in server.doc["nodes"]])

    def test_it_reports_the_attachment_it_may_not_propose_itself(self):
        # Attaching the constraint means replacing a Service (a Declaration), which
        # is outside this role's rights. The gap is reported, not silently crossed.
        doc = golden()
        for node in doc["nodes"]:
            if node["kind"] == "Service":
                node["constraints"] = [c for c in node["constraints"]
                                       if not c.startswith("security.")]
        doc["nodes"] = [n for n in doc["nodes"] if n["kind"] != "Security"]
        server = Server(doc, KnowledgeBase())
        rec = SecurityAuditor(server).audit(_task(server, "SecurityAuditor", "s5"))
        self.assertTrue(rec["attachment_required"])
        kinds = {n["kind"] for n in server.proposals[rec["proposal_id"]]["nodes"]}
        allowed = set(server.call("agent.card",
                                  role="SecurityAuditor")["ir_access"]["propose"])
        self.assertTrue(kinds <= allowed, kinds - allowed)

    def test_no_password_field_means_no_finding(self):
        doc = golden()
        for node in doc["nodes"]:
            if node["kind"] == "Entity":
                node["fields"] = [f for f in node["fields"] if f["type"] != "Password"]
        server = Server(doc, KnowledgeBase())
        rec = SecurityAuditor(server).audit(_task(server, "SecurityAuditor", "s3"))
        self.assertIsNone(rec["proposal_id"])
        self.assertIn("Password", rec["reason"])

    def test_the_finding_records_its_kb_provenance(self):
        doc = golden()
        for node in doc["nodes"]:
            if node["kind"] == "Service":
                node["constraints"] = [c for c in node["constraints"]
                                       if not c.startswith("security.")]
        doc["nodes"] = [n for n in doc["nodes"] if n["kind"] != "Security"]
        server = Server(doc, KnowledgeBase())
        rec = SecurityAuditor(server).audit(_task(server, "SecurityAuditor", "s4"))
        node = next(n for n in server.proposals[rec["proposal_id"]]["nodes"]
                    if n["kind"] == "Security")
        self.assertIn("kb:security-jwt-issuance@", node["meta"]["source"])


class TestPerformanceAnalyzer(unittest.TestCase):
    def _server_without_budget(self):
        doc = golden()
        for node in doc["nodes"]:
            if node["kind"] == "Service":
                node["constraints"] = [c for c in node["constraints"]
                                       if not c.startswith("perf.")]
        doc["nodes"] = [n for n in doc["nodes"] if n["kind"] != "Performance"]
        return Server(doc, KnowledgeBase())

    def test_no_measurements_means_no_proposal(self):
        server = self._server_without_budget()
        rec = PerformanceAnalyzer(server).analyze(
            _task(server, "PerformanceAnalyzer", "p1"), "wf.login", [])
        self.assertIsNone(rec["proposal_id"])
        self.assertIn("RFC-0006", rec["clause"])

    def test_a_budget_is_derived_by_rounding_the_observed_max_up_to_10ms(self):
        server = self._server_without_budget()
        rec = PerformanceAnalyzer(server).analyze(
            _task(server, "PerformanceAnalyzer", "p2"), "wf.login",
            [{"duration_ms": 33}, {"duration_ms": 28}])
        self.assertEqual(rec["observed_max_ms"], 33)
        self.assertEqual(rec["budget_ms"], 40)

    def test_an_exact_multiple_is_not_rounded_further(self):
        server = self._server_without_budget()
        rec = PerformanceAnalyzer(server).analyze(
            _task(server, "PerformanceAnalyzer", "p3"), "wf.login",
            [{"duration_ms": 30}])
        self.assertEqual(rec["budget_ms"], 30)

    def test_a_zero_or_negative_duration_is_refused(self):
        for bad in (0, -500):
            server = self._server_without_budget()
            rec = PerformanceAnalyzer(server).analyze(
                _task(server, "PerformanceAnalyzer", "pz%d" % bad), "wf.login",
                [{"duration_ms": bad}])
            self.assertIsNone(rec["proposal_id"], bad)
            self.assertIn("positive", rec["reason"])

    def test_a_measurement_without_a_duration_is_refused_not_crashed(self):
        server = self._server_without_budget()
        rec = PerformanceAnalyzer(server).analyze(
            _task(server, "PerformanceAnalyzer", "pk"), "wf.login", [{"steps": []}])
        self.assertIsNone(rec["proposal_id"])
        self.assertIn("duration_ms", rec["reason"])

    def test_an_existing_budget_is_not_overwritten(self):
        server = Server(golden(), KnowledgeBase())      # golden has response < 50ms
        rec = PerformanceAnalyzer(server).analyze(
            _task(server, "PerformanceAnalyzer", "p4"), "wf.login",
            [{"duration_ms": 999}])
        self.assertIsNone(rec["proposal_id"])
        self.assertEqual(len(server.proposals), 0)


class TestTester(unittest.TestCase):
    def setUp(self):
        self.server = Server(golden(), KnowledgeBase())
        self.manifest = Tester(self.server).derive(
            _task(self.server, "Tester", "t1"), "wf.login")

    def test_the_derived_manifest_actually_runs_and_passes(self):
        passed, failed, lines = run_manifest(self.manifest, self.server.doc)
        self.assertEqual(failed, 0, lines)
        self.assertGreater(passed, 0)

    def test_a_retry_policy_produces_an_exhaustion_case(self):
        names = [c["name"] for c in self.manifest["cases"]]
        self.assertTrue(any("retries" in n for n in names), names)
        case = next(c for c in self.manifest["cases"] if "retries" in c["name"])
        self.assertIn("attempts 4", case["expect"])   # golden declares retry 3

    def test_every_expectation_is_in_the_runner_vocabulary(self):
        for case in self.manifest["cases"]:
            for phrase in case["expect"]:
                self.assertIn(phrase.split()[0], EXPECTATIONS, phrase)

    def test_tester_proposes_no_ir_at_all(self):
        self.assertEqual(len(self.server.proposals), 0)
        self.assertNotIn("ir.propose", {m for m, _p in self.server.log})

    def test_an_unknown_workflow_is_refused_with_a_citation(self):
        server = Server(golden(), KnowledgeBase())
        rec = Tester(server).derive(_task(server, "Tester", "t2"), "wf.nope")
        self.assertIsNone(rec["proposal_id"])
        self.assertIn("RFC-0001", rec["clause"])


class TestReleaseAgent(unittest.TestCase):
    def setUp(self):
        self.server = Server(golden(), KnowledgeBase())
        self.agent = ReleaseAgent(self.server)

    def test_the_summary_counts_kinds_and_lists_capabilities(self):
        s = self.agent.summarize(_task(self.server, "ReleaseAgent", "r1"),
                                 verification={"tests": True})
        self.assertEqual(s["node_count"], 19)
        self.assertEqual(s["capabilities"], ["jwt", "postgres", "redis"])
        self.assertEqual(s["by_kind"]["WorkflowStep"], 6)

    def test_missing_verification_blocks_readiness(self):
        s = self.agent.summarize(_task(self.server, "ReleaseAgent", "r2"))
        self.assertFalse(s["ready"])
        self.assertIn("no verification result was supplied", s["blockers"])

    def test_an_empty_verification_map_is_not_evidence(self):
        # `{}` looks like a result and carries none. It must block as hard as None.
        s = self.agent.summarize(_task(self.server, "ReleaseAgent", "r5"),
                                 verification={})
        self.assertFalse(s["ready"])

    def test_a_verification_result_that_is_not_a_map_blocks_readiness(self):
        # "it passed", True, a list of pairs: a caller asserting success in a shape
        # this cannot audit per check. It must block, and it must not crash — a
        # traceback while auditing evidence leaves no verdict at all.
        for i, bad in enumerate([True, "all green", [("tests", True)], 0.0]):
            s = self.agent.summarize(_task(self.server, "ReleaseAgent", "rn%d" % i),
                                     verification=bad)
            self.assertFalse(s["ready"])
            self.assertTrue(any("must be a map" in b or "no verification" in b
                                for b in s["blockers"]),
                            "blockers for %r were %r" % (bad, s["blockers"]))

    def test_verification_keys_of_mixed_types_do_not_crash_the_audit(self):
        s = self.agent.summarize(_task(self.server, "ReleaseAgent", "rmix"),
                                 verification={1: True, "a": False})
        self.assertFalse(s["ready"])
        self.assertTrue(any("not a pass" in b for b in s["blockers"]))

    def test_a_truthy_non_pass_marker_does_not_count_as_a_pass(self):
        s = self.agent.summarize(_task(self.server, "ReleaseAgent", "r6"),
                                 verification={"tests": "FAILED"})
        self.assertFalse(s["ready"])
        self.assertTrue(any("not a pass" in b for b in s["blockers"]))

    def test_a_failing_verification_is_not_turned_into_a_pass(self):
        s = self.agent.summarize(_task(self.server, "ReleaseAgent", "r3"),
                                 verification={"tests": True, "differential": False})
        self.assertFalse(s["ready"])
        self.assertTrue(any("differential" in b for b in s["blockers"]))

    def test_it_proposes_nothing(self):
        self.agent.summarize(_task(self.server, "ReleaseAgent", "r4"),
                             verification={"tests": True})
        self.assertNotIn("ir.propose", {m for m, _p in self.server.log})


TWO_ACCESS = {
    "lir_version": "0.1", "module": "t",
    "nodes": [
        {"kind": "Entity", "id": "entity.user", "name": "User",
         "fields": [{"name": "id", "type": "UUID"}]},
        {"kind": "Policy", "id": "policy.p",
         "rules": [{"name": "retry", "value": "2"}]},
        {"kind": "Service", "id": "svc.s", "name": "S", "children": ["wf.w"]},
        {"kind": "Workflow", "id": "wf.w", "name": "W",
         "children": ["wf.w.step.1", "wf.w.step.2"]},
        {"kind": "WorkflowStep", "id": "wf.w.step.1", "name": "load and audit",
         "children": ["wf.w.step.1.a", "wf.w.step.1.b"],
         "constraints": ["policy.p"]},
        {"kind": "RepositoryCall", "id": "wf.w.step.1.a",
         "entity": "entity.user", "operation": "read"},
        {"kind": "RepositoryCall", "id": "wf.w.step.1.b",
         "entity": "entity.user", "operation": "update"},
        {"kind": "WorkflowStep", "id": "wf.w.step.2", "name": "return user"},
    ],
}

# A node this proposal authors carries both; an *existing* node edited only for
# attachment carries `origin` alone — adding `source` to a node that has its own
# provenance would be rewriting it, which the gate refuses on purpose.
NEW_META = {"origin": "agent:RefactoringAgent",
            "source": "kb:patterns-repository-call@0.1.0"}
EDIT_META = {"origin": "agent:RefactoringAgent"}


class TestReviewerHonoursDeclaredIntent(unittest.TestCase):
    """RFC-0010 at the review gate — the second, independent check.

    A proposal planted straight into `server.proposals` never passes through
    `ir.propose`, so every condition has to hold here too. These tests use that
    seam, exactly as `test_it_rejects_a_kind_outside_the_proposers_rights` does.
    """

    ROLE = "RefactoringAgent"

    def setUp(self):
        self.server = Server(json.loads(json.dumps(TWO_ACCESS)), KnowledgeBase())
        self.reviewer = Reviewer(self.server)

    def _assess(self, nodes, intent):
        """Plant a proposal and get the Reviewer's verdict on it."""
        self.server.proposals["p1"] = {
            "id": "p1", "role": self.ROLE, "state": "pending",
            "nodes": nodes, "intent": intent, "review_task_id": "t1"}
        return self.reviewer._assess("p1")

    def _split(self, parent_children=None, to_children=None):
        parent = {"kind": "Workflow", "id": "wf.w", "name": "W",
                  "children": parent_children
                  or ["wf.w.step.1", "wf.w.split.1", "wf.w.step.2"],
                  "meta": dict(EDIT_META)}
        original = {"kind": "WorkflowStep", "id": "wf.w.step.1",
                    "name": "load and audit", "children": ["wf.w.step.1.a"],
                    "constraints": ["policy.p"]}
        new = {"kind": "WorkflowStep", "id": "wf.w.split.1", "name": "update user",
               "children": to_children if to_children is not None
               else ["wf.w.step.1.b"], "meta": dict(NEW_META)}
        return [parent, original, new]

    def _intent(self):
        return {"attach": [{"parent": "wf.w", "child": "wf.w.split.1"}],
                "move": [{"node": "wf.w.step.1.b", "from": "wf.w.step.1",
                          "to": "wf.w.split.1"}]}

    def test_a_declared_split_is_approved(self):
        ok, reason = self._assess(self._split(), self._intent())
        self.assertTrue(ok, reason)

    def test_an_undeclared_drop_is_still_a_removal(self):
        """Only the two steps — both Behavior, so rights are not the issue here.

        Including the `Workflow` parent would make this a rights refusal instead,
        since without an `intent` there is no declaration to permit that edit.
        """
        ok, reason = self._assess(self._split()[1:], {})
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("removal:"), reason)
        self.assertIn("RFC-0010", reason)

    def test_a_move_whose_destination_does_not_take_it_is_rejected(self):
        ok, reason = self._assess(self._split(to_children=[]), self._intent())
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("move:"), reason)

    def test_a_move_to_a_destination_that_already_had_it_is_rejected(self):
        """A pure removal dressed as a move.

        Two nodes constrain the same Policy. Dropping it from one and naming the
        other as `to` satisfies "the destination references it in the same field"
        without anything being transferred — measured to take retry from 2 to 1
        before this check existed.
        """
        doc = json.loads(json.dumps(TWO_ACCESS))
        step2 = next(n for n in doc["nodes"] if n["id"] == "wf.w.step.2")
        step2["constraints"] = ["policy.p"]
        server = Server(doc, KnowledgeBase())
        server.proposals["p1"] = {
            "id": "p1", "role": self.ROLE, "state": "pending",
            "nodes": [{"kind": "WorkflowStep", "id": "wf.w.step.1",
                       "name": "load and audit",
                       "children": ["wf.w.step.1.a", "wf.w.step.1.b"],
                       "constraints": []}],
            "intent": {"move": [{"node": "policy.p", "from": "wf.w.step.1",
                                 "to": "wf.w.step.2"}]},
            "review_task_id": "t1"}
        ok, reason = Reviewer(server)._assess("p1")
        self.assertFalse(ok)
        self.assertIn("already referenced", reason)

    def test_a_reference_migrated_between_fields_is_rejected_without_any_intent(self):
        """The drop gate is per field, not across their union.

        `node_references` unions `children` with the named fields, so moving a
        Policy out of `constraints` into `children` looks like no change at all —
        and the interpreter reads `constraints` for retry, timeout and rollback.
        This needs no `intent` and no out-of-rights node: the role owns the step.
        """
        server = Server(json.loads(json.dumps(TWO_ACCESS)), KnowledgeBase())
        server.proposals["p1"] = {
            "id": "p1", "role": self.ROLE, "state": "pending",
            "nodes": [{"kind": "WorkflowStep", "id": "wf.w.step.1",
                       "name": "load and audit",
                       "children": ["wf.w.step.1.a", "wf.w.step.1.b", "policy.p"],
                       "constraints": []}],
            "intent": {}, "review_task_id": "t1"}
        ok, reason = Reviewer(server)._assess("p1")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("removal:"), reason)
        self.assertIn("constraints", reason)

    def test_an_attachment_may_only_be_written_into_children(self):
        """Otherwise "attach what you authored" becomes "write an id anywhere"."""
        nodes = self._split()
        nodes[0]["constraints"] = ["wf.w.split.1"]
        ok, reason = self._assess(nodes, self._intent())
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("rights:"), reason)

    def test_a_move_into_a_different_field_is_rejected(self):
        """The laundered-removal attack: a Constraint 'moved' into `children`."""
        original = {"kind": "WorkflowStep", "id": "wf.w.step.1",
                    "name": "load and audit",
                    "children": ["wf.w.step.1.a", "wf.w.step.1.b"],
                    "constraints": []}
        new = {"kind": "WorkflowStep", "id": "wf.w.split.1", "name": "hold policy",
               "children": ["policy.p"], "meta": dict(NEW_META)}
        parent = {"kind": "Workflow", "id": "wf.w", "name": "W",
                  "children": ["wf.w.step.1", "wf.w.split.1", "wf.w.step.2"],
                  "meta": dict(EDIT_META)}
        ok, reason = self._assess(
            [parent, original, new],
            {"attach": [{"parent": "wf.w", "child": "wf.w.split.1"}],
             "move": [{"node": "policy.p", "from": "wf.w.step.1",
                       "to": "wf.w.split.1"}]})
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("move:"), reason)

    def test_attaching_a_node_it_did_not_author_is_rejected(self):
        ok, reason = self._assess(
            self._split(), {"attach": [{"parent": "wf.w",
                                        "child": "wf.w.step.2"}]})
        self.assertFalse(ok)
        # The specific reason, not just the `attach:` prefix — dropping the
        # containment check makes the V5 pairing gate reject this too, and its
        # message carries the same prefix, so a prefix-only assertion cannot tell
        # the two apart and the containment branch would go untested.
        self.assertIn("was not authored by this proposal", reason)

    def test_attaching_a_child_the_parent_may_not_own_is_rejected(self):
        entity = {"kind": "Entity", "id": "entity.user", "name": "User",
                  "fields": [{"name": "id", "type": "UUID"}],
                  "children": ["wf.w.split.1"], "meta": dict(EDIT_META)}
        new = {"kind": "WorkflowStep", "id": "wf.w.split.1", "name": "update user",
               "meta": dict(NEW_META)}
        ok, reason = self._assess(
            [entity, new], {"attach": [{"parent": "entity.user",
                                        "child": "wf.w.split.1"}]})
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("attach:"), reason)
        self.assertIn("Entity", reason)

    def test_a_non_reference_change_on_an_out_of_rights_node_is_rejected(self):
        nodes = self._split()
        nodes[0]["name"] = "renamed"
        ok, reason = self._assess(nodes, self._intent())
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("rights:"), reason)

    def test_an_out_of_rights_edit_without_an_agent_origin_is_rejected(self):
        nodes = self._split()
        nodes[0].pop("meta")
        ok, reason = self._assess(nodes, self._intent())
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("rights:"), reason)

    def test_a_declared_move_the_fragment_does_not_perform_is_rejected(self):
        """The intent says one thing and the nodes do another.

        Both steps keep the child, so nothing was given up. RFC-0010 makes a
        mismatch between the declaration and the fragment an error, and naming it
        `move:` diagnoses it better than letting the contested ownership surface.
        """
        nodes = self._split()
        nodes[1]["children"] = ["wf.w.step.1.a", "wf.w.step.1.b"]
        ok, reason = self._assess(nodes, self._intent())
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("move:"), reason)

    def test_a_correct_move_to_an_unattached_step_is_caught_by_the_invariant_gate(self):
        """Not by the new branches — by `_structure_fault`.

        The move is honest: step.1 gives up the access and the new step takes it in
        the same field, newly. But nothing attaches the new step, so it is an orphan
        — and the reason must say `orphan:`, which is what shows the invariant check
        still does the structural work these branches lean on.
        """
        ok, reason = self._assess(self._split()[1:], self._intent())
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("orphan:"), reason)


class TestRefactoringAgent(unittest.TestCase):
    """The ninth role. One prescription, and a refusal for everything else."""

    def _server(self, doc=None):
        return Server(json.loads(json.dumps(doc or TWO_ACCESS)), KnowledgeBase())

    def _run(self, server, key="k1"):
        agent = RefactoringAgent(server)
        task = server.call("agent.dispatch", role="RefactoringAgent",
                           objective="split", deadline_ms=5000,
                           idempotency_key=key)
        return agent.propose(task)

    def _apply(self, server, out):
        Reviewer(server).decide(out["review_task_id"], out["proposal_id"])
        return {n["id"]: n for n in server.doc["nodes"]}

    def _accesses(self, nodes, step_id):
        return [c for c in nodes[step_id].get("children", [])
                if nodes.get(c, {}).get("kind") == "RepositoryCall"]

    def test_it_splits_a_step_with_two_repository_accesses(self):
        server = self._server()
        nodes = self._apply(server, self._run(server))
        self.assertEqual(len(self._accesses(nodes, "wf.w.step.1")), 1)
        self.assertEqual(len(self._accesses(nodes, "wf.w.split.1")), 1)

    def test_the_new_step_runs_immediately_after_the_original(self):
        """`children` order is execution order, so the tail is a different program."""
        server = self._server()
        nodes = self._apply(server, self._run(server))
        self.assertEqual(nodes["wf.w"]["children"],
                         ["wf.w.step.1", "wf.w.split.1", "wf.w.step.2"])

    def test_the_original_step_keeps_its_id_and_its_first_access(self):
        server = self._server()
        nodes = self._apply(server, self._run(server))
        self.assertIn("wf.w.step.1.a", nodes["wf.w.step.1"]["children"])

    def test_the_new_step_is_grounded_in_the_kb(self):
        server = self._server()
        nodes = self._apply(server, self._run(server))
        self.assertEqual(nodes["wf.w.split.1"]["meta"]["source"],
                         "kb:patterns-repository-call@0.1.0")

    def test_the_new_step_name_is_a_verb_phrase_from_the_operation(self):
        server = self._server()
        nodes = self._apply(server, self._run(server))
        self.assertEqual(nodes["wf.w.split.1"]["name"], "update user")

    def test_a_query_operation_is_named_with_the_dictionarys_verb(self):
        """`query` is not in `patterns-repository-call`'s verb dictionary.

        The dictionary maps authenticate/load/find/read → read, plus create/insert,
        update, delete. A step named `query user` would not round-trip through it,
        so the name uses `find`, the entry that means the same operation.
        """
        doc = json.loads(json.dumps(TWO_ACCESS))
        call = next(n for n in doc["nodes"] if n["id"] == "wf.w.step.1.b")
        call["operation"] = "query"
        server = self._server(doc)
        nodes = self._apply(server, self._run(server))
        self.assertEqual(nodes["wf.w.split.1"]["name"], "find user")

    def test_it_refuses_when_no_step_owns_two_accesses(self):
        server = Server(golden(), KnowledgeBase())
        out = self._run(server)
        self.assertIsNone(out["proposal_id"])
        self.assertEqual(server.proposals, {})

    def test_a_step_with_one_access_is_not_a_violation(self):
        doc = json.loads(json.dumps(TWO_ACCESS))
        step = next(n for n in doc["nodes"] if n["id"] == "wf.w.step.1")
        step["children"] = ["wf.w.step.1.a"]
        doc["nodes"] = [n for n in doc["nodes"] if n["id"] != "wf.w.step.1.b"]
        server = self._server(doc)
        self.assertIsNone(self._run(server)["proposal_id"])

    def test_three_accesses_split_into_three_steps(self):
        doc = json.loads(json.dumps(TWO_ACCESS))
        step = next(n for n in doc["nodes"] if n["id"] == "wf.w.step.1")
        step["children"].append("wf.w.step.1.c")
        doc["nodes"].append({"kind": "RepositoryCall", "id": "wf.w.step.1.c",
                             "entity": "entity.user", "operation": "delete"})
        server = self._server(doc)
        nodes = self._apply(server, self._run(server))
        for step_id in ("wf.w.step.1", "wf.w.split.1", "wf.w.split.2"):
            self.assertEqual(len(self._accesses(nodes, step_id)), 1, step_id)
        self.assertEqual(nodes["wf.w.split.2"]["name"], "delete user")

    def test_it_refuses_a_step_owned_by_a_concurrency_node(self):
        """Splitting there would make the new step a parallel branch.

        Mode A is single-threaded, so no differential test would reveal it — the
        refusal is the only thing standing between this transform and a silent
        concurrency change.
        """
        doc = json.loads(json.dumps(TWO_ACCESS))
        doc["nodes"].append({"kind": "Concurrency", "id": "wf.w.conc",
                             "mode": "parallel", "children": ["wf.w.step.1"]})
        wf = next(n for n in doc["nodes"] if n["id"] == "wf.w")
        wf["children"] = ["wf.w.conc", "wf.w.step.2"]
        server = self._server(doc)
        self.assertIsNone(self._run(server)["proposal_id"])

    def test_it_refuses_a_step_owned_by_a_guard(self):
        """RFC-0001 allows a Guard exactly one guarded item."""
        doc = json.loads(json.dumps(TWO_ACCESS))
        doc["nodes"].append({"kind": "Guard", "id": "wf.w.guard",
                             "mode": "repeat", "count": 3,
                             "children": ["wf.w.step.1"]})
        wf = next(n for n in doc["nodes"] if n["id"] == "wf.w")
        wf["children"] = ["wf.w.guard", "wf.w.step.2"]
        server = self._server(doc)
        self.assertIsNone(self._run(server)["proposal_id"])

    def test_a_nested_access_is_not_counted(self):
        """Under-detection, stated in the docstring rather than answered wrongly."""
        doc = json.loads(json.dumps(TWO_ACCESS))
        step = next(n for n in doc["nodes"] if n["id"] == "wf.w.step.1")
        step["children"] = ["wf.w.step.1.a", "wf.w.step.1.tx"]
        doc["nodes"].append({"kind": "Transaction", "id": "wf.w.step.1.tx",
                             "children": ["wf.w.step.1.b"]})
        server = self._server(doc)
        self.assertIsNone(self._run(server)["proposal_id"])

    def test_it_declines_instead_of_crashing_on_an_underivable_name(self):
        """Refuse, and refuse *cleanly*.

        A whitespace-only entity name used to reach `.split()[0]` and come out as an
        IndexError rather than a declined task — a crash where the docstring
        promises a refusal.
        """
        for name in ("   ", 123, None):
            doc = json.loads(json.dumps(TWO_ACCESS))
            entity = next(n for n in doc["nodes"] if n["id"] == "entity.user")
            entity["name"] = name
            server = self._server(doc)
            self.assertIsNone(self._run(server)["proposal_id"], repr(name))

    def test_it_declines_when_a_repository_call_has_no_operation(self):
        doc = json.loads(json.dumps(TWO_ACCESS))
        call = next(n for n in doc["nodes"] if n["id"] == "wf.w.step.1.b")
        del call["operation"]
        server = self._server(doc)
        self.assertIsNone(self._run(server)["proposal_id"])

    def test_it_pins_the_kb_document_through_the_protocol(self):
        """Architect and Coder route/load/verify; reading server.kb skips the pin."""
        server = self._server()
        self._run(server)
        used = {m for m, _p in server.log}
        self.assertIn("kb.load", used)
        self.assertIn("kb.verify", used)

    def test_all_nine_roles_now_have_an_implementation(self):
        """What makes "8 of 9" impossible to regress to."""
        import inspect

        from lnpl import agents, protocol
        implemented = {name for name, obj in inspect.getmembers(agents, inspect.isclass)
                       if obj.__module__ == "lnpl.agents" and not name.startswith("_")}
        self.assertEqual(set(protocol.ROLES), implemented)


if __name__ == "__main__":
    unittest.main()
