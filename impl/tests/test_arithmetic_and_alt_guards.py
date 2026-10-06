"""Issue #93 / RFC-0028 — `*`/`/` arithmetic and alternative (`or`) guards.

The two reproductions from the issue:

    $ lnpl compile p1_mult.lnpl
    compile error: line 8: invalid arithmetic operator '*': 'set product.price
    to product.price * 2' (RFC-0015 supports `+` and `-` only)
    $ lnpl compile p2_or.lnpl
    compile error: line 9: invalid condition: more than one comparator in
    'item.a > 0 or item.b > 0'

`TestRedRepro` asserts the final contract RFC-0028 defines, so it fails on the
code that shipped before this issue. The second repro's exact one-line form
(`item.a > 0 or item.b > 0` inside a single condition string) stays rejected
by design — RFC-0028 makes `or` a guard-line STRUCTURE (Rego's "same head,
separate rule"), not a `Condition`-grammar operator; `TestStaticRejections`
pins that the old rejection survives unchanged for that exact shape.
"""

import json
import os
import subprocess
import sys
import unittest

from lnpl.drivers import FakeNetworkDriver
from lnpl.interp import Interpreter, RunError, _condition_holds
from lnpl.lower import LowerError, lower
from lnpl.parser import ParseError, parse
from lnpl.repo_policy import default_rows, row_key

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from tests.fixtures import ALT_GUARD_APPROVE, PRICE_INVENTORY

PRODUCT_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
PAYMENT_ID = "9e3f1b7a-2b3c-4d5e-8f9a-0b1c2d3e4f5a"


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


def price_interp(stock, price):
    doc = compile_doc(PRICE_INVENTORY, "price")
    payload = {"id": PRODUCT_ID, "stock": stock, "price": price, "quantity": 0}
    rows = {"entity.product": {row_key("entity.product", payload):
                               {"id": PRODUCT_ID, "stock": stock, "price": price}},
            "entity.order": {row_key("entity.order", payload):
                             {"id": PRODUCT_ID, "quantity": 0, "total": 0}}}
    return Interpreter(doc, repo_rows=rows)


def approve_interp():
    doc = compile_doc(ALT_GUARD_APPROVE, "approve")
    return Interpreter(doc, repo_rows={})


class TestRedRepro(unittest.TestCase):
    """The issue's two blockers, each at RFC-0028's final contract."""

    def test_multiplication_compiles(self):
        doc = compile_doc(PRICE_INVENTORY, "price")
        assigns = [a for a in nodes_of(doc, "Assignment")
                  if a["target"] == "order.total"]
        self.assertEqual(len(assigns), 1)
        self.assertEqual(assigns[0]["expression"], "product.price * input.quantity")

    def test_multiplication_computes_the_stored_total(self):
        interp = price_interp(stock=5, price=100)
        result = interp.run_workflow(
            "wf.place.order",
            {"id": PRODUCT_ID, "stock": 5, "price": 100, "quantity": 2})
        self.assertEqual(result["status"], "completed")
        stock_row = interp.repo.rows["entity.product"][
            row_key("entity.product", {"id": PRODUCT_ID})]
        self.assertEqual(stock_row["stock"], 3)
        order_row = interp.repo.rows["entity.order"][
            row_key("entity.order", {"id": PRODUCT_ID})]
        self.assertEqual(order_row["total"], 200)

    def test_or_guard_compiles_as_a_structure_not_an_operator(self):
        doc = compile_doc(ALT_GUARD_APPROVE, "approve")
        guards = nodes_of(doc, "Guard")
        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0]["condition"], "input.channel == 1")
        self.assertEqual(guards[0]["alternatives"], ["input.amount <= 100"])

    def test_the_issues_exact_one_line_or_still_fails_unchanged(self):
        """The literal repro (`or` inside ONE condition string) is not the fix.

        RFC-0028 deliberately leaves the `Condition` grammar untouched — `or`
        only works as a separate guard line. This is the regression pin for
        that boundary: widening `Condition` itself would be the rejected
        alternative in RFC-0028 §Alternatives.
        """
        source = """capability postgres

entity Item
    field
        id UUID
        a Integer
        b Integer

service S
    policy
        timeout 5s

workflow W
    when item.a > 0 or item.b > 0
    create item
"""
        with self.assertRaises(ParseError) as ctx:
            compile_doc(source, "m")
        self.assertIn("more than one comparator", str(ctx.exception))


