"""Declared but not enforced does not pass in silence (issue #38).

`security jwt`, `role admin`, `policy rollback` and `performance response` all
parse, all reach the IR, and all reads as a promise the platform keeps. None of
them is enforced: `_constraints()` collects `mechanisms` and no execution path
ever reads it, `rollback` has no Transaction boundary to compensate at, and the
response budget is measured and reported but never blocks a run.

That gap is issue #25 and the roadmap. Making it *visible* is this file's
subject, so what is pinned here is the reporting — including the negative half,
that a genuinely enforced declaration produces no diagnostic. Without that half
a "warn about everything" implementation would pass and the matrix would carry
no information.
"""

import json
import os
import unittest

from lnpl.diagnostics import ENFORCEMENT
from lnpl.interp import (Interpreter, RunError, refinement_index,
                         sample_payload)
from lnpl.lower import LowerError, lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN_LNPL = os.path.join(REPO, "examples", "login.lnpl")
GOLDEN_IR = os.path.join(REPO, "examples", "login.lir.json")

DECLARATION_CODES = ("declared-not-enforced", "declared-measured-only")

JWT_ONLY = """
entity User
    field
        id UUID
service LoginService
    security
        jwt
workflow Login
    validate input
"""

RESPONSE_BUDGET = """
entity User
    field
        id UUID
service LoginService
    performance
        response < 50ms
workflow Login
    validate input
"""

ONLY_ENFORCED = """
entity User
    field
        id UUID
service LoginService
    policy
        retry 3
        timeout 3s
    performance
        cache 5m
workflow Login
    validate input
"""

NO_SERVICE = """
entity User
    field
        id UUID
workflow Login
    validate input
"""

DECLARED_BUT_NO_WORKFLOW = """
entity User
    field
        id UUID
service LoginService
    policy
        rollback
    security
        jwt
"""

TWO_SERVICES_SAME_MECHANISM = """
entity User
    field
        id UUID
service LoginService
    security
        jwt
service BillingService
    security
        jwt
"""

UNKNOWN_MECHANISM = """
entity User
    field
        id UUID
service LoginService
    security
        oauth
"""

AUTHORIZE_STEP = """
entity User
    field
        id UUID
        email Email
workflow Login
    authorize admin
"""

TWO_AUTHORIZE_STEPS = """
entity User
    field
        id UUID
        email Email
workflow Login
    authorize admin
    authorize owner
"""

NO_AUTHORIZE_STEP = """
entity User
    field
        id UUID
        email Email
workflow Login
    validate input
"""


def compile_module(source, name="t"):
    return lower(parse(source), name)


def declaration_diagnostics(mod):
    """Only the #38 declaration diagnostics, in order."""
    return [d for d in mod.diagnostics.all() if d.code in DECLARATION_CODES]


def run(source, name="t"):
    """Compile and execute the module's single workflow; return the interpreter.

    Payload and repository seed come from the same helpers `lnpl run` uses, so
    these tests exercise the real execution path rather than a hand-built one
    that could pass while the CLI fails.
    """
    doc = compile_module(source, name).to_document()
    workflow = [n for n in doc["nodes"] if n["kind"] == "Workflow"][0]
    payload = sample_payload([n for n in doc["nodes"] if n["kind"] == "Entity"],
                             refinement_index(doc))
    interp = Interpreter(doc, repo_rows=default_rows(doc, workflow["id"], payload))
    result = interp.run_workflow(workflow["id"], payload)
    return interp, result


class TestUnenforcedDeclarationsAreReported(unittest.TestCase):
    def test_security_jwt_is_reported_as_not_enforced(self):
        diags = declaration_diagnostics(compile_module(JWT_ONLY))
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].code, "declared-not-enforced")
        self.assertEqual(diags[0].subject, "security jwt")
        self.assertEqual(diags[0].severity, "info")   # #52
        self.assertEqual(diags[0].where, "security.login")

    def test_response_budget_is_reported_as_measured_only(self):
        # A distinct code: "we watch it" is a different promise from "we ignore
        # it", and collapsing them would misreport one of the two.
        diags = declaration_diagnostics(compile_module(RESPONSE_BUDGET))
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].code, "declared-measured-only")
        self.assertEqual(diags[0].subject, "performance response")
        self.assertEqual(diags[0].where, "perf.login")

    def test_the_message_says_what_is_missing(self):
        diags = declaration_diagnostics(compile_module(JWT_ONLY))
        self.assertIn("unenforced", diags[0].message)

    def test_enforced_declarations_produce_no_diagnostic(self):
        # The negative half. `retry`, `timeout` and `cache` genuinely change
        # what execution does, so reporting them would be a false alarm — and a
        # "warn about every declaration" implementation fails right here.
        self.assertEqual(declaration_diagnostics(compile_module(ONLY_ENFORCED)), [])

    def test_rollback_is_reported_even_though_retry_beside_it_is_not(self):
        source = """
entity User
    field
        id UUID
service LoginService
    policy
        retry 3
        rollback
        timeout 3s
workflow Login
    validate input
"""
        diags = declaration_diagnostics(compile_module(source))
        self.assertEqual([d.subject for d in diags], ["policy rollback"])
        self.assertEqual(diags[0].where, "policy.login")


