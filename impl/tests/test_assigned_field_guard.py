"""RFC-0060 (RFC-0015 Open Question 1): mode A lets a guard read a field this
workflow already assigned, and evaluates it against the value at that point
(issue #211 (1)).

Before RFC-0060 this was a compile error — mode B fixes condition fields at
entry, so the two modes would have compared different numbers. Mode B now
refuses such a workflow instead (`test_assigned_field_guard_mode_b.py`); mode
A compiles it and reads the current value.

The decisive case is the one where the entry value and the current value
disagree: stock 1, quantity 2. At entry `1 >= 0` holds; after the decrement
`-1 >= 0` does not. Only reading the current value skips the update.
"""

import unittest

from lnpl.interp import Interpreter
from lnpl.lower import LowerError, lower
from lnpl.parser import ParseError, parse
from lnpl.repo_policy import row_key

PRODUCT_ID = "00000000-0000-4000-8000-000000000211"

HEAD = """capability postgres

entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

service ShopService
    policy
        timeout 5s

workflow PlaceOrder
    find product
"""

# Issue #211 (1), verbatim, after a `create order` the first guard owns.
ISSUE_REPRO = HEAD + """    when product.stock >= input.quantity
    create order
    when product.stock >= input.quantity
    set product.stock to product.stock - input.quantity
    when product.stock >= 0
    update product
"""

# The decrement is unguarded, so it CAN drive stock below 0 — the case where
# the entry value and the current value give different answers.
UNGUARDED_DECREMENT = HEAD + """    set product.stock to product.stock - input.quantity
    when product.stock >= 0
    update product
"""


def compile_doc(source):
    return lower(parse(source), "shop").to_document()


def run(source, stock, quantity):
    rows = {"entity.product": {row_key("entity.product", {"id": PRODUCT_ID}):
                               {"id": PRODUCT_ID, "stock": stock}}}
    interp = Interpreter(compile_doc(source), repo_rows=rows)
    result = interp.run_workflow("wf.place.order",
                                 {"id": PRODUCT_ID, "quantity": quantity})
    stored = interp.repo.rows["entity.product"][
        row_key("entity.product", {"id": PRODUCT_ID})]["stock"]
    return result, stored


def ran(result):
    return [s["step"] for s in result["steps"]]


class TestAssignedFieldGuardModeA(unittest.TestCase):

    def test_the_issue_repro_compiles(self):
        doc = compile_doc(ISSUE_REPRO)
        conditions = [n["condition"] for n in doc["nodes"] if n["kind"] == "Guard"]
        self.assertEqual(conditions, ["product.stock >= input.quantity",
                                      "product.stock >= input.quantity",
                                      "product.stock >= 0"])

    def test_enough_stock_runs_the_update_on_the_decremented_row(self):
        result, stored = run(ISSUE_REPRO, stock=5, quantity=2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(ran(result), ["find product", "create order",
                                       "set product.stock to product.stock - "
                                       "input.quantity", "update product"])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(stored, 3)

    def test_a_decrement_below_zero_skips_the_guarded_update(self):
        result, stored = run(UNGUARDED_DECREMENT, stock=1, quantity=2)
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("update product", ran(result))
        self.assertEqual(stored, -1)
        [record] = result["skipped"]
        self.assertEqual(record["steps"], ["update product"])
        self.assertEqual(record["condition"], "product.stock >= 0")
        # the guard saw the CURRENT value, not the entry value 1
        self.assertEqual([(e["ref"], e["value"], e["holds"])
                          for e in record["evaluations"]],
                         [("product.stock", -1, False)])

    def test_an_or_alternative_reads_the_current_value_too(self):
        source = UNGUARDED_DECREMENT.replace(
            "    when product.stock >= 0\n",
            "    when product.stock >= 100\n    or product.stock >= 0\n")
        self.assertNotEqual(source, UNGUARDED_DECREMENT)
        self.assertIn("update product", ran(run(source, stock=5, quantity=2)[0]))
        self.assertNotIn("update product",
                         ran(run(source, stock=1, quantity=2)[0]))

    # ---- boundary -------------------------------------------------------

    def test_a_decrement_to_exactly_zero_still_runs_the_update(self):
        result, stored = run(UNGUARDED_DECREMENT, stock=2, quantity=2)
        self.assertIn("update product", ran(result))
        self.assertEqual(stored, 0)
        self.assertEqual(result["skipped"], [])

    def test_a_guard_above_the_assignment_reads_the_entry_value(self):
        source = HEAD + """    when product.stock >= 2
    update product
    set product.stock to product.stock - input.quantity
"""
        result, stored = run(source, stock=2, quantity=2)
        self.assertIn("update product", ran(result))
        self.assertEqual(stored, 0)

    # ---- error: the relaxation does not open any other check ------------

    def test_the_guard_is_still_checked_for_everything_else(self):
        source = UNGUARDED_DECREMENT.replace("when product.stock >= 0",
                                             "when product.stock >= order.quantity")
        with self.assertRaises((LowerError, ParseError)) as ctx:
            compile_doc(source)
        self.assertIn("order.quantity", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
