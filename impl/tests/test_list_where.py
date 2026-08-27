"""Issue #116 — `list <Entity> where <cond> [order by <field> [desc]]
[limit <N>]`, the lowering-time contract (Task 01 of t116's plan).

Follows `test_row_sets.py`'s convention: no running interpreter here, only
`lower()` and the emitted `RepositoryCall` node's shape. Runtime execution
(mode A binding a FILTERED RowSet) is `test_list_where_runtime.py`; driver
pushdown is `test_drivers.py`/`RepositoryDriverTCK` (testing.py).
"""

import json
import os
import unittest

from lnpl.lower import LowerError, lower
from lnpl.parser import parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def compile_doc(source, module="m"):
    return lower(parse(source), module)


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


def orders_source(body, amount_field="amount Integer"):
    """`Customer`/`Order` fixture: an Integer field (`amount`), a DateTime
    field (`placedAt`), a Text field (`status`) and a UUID field
    (`customerId`) — enough field bases to exercise both the order-comparison
    restriction (Integer/DateTime only) and the any-type equality path
    (D2). `find customer` binds `customer` so a predicate's right side can
    name a single-row binding field (`customer.id`, `customer.tier`), the
    other of D1's three allowed right-side shapes besides `input.<field>`
    and a literal.
    """
    return """capability postgres

entity Customer
    field
        id UUID
        tier Text

entity Order
    field
        id UUID
        customerId UUID
        %s
        placedAt DateTime
        status Text

service Shop
    policy
        timeout 5s

workflow ListOrders
    find customer
%s
""" % (amount_field, body)


def list_calls(doc, entity="entity.order"):
    return [n for n in nodes_of(doc, "RepositoryCall")
           if n["entity"] == entity and n["operation"] == "query"]


class TestPredicateGrammar(unittest.TestCase):
    """D1: `where` reuses the guard condition grammar verbatim; D4: the
    predicate lowers to a structured conjunction list, not a raw string."""

    def test_bare_list_has_no_predicate_order_or_limit(self):
        """The regression path: no `rest` tokens means the node is byte-
        identical to the pre-#116 shape — no new keys at all (constraints:
        "predicate=None 경로 바이트 동일")."""
        doc = compile_doc(orders_source("    list order\n")).to_document()
        call = list_calls(doc)[0]
        self.assertNotIn("predicate", call)
        self.assertNotIn("order", call)
        self.assertNotIn("limit", call)

    def test_single_comparison_lowers_to_a_one_term_predicate(self):
        doc = compile_doc(orders_source(
            "    list order where amount > 100\n")).to_document()
        call = list_calls(doc)[0]
        self.assertEqual(call["predicate"],
                         [{"field": "amount", "op": ">", "value": "100"}])

    def test_and_conjunction_lowers_to_a_multi_term_predicate(self):
        doc = compile_doc(orders_source(
            "    list order where amount > 100 and status == customer.tier\n"
        )).to_document()
        call = list_calls(doc)[0]
        self.assertEqual(call["predicate"], [
            {"field": "amount", "op": ">", "value": "100"},
            {"field": "status", "op": "==", "value": "customer.tier"},
        ])

    def test_right_side_input_field_is_accepted(self):
        doc = compile_doc(orders_source(
            "    list order where amount > input.amount\n"
        )).to_document()
        call = list_calls(doc)[0]
        self.assertEqual(call["predicate"],
                         [{"field": "amount", "op": ">", "value": "input.amount"}])

    def test_right_side_one_arithmetic_op_is_accepted(self):
        doc = compile_doc(orders_source(
            "    list order where amount > input.amount - 10\n"
        )).to_document()
        call = list_calls(doc)[0]
        self.assertEqual(call["predicate"], [
            {"field": "amount", "op": ">", "value": "input.amount - 10"}])

    def test_presence_check_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source("    list order where status exists\n"))
        self.assertIn("comparisons only", str(ctx.exception))

    def test_left_side_must_be_a_bare_field_of_the_listed_entity(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source(
                "    list order where input.amount > 5\n"))
        self.assertIn("bare field", str(ctx.exception))

    def test_left_side_literal_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source("    list order where 5 > amount\n"))
        self.assertIn("bare field", str(ctx.exception))

    def test_missing_where_keyword_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source("    list order amount > 100\n"))
        self.assertIn("where", str(ctx.exception))

    def test_empty_where_condition_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source("    list order where order by amount\n"))
        self.assertIn("where", str(ctx.exception))


class TestUndeclaredField(unittest.TestCase):
    """Definition-of-done item 5: an undeclared field names its candidates."""

    def test_where_field_not_on_entity_lists_candidates(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source("    list order where bogus == 1\n"))
        message = str(ctx.exception)
        self.assertIn("bogus", message)
        self.assertIn("candidates", message)
        for name in ("id", "customerId", "amount", "placedAt", "status"):
            self.assertIn(name, message)

    def test_order_by_field_not_on_entity_lists_candidates(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source(
                "    list order where amount > 0 order by bogus\n"))
        message = str(ctx.exception)
        self.assertIn("bogus", message)
        self.assertIn("candidates", message)


