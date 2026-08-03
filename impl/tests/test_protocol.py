"""Agent protocol — RFC-0006: methods, errors, idempotency, task lifecycle."""

import json
import os
import unittest

from lnpl.kb import KnowledgeBase
from lnpl.protocol import ERRORS, RpcError, Server, reference_only_edit

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_golden():
    with open(os.path.join(REPO, "examples", "login.lir.json"), encoding="utf-8") as fh:
        return json.load(fh)


def server():
    return Server(load_golden(), KnowledgeBase())


AUTHZ = {"kind": "Authorization", "id": "wf.login.step.4.authz",
         "requirement": "verified jwt"}

# A structurally-valid way to add AUTHZ: the step that performs it must own it.
# An Authorization is an effect, not an entry kind, so a merged document that adds
# it without an owner leaves it orphaned — which `ir.apply` now refuses on every
# path, including the approval override (issue #15). Pairing the effect with its
# owning step keeps the merged document valid.
STEP4_OWNS_AUTHZ = {"kind": "WorkflowStep", "id": "wf.login.step.4",
                    "name": "generate token",
                    "children": ["wf.login.step.4.authz"]}


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
                           kb_pins=[], deadline_ms=1000, idempotency_key="p-%s" % role)

    def test_propose_does_not_mutate_the_document(self):
        out = self._propose()
        self.assertEqual(out["state"], "pending")
        self.assertEqual(len(self.s.doc["nodes"]), self.before)

    def test_approval_applies_the_nodes(self):
        # A valid proposal: the new Authorization effect is owned by its step, so
        # the merged document satisfies the structure rules `ir.apply` enforces.
        out = self._propose([STEP4_OWNS_AUTHZ, AUTHZ])
        task = self.s.call("agent.report", task_id=out["review_task_id"],
                           payload={"proposal_id": out["proposal_id"],
                                    "decision": "approved"})
        self.assertEqual(task["state"], "completed")
        # step.4 is replaced in place; only the authz node is new.
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
        # A VALID fragment, so the only thing that can refuse the approval is the
        # role gate — not the merged-document structure check. With an invalid
        # (orphan) fragment the structure check would raise regardless of the role,
        # masking a regression in the approve-rights gate.
        out = self._propose([STEP4_OWNS_AUTHZ, AUTHZ])
        # Re-purpose the review task to a non-approving role.
        self.s.tasks[out["review_task_id"]].role = "Coder"
        with self.assertRaises(RpcError) as ctx:
            self.s.call("agent.report", task_id=out["review_task_id"],
                        payload={"proposal_id": out["proposal_id"],
                                 "decision": "approved"})
        self.assertEqual(ctx.exception.type, "proposal_rejected")
        self.assertIn("may not approve", str(ctx.exception))
        self.assertEqual(len(self.s.doc["nodes"]), self.before)

    def test_a_role_may_not_propose_a_kind_outside_its_rights(self):
        with self.assertRaises(RpcError) as ctx:
            self.s.call("ir.propose", role="Planner", ir_fragment=fragment(),
                        kb_pins=[], deadline_ms=1000, idempotency_key="pp")
        self.assertIn("may not propose", str(ctx.exception))

    def test_module_mismatch_is_rejected(self):
        with self.assertRaises(RpcError) as ctx:
            self.s.call("ir.propose", role="Coder",
                        ir_fragment={"module": "other", "nodes": [AUTHZ]},
                        kb_pins=[], deadline_ms=1000, idempotency_key="pm")
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

    def test_override_refuses_an_orphaned_effect(self):
        """The approval override runs the same document invariants the Reviewer
        does (issue #15). An Authorization effect with no owning step passes
        propose-time (the fragment is internally consistent) but is orphaned once
        merged — `ir.apply` must refuse it, not apply it."""
        out = self._propose([AUTHZ])
        with self.assertRaises(RpcError) as ctx:
            self.s.call("agent.report", task_id=out["review_task_id"],
                        payload={"proposal_id": out["proposal_id"],
                                 "decision": "approved"})
        self.assertEqual(ctx.exception.type, "ir_invalid")
        self.assertIn("orphan", str(ctx.exception))
        self.assertEqual(len(self.s.doc["nodes"]), self.before)

    def test_override_refuses_a_v5_children_violation(self):
        """RFC-0004 V5 on the override path: an Entity may not own a WorkflowStep.
        Regular `children` edits are not V5-checked at propose time (that gate is
        for the attach intent only), so without the check in `_apply` this merged
        clean and the review gate approved it — exactly the hole #15 names."""
        bad = [{"kind": "Entity", "id": "e.z", "name": "Z",
                "children": ["e.z.step"]},
               {"kind": "WorkflowStep", "id": "e.z.step", "name": "s"}]
        out = self._propose(bad, role="Architect")
        with self.assertRaises(RpcError) as ctx:
            self.s.call("agent.report", task_id=out["review_task_id"],
                        payload={"proposal_id": out["proposal_id"],
                                 "decision": "approved"})
        self.assertEqual(ctx.exception.type, "ir_invalid")
        self.assertIn("v5_children", str(ctx.exception))
        self.assertEqual(len(self.s.doc["nodes"]), self.before)

    def test_override_refuses_a_guard_with_wrong_cardinality(self):
        """RFC-0001 Guard row: a Guard owns exactly one guarded item ("피가드 항목
        1개"). CHILDREN_ALLOWED cannot express that count, so nothing but the
        `_structure_fault` cardinality check catches a Guard with two children —
        and it must run on the override path too (issue #15)."""
        bad = [{"kind": "Workflow", "id": "wf.gc", "name": "gc",
                "children": ["wf.gc.g"]},
               {"kind": "Guard", "id": "wf.gc.g", "mode": "when",
                "condition": "x missing", "children": ["wf.gc.s1", "wf.gc.s2"]},
               {"kind": "WorkflowStep", "id": "wf.gc.s1", "name": "s1"},
               {"kind": "WorkflowStep", "id": "wf.gc.s2", "name": "s2"}]
        out = self._propose(bad, role="Architect")
        with self.assertRaises(RpcError) as ctx:
            self.s.call("agent.report", task_id=out["review_task_id"],
                        payload={"proposal_id": out["proposal_id"],
                                 "decision": "approved"})
        self.assertEqual(ctx.exception.type, "ir_invalid")
        self.assertIn("guard_cardinality", str(ctx.exception))
        self.assertEqual(len(self.s.doc["nodes"]), self.before)

    def test_double_decision_on_one_proposal_is_refused(self):
        out = self._propose([STEP4_OWNS_AUTHZ, AUTHZ])
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