class TestGoldenScenario(unittest.TestCase):
    def setUp(self):
        with open(GOLDEN_LNPL, encoding="utf-8") as fh:
            self.mod = lower(parse(fh.read()), "login")

    def test_reports_exactly_the_three_unenforced_declarations(self):
        subjects = sorted(d.subject for d in declaration_diagnostics(self.mod))
        self.assertEqual(subjects,
                         ["performance response", "policy rollback", "security jwt"])

    def test_the_enforced_declarations_of_the_golden_are_not_reported(self):
        subjects = [d.subject for d in declaration_diagnostics(self.mod)]
        for enforced in ("performance cache", "policy retry", "policy timeout"):
            self.assertNotIn(enforced, subjects)

    def test_each_code_appears_where_expected(self):
        by_code = {d.subject: d.code for d in declaration_diagnostics(self.mod)}
        self.assertEqual(by_code["security jwt"], "declared-not-enforced")
        self.assertEqual(by_code["policy rollback"], "declared-not-enforced")
        self.assertEqual(by_code["performance response"], "declared-measured-only")

    def test_the_golden_ir_is_unchanged(self):
        # Reporting a declaration must not put anything about it into the
        # program's meaning. If this fails, `examples/login.lir.json` would need
        # regenerating and the change has escaped its blast radius.
        with open(GOLDEN_IR, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(self.mod.to_document(), committed)

    def test_the_constraint_nodes_still_carry_exactly_what_they_did(self):
        # Narrower than the golden comparison above, and aimed at this task's
        # own code path: the three blocks that now also emit diagnostics.
        nodes = {n["id"]: n for n in self.mod.to_document()["nodes"]}
        self.assertEqual(nodes["policy.login"]["rules"],
                         [{"name": "retry", "value": 3},
                          {"name": "rollback"},
                          {"name": "timeout", "value": "3s"}])
        self.assertEqual(nodes["security.login"]["mechanisms"], ["jwt"])
        self.assertEqual(nodes["perf.login"]["budgets"],
                         [{"metric": "response", "value": "<50ms"},
                          {"metric": "cache", "value": "5m"}])
        for node_id in ("policy.login", "security.login", "perf.login"):
            self.assertNotIn("diagnostics", nodes[node_id])


class TestErrorPathsAreStillErrors(unittest.TestCase):
    def test_an_unknown_security_mechanism_still_fails_to_lower(self):
        with self.assertRaises(LowerError) as cm:
            compile_module(UNKNOWN_MECHANISM)
        message = str(cm.exception)
        self.assertIn("oauth", message)
        # The allowed set is still offered to the author.
        self.assertIn("jwt", message)

    def test_role_still_requires_its_argument(self):
        source = """
entity User
    field
        id UUID
service LoginService
    security
        role
"""
        with self.assertRaises(LowerError) as cm:
            compile_module(source)
        self.assertIn("role", str(cm.exception))

    def test_jwt_still_rejects_an_argument(self):
        source = """
entity User
    field
        id UUID
service LoginService
    security
        jwt admin
"""
        with self.assertRaises(LowerError):
            compile_module(source)


class TestBoundaries(unittest.TestCase):
    def test_a_module_with_no_service_declares_nothing_to_report(self):
        self.assertEqual(declaration_diagnostics(compile_module(NO_SERVICE)), [])

    def test_declarations_are_reported_when_there_is_no_workflow_at_all(self):
        # An unenforced declaration is a static fact about the declaration; it
        # does not need a step to have run, or to exist.
        diags = declaration_diagnostics(compile_module(DECLARED_BUT_NO_WORKFLOW))
        self.assertEqual(sorted(d.subject for d in diags),
                         ["policy rollback", "security jwt"])

    def test_the_same_mechanism_in_two_services_is_reported_twice(self):
        diags = declaration_diagnostics(compile_module(TWO_SERVICES_SAME_MECHANISM))
        self.assertEqual(len(diags), 2)
        self.assertEqual([d.subject for d in diags],
                         ["security jwt", "security jwt"])
        self.assertEqual(sorted(d.where for d in diags),
                         ["security.billing", "security.login"])

    def test_role_carries_its_head_token_as_the_subject(self):
        # `role admin` and `role owner` are the same declaration for enforcement
        # purposes; the subject names the mechanism, not the argument.
        source = """
entity User
    field
        id UUID
service LoginService
    security
        role admin
"""
        diags = declaration_diagnostics(compile_module(source))
        self.assertEqual([d.subject for d in diags], ["security role"])


class TestAuthorizationIsRecordedNeverChecked(unittest.TestCase):
    """The runtime half of #38 (interp.py `_run_effect`)."""

    def test_an_executed_authorize_step_reports_that_nothing_was_verified(self):
        interp, result = run(AUTHORIZE_STEP)
        diags = interp.diagnostics.all()
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].code, "authorization-not-verified")
        self.assertEqual(diags[0].subject, "admin")
        self.assertEqual(diags[0].where, "wf.login.step.1.authz")
        self.assertEqual(diags[0].severity, "info")   # #52
        # And it did not block anything — which is exactly the problem.
        self.assertEqual(result["status"], "completed")

    def test_the_requirement_is_still_recorded_on_the_trace(self):
        # The diagnostic is added beside the existing behaviour, not instead of
        # it: the span attribute other tooling reads must survive.
        interp, _ = run(AUTHORIZE_STEP)
        spans = interp.trace.root.children
        self.assertEqual(spans[0].children[0].attrs["requirement"], "admin")

    def test_no_warn_or_error_log_is_added_to_the_trace(self):
        # Mode A/B equivalence covers log levels (docs/ROADMAP.md Phase 2) and
        # mode B cannot emit these, so the diagnostic must stay off the trace.
        interp, _ = run(AUTHORIZE_STEP)
        levels = [entry["level"] for entry in interp.trace.logs]
        self.assertEqual([lv for lv in levels if lv in ("WARN", "ERROR")], [])

    def test_two_authorize_steps_are_reported_separately(self):
        interp, _ = run(TWO_AUTHORIZE_STEPS)
        diags = interp.diagnostics.all()
        self.assertEqual(len(diags), 2)
        self.assertEqual([d.subject for d in diags], ["admin", "owner"])
        self.assertEqual([d.where for d in diags],
                         ["wf.login.step.1.authz", "wf.login.step.2.authz"])

    def test_a_workflow_without_authorize_reports_nothing(self):
        interp, result = run(NO_AUTHORIZE_STEP)
        self.assertEqual(len(interp.diagnostics), 0)
        self.assertEqual(result["status"], "completed")

    def test_nothing_is_reported_when_the_workflow_never_runs(self):
        doc = compile_module(AUTHORIZE_STEP).to_document()
        interp = Interpreter(doc)
        with self.assertRaises(RunError) as cm:
            interp.run_workflow("wf.no.such.workflow", {})
        self.assertIn("wf.no.such.workflow", str(cm.exception))
        self.assertEqual(len(interp.diagnostics), 0)

    def test_the_golden_scenario_has_no_authorize_step(self):
        with open(GOLDEN_LNPL, encoding="utf-8") as fh:
            doc = lower(parse(fh.read()), "login").to_document()
        payload = sample_payload([n for n in doc["nodes"] if n["kind"] == "Entity"],
                                 refinement_index(doc))
        interp = Interpreter(doc, repo_rows=default_rows(doc, "wf.login", payload))
        result = interp.run_workflow("wf.login", payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(interp.diagnostics), 0)


class TestMatrixIsTheSourceOfTheReport(unittest.TestCase):
    def test_every_reported_declaration_is_non_enforced_in_the_matrix(self):
        with open(GOLDEN_LNPL, encoding="utf-8") as fh:
            mod = lower(parse(fh.read()), "login")
        reported = declaration_diagnostics(mod)
        self.assertTrue(reported, "the golden must report something")
        for d in reported:
            clause, name = d.subject.split(" ", 1)
            self.assertNotEqual(ENFORCEMENT[(clause, name)][0], "enforced",
                                "reported an enforced declaration: %s" % d.subject)


if __name__ == "__main__":
    unittest.main()
