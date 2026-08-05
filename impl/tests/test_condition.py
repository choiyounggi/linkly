"""Test guard condition parsing (RFC-0008)."""

import unittest
from impl.lnpl.condition import (
    parse_condition, condition_to_string,
    Presence, Comparison, ConditionError
)


class TestConditionParsing(unittest.TestCase):
    """RFC-0008: condition must be Presence or Comparison; nothing else."""

    # Presence checks
    def test_presence_exists(self):
        c = parse_condition("tokenCache exists")
        self.assertIsInstance(c, Presence)
        self.assertEqual(c.field, "tokenCache")
        self.assertEqual(c.kind, "exists")

    def test_presence_missing(self):
        c = parse_condition("tokenCache missing")
        self.assertIsInstance(c, Presence)
        self.assertEqual(c.field, "tokenCache")
        self.assertEqual(c.kind, "missing")

    # Comparison with integer
    def test_comparison_integer_less_than(self):
        c = parse_condition("retryCount < 3")
        self.assertIsInstance(c, Comparison)
        self.assertEqual(c.field, "retryCount")
        self.assertEqual(c.op, "<")
        self.assertEqual(c.value, 3)
        self.assertFalse(c.is_duration)

    def test_comparison_integer_greater_equal(self):
        c = parse_condition("statusCode >= 500")
        self.assertIsInstance(c, Comparison)
        self.assertEqual(c.op, ">=")
        self.assertEqual(c.value, 500)

    def test_comparison_integer_equal(self):
        c = parse_condition("retryBudget == 0")
        self.assertIsInstance(c, Comparison)
        self.assertEqual(c.op, "==")
        self.assertEqual(c.value, 0)

    def test_comparison_integer_not_equal(self):
        c = parse_condition("retryBudget != 0")
        self.assertIsInstance(c, Comparison)
        self.assertEqual(c.op, "!=")

    # Comparison with Duration
    def test_comparison_duration_ms(self):
        c = parse_condition("timeoutMs > 5000ms")
        self.assertIsInstance(c, Comparison)
        self.assertEqual(c.value, 5000)
        self.assertTrue(c.is_duration)

    def test_comparison_duration_seconds(self):
        c = parse_condition("elapsedTime < 30s")
        self.assertIsInstance(c, Comparison)
        self.assertEqual(c.value, 30000)  # converted to ms
        self.assertTrue(c.is_duration)

    def test_comparison_duration_minutes(self):
        c = parse_condition("totalRuntime <= 5m")
        self.assertIsInstance(c, Comparison)
        self.assertEqual(c.value, 300000)  # 5 * 60 * 1000
        self.assertTrue(c.is_duration)

    # Round-trip: parse -> to_string -> parse
    def test_roundtrip_presence(self):
        orig = "tokenCache missing"
        c = parse_condition(orig)
        back = condition_to_string(c)
        self.assertEqual(parse_condition(back), c)

    def test_roundtrip_comparison_integer(self):
        orig = "retryCount < 3"
        c = parse_condition(orig)
        back = condition_to_string(c)
        c2 = parse_condition(back)
        self.assertEqual(c2.field, c.field)
        self.assertEqual(c2.op, c.op)
        self.assertEqual(c2.value, c.value)

    def test_roundtrip_comparison_duration(self):
        orig = "timeout > 10s"
        c = parse_condition(orig)
        back = condition_to_string(c)
        c2 = parse_condition(back)
        self.assertEqual(c2.value, 10000)

    # None / empty
    def test_none_condition(self):
        self.assertIsNone(parse_condition(None))

    def test_empty_condition(self):
        self.assertIsNone(parse_condition(""))
        self.assertIsNone(parse_condition("   "))

    # Error cases: invalid forms (RFC-0002 OQ2 deferred)
    def test_rejects_freeform_words(self):
        with self.assertRaises(ConditionError):
            parse_condition("word word word")  # Old: `Word Word? Word? Word?`

    def test_rejects_and_or_not(self):
        with self.assertRaises(ConditionError):
            parse_condition("a and b")

    def test_rejects_membership(self):
        with self.assertRaises(ConditionError):
            parse_condition("field in [1, 2, 3]")

    def test_rejects_invalid_comparator(self):
        with self.assertRaises(ConditionError):
            parse_condition("count <> 5")  # not a valid op

    def test_rejects_non_camelcase_field(self):
        with self.assertRaises(ConditionError):
            parse_condition("TokenCache exists")  # PascalCase, not camelCase

    def test_rejects_too_many_tokens(self):
        with self.assertRaises(ConditionError):
            parse_condition("retryCount < 3 extra")

    def test_rejects_empty_field(self):
        with self.assertRaises(ConditionError):
            parse_condition(" exists")

    def test_rejects_invalid_duration_unit(self):
        with self.assertRaises(ConditionError):
            parse_condition("timeout > 10x")  # 'x' is not ms|s|m


