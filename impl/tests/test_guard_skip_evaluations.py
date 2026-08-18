"""Issue #83: a guard skip record carries the values it actually measured.

RFC-0014 §2.4 gave `result["skipped"]` five fields (`guard`, `mode`,
`condition`, `steps`, `rounds`) but none of them says WHAT the condition
compared — only that it was false. This module pins the addition: an
`evaluations` list, one entry per Presence/Comparison term
(`{"ref", "value", "op", "expected", "holds"}`), masked through the same
`mask_payload` chokepoint every other outbound channel uses, and additive only
— the original five keys are unchanged (plan D2).

`entity Order { stock Integer }` / `when stock > 0` is RFC-0014's own example 1
verbatim (Guide-level Explanation) — not a fixture invented to make the feature
look good.
"""

import unittest

from lnpl.differential import _normalise_skips
from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

ORDER_SRC = """
entity Order
    field
        id UUID
        stock Integer
workflow PlaceOrder
    validate order
    when stock > 0
    create order
"""

ORDER_PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "stock": 0}

# A Password-typed field a guard can reference. `find payment` binds the row
# before the guard reads it (same vocabulary as PAYMENT_SRC in
# test_masking_channels.py). The guard condition here is a placeholder — RFC-
# 0016's static check (lower.py `_dimension_of`) refuses ANY guard reference
# to a non-Integer/DateTime field, Presence included, so a Password reference
# cannot compile. `_payment_doc` compiles this valid condition and then
# rewrites the Guard node's `condition` directly on the IR, the same
# post-compile mutation `test_repo_state.py`'s
# `test_a_qualified_presence_guard_derives_the_same_skip_flag` uses — the
# interpreter itself has no such type check (it evaluates whatever condition
# string the IR carries), so this exercises exactly the runtime path D3
# describes without fighting a compile-time refusal that is orthogonal to it.
PAYMENT_SRC = """
capability postgres
entity Payment
    field
        id UUID
        cardNumber Password
        amountCents Integer
service PaymentService
    policy
        retry 0
workflow Approval
    find payment
    when payment.amountCents <= 1000000
    update payment
"""

CARD = "4111111111111111"
PAYMENT_PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
                   "cardNumber": CARD, "amountCents": 500}


def _payment_doc(condition):
    doc = _doc(PAYMENT_SRC, "pay")
    for node in doc["nodes"]:
        if node["kind"] == "Guard":
            node["condition"] = condition
    return doc

# Two Comparison terms under one `and` (RFC-0015), so the collector's `And`
# branch — a second code path `_condition_holds` threads `collector` through —
# is exercised directly rather than only through a single-term guard.
TWO_TERM_SRC = """
entity Order
    field
        id UUID
        stock Integer
        approved Integer
workflow PlaceOrder
    validate order
    when stock > 0 and approved > 0
    create order
"""

TWO_TERM_PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
                    "stock": 0, "approved": 1}


def _doc(src, module):
    return lower(parse(src), module).to_document()


def _run_doc(doc, payload, workflow="wf.place.order", entities=(), shaped=None):
    shaped = shaped or {}
    rows = {e: {row_key(e, payload): dict(shaped.get(e, payload))}
            for e in entities}
    interp = Interpreter(doc, repo_rows=rows)
    result = interp.run_workflow(workflow, dict(payload))
    return interp, result


def _run(src, payload, module="t", workflow="wf.place.order",
        entities=(), shaped=None):
    return _run_doc(_doc(src, module), payload, workflow=workflow,
                    entities=entities, shaped=shaped)


class TestEvaluationsOnAComparisonGuard(unittest.TestCase):
    """RFC-0014 example 1 (`stock = 0`): the skip's `evaluations` names what
    was actually measured, not just that the guard was false."""

    def test_the_skip_record_carries_ref_value_expected_and_holds(self):
        _interp, result = _run(ORDER_SRC, ORDER_PAYLOAD)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["evaluations"],
                         [{"ref": "stock", "value": 0, "op": ">",
                           "expected": 0, "holds": False}])

    def test_the_five_original_keys_are_unchanged(self):
        # Additive only (plan D2): the pre-#83 keys keep their exact values.
        _interp, result = _run(ORDER_SRC, ORDER_PAYLOAD)
        record = result["skipped"][0]
        self.assertEqual(record["guard"], "wf.place.order.guard.1")
        self.assertEqual(record["mode"], "when")
        self.assertEqual(record["condition"], "stock > 0")
        self.assertEqual(record["steps"], ["create order"])
        self.assertIsNone(record["rounds"])

    def test_a_guard_that_holds_has_no_skip_record_at_all(self):
        # Positive control: stock=1 takes the guard, so there is no skip
        # record — and therefore nothing for `evaluations` to be wrong about.
        _interp, result = _run(ORDER_SRC, dict(ORDER_PAYLOAD, stock=1))
        self.assertEqual(result["skipped"], [])