TWO_ACCESS = {
    "lir_version": "0.1", "module": "t",
    "nodes": [
        {"kind": "Entity", "id": "entity.user", "name": "User",
         "fields": [{"name": "id", "type": "UUID"}]},
        {"kind": "Policy", "id": "policy.p", "rules": [{"name": "retry", "value": "2"}]},
        {"kind": "Service", "id": "svc.s", "name": "S", "children": ["wf.w"],
         "constraints": ["policy.p"]},
        {"kind": "Workflow", "id": "wf.w", "name": "W",
         "children": ["wf.w.step.1", "wf.w.step.2"]},
        {"kind": "WorkflowStep", "id": "wf.w.step.1", "name": "load and audit",
         "children": ["wf.w.step.1.a", "wf.w.step.1.b"]},
        {"kind": "RepositoryCall", "id": "wf.w.step.1.a",
         "entity": "entity.user", "operation": "read"},
        {"kind": "RepositoryCall", "id": "wf.w.step.1.b",
         "entity": "entity.user", "operation": "update"},
        {"kind": "WorkflowStep", "id": "wf.w.step.2", "name": "return user"},
    ],
}

PROV = {"origin": "agent:RefactoringAgent",
        "source": "kb:patterns-repository-call@0.1.0"}

# An *existing* node edited for attachment carries `origin` only. `source` is
# provenance for a node being authored; adding it to a node that already has its own
# would be rewriting provenance, which condition (c) refuses on purpose.
EDIT_META = {"origin": "agent:RefactoringAgent"}


