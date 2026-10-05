"""Issue #47 — value semantics: the four blockers, reproduced first.

Every test in `TestRedRepro` asserts the FINAL behaviour RFC-0015 defines, so on
the code that shipped before this issue they all fail. That failing run is the
evidence the tests guard the reported defects rather than the fix
(`.orchestration/verify/i47-value-semantics.md` keeps its output).

The four are the QA report's own reproductions:

  t1 F-1  `when product.stock >= input.quantity` was refused, so the quantity
          -aware stock check could not be written and S2 (stock 1, qty 2) ran to
          `completed` with the order created — overselling, in the language.
  t1 F-2  no arithmetic and no assignment, so the deduction `stock - quantity`
          had no syntax at all.
  t2 F-3  no `==` and no `and`, so a range (0 < amount <= limit) collapsed to one
          bound and full-vs-partial refund could not be distinguished.
  t2 F-1  a guard could only name a row the workflow had READ, so validating the
          workflow's own input needed the workflow to be rewritten around it.
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

# The sources live in `tests.fixtures` — `test_backend.py` runs the same three
# through the differential, and one home per source is that module's rule.
from tests.fixtures import (VALUE_INVENTORY as INVENTORY,
                            VALUE_PAYMENT as PAYMENT,
                            VALUE_REFUND as REFUND)

PRODUCT_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


def inventory_interp(stock):
    """`INVENTORY` with one Product row holding `stock`, Order table empty."""
    doc = compile_doc(INVENTORY, "inventory")
    payload = {"id": PRODUCT_ID, "stock": stock, "quantity": 0}
    rows = {"entity.product": {row_key("entity.product", payload):
                               {"id": PRODUCT_ID, "stock": stock}}}
    return Interpreter(doc, repo_rows=rows)


class TestRedRepro(unittest.TestCase):
    """The four blockers, each asserted at its final contract."""

    def test_guard_rhs_field_reference_compiles(self):
        """t1 F-1: the comparison's right side may name a field, not just a literal."""
        doc = compile_doc(INVENTORY, "inventory")
        guards = nodes_of(doc, "Guard")
        self.assertEqual(len(guards), 2,
                         "both `when` lines must survive lowering as their own Guard")
        for guard in guards:
            self.assertEqual(guard["condition"], "product.stock >= input.quantity")

    def test_guard_rhs_field_reference_rejects_overselling(self):
        """t1 F-1 / S2: stock 1, quantity 2 -> the order is NOT created.

        This is the whole point of the issue: the refusal has to happen inside
        the language, not in a reviewer's head.
        """
        interp = inventory_interp(stock=1)
        result = interp.run_workflow("wf.place.order",
                                     {"id": PRODUCT_ID, "stock": 1, "quantity": 2})
        self.assertEqual(result["status"], "completed")   # i44: status stays completed
        self.assertEqual([s["step"] for s in result["steps"]], ["read product"],
                         "create/set must be skipped when stock < quantity")
        self.assertEqual(len(result["skipped"]), 2,
                         "both guards record a skip (issue #44's contract)")

    def test_assignment_step_lowers(self):
        """t1 F-2: `set <ref> to <value>` becomes an Assignment effect node."""
        doc = compile_doc(INVENTORY, "inventory")
        assigns = nodes_of(doc, "Assignment")
        self.assertEqual(len(assigns), 1)
        self.assertEqual(assigns[0]["target"], "product.stock")
        self.assertEqual(assigns[0]["expression"], "product.stock - input.quantity")
        self.assertEqual(assigns[0]["entity"], "entity.product")

    def test_assignment_deducts_the_stored_row(self):
        """t1 F-2 / S1: stock 5, quantity 2 -> the stored row holds 3."""
        interp = inventory_interp(stock=5)
        result = interp.run_workflow("wf.place.order",
                                     {"id": PRODUCT_ID, "stock": 5, "quantity": 2})
        self.assertEqual(result["status"], "completed")
        row = interp.repo.rows["entity.product"][
            row_key("entity.product", {"id": PRODUCT_ID})]
        self.assertEqual(row["stock"], 3,
                         "the deduction must reach the stored row, not only the trace")

    def test_and_combines_a_range(self):
        """t2 F-3: `and` expresses 0 < amount <= limit in ONE guard."""
        doc = compile_doc(PAYMENT, "payment")
        guards = nodes_of(doc, "Guard")
        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0]["condition"],
                         "input.amount > 0 and input.amount <= 10000")

    def test_equality_compares_two_fields(self):
        """t2 F-3 / t4 F-7: `==` exists in the grammar and compares two references."""
        doc = compile_doc(REFUND, "refund")
        guards = nodes_of(doc, "Guard")
        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0]["condition"], "payment.amount == input.amount")

    def test_payload_namespace_guard_needs_no_read(self):
        """t2 F-1: `input.<field>` validates the workflow's input with no read."""
        doc = compile_doc(PAYMENT, "payment")
        reads = [n for n in nodes_of(doc, "RepositoryCall")
                 if n["operation"] in ("read", "query")]
        self.assertEqual(reads, [],
                         "the fixture must not read anything — that is the point")
        interp = Interpreter(compile_doc(PAYMENT, "payment"), repo_rows={})
        result = interp.run_workflow("wf.approve",
                                     {"id": PRODUCT_ID, "amount": 0})
        self.assertEqual([s["step"] for s in result["steps"]], [],
                         "amount 0 fails the lower bound, so nothing is created")


