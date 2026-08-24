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

from lnpl.interp import Interpreter, RunError, _condition_holds
from lnpl.lower import LowerError, lower
from lnpl.parser import ParseError, parse
from lnpl.repo_policy import row_key

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


class TestIrSchemaGate(unittest.TestCase):
    """The Guard.alternatives field against schemas/lir.schema.json."""

    def test_an_alt_guard_document_validates(self):
        import jsonschema
        with open(os.path.join(REPO_ROOT, "schemas", "lir.schema.json"),
                  encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.validate(compile_doc(ALT_GUARD_APPROVE, "approve"), schema)

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


if __name__ == "__main__":
    unittest.main()