class TestProposalIntent(unittest.TestCase):
    """RFC-0010: a role may attach what it authored, and nothing more.

    The attachment exception exists so a role can put a node it wrote where the
    document will see it. Its whole content is "write a reference into a node whose
    kind you do not own", so most of these tests are the refusals — an exception
    that cannot refuse is not an exception, it is a hole.
    """

    def setUp(self):
        self.server = Server(json.loads(json.dumps(TWO_ACCESS)), KnowledgeBase())

    def _split_nodes(self, workflow_children=None, step_2_extra=None):
        """The honest split: parent gains the new step, step.1 gives up `…b`."""
        parent = {"kind": "Workflow", "id": "wf.w", "name": "W",
                  "children": workflow_children
                  or ["wf.w.step.1", "wf.w.split.1", "wf.w.step.2"],
                  "meta": dict(EDIT_META)}
        original = {"kind": "WorkflowStep", "id": "wf.w.step.1",
                    "name": "load and audit", "children": ["wf.w.step.1.a"]}
        new = {"kind": "WorkflowStep", "id": "wf.w.split.1", "name": "update user",
               "children": ["wf.w.step.1.b"], "meta": dict(PROV)}
        if step_2_extra:
            parent.update(step_2_extra)
        return [parent, original, new]

    def _intent(self):
        return {"attach": [{"parent": "wf.w", "child": "wf.w.split.1"}],
                "move": [{"node": "wf.w.step.1.b", "from": "wf.w.step.1",
                          "to": "wf.w.split.1"}]}

    def _propose(self, nodes, intent=None, key="s1"):
        return self.server.call(
            "ir.propose", role="RefactoringAgent",
            ir_fragment={"lir_version": "0.1", "module": "t", "nodes": nodes},
            intent=intent, kb_pins=[], deadline_ms=1000, idempotency_key=key)

    def test_a_declared_attachment_is_accepted(self):
        out = self._propose(self._split_nodes(), self._intent())
        self.assertEqual(out["state"], "pending")

    def test_the_stored_proposal_carries_the_intent(self):
        out = self._propose(self._split_nodes(), self._intent())
        stored = self.server.proposals[out["proposal_id"]]["intent"]
        self.assertEqual(stored["attach"][0]["child"], "wf.w.split.1")

    def test_the_same_edit_without_an_attach_entry_is_refused(self):
        with self.assertRaises(RpcError) as ctx:
            self._propose(self._split_nodes(), {})
        self.assertIn("may not propose Workflow", str(ctx.exception))

    def test_changing_another_field_while_attaching_is_refused(self):
        """Condition (c). Without it the exception is a general escape hatch."""
        with self.assertRaises(RpcError) as ctx:
            self._propose(self._split_nodes(step_2_extra={"name": "renamed"}),
                          self._intent())
        self.assertIn("may not propose Workflow", str(ctx.exception))

    def test_reordering_children_while_attaching_is_refused(self):
        """Condition (d) per-field AND order-preserving.

        `children` order is execution order (RFC-0001 rule 3), so a permutation is a
        behaviour change. A set comparison approves this.
        """
        with self.assertRaises(RpcError) as ctx:
            self._propose(
                self._split_nodes(workflow_children=["wf.w.step.2", "wf.w.step.1",
                                                     "wf.w.split.1"]),
                self._intent())
        self.assertIn("may not propose Workflow", str(ctx.exception))

    def test_migrating_a_reference_between_fields_is_refused(self):
        """Condition (d) again, and the reason it is per-field.

        Moving `policy.p` out of `constraints` into `children` is set-identical, but
        the interpreter reads `constraints` for retry — so this silently drops a
        declared policy.
        """
        # A BusinessRule, because a Service may own one (RFC-0001) — otherwise the
        # V5 gate fires first and this test would not reach condition (d).
        service = {"kind": "Service", "id": "svc.s", "name": "S",
                   "children": ["wf.w", "policy.p", "svc.s.rule"],
                   "constraints": [], "meta": dict(EDIT_META)}
        new = {"kind": "BusinessRule", "id": "svc.s.rule", "name": "audited",
               "statement": "every access is audited", "meta": dict(PROV)}
        with self.assertRaises(RpcError) as ctx:
            self._propose([service, new],
                          {"attach": [{"parent": "svc.s", "child": "svc.s.rule"}]})
        self.assertIn("may not propose Service", str(ctx.exception))

    def test_attaching_a_node_it_did_not_author_is_refused(self):
        with self.assertRaises(RpcError) as ctx:
            self._propose(self._split_nodes(),
                          {"attach": [{"parent": "wf.w",
                                       "child": "wf.w.step.2"}]})
        self.assertIn("did not", str(ctx.exception))

    def test_attaching_a_child_the_parent_may_not_own_is_refused(self):
        """RFC-0004 §S2 invariant V5, which nothing else in the codebase checks."""
        entity = {"kind": "Entity", "id": "entity.user", "name": "User",
                  "fields": [{"name": "id", "type": "UUID"}],
                  "children": ["wf.w.split.1"], "meta": dict(EDIT_META)}
        new = {"kind": "WorkflowStep", "id": "wf.w.split.1", "name": "update user",
               "meta": dict(PROV)}
        with self.assertRaises(RpcError) as ctx:
            self._propose([entity, new],
                          {"attach": [{"parent": "entity.user",
                                       "child": "wf.w.split.1"}]})
        message = str(ctx.exception)
        self.assertIn("Entity", message)
        self.assertIn("WorkflowStep", message)

    def test_an_out_of_rights_edit_must_record_an_agent_origin(self):
        nodes = self._split_nodes()
        nodes[0].pop("meta")
        with self.assertRaises(RpcError) as ctx:
            self._propose(nodes, self._intent())
        self.assertIn("meta.origin", str(ctx.exception))

    def test_a_malformed_intent_names_intent_in_the_error(self):
        with self.assertRaises(RpcError) as ctx:
            self._propose(self._split_nodes(), {"attach": [{"parent": "wf.w"}]})
        self.assertIn("intent.attach", str(ctx.exception))

    def test_a_fragment_naming_an_id_twice_is_refused(self):
        """`_assess` merges last-wins while `_apply` appends every unseen id.

        So a duplicate would put two nodes with one id into the document and the
        reviewer would only ever have judged one of them. RFC-0001's id-uniqueness
        invariant is otherwise unenforced.
        """
        twin = {"kind": "WorkflowStep", "id": "wf.w.step.3", "name": "decoy",
                "meta": dict(PROV)}
        with self.assertRaises(RpcError) as ctx:
            self._propose([twin, dict(twin, name="real")])
        self.assertIn("more than once", str(ctx.exception))

    def test_without_intent_the_gate_behaves_exactly_as_before(self):
        """Backward compatibility: absent `intent` is the pre-RFC-0010 contract."""
        within_rights = [{"kind": "WorkflowStep", "id": "wf.w.step.3",
                          "name": "audit user", "meta": dict(PROV)}]
        self.assertEqual(self._propose(within_rights)["state"], "pending")
        with self.assertRaises(RpcError):
            self._propose([{"kind": "Workflow", "id": "wf.w", "name": "W",
                            "children": ["wf.w.step.1"]}], key="s2")