class TestStaticRejections(unittest.TestCase):
    """RFC-0015 §Static rejections — one case per row of the table, plus a control.

    Each asserts the exception type AND the part of the message an author needs
    (the token, the accepted set, or the fix): "it raises" would pass when the
    wrong rule fires for the wrong reason.
    """

    def compile_fails(self, source, *fragments):
        with self.assertRaises((LowerError, ParseError)) as ctx:
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

    def test_a_guard_may_not_compare_two_literals(self):
        self.compile_fails(self.workflow("    read product\n    when 1 < 2\n"
                                         "    create product"),
                           "compares two literals", "decides nothing")

    def test_a_non_integer_field_is_refused_at_compile_time(self):
        # t2 F-4: this used to compile clean and then raise a raw Python
        # TypeError out of the interpreter at run time.
        #
        # RFC-0016 narrowed the refusal rather than relaxing it: `DateTime` left
        # this branch (it has an evaluator now — epoch milliseconds). RFC-0051
        # did the same for `Money`: it is a dimension of its own now, so
        # `price > 0` is refused as a MISMATCH (Money against a plain number),
        # not as "no evaluator" — still at compile time, which is what this
        # test guards.
        self.compile_fails(self.workflow("    read product\n"
                                         "    when product.price > 0\n"
                                         "    create product"),
                           "compares", "(money)", "(scalar)", "RFC-0051")

    def test_an_input_field_no_entity_declares_is_refused(self):
        self.compile_fails(self.workflow("    when input.quantitee > 0\n"
                                         "    create product"),
                           "which no entity declares", "declared fields")

    def test_an_entity_named_input_is_refused(self):
        source = """capability postgres

entity Input
    field
        id UUID
        stock Integer

service S
    policy
        timeout 5s

workflow W
    read input
"""
        self.compile_fails(source, "Input", "input")

    def test_an_assignment_to_the_payload_is_refused(self):
        self.compile_fails(self.workflow("    read product\n"
                                         "    set input.stock to 1"),
                           "not state")

    def test_an_assignment_to_an_unread_entity_is_refused(self):
        self.compile_fails(self.workflow("    set product.stock to 1"),
                           "never reads it")

    def test_an_assignment_without_to_is_refused(self):
        self.compile_fails(self.workflow("    read product\n"
                                         "    set product.stock 1"),
                           "needs `to`")

    def test_a_guard_reading_an_assigned_field_compiles_and_mode_b_refuses_it(self):
        # Was `test_a_guard_reading_an_assigned_field_is_refused`, asserting
        # RFC-0015's compile error. RFC-0062 resolved RFC-0015 Open Question 1:
        # mode A now reads the current value, and the mode-equivalence rule
        # (mode B fixes condition fields at entry) moved to mode B, which
        # refuses the same program as a recorded exemption.
        from lnpl import backend
        doc = compile_doc(self.workflow("    read product\n"
                                        "    set product.stock to product.stock - 1\n"
                                        "    when product.stock > 0\n"
                                        "    create product"), "m")
        self.assertTrue(backend.workflow_uses_assigned_guard_field(doc, "wf.w"))
        with self.assertRaises(backend.BackendError) as ctx:
            backend.emit_mlir(doc, "wf.w")
        self.assertIn("which an earlier step assigns", str(ctx.exception))
        self.assertIn("RFC-0062", str(ctx.exception))

    def test_presence_inside_and_is_refused(self):
        self.compile_fails(self.workflow("    read product\n"
                                         "    when product.stock exists and "
                                         "product.stock > 0\n"
                                         "    create product"),
                           "cannot appear inside `and`")

    def test_chained_guards_are_refused_and_point_at_and(self):
        """The refusal survives RFC-0015, but its advice had to change.

        Two `when` lines in a row still lose the first guard silently (issue #45,
        t2 F-2), so the rejection stays. What it used to say -- "chaining guards
        (AND) is not supported" -- is now false: `and` joins conditions inside one
        guard. The message has to name the fix that exists.
        """
        message = self.compile_fails(
            self.workflow("    read product\n"
                          "    when product.stock > 0\n"
                          "    when product.stock <= 100\n"
                          "    create product"),
            "a guard owns exactly one step or block", "joined by `and`")
        self.assertNotIn("is not supported", message,
                         "the old wording told the author `and` was unavailable")
        # ...and the shape it now recommends really does compile.
        compile_doc(self.workflow("    read product\n"
                                  "    when product.stock > 0 and product.stock <= 100\n"
                                  "    create product"), "joined")

    # ---- control: the refusals are not over-broad -------------------------
    def test_the_same_shapes_compile_when_they_are_legal(self):
        doc = compile_doc(self.workflow(
            "    read product\n"
            "    when product.stock > 0 and product.stock <= 100\n"
            "    create product\n"
            "    set product.stock to product.stock - 1"), "control")
        self.assertEqual(len(nodes_of(doc, "Guard")), 1)
        self.assertEqual(len(nodes_of(doc, "Assignment")), 1)


