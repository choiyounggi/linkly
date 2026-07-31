"""The RFC-0006 Examples cycle — ROADMAP Phase 3's completion criterion."""

import json
import os
import unittest

from lnpl.agents import (Architect, Coder, PerformanceAnalyzer, Planner,
                         ReleaseAgent, Reviewer, SecurityAuditor, Tester,
                         run_cycle)
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


if __name__ == "__main__":
    unittest.main()