class TestEvaluationsAreMaskedLikeAnyOtherChannel(unittest.TestCase):
    """D3: a `ref` naming a sensitive entity field gets its `value` masked the
    same way `mask_payload` masks a bound row — reusing that chokepoint, not a
    second masking rule."""

    def test_a_sensitive_field_s_measured_value_is_masked(self):
        doc = _payment_doc("payment.cardNumber missing")
        _interp, result = _run_doc(doc, PAYMENT_PAYLOAD, workflow="wf.approval",
                                   entities=("entity.payment",))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["skipped"][0]["evaluations"],
                         [{"ref": "payment.cardNumber", "value": "***",
                           "op": "missing", "expected": None,
                           "holds": False}])

    def test_the_raw_secret_never_reaches_the_evaluations_channel(self):
        doc = _payment_doc("payment.cardNumber missing")
        _interp, result = _run_doc(doc, PAYMENT_PAYLOAD, workflow="wf.approval",
                                   entities=("entity.payment",))
        self.assertNotIn(CARD, repr(result["skipped"]))

    def test_a_non_sensitive_field_on_the_same_entity_stays_verbatim(self):
        # Negative control: masking must not over-apply to every field of an
        # entity that happens to have ONE Password field. PAYMENT_SRC's own
        # (compiled, not rewritten) guard already reads `amountCents`.
        over = dict(PAYMENT_PAYLOAD, amountCents=1000001)
        _interp, result = _run(PAYMENT_SRC, over, module="pay",
                               workflow="wf.approval",
                               entities=("entity.payment",))
        self.assertEqual(result["skipped"][0]["evaluations"],
                         [{"ref": "payment.amountCents", "value": 1000001,
                           "op": "<=", "expected": 1000000, "holds": False}])

    def test_an_input_namespace_reference_is_never_masked(self):
        # D3 boundary: `input.*` names no entity, so it is returned verbatim
        # even when its bare-name twin would resolve to a sensitive field.
        doc = _payment_doc("input.cardNumber missing")
        _interp, result = _run_doc(doc, PAYMENT_PAYLOAD, workflow="wf.approval",
                                   entities=("entity.payment",))
        self.assertEqual(result["skipped"][0]["evaluations"],
                         [{"ref": "input.cardNumber", "value": CARD,
                           "op": "missing", "expected": None,
                           "holds": False}])


class TestEvaluationsOnAnAndCondition(unittest.TestCase):
    """RFC-0015 `and`: `_condition_holds` threads `collector` through its own
    per-term loop, a second code path from the single-Comparison branch."""

    def test_one_entry_per_term_in_declared_order(self):
        _interp, result = _run(TWO_TERM_SRC, TWO_TERM_PAYLOAD)
        self.assertEqual(result["skipped"][0]["evaluations"],
                         [{"ref": "stock", "value": 0, "op": ">",
                           "expected": 0, "holds": False},
                          {"ref": "approved", "value": 1, "op": ">",
                           "expected": 0, "holds": True}])


class TestEvaluationsAreExcludedFromTheDifferentialProjection(unittest.TestCase):
    """Task 02 / plan D2: `evaluations` must never reach the mode A/B
    comparison — `_normalise_skips` is an ALLOW-list, so a record carrying it
    projects exactly as one without it would."""

    def test_normalise_skips_drops_evaluations_the_same_way_it_drops_guard(self):
        with_evals = [{"guard": "wf.w.guard.1", "mode": "when",
                       "condition": "stock > 0", "steps": ["create order"],
                       "rounds": None,
                       "evaluations": [{"ref": "stock", "value": 0, "op": ">",
                                       "expected": 0, "holds": False}]}]
        without_evals = [{"guard": "wf.w.guard.1", "mode": "when",
                          "condition": "stock > 0", "steps": ["create order"],
                          "rounds": None}]
        self.assertEqual(_normalise_skips(with_evals),
                         _normalise_skips(without_evals))
        self.assertNotIn("evaluations", _normalise_skips(with_evals)[0])

    def test_a_real_run_s_skip_record_survives_normalisation_unaffected(self):
        # End to end (still no toolchain needed): a real `_skip_record`
        # carries `evaluations`, and normalising it changes nothing about the
        # projection mode A/B are actually compared on.
        _interp, result = _run(ORDER_SRC, ORDER_PAYLOAD)
        self.assertIn("evaluations", result["skipped"][0])
        self.assertEqual(_normalise_skips(result["skipped"]),
                         [{"mode": "when", "condition": "stock > 0",
                           "step": "create order", "rounds": None}])


if __name__ == "__main__":
    unittest.main()