class TestStaticRejections(unittest.TestCase):
    """One case per new rejection RFC-0028 adds, plus the unchanged controls."""

    def compile_fails(self, source, *fragments, error=(LowerError, ParseError)):
        with self.assertRaises(error) as ctx:
            compile_doc(source, "m")
        message = str(ctx.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

    def workflow(self, body, extra_field="stock Integer"):
        return """capability postgres

entity Product
    field
        id UUID
        %s
        price Money

service S
    policy
        timeout 5s

workflow W
%s
""" % (extra_field, body)

    # ---- unchanged (regression) --------------------------------------------

    def test_nested_arithmetic_is_still_refused_with_the_rfc_citation(self):
        # Three operands (two operators) is the "nesting" RFC-0015 §1 refuses
        # — the message that names it is unchanged by this RFC.
        self.compile_fails(
            self.workflow("    when product.stock - input.a - input.b > 0\n"
                          "    create product"),
            "RFC-0015 does not nest arithmetic", error=ParseError)

    def test_parentheses_are_still_refused(self):
        # Parens were never a lexed token — `(product.stock` tokenizes as one
        # word — so this fails as a bad operand, not the "nesting" message
        # above. Both are unchanged by this RFC (test_condition.py's
        # `test_rejects_parentheses` pins the same shape at the parser
        # level); this is the end-to-end regression check.
        self.compile_fails(
            self.workflow("    when (product.stock - input.quantity) > 0\n"
                          "    create product"),
            error=ParseError)

    # ---- new: `or` scoped to `when` ----------------------------------------

    def test_or_after_until_is_refused(self):
        self.compile_fails(
            self.workflow("    read product\n"
                          "    until product.stock >= 10\n"
                          "    or product.stock >= 20\n"
                          "    set product.stock to product.stock + 1",
                          extra_field="stock Integer"),
            "alternative guards apply to", "when", error=ParseError)

    def test_or_after_repeat_is_refused(self):
        self.compile_fails(
            self.workflow("    read product\n"
                          "    repeat 3\n"
                          "    or product.stock >= 20\n"
                          "    set product.stock to product.stock + 1"),
            "alternative guards apply to", error=ParseError)

    def test_or_with_no_pending_guard_is_an_ordinary_unknown_verb(self):
        """`or` is not globally reserved — only special after a `when`.

        A bare `or ...` line with nothing pending must parse and lower
        exactly as it did before this RFC — an ordinary step whose verb is
        outside `VERB_LEXICON` (a diagnostic, not a raised error) — not a
        new guard-specific rejection that would imply `or` is reserved
        everywhere.
        """
        mod = lower(parse(self.workflow("    or product")), "m")
        codes = [d.code for d in mod.diagnostics.by_code("unknown-verb")]
        self.assertEqual(codes, ["unknown-verb"])

    def test_or_needs_a_condition(self):
        self.compile_fails(
            self.workflow("    read product\n"
                          "    when product.stock > 0\n"
                          "    or\n"
                          "    create product"),
            error=ParseError)

    # ---- new: division ------------------------------------------------------

    def test_division_by_the_literal_zero_is_refused_at_compile_time(self):
        self.compile_fails(
            self.workflow("    read product\n"
                          "    set product.stock to product.stock / 0"),
            "division", "0", error=LowerError)

    def test_division_by_a_referenced_zero_is_not_refused_at_compile_time(self):
        # Control: only a LITERAL 0 divisor is a static fault. A reference
        # that might be 0 at runtime is a §Reference-level Specification/2
        # RunError, decided at run time, not a compile-time refusal.
        doc = compile_doc(self.workflow(
            "    read product\n"
            "    set product.stock to product.stock / input.quantity",
            extra_field="stock Integer\n        quantity Integer"), "m")
        self.assertEqual(len(nodes_of(doc, "Assignment")), 1)


class TestModeAEvaluation(unittest.TestCase):
    """RFC-0028 evaluation: normal / error / boundary per operator."""

    def holds(self, condition, payload=None, bindings=None):
        return _condition_holds(condition, payload or {}, bindings or {})

    # ---- normal --------------------------------------------------------------

    def test_multiplication_is_evaluated_before_the_comparison(self):
        self.assertTrue(self.holds("input.price * input.quantity > 150",
                                   {"price": 100, "quantity": 2}))
        self.assertFalse(self.holds("input.price * input.quantity > 150",
                                    {"price": 100, "quantity": 1}))

    def test_division_is_evaluated_before_the_comparison(self):
        self.assertTrue(self.holds("input.total / input.quantity >= 40",
                                   {"total": 100, "quantity": 2}))
        self.assertFalse(self.holds("input.total / input.quantity >= 40",
                                    {"total": 100, "quantity": 3}))

    # ---- error -----------------------------------------------------------

    def test_division_by_a_runtime_zero_raises_run_error(self):
        with self.assertRaises(RunError) as ctx:
            self.holds("input.a / input.b > 0", {"a": 10, "b": 0})
        self.assertIn("division by zero", str(ctx.exception))

    def test_multiplication_past_the_64_bit_range_fails(self):
        with self.assertRaises(RunError) as ctx:
            self.holds("input.a * input.b > 0",
                       {"a": 2 ** 62, "b": 4})
        self.assertIn("64-bit range", str(ctx.exception))

    # ---- boundary --------------------------------------------------------

    def test_division_truncates_toward_zero(self):
        # C-style truncation, not Python floor division: -7 / 2 == -3 (not
        # -4). Compared against a payload field, not a negative literal —
        # RFC-0015 §1's literals stay unsigned; only a computed RESULT may be
        # negative. Both sign combinations are checked so a floor-division
        # regression cannot hide in only one of them.
        self.assertTrue(self.holds("input.a / input.b == input.expected",
                                   {"a": -7, "b": 2, "expected": -3}))
        self.assertTrue(self.holds("input.a / input.b == input.expected",
                                   {"a": 7, "b": -2, "expected": -3}))
        self.assertTrue(self.holds("input.a / input.b == input.expected",
                                   {"a": -7, "b": -2, "expected": 3}))

    def test_zero_divided_by_a_nonzero_value_is_zero(self):
        self.assertTrue(self.holds("input.a / input.b == 0",
                                   {"a": 0, "b": 5}))

    def test_multiplication_by_zero(self):
        self.assertTrue(self.holds("input.a * input.b == 0",
                                   {"a": 0, "b": 999}))


class TestTextTermsChainLikeAnyOtherTerm(unittest.TestCase):
    """RFC-0054: `!=` and `and` with a Text term, run end to end."""

    def _run(self, condition, status, total=10):
        interp = text_chain_interp(
            "    when %s\n    update order" % condition, status, total)
        result = interp.run_workflow("wf.cancel.order", {"id": ORDER_ID})
        self.assertEqual("completed", result["status"], result.get("failure_reason"))
        return interp, result

    def test_text_not_equal_compiles_and_runs(self):
        _interp, result = self._run("order.status != cancelled", "pending")
        self.assertEqual([], result["skipped"])
        self.assertEqual(["find order", "update order"],
                         [s["step"] for s in result["steps"]])

    def test_text_not_equal_skips_when_equal(self):
        _interp, result = self._run("order.status != cancelled", "cancelled")
        self.assertEqual(1, len(result["skipped"]))
        self.assertEqual([{"ref": "order.status", "value": "cancelled", "op": "!=",
                           "expected": "cancelled", "holds": False}],
                         result["skipped"][0]["evaluations"])

    def test_and_chain_with_a_text_term_and_a_numeric_term_compiles_and_runs(self):
        _interp, result = self._run("order.status == pending and order.total > 0",
                                    "pending")
        self.assertEqual([], result["skipped"])
        self.assertEqual(["find order", "update order"],
                         [s["step"] for s in result["steps"]])

    def test_and_chain_skips_on_the_text_side(self):
        _interp, result = self._run("order.status == pending and order.total > 0",
                                    "paid")
        self.assertEqual(
            [("order.status", False), ("order.total", True)],
            [(e["ref"], e["holds"]) for e in result["skipped"][0]["evaluations"]])

    def test_and_chain_skips_on_the_numeric_side(self):
        _interp, result = self._run("order.status == pending and order.total > 0",
                                    "pending", total=0)
        self.assertEqual(
            [("order.status", True), ("order.total", False)],
            [(e["ref"], e["holds"]) for e in result["skipped"][0]["evaluations"]])


class TestAlternativeGuardRuntimeWithATextTerm(unittest.TestCase):
    """RFC-0054 + RFC-0028: an `or` alternative may carry a Text term."""

    BODY = ("    when order.total > 1000000\n"
            "    or order.status == pending\n"
            "    update order")

    def test_the_text_alternative_fires_and_the_trace_names_it(self):
        interp = text_chain_interp(self.BODY, "pending", 10)
        result = interp.run_workflow("wf.cancel.order", {"id": ORDER_ID})
        self.assertEqual([], result["skipped"])
        matched = [log for log in interp.trace.to_dict()["logs"]
                   if log["message"] == "guard alternative matched"]
        self.assertEqual(["order.status == pending"],
                         [log["condition"] for log in matched])

    def test_both_the_primary_and_the_text_alternative_false_skip(self):
        interp = text_chain_interp(self.BODY, "cancelled", 10)
        result = interp.run_workflow("wf.cancel.order", {"id": ORDER_ID})
        self.assertEqual(
            [("order.total", False), ("order.status", False)],
            [(e["ref"], e["holds"]) for e in result["skipped"][0]["evaluations"]])

    def test_a_text_primary_with_a_numeric_alternative(self):
        # Mirror: the recorded operands follow the text index, so the Text
        # term in position 0 and the numeric one in position 1 each evaluate
        # with their own entry.
        body = ("    when order.status == paid\n"
                "    or order.total > 5\n"
                "    update order")
        interp = text_chain_interp(body, "pending", 10)
        result = interp.run_workflow("wf.cancel.order", {"id": ORDER_ID})
        self.assertEqual([], result["skipped"])
        interp = text_chain_interp(body, "pending", 1)
        result = interp.run_workflow("wf.cancel.order", {"id": ORDER_ID})
        self.assertEqual(
            [("order.status", False), ("order.total", False)],
            [(e["ref"], e["holds"]) for e in result["skipped"][0]["evaluations"]])


class TestAlternativeGuardRuntime(unittest.TestCase):
    """D7 boundary: each branch of the alt guard, `skipped[]` observed."""

    def _approve(self, channel, amount):
        interp = approve_interp()
        result = interp.run_workflow("wf.approve",
                                     {"id": PAYMENT_ID, "channel": channel,
                                      "amount": amount})
        return interp, result

    # ---- normal: the primary condition fires -------------------------------

    def test_primary_condition_true_runs_with_no_new_trace_signal(self):
        interp, result = self._approve(channel=1, amount=5000)
        self.assertEqual([s["step"] for s in result["steps"]], ["create payment"])
        self.assertEqual(result["skipped"], [])
        matched = [log for log in interp.trace.to_dict()["logs"]
                  if log["message"] == "guard alternative matched"]
        self.assertEqual(matched, [],
                         "the primary firing must look identical to a plain "
                         "`when` — no alternative-specific signal")

    # ---- normal: the alternative fires -------------------------------------

    def test_alternative_true_runs_and_the_trace_names_it(self):
        interp, result = self._approve(channel=2, amount=50)
        self.assertEqual([s["step"] for s in result["steps"]], ["create payment"])
        self.assertEqual(result["skipped"], [])
        matched = [log for log in interp.trace.to_dict()["logs"]
                  if log["message"] == "guard alternative matched"]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["condition"], "input.amount <= 100")

    def test_boundary_amount_exactly_at_the_alternative_threshold(self):
        _interp, result = self._approve(channel=2, amount=100)
        self.assertEqual([s["step"] for s in result["steps"]], ["create payment"])

    # ---- error/reject: every alternative is false --------------------------

    def test_all_false_skips_and_the_skip_record_covers_every_alternative(self):
        interp, result = self._approve(channel=2, amount=5000)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]], [])
        self.assertEqual(len(result["skipped"]), 1)
        record = result["skipped"][0]
        self.assertEqual(record["condition"],
                         "input.channel == 1 or input.amount <= 100")
        self.assertEqual(record["steps"], ["create payment"])
        refs = {(e["ref"], e["holds"]) for e in record["evaluations"]}
        self.assertEqual(refs, {("input.channel", False), ("input.amount", False)})


