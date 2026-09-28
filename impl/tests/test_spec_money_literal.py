"""Issue #160 (RFC-0044 §Reference-level Specification/3): MoneyLiteral in
`spec`'s `given`/`expect` `<value>` slot.

`money.parse_money_literal` (issue #145/task 01) is the SSOT for the token
grammar; this file pins the wiring — where the target field's declared type
is Money, `given`/`stored` seed the wire dict and `expect result` asserts
against it, with `==`/`!=` only (order comparisons explicitly refused). A
non-Money field's literal-shaped token stays the pre-existing raw string
(backward compatibility, D3(2)).
"""

import unittest

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import (SpecError, _indexed_seeds_from_given,
                       _payload_from_given, extract, run_manifest)
from lnpl.interp import refinement_index

MONEY_SRC = """
entity Product
    field
        id UUID
        price Money
        name Text
workflow Check
    find product
    spec
        given
            valid product
            stored product price 100.50USD
        when
            check
        expect
            completed
            result product.price == 100.50USD
"""

INPUT_MONEY_SRC = """
entity Order
    field
        id UUID
        total Money
workflow Place
    validate order
    spec
        given
            total 42.00USD
        when
            place
        expect
            completed
"""


def build(src, module="m"):
    decls = parse(src)
    return lower(decls, module).to_document(), extract(decls, module)


def payload_and_stored_for(src):
    doc, manifest = build(src)
    entity = next(n for n in doc["nodes"] if n["kind"] == "Entity")
    return _payload_from_given(manifest["cases"][0]["given"], entity,
                               refinement_index(doc), doc)


class TestStoredSeedsAMoneyWireDict(unittest.TestCase):
    """(정상) `stored <entity> <field> <value>` on a Money field."""

    def test_stored_seeds_the_wire_dict(self):
        _payload, stored = payload_and_stored_for(MONEY_SRC)
        entity_id = next(iter(stored))
        self.assertEqual({"price": {"amount": "100.50", "currency": "USD"}},
                         stored[entity_id])

    def test_the_end_to_end_case_passes(self):
        doc, manifest = build(MONEY_SRC)
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2, lines)

    # (경계) exponent 0 — no decimal point.
    def test_exponent_zero_currency_stores_without_a_decimal_point(self):
        src = MONEY_SRC.replace("100.50USD", "100JPY")
        _payload, stored = payload_and_stored_for(src)
        entity_id = next(iter(stored))
        self.assertEqual({"amount": "100", "currency": "JPY"},
                         stored[entity_id]["price"])

    # (경계) exponent 3.
    def test_exponent_three_currency_stores_three_decimal_places(self):
        src = MONEY_SRC.replace("100.50USD", "1.500BHD")
        _payload, stored = payload_and_stored_for(src)
        entity_id = next(iter(stored))
        self.assertEqual({"amount": "1.500", "currency": "BHD"},
                         stored[entity_id]["price"])


class TestStoredIndexedSeedsAMoneyWireDict(unittest.TestCase):
    """(정상/에러) `stored <entity>[<i>] <field> <value>` (RFC-0025 §8) on a
    Money field — the indexed form shares `_check_given_money_literal`'s
    validation and `_entity_field_base`'s type resolution with the single-row
    `stored` form above, so this pins that the same MoneyLiteral rule applies
    there too."""

    def test_an_indexed_stored_line_seeds_the_wire_dict(self):
        src = MONEY_SRC.replace("stored product price 100.50USD",
                                "stored product[0] price 100.50USD")
        doc, manifest = build(src)
        entity_id = next(n["id"] for n in doc["nodes"] if n["kind"] == "Entity")
        seeds = _indexed_seeds_from_given(manifest["cases"][0]["given"], doc)
        self.assertEqual({"amount": "100.50", "currency": "USD"},
                         seeds[entity_id]["0"]["price"])

    # (에러) 자릿수 위반은 stored-indexed 경로도 매니페스트 단계에서 거부.
    def test_a_malformed_indexed_literal_is_refused_at_manifest_time(self):
        src = MONEY_SRC.replace("stored product price 100.50USD",
                                "stored product[0] price 100.5USD")
        with self.assertRaises(SpecError):
            build(src)


class TestNonMoneyFieldLiteralShapedTokenStaysRaw(unittest.TestCase):
    """(경계) D3(2) backward compatibility: a non-Money field keeps the
    pre-existing raw-string/int-coerce `stored` behaviour even when the
    token happens to look Money-literal-shaped."""

    NAME_SRC = MONEY_SRC.replace("stored product price 100.50USD",
                                 "stored product name 100.50USD")

    def test_a_non_money_field_keeps_the_raw_string(self):
        _payload, stored = payload_and_stored_for(self.NAME_SRC)
        entity_id = next(iter(stored))
        self.assertEqual("100.50USD", stored[entity_id]["name"])