class TestScopedReference(unittest.TestCase):
    """RFC-0012 §Full grammar: `Reference ::= CamelName | CamelName '.' CamelName`.

    A qualified reference names a bound row's field (`product.stock`) rather than
    an input payload field. `condition.py` owns the SYNTAX only — whether the
    entity exists and declares the field is `lower.py`'s judgement (RFC-0012
    §G12.5), because this module never sees the document.
    """

    def test_qualified_comparison_keeps_the_whole_reference_as_the_field(self):
        c = parse_condition("product.stock > 0")
        self.assertIsInstance(c, Comparison)
        self.assertEqual(c.field, "product.stock")
        self.assertEqual(c.op, ">")
        self.assertEqual(c.value, 0)
        self.assertFalse(c.is_duration)

    def test_qualified_presence(self):
        c = parse_condition("product.name exists")
        self.assertIsInstance(c, Presence)
        self.assertEqual(c.field, "product.name")
        self.assertEqual(c.kind, "exists")

    def test_qualified_binding_may_be_multiword_camelcase(self):
        # `OrderItem` -> binding `orderItem` (RFC-0012 G12.2 derives the binding
        # name from the declared name, so it can carry inner capitals).
        c = parse_condition("orderItem.unitPrice >= 100")
        self.assertEqual(c.field, "orderItem.unitPrice")

    def test_roundtrip_qualified_comparison(self):
        self.assertEqual(condition_to_string(parse_condition("product.stock >= 10")),
                         "product.stock >= 10")

    def test_roundtrip_qualified_presence(self):
        self.assertEqual(condition_to_string(parse_condition("product.name missing")),
                         "product.name missing")

    def test_qualified_duration_still_normalizes(self):
        # The duration path is orthogonal to the reference form; a qualified
        # reference must not lose it.
        c = parse_condition("session.ttl < 5s")
        self.assertTrue(c.is_duration)
        self.assertEqual(c.value, 5000)
        self.assertEqual(condition_to_string(c), "session.ttl < 5s")

    # ---- error cases -------------------------------------------------------
    def test_rejects_pascalcase_binding(self):
        # The binding name is camelCase (RFC-0012 G12.2), not the declared
        # PascalCase entity name.
        with self.assertRaises(ConditionError):
            parse_condition("Product.stock > 0")

    def test_rejects_pascalcase_field_segment(self):
        with self.assertRaises(ConditionError):
            parse_condition("product.Stock > 0")

    def test_rejects_three_segment_path(self):
        # RFC-0012 rejects paths of 3+ segments: a bound row is flat, so there is
        # nothing for a nested walk to evaluate.
        with self.assertRaises(ConditionError):
            parse_condition("a.b.c > 0")

    # ---- boundary cases ----------------------------------------------------
    def test_rejects_empty_binding_segment(self):
        with self.assertRaises(ConditionError):
            parse_condition(".stock > 0")

    def test_rejects_empty_field_segment(self):
        with self.assertRaises(ConditionError):
            parse_condition("product. > 0")

    def test_rejects_bare_dot(self):
        with self.assertRaises(ConditionError):
            parse_condition(". exists")

    def test_bare_reference_is_unchanged(self):
        # Control (RFC-0012 G12.3): widening the grammar must not move the
        # existing form. If this breaks, every guard written before RFC-0012
        # changed meaning.
        c = parse_condition("stock > 0")
        self.assertEqual(c.field, "stock")
        self.assertEqual(condition_to_string(c), "stock > 0")


class TestModeARefusesUnevaluableConditions(unittest.TestCase):
    """Issue #3's acceptance bullet: mode A must refuse what it cannot evaluate.

    The parser rejects these forms, so a document built through `parse` can never
    carry one — which is exactly why the refusal inside the interpreter needs its
    own test. `Guard.condition` is a plain string in the IR, so an agent or a
    hand-written `.lir.json` can still put an unevaluable condition there, and
    treating it as true would silently turn a declared guard into a no-op. That
    is the outcome RFC-0008 argued against.

    Before this test the corresponding mutation in `mutation_check.py` — return
    True instead of raising — survived, because nothing reached the branch.
    """

    def _holds(self, condition, payload=None, bindings=None):
        from impl.lnpl.interp import _condition_holds
        return _condition_holds(condition, payload or {}, bindings or {})

    def test_an_unknown_comparator_is_refused(self):
        from impl.lnpl.interp import RunError
        with self.assertRaises(RunError) as ctx:
            self._holds("latency exceeds budget")
        self.assertIn("Invalid condition", str(ctx.exception))

    def test_a_bare_word_is_refused(self):
        from impl.lnpl.interp import RunError
        with self.assertRaises(RunError):
            self._holds("token")

    def test_a_four_token_phrase_is_refused(self):
        """The production RFC-0008 removed — no evaluator ever implemented it."""
        from impl.lnpl.interp import RunError
        with self.assertRaises(RunError):
            self._holds("foo bar baz qux")

    def test_an_evaluable_condition_still_evaluates(self):
        """Control: refusal must be about the form, not about refusing broadly."""
        self.assertTrue(self._holds("token missing", {}))
        self.assertFalse(self._holds("token missing", {"token": "abc"}))

    def test_no_condition_holds_vacuously(self):
        """Boundary: an unguarded step is not a refusal."""
        self.assertTrue(self._holds(None))


if __name__ == '__main__':
    unittest.main()