TEXT_CHAIN_SOURCE = """
capability postgres
refine OrderStatus of Text
    enum pending paid cancelled
entity Order
    field
        id UUID
        status OrderStatus
        total Integer
service OrderService
workflow CancelOrder
    find order
%s
"""

ORDER_ID = "00000000-0000-4000-8000-000000000207"


def text_chain_interp(body, status, total):
    doc = compile_doc(TEXT_CHAIN_SOURCE % body, "shop")
    return Interpreter(doc, repo_rows={"entity.order": {
        row_key("entity.order", {"id": ORDER_ID}): {
            "id": ORDER_ID, "status": status, "total": total}}})


class TestIrSchemaGate(unittest.TestCase):
    """The Guard.alternatives field against schemas/lir.schema.json."""

    def test_an_alt_guard_document_validates(self):
        import jsonschema
        with open(os.path.join(REPO_ROOT, "schemas", "lir.schema.json"),
                  encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.validate(compile_doc(ALT_GUARD_APPROVE, "approve"), schema)

    def _schema(self):
        with open(os.path.join(REPO_ROOT, "schemas", "lir.schema.json"),
                  encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_guard_with_text_equality_operands_validates_against_the_schema(self):
        import jsonschema
        doc = json.loads(json.dumps(compile_doc(TEXT_CHAIN_SOURCE % (
            "    when order.status == paid\n    update order"), "shop")))
        guards = [n for n in nodes_of(doc, "Guard") if "textEqualityOperands" in n]
        self.assertEqual([["order.status", "paid"]],
                         guards[0]["textEqualityOperands"])
        jsonschema.validate(doc, self._schema())

    def test_a_malformed_text_equality_operands_is_rejected_by_the_schema(self):
        import jsonschema
        doc = json.loads(json.dumps(compile_doc(TEXT_CHAIN_SOURCE % (
            "    when order.status == paid\n    update order"), "shop")))
        guard = [n for n in nodes_of(doc, "Guard") if "textEqualityOperands" in n][0]
        for bad in ([[1]], ["order.status"], "order.status"):
            guard["textEqualityOperands"] = bad
            with self.assertRaises(jsonschema.ValidationError, msg=repr(bad)):
                jsonschema.validate(doc, self._schema())

    def test_the_schema_self_test_passes_including_the_new_negatives(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "validate_ir.py"),
             "--self-test"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ALT_GUARD_FIXTURE", proc.stdout)
        for label in ("alternatives is not an array",
                      "alternatives item is not a string",
                      "alternatives on a repeat guard",
                      "undeclared property"):
            self.assertIn(label, proc.stdout,
                          "the gate no longer runs the %r negative" % label)


NUMERIC_ALT_SOURCE = """capability postgres

entity Payment
    field
        id UUID
        status Integer
        rate Integer

service PaymentService
    policy
        timeout 5s

workflow Convert
    when input.status != 200
    or input.rate is-not-numeric
    create payment
"""


class TestNumericPredicateInConditions(unittest.TestCase):
    """Issue #177 / RFC-0050: the predicate parses as an `or` alternative
    and evaluates in mode A — bare, or as an `and` term next to a
    `Comparison` (never an `AttributeError` from a path that assumed every
    `and` term is a `Comparison`)."""

    def test_an_or_alternative_with_the_predicate_parses_and_lowers(self):
        doc = compile_doc(NUMERIC_ALT_SOURCE, "convert")
        guards = nodes_of(doc, "Guard")
        self.assertEqual(guards[0]["alternatives"], ["input.rate is-not-numeric"])

    def test_a_bare_predicate_evaluates(self):
        self.assertTrue(_condition_holds("input.rate is-numeric", {"rate": 1350}, {}))
        self.assertFalse(_condition_holds("input.rate is-numeric", {"rate": "abc"}, {}))

    def test_a_predicate_inside_and_is_evaluated_with_the_comparison(self):
        cond = "input.status == 200 and input.rate is-numeric"
        self.assertTrue(_condition_holds(cond, {"status": 200, "rate": 1350}, {}))
        self.assertFalse(_condition_holds(cond, {"status": 200, "rate": "abc"}, {}))
        self.assertFalse(_condition_holds(cond, {"status": 500, "rate": 1350}, {}))

    def test_a_non_numeric_comparison_in_the_same_and_still_raises(self):
        # RFC-0028 §2's non-numeric RunError row is unchanged: the predicate
        # guards nothing it is not asked about.
        with self.assertRaises(RunError) as ctx:
            _condition_holds("input.rate is-numeric and input.rate >= 0",
                             {"rate": "abc"}, {})
        self.assertIn("Cannot compare non-numeric", str(ctx.exception))

    def test_an_absent_reference_is_not_numeric(self):
        self.assertTrue(_condition_holds("input.rate is-not-numeric", {}, {}))
        self.assertFalse(_condition_holds("input.rate is-numeric", {}, {}))


F5_SOURCE = """capability postgres

entity Quote
    field
        id UUID

service QuoteService
    policy
        timeout 5s

workflow Convert
    call Fx as fxResult
    when fxResult.status == 200 and fxResult.rate is-numeric
    create quote
    when fxResult.status != 200
    or fxResult.rate is-not-numeric
    note "fallback"
"""


def fx_run(status, body):
    """Run the F-5 program (issue #177, RFC-0050 §Examples) against a
    stubbed `Fx` response."""
    doc = compile_doc(F5_SOURCE, "fx")
    wf = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
    payload = {"id": PAYMENT_ID}
    interp = Interpreter(doc, repo_rows=default_rows(doc, wf, payload),
                         network=FakeNetworkDriver({"Fx": (status, body)}))
    return interp, interp.run_workflow(wf, payload)


class TestNumericPredicateRuntime(unittest.TestCase):
    """DoD 1: the F-5 program routes a non-numeric response to the fallback
    branch instead of dying on the comparison `RunError`."""

    def _matched_alternatives(self, interp):
        return [log for log in interp.trace.to_dict()["logs"]
                if log["message"] == "guard alternative matched"]

    # ---- normal: numeric rate -> live branch --------------------------------
    def test_numeric_rate_takes_the_live_branch(self):
        interp, result = fx_run(200, {"rate": 1350})
        self.assertEqual(result["status"], "completed")
        steps = [s["step"] for s in result["steps"]]
        self.assertIn("create quote", steps)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["condition"],
                         "fxResult.status != 200 or fxResult.rate is-not-numeric")
        self.assertEqual(self._matched_alternatives(interp), [],
                         "no alternative matched, so no RFC-0028 alt log")

    # ---- error input: non-numeric rate -> fallback, no RunError ------------
    def test_non_numeric_rate_takes_the_fallback_branch(self):
        interp, result = fx_run(200, {"rate": "abc"})
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("create quote", [s["step"] for s in result["steps"]])
        self.assertEqual(len(result["skipped"]), 1)
        skipped = result["skipped"][0]
        self.assertEqual(skipped["condition"],
                         "fxResult.status == 200 and fxResult.rate is-numeric")
        self.assertEqual(skipped["steps"], ["create quote"])
        self.assertIn({"ref": "fxResult.rate", "value": "abc", "op": "is-numeric",
                       "expected": None, "holds": False},
                      skipped["evaluations"])
        self.assertEqual(len(self._matched_alternatives(interp)), 1,
                         "the fallback ran through its `or` alternative")

    # ---- boundary: rate absent -> same as non-numeric ----------------------
    def test_absent_rate_takes_the_fallback_branch(self):
        interp, result = fx_run(200, {})
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("create quote", [s["step"] for s in result["steps"]])
        skipped = result["skipped"][0]
        self.assertIn({"ref": "fxResult.rate", "value": None, "op": "is-numeric",
                       "expected": None, "holds": False},
                      skipped["evaluations"])
        self.assertEqual(len(self._matched_alternatives(interp)), 1)

    def test_non_200_takes_the_fallback_through_the_primary_condition(self):
        interp, result = fx_run(500, {"rate": 1350})
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("create quote", [s["step"] for s in result["steps"]])
        self.assertEqual(self._matched_alternatives(interp), [],
                         "the primary `status != 200` matched, not the alternative")


if __name__ == "__main__":
    unittest.main()