class TestReferenceOnlyEdit(unittest.TestCase):
    """RFC-0010: an out-of-rights edit is permitted ONLY to attach declared
    children, and only into `children` (or a Constraint's `constraints`). Writing
    the declared id into any other reference field is not a reference-only edit."""

    def test_a_declared_child_added_to_children_is_a_reference_only_edit(self):
        existing = {"kind": "Service", "id": "s", "children": ["a"]}
        proposed = {"kind": "Service", "id": "s", "children": ["a", "new"]}
        self.assertTrue(reference_only_edit(proposed, existing, {"new"}))

    def test_a_declared_child_written_into_a_non_children_field_is_refused(self):
        # The mutation "let an attachment be written into any reference field"
        # (allowed_new = declared_children in the else branch) makes this pass;
        # the rule is that only `children`/`constraints` may take the addition, so
        # a declared id appearing in `requires` must make the edit invalid.
        existing = {"kind": "Service", "id": "s", "children": ["a"]}
        proposed = {"kind": "Service", "id": "s", "children": ["a"],
                    "requires": ["new"]}
        self.assertFalse(reference_only_edit(proposed, existing, {"new"}))

    def test_an_edit_that_also_changes_a_non_reference_field_is_refused(self):
        existing = {"kind": "Service", "id": "s", "name": "S", "children": ["a"]}
        proposed = {"kind": "Service", "id": "s", "name": "RENAMED",
                    "children": ["a", "new"]}
        self.assertFalse(reference_only_edit(proposed, existing, {"new"}))


if __name__ == "__main__":
    unittest.main()