class TestExpectResultMoneyEquality(unittest.TestCase):
    """(정상/에러) `expect result <ref> ==/!= <MoneyLiteral>`."""

    def test_equality_passes_for_the_matching_wire_value(self):
        doc, manifest = build(MONEY_SRC)
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)

    def test_equality_fails_for_a_mismatched_amount(self):
        src = MONEY_SRC.replace("result product.price == 100.50USD",
                                "result product.price == 999.99USD")
        doc, manifest = build(src)
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 1, lines)

    def test_inequality_is_supported(self):
        src = MONEY_SRC.replace("result product.price == 100.50USD",
                                "result product.price != 1.00USD")
        doc, manifest = build(src)
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)

    # (정상) RFC-0051 §3 opens order comparison: the same `money.compare`
    # evaluator a guard uses (100.50 USD < 200.00 USD).
    def test_an_order_comparison_on_a_money_ref_is_evaluated(self):
        src = MONEY_SRC.replace("result product.price == 100.50USD",
                                "result product.price < 200.00USD")
        doc, manifest = build(src)
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2, lines)   # `completed` + the result line


class TestExpectResultMoneyOrder(unittest.TestCase):
    """RFC-0051 §3: `expect result <ref> <order-cmp> <MoneyLiteral>`."""

    def _run(self, clause):
        src = MONEY_SRC.replace("result product.price == 100.50USD",
                                "result " + clause)
        doc, manifest = build(src)
        return run_manifest(manifest, doc)

    # (에러) a false order comparison is a failed case, not a refusal.
    def test_a_false_order_comparison_fails_the_case(self):
        passed, failed, lines = self._run("product.price > 200.00USD")
        self.assertEqual((passed, failed), (1, 1), lines)   # `completed` holds

    # (경계) the stored value itself: <= and >= hold, < and > do not.
    def test_the_boundary_value_is_inclusive_only_for_the_inclusive_comparators(self):
        for clause, want_failed in (("product.price <= 100.50USD", 0),
                                    ("product.price >= 100.50USD", 0),
                                    ("product.price < 100.50USD", 1),
                                    ("product.price > 100.50USD", 1)):
            with self.subTest(clause=clause):
                passed, failed, lines = self._run(clause)
                self.assertEqual(failed, want_failed, lines)

    # (경계) an order comparison against a ref holding no Money value is a
    # RunError naming the ref, not a Python TypeError.
    def test_an_order_comparison_on_an_absent_value_raises(self):
        from lnpl.interp import RunError, _condition_holds
        for actual in (None, "12.00"):
            with self.subTest(actual=actual):
                with self.assertRaises(RunError) as ctx:
                    _condition_holds("product.price < 1.00USD", {},
                                     {"product": {"price": actual}},
                                     money_fields=lambda ref: True)
                self.assertIn("product.price", str(ctx.exception))
                self.assertIn("is not a Money value", str(ctx.exception))

    # (에러) different currencies under an order comparator fail loudly.
    def test_a_cross_currency_order_comparison_raises(self):
        with self.assertRaises(SpecError) as ctx:
            self._run("product.price < 200.00EUR")
        self.assertIn("money-currency-mismatch", str(ctx.exception))


class TestInputFieldMoneySeeding(unittest.TestCase):
    """(경계) `given <field> <value>` (input-field path, `_typed_value`) on
    a Money field."""

    def test_the_input_field_path_seeds_the_wire_dict(self):
        doc, manifest = build(INPUT_MONEY_SRC)
        entity = next(n for n in doc["nodes"] if n["kind"] == "Entity")
        payload, _stored = _payload_from_given(
            manifest["cases"][0]["given"], entity, refinement_index(doc), doc)
        self.assertEqual({"amount": "42.00", "currency": "USD"},
                         payload["total"])

    def test_the_end_to_end_case_passes(self):
        doc, manifest = build(INPUT_MONEY_SRC)
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)


class TestCompileRejectsBadMoneyLiterals(unittest.TestCase):
    """(에러) D2/D5: 자릿수 불일치·exponent 0에 소수점은 컴파일(매니페스트
    단계) 거부, 반올림하지 않는다."""

    def test_too_few_decimal_places_is_refused_at_manifest_time(self):
        src = MONEY_SRC.replace("100.50USD", "100.5USD")
        with self.assertRaises(SpecError):
            build(src)

    def test_exponent_zero_with_a_decimal_point_is_refused(self):
        src = MONEY_SRC.replace("100.50USD", "100.00JPY")
        with self.assertRaises(SpecError):
            build(src)

    def test_a_bad_expect_literal_is_refused_at_manifest_time_too(self):
        src = MONEY_SRC.replace("result product.price == 100.50USD",
                                "result product.price == 100.5USD")
        with self.assertRaises(SpecError):
            build(src)

    def test_an_input_field_bad_literal_is_refused(self):
        src = INPUT_MONEY_SRC.replace("total 42.00USD", "total 42.0USD")
        with self.assertRaises(SpecError):
            build(src)


if __name__ == "__main__":
    unittest.main()