class TestMoneyDimension(unittest.TestCase):
    """RFC-0051 — the Money dimension in `set` and guards (issue #172).

    Admitted: copy, Money ± Money, Money × Integer (either order, a literal
    included), Money-vs-Money comparison. Everything else Money is a compile
    refusal that names RFC-0051; Decimal stays refused by the catch-all.
    """

    FIELDS = ("stock Integer\n        cost Money\n        createdAt DateTime"
              "\n        rate Decimal")

    def source(self, body):
        return TestStaticRejections.workflow(None, body, self.FIELDS)

    def assignment(self, line):
        return self.source("    read product\n    create product\n    " + line)

    def guard(self, cond):
        return self.source("    read product\n    when %s\n    create product"
                           % cond)

    def compile_fails(self, source, *fragments):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source, "m")
        message = str(ctx.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

    # ---- admitted --------------------------------------------------------
    def test_admitted_money_assignments_lower_with_the_expression_verbatim(self):
        for expr in ("product.cost",                        # copy
                     "input.cost",                          # copy from input
                     "product.price + product.cost",
                     "product.price - product.cost",
                     "product.price * product.stock",
                     "product.stock * product.price",
                     "product.price * 3",
                     "3 * product.price"):
            with self.subTest(expr=expr):
                doc = compile_doc(self.assignment(
                    "set product.price to %s" % expr), "m")
                [node] = nodes_of(doc, "Assignment")
                self.assertEqual("product.price", node["target"])
                self.assertEqual(expr, node["expression"])

    def test_a_money_guard_compares_money_with_money_under_every_comparator(self):
        for op in ("==", "!=", "<", "<=", ">", ">="):
            with self.subTest(op=op):
                doc = compile_doc(self.guard(
                    "product.price %s product.cost" % op), "m")
                [guard] = nodes_of(doc, "Guard")
                self.assertEqual("product.price %s product.cost" % op,
                                 guard["condition"])

    def test_money_arithmetic_may_meet_money_inside_a_guard(self):
        doc = compile_doc(self.guard(
            "product.price - product.cost > product.cost"), "m")
        self.assertEqual(1, len(nodes_of(doc, "Guard")))

    # ---- refused arithmetic ---------------------------------------------
    def test_money_times_money_is_refused(self):
        self.compile_fails(self.assignment(
            "set product.price to product.price * product.cost"),
            "multiplies two Money values", "RFC-0051")

    def test_money_divided_by_money_is_refused(self):
        self.compile_fails(self.assignment(
            "set product.price to product.price / product.cost"),
            "divides two Money values", "RFC-0051")

    def test_money_divided_by_an_integer_is_refused(self):
        self.compile_fails(self.assignment(
            "set product.price to product.price / product.stock"),
            "combines a Money value with a scalar value via '/'", "RFC-0051")

    def test_an_integer_divided_by_money_is_refused(self):
        self.compile_fails(self.assignment(
            "set product.stock to product.stock / product.price"),
            "combines a Money value with a scalar value via '/'", "RFC-0051")

    def test_money_plus_a_number_literal_is_refused(self):
        # Boundary: a literal is admitted ONLY under `*` — `price + 3` has no
        # currency to add in.
        self.compile_fails(self.assignment(
            "set product.price to product.price + 3"),
            "combines a Money value with a scalar value via '+'",
            "a number literal", "RFC-0051")

    def test_money_plus_a_datetime_is_refused(self):
        self.compile_fails(self.assignment(
            "set product.price to product.price + product.createdAt"),
            "combines a Money value with an instant value via '+'", "RFC-0051")

    # ---- refused comparisons --------------------------------------------
    def test_money_against_an_integer_field_is_a_mismatch(self):
        self.compile_fails(self.guard("product.price > product.stock"),
                           "product.price (money)", "product.stock (scalar)",
                           "Money compares only to Money (RFC-0051)")

    def test_money_against_a_datetime_is_a_mismatch(self):
        self.compile_fails(self.guard("product.createdAt < product.price"),
                           "(instant)", "(money)", "RFC-0051")

    def test_a_non_money_mismatch_keeps_its_rfc_0016_message_only(self):
        message = self.compile_fails(
            self.guard("product.createdAt > product.stock"),
            "compares like with like")
        self.assertNotIn("RFC-0051", message)

    # ---- target vs right-hand side --------------------------------------
    def test_assigning_money_to_an_integer_field_is_refused(self):
        self.compile_fails(self.assignment(
            "set product.stock to product.price"),
            "assigns product.price (money) to product.stock (scalar)",
            "RFC-0051")

    def test_assigning_an_integer_to_a_money_field_is_refused(self):
        self.compile_fails(self.assignment(
            "set product.price to product.stock + 1"),
            "to product.price (money)", "RFC-0051")

    def test_a_bare_right_hand_side_is_left_to_the_runtime(self):
        # Boundary: a bare reference has no declared type, so the new
        # target/RHS check has nothing to compare and must not refuse —
        # `stock` is Integer as a field, yet the bare input name is untyped.
        # (RFC-0057 §7: the name must be declared somewhere; `amount` was
        # not, and an undeclared bare name is now a compile error.)
        doc = compile_doc(self.assignment("set product.price to stock"), "m")
        self.assertEqual(1, len(nodes_of(doc, "Assignment")))

    # ---- Decimal stays refused --------------------------------------------
    def test_a_decimal_guard_is_still_refused_citing_rfc_0044(self):
        self.compile_fails(self.guard("product.rate > 0"),
                           "neither Integer nor DateTime", "Decimal",
                           "RFC-0051", "RFC-0044")

    def test_decimal_arithmetic_is_still_refused(self):
        self.compile_fails(self.assignment(
            "set product.price to product.price * product.rate"),
            "neither Integer nor DateTime", "Decimal", "RFC-0044")


class TestModeAEvaluation(unittest.TestCase):
    """RFC-0015 evaluation: normal / error / boundary per behaviour."""

    def holds(self, condition, payload=None, bindings=None):
        return _condition_holds(condition, payload or {}, bindings or {})

    # ---- normal ------------------------------------------------------------
    def test_a_field_on_the_right_decides_the_comparison(self):
        bindings = {"product": {"stock": 5}}
        self.assertTrue(self.holds("product.stock >= input.quantity",
                                   {"quantity": 2}, bindings))
        self.assertFalse(self.holds("product.stock >= input.quantity",
                                    {"quantity": 9}, bindings))

    def test_arithmetic_is_evaluated_before_the_comparison(self):
        bindings = {"product": {"stock": 5}}
        self.assertTrue(self.holds("product.stock - input.quantity >= 0",
                                   {"quantity": 5}, bindings))
        self.assertFalse(self.holds("product.stock - input.quantity >= 0",
                                    {"quantity": 6}, bindings))

    def test_and_requires_every_term(self):
        self.assertTrue(self.holds("input.amount > 0 and input.amount <= 10",
                                   {"amount": 10}))
        self.assertFalse(self.holds("input.amount > 0 and input.amount <= 10",
                                    {"amount": 11}))
        self.assertFalse(self.holds("input.amount > 0 and input.amount <= 10",
                                    {"amount": 0}))

    def test_input_and_the_bare_form_read_the_same_payload(self):
        self.assertEqual(self.holds("input.stock > 0", {"stock": 1}),
                         self.holds("stock > 0", {"stock": 1}))

    # ---- error -------------------------------------------------------------
    def test_a_non_numeric_value_fails_with_a_domain_error(self):
        for raw in ("ten", {"value": 10}):
            with self.subTest(raw=raw):
                with self.assertRaises(RunError) as ctx:
                    self.holds("input.amount > 0", {"amount": raw})
                self.assertIn("non-numeric", str(ctx.exception))
                self.assertIn("amount", str(ctx.exception))

    def test_a_money_value_against_a_number_fails_with_a_domain_error(self):
        # RFC-0051: a Money-shaped value is money now, not "non-numeric" — but
        # it still cannot meet a plain number, and that still fails the run.
        with self.assertRaises(RunError) as ctx:
            self.holds("input.amount > 0",
                       {"amount": {"amount": "10.00", "currency": "USD"}})
        self.assertIn("cannot compare a Money value with a plain number",
                      str(ctx.exception))
        self.assertIn("input.amount", str(ctx.exception))

    def test_arithmetic_past_the_64_bit_range_fails(self):
        with self.assertRaises(RunError) as ctx:
            self.holds("input.a + input.b > 0",
                       {"a": 2 ** 63 - 1, "b": 1})
        self.assertIn("64-bit range", str(ctx.exception))

    def test_a_value_past_the_64_bit_range_fails_before_it_is_compared(self):
        with self.assertRaises(RunError) as ctx:
            self.holds("input.a > 0", {"a": 2 ** 63})
        self.assertIn("64-bit range", str(ctx.exception))

    # ---- boundary ----------------------------------------------------------
    def test_zero_and_equality_and_negative_results(self):
        self.assertTrue(self.holds("input.a == 0", {"a": 0}))
        self.assertTrue(self.holds("input.a - input.b == 0", {"a": 3, "b": 3}))
        self.assertTrue(self.holds("input.a - input.b < 0", {"a": 3, "b": 4}))

    def test_an_absent_field_makes_every_comparison_false(self):
        for op in ("<", "<=", ">", ">=", "==", "!="):
            self.assertFalse(self.holds("input.missingOne %s 0" % op, {}),
                             "absent field must not satisfy %r" % op)

    def test_an_empty_payload_leaves_an_and_false_rather_than_raising(self):
        self.assertFalse(self.holds("input.a > 0 and input.b < 1", {}))

    def test_an_unbound_row_on_either_side_is_false(self):
        self.assertFalse(self.holds("product.stock >= input.quantity",
                                    {"quantity": 1}, {}))
        self.assertFalse(self.holds("input.quantity <= product.stock",
                                    {"quantity": 1}, {}))


class TestAssignmentRuntime(unittest.TestCase):
    """The assignment's effect, its observability, and its isolation."""

    def test_the_effect_is_recorded_not_silent(self):
        interp = inventory_interp(stock=5)
        result = interp.run_workflow("wf.place.order",
                                     {"id": PRODUCT_ID, "stock": 5, "quantity": 2})
        effects = [kind for step in result["steps"] for kind in step["effects"]]
        self.assertIn("Assignment", effects)
        applied = [log for log in interp.trace.to_dict()["logs"]
                   if log["message"] == "assignment applied"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["value"], 3)

    def test_a_skipped_assignment_leaves_the_row_alone(self):
        interp = inventory_interp(stock=1)
        interp.run_workflow("wf.place.order",
                            {"id": PRODUCT_ID, "stock": 1, "quantity": 2})
        row = interp.repo.rows["entity.product"][
            row_key("entity.product", {"id": PRODUCT_ID})]
        self.assertEqual(row["stock"], 1)

    def test_the_boundary_where_stock_exactly_meets_the_order(self):
        interp = inventory_interp(stock=2)
        result = interp.run_workflow("wf.place.order",
                                     {"id": PRODUCT_ID, "stock": 2, "quantity": 2})
        self.assertEqual(result["skipped"], [])
        row = interp.repo.rows["entity.product"][
            row_key("entity.product", {"id": PRODUCT_ID})]
        self.assertEqual(row["stock"], 0)

    def test_a_zero_quantity_order_changes_nothing_but_still_runs(self):
        interp = inventory_interp(stock=2)
        interp.run_workflow("wf.place.order",
                            {"id": PRODUCT_ID, "stock": 2, "quantity": 0})
        row = interp.repo.rows["entity.product"][
            row_key("entity.product", {"id": PRODUCT_ID})]
        self.assertEqual(row["stock"], 2)

    def test_one_runs_writes_do_not_reach_the_next_runs_seed(self):
        # The seed dict is the caller's. `set` writes into a bound row, and a
        # bound row is the stored row, so a shallow copy of the table would hand
        # run two the row run one deducted.
        doc = compile_doc(INVENTORY, "inventory")
        payload = {"id": PRODUCT_ID, "stock": 5, "quantity": 2}
        seed = {"entity.product": {row_key("entity.product", payload):
                                   {"id": PRODUCT_ID, "stock": 5}}}
        for _ in range(2):
            interp = Interpreter(doc, repo_rows=seed)
            interp.run_workflow("wf.place.order", payload)
            row = interp.repo.rows["entity.product"][
                row_key("entity.product", payload)]
            self.assertEqual(row["stock"], 3,
                             "each run must start from the seed, not from the "
                             "previous run's deduction")
        self.assertEqual(
            seed["entity.product"][row_key("entity.product", payload)]["stock"], 5,
            "the caller's seed must be untouched")


def _with_bare_inputs(source):
    """RFC-0057 §7: a bare operand must name a declared field. These names
    are declared Text on an entity no workflow touches, so the operand stays
    untyped for lowering and its runtime shape is the payload's."""
    return source.replace("service S\n", "entity Inputs\n    field\n"
                          "        id UUID\n        extra Text\n"
                          "        left Text\n        right Text\n\n"
                          "service S\n", 1)


MONEY_RUNTIME = """capability postgres

entity Order
    field
        id UUID
        qty Integer
        unitPrice Money
        lineTotal Money
        gross Money
        fees Money
        net Money
        total Money
        threshold Money

service S
    policy
        timeout 5s

workflow PriceLine
    read order
    set order.lineTotal to order.unitPrice * order.qty

workflow ScaleLine
    read order
    set order.lineTotal to 3 * order.unitPrice

workflow AddUp
    read order
    set order.total to order.gross + order.fees

workflow Settle
    read order
    set order.net to order.gross - order.fees

workflow Carry
    read order
    set order.net to input.net

workflow Approve
    read order
    when order.total > order.threshold
    set order.net to order.total

workflow Match
    read order
    when order.total == order.threshold
    set order.net to order.total
"""


def usd(amount, currency="USD"):
    return {"amount": amount, "currency": currency}


class TestMoneyRuntime(unittest.TestCase):
    """RFC-0051 §3 — mode A evaluates the Gate-1 Money subset in exact minor
    units (issue #172: s1 F-1, s3 F-1). Every value is read back through the
    repository, not only the trace."""

    def run_on(self, workflow, row, payload_extra=None):
        doc = compile_doc(MONEY_RUNTIME, "money")
        [wf] = [n for n in doc["nodes"]
                if n["kind"] == "Workflow" and n["name"] == workflow]
        payload = dict({"id": PRODUCT_ID}, **(payload_extra or {}))
        key = row_key("entity.order", payload)
        interp = Interpreter(doc, repo_rows={
            "entity.order": {key: dict({"id": PRODUCT_ID}, **row)}})
        result = interp.run_workflow(wf["id"], payload)
        return result, interp.repo.rows["entity.order"][key]

    # ---- normal ------------------------------------------------------------
    def test_money_times_an_integer_field_is_exact(self):
        # s1 F-1: 12.50 USD × 3.
        result, row = self.run_on("PriceLine",
                                  {"unitPrice": usd("12.50"), "qty": 3})
        self.assertEqual("completed", result["status"])
        self.assertEqual(usd("37.50"), row["lineTotal"])

    def test_an_exponent_zero_currency_multiplies_without_a_decimal_point(self):
        result, row = self.run_on("PriceLine",
                                  {"unitPrice": usd("1000", "JPY"), "qty": 3})
        self.assertEqual(usd("3000", "JPY"), row["lineTotal"])

    def test_a_literal_on_the_left_multiplies_the_same_way(self):
        result, row = self.run_on("ScaleLine", {"unitPrice": usd("0.05")})
        self.assertEqual(usd("0.15"), row["lineTotal"])

    def test_an_exponent_three_currency_adds_with_three_places(self):
        result, row = self.run_on("AddUp", {"gross": usd("1.250", "KWD"),
                                            "fees": usd("0.750", "KWD")})
        self.assertEqual("completed", result["status"])
        self.assertEqual(usd("2.000", "KWD"), row["total"])

    def test_money_minus_money_is_exact(self):
        # s3 F-1: 100.00 USD − 30.25 USD.
        result, row = self.run_on("Settle", {"gross": usd("100.00"),
                                             "fees": usd("30.25")})
        self.assertEqual(usd("69.75"), row["net"])

    def test_a_money_shaped_payload_value_is_copied(self):
        # s3 F-1's operator-free copy from the input.
        result, row = self.run_on("Carry", {"net": usd("0.00")},
                                  {"net": usd("69.75")})
        self.assertEqual("completed", result["status"])
        self.assertEqual(usd("69.75"), row["net"])

    def test_a_same_currency_money_guard_takes_the_branch(self):
        result, row = self.run_on("Approve", {"total": usd("500.00"),
                                              "threshold": usd("100.00"),
                                              "net": usd("0.00")})
        self.assertEqual("completed", result["status"])
        self.assertEqual([], result["skipped"])
        self.assertEqual(usd("500.00"), row["net"])

    def test_a_skipped_money_guard_records_wire_shaped_evaluations(self):
        result, row = self.run_on("Approve", {"total": usd("50.00"),
                                              "threshold": usd("100.00"),
                                              "net": usd("0.00")})
        self.assertEqual(usd("0.00"), row["net"])
        [record] = result["skipped"]
        [evaluation] = record["evaluations"]
        self.assertEqual({"ref": "order.total", "value": usd("50.00"),
                          "op": ">", "expected": usd("100.00"),
                          "holds": False}, evaluation)

    # ---- error -------------------------------------------------------------
    def test_different_currencies_under_an_order_comparator_stop_the_run(self):
        # A guard value fault takes the existing guard path (like a
        # non-numeric or divide-by-zero guard): the RunError escapes the run,
        # which rolls back — `lnpl run` reports it as a runtime error, rc=3.
        doc = compile_doc(MONEY_RUNTIME, "money")
        [wf] = [n for n in doc["nodes"] if n.get("name") == "Approve"]
        key = row_key("entity.order", {"id": PRODUCT_ID})
        interp = Interpreter(doc, repo_rows={"entity.order": {key: {
            "id": PRODUCT_ID, "total": usd("500.00"),
            "threshold": usd("100.00", "EUR"), "net": usd("0.00")}}})
        with self.assertRaises(RunError) as ctx:
            interp.run_workflow(wf["id"], {"id": PRODUCT_ID})
        self.assertIn("money-currency-mismatch", str(ctx.exception))
        self.assertIn("order.total > order.threshold", str(ctx.exception))
        self.assertEqual(usd("0.00"),
                         interp.repo.rows["entity.order"][key]["net"])

    def test_subtracting_different_currencies_fails_the_run(self):
        result, row = self.run_on("Settle", {"gross": usd("100.00"),
                                             "fees": usd("1.00", "EUR"),
                                             "net": usd("0.00")})
        self.assertEqual("failed", result["status"])
        self.assertIn("money-currency-mismatch", result["failure_reason"])
        self.assertEqual(usd("0.00"), row["net"])

    def test_a_product_past_the_64_bit_range_fails_the_run(self):
        result, row = self.run_on("PriceLine", {"unitPrice": usd("1.00"),
                                                "qty": 2 ** 62,
                                                "lineTotal": usd("0.00")})
        self.assertEqual("failed", result["status"])
        self.assertIn("value out of the 64-bit range", result["failure_reason"])
        self.assertEqual(usd("0.00"), row["lineTotal"])

    def test_a_value_with_the_wrong_scale_fails_the_run(self):
        result, row = self.run_on("Settle", {"gross": usd("100.0"),
                                             "fees": usd("1.00"),
                                             "net": usd("0.00")})
        self.assertEqual("failed", result["status"])
        self.assertIn("money-encode-precision", result["failure_reason"])

    def test_a_money_payload_value_meeting_an_integer_fails_the_run(self):
        # A bare (input) ref can carry Money where lowering could not see it.
        doc = compile_doc(_with_bare_inputs(MONEY_RUNTIME.replace(
            "set order.net to input.net", "set order.qty to order.qty + extra")),
            "money")
        [wf] = [n for n in doc["nodes"] if n.get("name") == "Carry"]
        key = row_key("entity.order", {"id": PRODUCT_ID})
        interp = Interpreter(doc, repo_rows={
            "entity.order": {key: {"id": PRODUCT_ID, "qty": 1}}})
        result = interp.run_workflow(wf["id"], {"id": PRODUCT_ID,
                                                "extra": usd("1.00")})
        self.assertEqual("failed", result["status"])
        self.assertIn("Money", result["failure_reason"])
        self.assertEqual(1, interp.repo.rows["entity.order"][key]["qty"])

    def _run_bare(self, expression, payload):
        """`set order.qty to <expression>` over bare (payload) refs —
        lowering cannot see their shapes, so the refusal is the runtime's."""
        doc = compile_doc(_with_bare_inputs(MONEY_RUNTIME.replace(
            "set order.net to input.net", "set order.qty to " + expression)),
            "money")
        [wf] = [n for n in doc["nodes"] if n.get("name") == "Carry"]
        key = row_key("entity.order", {"id": PRODUCT_ID})
        interp = Interpreter(doc, repo_rows={
            "entity.order": {key: {"id": PRODUCT_ID, "qty": 7}}})
        result = interp.run_workflow(wf["id"], dict({"id": PRODUCT_ID},
                                                    **payload))
        return result, interp.repo.rows["entity.order"][key]

    def test_money_combinations_lowering_cannot_see_fail_the_run(self):
        a, b = usd("2.00"), usd("3.00")
        for expression, payload, message in (
                ("left * right", {"left": a, "right": b},
                 "cannot multiply two Money values"),
                ("left / right", {"left": a, "right": b},
                 "cannot divide two Money values"),
                ("left / right", {"left": a, "right": 2},
                 "cannot combine a Money value and a plain number with '/'"),
                ("left / right", {"left": 2, "right": a},
                 "cannot combine a Money value and a plain number with '/'"),
                ("left + right", {"left": a,
                                  "right": "2026-07-01T00:00:00Z"},
                 "cannot combine a Money value and a plain number with '+'")):
            with self.subTest(expression=expression, payload=payload):
                result, row = self._run_bare(expression, payload)
                self.assertEqual("failed", result["status"])
                self.assertIn(message, result["failure_reason"])
                self.assertIn(expression, result["failure_reason"])
                self.assertEqual(7, row["qty"])

    # ---- boundary ----------------------------------------------------------
    def test_equality_across_currencies_is_false_not_a_failure(self):
        result, row = self.run_on("Match", {"total": usd("100.00"),
                                            "threshold": usd("100.00", "EUR"),
                                            "net": usd("0.00")})
        self.assertEqual("completed", result["status"])
        self.assertEqual(1, len(result["skipped"]))
        self.assertEqual(usd("0.00"), row["net"])

    def test_equal_amounts_in_one_currency_are_equal(self):
        result, row = self.run_on("Match", {"total": usd("100.00"),
                                            "threshold": usd("100.00"),
                                            "net": usd("0.00")})
        self.assertEqual([], result["skipped"])
        self.assertEqual(usd("100.00"), row["net"])

    def test_an_unresolved_side_of_a_money_comparison_is_false(self):
        # RFC-0015: a reference that names nothing compares false — Money
        # does not turn it into a failure.
        result, row = self.run_on("Approve", {"total": usd("500.00"),
                                              "net": usd("0.00")})
        self.assertEqual("completed", result["status"])
        [record] = result["skipped"]
        self.assertIsNone(record["evaluations"][0]["expected"])
        self.assertEqual(usd("0.00"), row["net"])

    def test_a_negative_result_keeps_its_sign(self):
        result, row = self.run_on("Settle", {"gross": usd("1.00"),
                                             "fees": usd("1.05")})
        self.assertEqual(usd("-0.05"), row["net"])


class TestIrSchemaGate(unittest.TestCase):
    """The Assignment node against schemas/lir.schema.json, and the gate itself.

    A suite in which nothing loads the schema is unaffected by any edit to it,
    so the gate is invoked here rather than only from the command line.
    """

    def test_a_lowered_assignment_document_validates(self):
        import jsonschema
        with open(os.path.join(REPO_ROOT, "schemas", "lir.schema.json"),
                  encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.validate(compile_doc(INVENTORY, "inventory"), schema)

    def test_the_schema_self_test_passes_including_the_new_negatives(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "validate_ir.py"),
             "--self-test"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ASSIGNMENT_FIXTURE", proc.stdout)
        for label in ("Assignment.target", "expression is not a string",
                      "kind outside the catalogue",
                      "undeclared property on Assignment",
                      "entity is not a node id"):
            self.assertIn(label, proc.stdout,
                          "the gate no longer runs the %r negative" % label)


if __name__ == "__main__":
    unittest.main()
