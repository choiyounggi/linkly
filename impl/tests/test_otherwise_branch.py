"""RFC-0062: `otherwise` — a `when` guard's sibling item (issue #211 (4)).

`otherwise` on the line after a `when` guard's item owns exactly one item and
runs exactly when the guard and every `or` alternative are false. It is the
guard's sibling, not a nested block, so nesting depth stays at 2 (RFC-0002).

Covered here, through the real compiler and mode A interpreter:
- lowering: the Guard node gains a second child only when `otherwise` is
  written; every other guard keeps its one child;
- execution: the full truth table (guard true / false, alternative true / all
  false) with the `skipped[]` record for whichever branch did not run;
- compile-time scope: the two branches never run together, so a binding or a
  presence guarantee from one branch does not reach the other.
"""

import contextlib
import io
import unittest

from lnpl import cli
from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse

PAYMENT_ID = "00000000-0000-4000-8000-000000000062"

SETTLE = """capability postgres

entity Payment
    field
        id UUID
        channel Integer
        amount Integer

entity Hold
    field
        id UUID

entity Receipt
    field
        id UUID

service PaymentService
    policy
        timeout 5s

workflow Settle
%s
"""

PLAIN = ("    when input.channel == 1\n"
         "    create payment\n"
         "    otherwise\n"
         "    fail declined")

WITH_ALTERNATIVE = ("    when input.channel == 1\n"
                    "    or input.amount <= 100\n"
                    "    create payment\n"
                    "    otherwise\n"
                    "    fail declined")

NO_OTHERWISE = ("    when input.channel == 1\n"
                "    create payment")


def compile_doc(body):
    return lower(parse(SETTLE % body), "settle").to_document()


def guards(doc):
    return [n for n in doc["nodes"] if n["kind"] == "Guard"]


def run(body, channel, amount):
    interp = Interpreter(compile_doc(body), repo_rows={})
    return interp.run_workflow("wf.settle", {"id": PAYMENT_ID, "channel": channel,
                                             "amount": amount})


def ran(result):
    return [s["step"] for s in result["steps"]]


class TestOtherwiseLowering(unittest.TestCase):

    def test_otherwise_is_the_guards_second_child(self):
        doc = compile_doc(PLAIN)
        by_id = {n["id"]: n for n in doc["nodes"]}
        [guard] = guards(doc)
        self.assertEqual(len(guard["children"]), 2)
        self.assertEqual([by_id[c]["name"] for c in guard["children"]],
                         ["create payment", "fail declined"])
        self.assertEqual(by_id[guard["children"][1]]["kind"], "WorkflowStep")
        # the otherwise item is owned by the guard, not by the workflow
        [wf] = [n for n in doc["nodes"] if n["kind"] == "Workflow"]
        self.assertEqual(wf["children"], [guard["id"]])

    def test_a_guard_without_otherwise_keeps_one_child(self):
        [guard] = guards(compile_doc(NO_OTHERWISE))
        self.assertEqual(len(guard["children"]), 1)

    def test_otherwise_owning_a_pipeline_lowers_the_whole_block(self):
        doc = compile_doc("    when input.channel == 1\n"
                          "    create payment\n"
                          "    otherwise\n"
                          "    pipeline refuse\n"
                          "        read payment\n"
                          "        fail declined")
        by_id = {n["id"]: n for n in doc["nodes"]}
        [guard] = guards(doc)
        block = by_id[guard["children"][1]]
        self.assertEqual(block["kind"], "Pipeline")
        self.assertEqual([by_id[c]["name"] for c in block["children"]],
                         ["read payment", "fail declined"])