class TestOrderComparisonDimension(unittest.TestCase):
    """D2: order comparators (`<`,`<=`,`>`,`>=`) keep the pre-existing
    Integer/DateTime restriction (`_dimension_of`, RFC-0016) — unchanged by
    this issue for scalar/instant fields."""

    def test_order_comparator_on_integer_field_is_accepted(self):
        doc = compile_doc(orders_source(
            "    list order where amount >= 100\n")).to_document()
        self.assertEqual(list_calls(doc)[0]["predicate"][0]["op"], ">=")

    def test_order_comparator_on_datetime_field_is_accepted(self):
        doc = compile_doc(orders_source(
            "    list order where placedAt > input.placedAt\n")).to_document()
        self.assertEqual(list_calls(doc)[0]["predicate"][0]["field"], "placedAt")

    def test_order_comparator_on_text_field_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source("    list order where status > input.status\n"))
        message = str(ctx.exception)
        self.assertIn("Integer or DateTime", message)
        self.assertIn("status", message)

    def test_order_comparator_on_uuid_field_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source(
                "    list order where customerId > customer.id\n"))
        self.assertIn("Integer or DateTime", str(ctx.exception))

    def test_money_field_order_comparator_is_refused_same_as_a_guard(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source(
                "    list order where amount > 0\n", amount_field="amount Money"))
        self.assertIn("Integer or DateTime", str(ctx.exception))


class TestEqualityAcrossTypes(unittest.TestCase):
    """D2: equality (`==`/`!=`) allows any type as long as both sides are the
    same declared base type — the issue's core motivating case (UUID/Text/
    Email fields, which `_dimension_of` alone would always refuse)."""

    def test_uuid_equality_against_a_bound_rows_uuid_field_is_accepted(self):
        doc = compile_doc(orders_source(
            "    list order where customerId == customer.id\n")).to_document()
        call = list_calls(doc)[0]
        self.assertEqual(call["predicate"],
                         [{"field": "customerId", "op": "==", "value": "customer.id"}])

    def test_text_inequality_against_a_bound_rows_text_field_is_accepted(self):
        doc = compile_doc(orders_source(
            "    list order where status != customer.tier\n")).to_document()
        self.assertEqual(list_calls(doc)[0]["predicate"][0]["op"], "!=")

    def test_text_equality_against_input_field_is_accepted(self):
        doc = compile_doc(orders_source(
            "    list order where status == input.status\n")).to_document()
        self.assertEqual(list_calls(doc)[0]["predicate"][0]["field"], "status")

    def test_equality_across_mismatched_types_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source(
                "    list order where customerId == customer.tier\n"))
        message = str(ctx.exception)
        self.assertIn("customerId", message)
        self.assertIn("same declared type", message)

    def test_equality_of_a_non_numeric_field_against_a_literal_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source("    list order where status == 5\n"))
        self.assertIn("reference", str(ctx.exception))

    def test_integer_equality_still_applies_the_dimension_check(self):
        """Equality on an Integer/DateTime field is unchanged: it still goes
        through the pre-existing scalar/instant dimension check, not the new
        any-type path (RFC-0016 is not relaxed for scalar/instant) — a Text
        field on the right is refused for having no evaluator at all, not
        merely for mismatching `amount`'s type."""
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source(
                "    list order where amount == customer.tier\n"))
        self.assertIn("neither Integer nor DateTime", str(ctx.exception))


class TestOrderByAndLimit(unittest.TestCase):
    """D7: `order by` reuses `expose list`'s sort-field check verbatim."""

    def test_order_by_ascending(self):
        doc = compile_doc(orders_source(
            "    list order where amount > 0 order by placedAt\n")).to_document()
        self.assertEqual(list_calls(doc)[0]["order"],
                         {"field": "placedAt", "desc": False})

    def test_order_by_descending(self):
        doc = compile_doc(orders_source(
            "    list order where amount > 0 order by placedAt desc\n")).to_document()
        self.assertEqual(list_calls(doc)[0]["order"],
                         {"field": "placedAt", "desc": True})

    def test_order_by_and_limit_together(self):
        doc = compile_doc(orders_source(
            "    list order where amount > 0 order by amount desc limit 5\n"
        )).to_document()
        call = list_calls(doc)[0]
        self.assertEqual(call["order"], {"field": "amount", "desc": True})
        self.assertEqual(call["limit"], 5)

    def test_limit_alone_after_where(self):
        doc = compile_doc(orders_source(
            "    list order where amount > 0 limit 3\n")).to_document()
        call = list_calls(doc)[0]
        self.assertEqual(call["limit"], 3)
        self.assertNotIn("order", call)

    def test_order_by_field_must_be_integer_or_datetime(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source(
                "    list order where amount > 0 order by status\n"))
        self.assertIn("Integer or DateTime", str(ctx.exception))

    def test_limit_must_be_a_positive_integer(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source("    list order where amount > 0 limit 0\n"))
        self.assertIn("limit", str(ctx.exception))

    def test_limit_before_order_by_is_refused(self):
        """D1: clause order is fixed where -> order by -> limit."""
        with self.assertRaises(LowerError) as ctx:
            compile_doc(orders_source(
                "    list order where amount > 0 limit 5 order by amount\n"))
        self.assertIn("clause order", str(ctx.exception))


class TestIrSchemaGate(unittest.TestCase):
    """issue #116, D10: a `list where`/`order by`/`limit` document validates
    against `schemas/lir.schema.json` (mirrors `test_row_sets.py`'s
    `TestIrSchemaGate` for the query-branch fields RFC-0025 already added)."""

    def test_a_lowered_predicate_document_validates(self):
        import jsonschema
        with open(os.path.join(REPO_ROOT, "schemas", "lir.schema.json"),
                  encoding="utf-8") as fh:
            schema = json.load(fh)
        doc = compile_doc(orders_source(
            "    list order where amount > 100 and status == customer.tier "
            "order by placedAt desc limit 5\n")).to_document()
        jsonschema.validate(doc, schema)


if __name__ == "__main__":
    unittest.main()
