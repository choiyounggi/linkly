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
        self.compile_fails(self.workflow("    read product\n"
                                         "    when product.price > 0\n"
                                         "    create product"),
                           "is not Integer", "Money")

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

    def test_a_guard_reading_an_assigned_field_is_refused(self):
        # RFC-0015's mode-equivalence rule: mode B fixes condition fields at
        # entry, so this program would compare a different number there.
        self.compile_fails(
            self.workflow("    read product\n"
                          "    set product.stock to product.stock - 1\n"
                          "    when product.stock > 0\n"
                          "    create product"),
            "which an earlier step assigns", "Move the guard above")

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
        with self.assertRaises(RunError) as ctx:
            self.holds("input.amount > 0", {"amount": {"amount": "10", "currency": "USD"}})
        self.assertIn("non-numeric", str(ctx.exception))
        self.assertIn("amount", str(ctx.exception))

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