class TestOtherwiseExecution(unittest.TestCase):
    """The truth table, mode A."""

    def test_guard_true_runs_the_guarded_item_and_records_otherwise_skipped(self):
        result = run(PLAIN, channel=1, amount=5000)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(ran(result), ["create payment"])
        self.assertEqual(len(result["skipped"]), 1)
        record = result["skipped"][0]
        self.assertEqual(record["mode"], "otherwise")
        self.assertEqual(record["steps"], ["fail declined"])
        self.assertEqual(record["condition"], "input.channel == 1")
        self.assertIsNone(record["rounds"])

    def test_guard_false_runs_otherwise_and_records_the_guarded_item_skipped(self):
        result = run(PLAIN, channel=2, amount=5000)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_kind"], "rejected")
        self.assertEqual(result["failed_step"], "fail declined")
        self.assertNotIn("create payment", ran(result))
        self.assertEqual(len(result["skipped"]), 1)
        record = result["skipped"][0]
        self.assertEqual(record["mode"], "when")
        self.assertEqual(record["steps"], ["create payment"])
        self.assertEqual({(e["ref"], e["holds"]) for e in record["evaluations"]},
                         {("input.channel", False)})

    def test_alternative_true_skips_otherwise(self):
        result = run(WITH_ALTERNATIVE, channel=2, amount=100)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(ran(result), ["create payment"])
        self.assertEqual([(r["mode"], r["steps"]) for r in result["skipped"]],
                         [("otherwise", ["fail declined"])])
        self.assertEqual(result["skipped"][0]["condition"],
                         "input.channel == 1 or input.amount <= 100")

    def test_guard_and_every_alternative_false_runs_otherwise(self):
        result = run(WITH_ALTERNATIVE, channel=2, amount=101)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "fail declined")
        self.assertEqual([(r["mode"], r["steps"]) for r in result["skipped"]],
                         [("when", ["create payment"])])
        self.assertEqual({(e["ref"], e["holds"])
                          for e in result["skipped"][0]["evaluations"]},
                         {("input.channel", False), ("input.amount", False)})

    def test_no_otherwise_keeps_todays_skip_record(self):
        result = run(NO_OTHERWISE, channel=2, amount=5000)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(ran(result), [])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(set(result["skipped"][0]),
                         {"guard", "mode", "condition", "steps", "rounds",
                          "evaluations"})
        self.assertEqual(result["skipped"][0]["mode"], "when")
        self.assertEqual(result["skipped"][0]["steps"], ["create payment"])
        # guard true: nothing skipped at all
        self.assertEqual(run(NO_OTHERWISE, channel=1, amount=0)["skipped"], [])

    def test_a_step_after_the_otherwise_item_runs_on_both_paths(self):
        body = PLAIN.replace("    fail declined", "    create hold") \
            + "\n    create receipt"
        for channel, first in ((1, "create payment"), (2, "create hold")):
            with self.subTest(channel=channel):
                result = run(body, channel=channel, amount=0)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(ran(result), [first, "create receipt"])

    def test_otherwise_owning_a_pipeline_runs_every_step_or_none(self):
        body = ("    when input.channel == 1\n"
                "    create payment\n"
                "    otherwise\n"
                "    pipeline refuse\n"
                "        create hold\n"
                "        create receipt")
        self.assertEqual(ran(run(body, channel=2, amount=0)),
                         ["create hold", "create receipt"])
        result = run(body, channel=1, amount=0)
        self.assertEqual(ran(result), ["create payment"])
        self.assertEqual(result["skipped"][0]["steps"],
                         ["create hold", "create receipt"])


class TestOtherwiseReporting(unittest.TestCase):
    """An `otherwise` skip record carries the guard that HELD in `condition`;
    the human line and the diagnostic must not read it as the `otherwise`'s
    own condition."""

    def _run(self, channel):
        interp = Interpreter(compile_doc(WITH_ALTERNATIVE.replace(
            "    fail declined", "    create hold")), repo_rows={})
        result = interp.run_workflow("wf.settle", {"id": PAYMENT_ID,
                                                   "channel": channel,
                                                   "amount": 5000})
        return interp, result

    def test_the_diagnostic_says_the_guard_held(self):
        interp, _result = self._run(channel=1)
        [diag] = interp.diagnostics.by_code("guard-skipped-steps")
        self.assertIn("the `otherwise` of the `when` guard, which held, did not "
                      "run create hold", diag.message)
        self.assertEqual(diag.subject, "input.channel == 1 or input.amount <= 100")

    def test_the_human_line_says_the_guard_held(self):
        interp, result = self._run(channel=1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_human(result, interp)
        self.assertIn("skipped by `otherwise` (`when input.channel == 1 or "
                      "input.amount <= 100` held): create hold", out.getvalue())

    def test_a_skipped_guarded_item_keeps_todays_wording(self):
        interp, result = self._run(channel=2)
        [diag] = interp.diagnostics.by_code("guard-skipped-steps")
        self.assertIn("the `when` guard did not run create payment", diag.message)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_human(result, interp)
        self.assertIn("skipped by `when input.channel == 1 or input.amount <= "
                      "100`: create payment", out.getvalue())


class TestOtherwiseDryRun(unittest.TestCase):
    """`lnpl run --dry-run` previews the plan from the IR; an `otherwise` item
    it walked past would be a step the preview says does not exist."""

    def test_the_plan_names_the_otherwise_item_apart_from_the_guarded_one(self):
        plan = cli._dry_run_plan(compile_doc(PLAIN), "wf.settle")["plan"]
        self.assertEqual(len(plan), 1)
        guard = plan[0]
        self.assertEqual([c["name"] for c in guard["children"]], ["create payment"])
        self.assertEqual(guard["otherwise"]["name"], "fail declined")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_dry_run_human(
                cli._dry_run_plan(compile_doc(PLAIN), "wf.settle"))
        self.assertIn("  guard when input.channel == 1\n"
                      "    step create payment\n"
                      "  otherwise\n"
                      "    step fail declined\n", out.getvalue())

    def test_a_guard_without_otherwise_has_no_otherwise_key(self):
        plan = cli._dry_run_plan(compile_doc(NO_OTHERWISE), "wf.settle")["plan"]
        self.assertNotIn("otherwise", plan[0])


SCOPE_HEAD = """capability postgres

entity Product
    field
        id UUID
        stock Integer
        bonus Integer optional

entity Order
    field
        id UUID
        quantity Integer

service ShopService

workflow PlaceOrder
    find product
"""


def scope_module(*steps):
    return lower(parse(SCOPE_HEAD + "".join("    %s\n" % s for s in steps)), "shop")


class TestOtherwiseScopeIsolation(unittest.TestCase):
    """The two branches of one guard never run in the same execution."""

    ESCAPE = "guard-scoped-binding-escape"

    def test_a_binding_from_the_guarded_item_is_not_bound_in_otherwise(self):
        mod = scope_module("when product.stock >= input.quantity",
                           "create order as o",
                           "otherwise",
                           "respond o.id")
        found = mod.diagnostics.by_code(self.ESCAPE)
        self.assertEqual(len(found), 1)
        self.assertIn("o", found[0].message)

    def test_a_binding_read_inside_its_own_branch_is_still_fine(self):
        mod = scope_module("when product.stock >= input.quantity",
                           "pipeline place",
                           "    create order as o",
                           "    respond o.id",
                           "otherwise",
                           "read product")
        self.assertEqual(mod.diagnostics.by_code(self.ESCAPE), [])

    def test_otherwise_is_not_protected_by_the_exists_guard_it_follows(self):
        """`otherwise` runs exactly when `product.bonus exists` is false."""
        code = "optional-field-unguarded-arithmetic"
        guarded = scope_module("when product.bonus exists",
                               "set product.stock to product.bonus + 1",
                               "otherwise",
                               "read product")
        self.assertEqual(guarded.diagnostics.by_code(code), [])
        in_otherwise = scope_module("when product.bonus exists",
                                    "read product",
                                    "otherwise",
                                    "set product.stock to product.bonus + 1")
        found = in_otherwise.diagnostics.by_code(code)
        self.assertEqual([d.subject for d in found], ["product.bonus"])

    def test_a_fail_owned_by_otherwise_counts_as_guarded(self):
        mod = scope_module("when product.stock >= input.quantity",
                           "create order",
                           "otherwise",
                           "fail out-of-stock")
        steps = [n["name"] for n in mod.to_document()["nodes"]
                 if n["kind"] == "WorkflowStep"]
        self.assertIn("fail out-of-stock", steps)


if __name__ == "__main__":
    unittest.main()
