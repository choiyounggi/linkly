"""Issue #43: masking must hold on EVERY output channel, not just the trace.

QA case t2 (qa/cases/payment-refund, F-7/F-8/F-9) measured the leak: the trace
channel masks Password-typed values (`***`) while `result["bindings"]` returns
them verbatim, the OpenAPI contract promises `writeOnly`, and the differential's
masking class never looks at the leaking channel. These tests promote that
reproduction to regressions using inline fixtures whose vocabulary is taken
verbatim from the QA case (closed vocabulary — nothing invented). All secret
values are synthetic (4111111111111111 is the canonical test PAN; s3cret-value
is the registry's own Password sample).
"""

import json
import unittest
from unittest import mock

from lnpl.differential import compare_observations, observe_mode_a
from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.openapi import generate
from lnpl.parser import parse
from lnpl.repo_policy import row_key

# Vocabulary reused from qa/cases/payment-refund/payment-refund.lnpl (read-only
# original): validate/find/update verbs, `when` guard on a read row's field.
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
    validate payment
    find payment
    when payment.amountCents <= 1000000
    update payment
"""

CARD = "4111111111111111"
PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
           "cardNumber": CARD, "amountCents": 500}

# Two entities, each carrying its own Password-based field, no validate step so
# a boundary (empty-string) secret can reach the repository row.
TWO_ENTITY_SRC = """
capability postgres
entity Payment
    field
        id UUID
        cardNumber Password
        amountCents Integer
entity Refund
    field
        id UUID
        cardToken Password
service PaymentService
    policy
        retry 0
workflow Approval
    find payment
    find refund
    update payment
"""

REFUND_ROW = {"id": PAYLOAD["id"], "cardToken": "s3cret-tok"}

# No read anywhere: nothing can bind, the bindings channel must be empty.
NO_READ_SRC = """
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
    validate payment
    update payment
"""


def _doc(src):
    return lower(parse(src), "pay").to_document()


def _rows(payload, entities=("entity.payment",), shaped=None):
    """Seed one row per entity, keyed the way the interpreter reads it."""
    shaped = shaped or {}
    return {e: {row_key(e, payload): dict(shaped.get(e, payload))}
            for e in entities}


def _run(src, payload, entities=("entity.payment",), shaped=None):
    doc = _doc(src)
    interp = Interpreter(doc, repo_rows=_rows(payload, entities, shaped))
    result = interp.run_workflow("wf.approval", dict(payload))
    return interp, result


class TestResultBindingsMasking(unittest.TestCase):
    """F-7: the result channel must mask exactly what the trace channel masks."""

    def test_password_binding_is_masked_in_the_result(self):
        _interp, result = self._completed_run()
        self.assertEqual(result["bindings"]["payment"]["cardNumber"], "***")
        # Negative control (evidence/04 D5(b)): a non-sensitive field of the
        # same row stays verbatim — masking must not over-apply.
        self.assertEqual(result["bindings"]["payment"]["amountCents"], 500)

    def test_no_raw_secret_in_the_full_json_dump(self):
        # The exact surface `lnpl run --json` prints (cli.py): result + trace.
        interp, result = self._completed_run()
        dump = json.dumps({"result": result, "trace": interp.trace.to_dict()},
                          default=repr)
        self.assertNotIn(CARD, dump)
        self.assertIn("***", dump)

    def test_guard_semantics_are_unchanged_and_bindings_stay_masked(self):
        # amountCents over the limit: the guard still skips its item exactly as
        # before (skip semantics are #44's, untouched here) and the masked copy
        # still covers the bound row.
        over = dict(PAYLOAD, amountCents=1000001)
        _interp, result = _run(PAYMENT_SRC, over)
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("update payment", [s["step"] for s in result["steps"]])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["bindings"]["payment"]["cardNumber"], "***")

    def test_an_empty_password_value_is_still_masked(self):
        # Boundary: an empty secret is still a secret-typed field; the masked
        # copy must not depend on the value's truthiness.
        empty = dict(PAYLOAD, cardNumber="")
        _interp, result = _run(TWO_ENTITY_SRC, empty,
                               entities=("entity.payment", "entity.refund"),
                               shaped={"entity.refund": REFUND_ROW})
        self.assertEqual(result["bindings"]["payment"]["cardNumber"], "***")

    def test_a_second_entity_binding_is_masked_too(self):
        # The per-entity view: each binding is masked by ITS entity's fields,
        # not just the document's first entity (the trace channel's pre-existing
        # first-entity limitation must not leak into this channel).
        _interp, result = _run(TWO_ENTITY_SRC, PAYLOAD,
                               entities=("entity.payment", "entity.refund"),
                               shaped={"entity.refund": REFUND_ROW})
        self.assertEqual(result["bindings"]["refund"]["cardToken"], "***")
        self.assertEqual(result["bindings"]["refund"]["id"], PAYLOAD["id"])
        self.assertEqual(result["bindings"]["payment"]["cardNumber"], "***")

    def test_a_workflow_without_reads_has_empty_bindings(self):
        # Boundary: nothing read, nothing bound, nothing to mask.
        _interp, result = _run(NO_READ_SRC, PAYLOAD)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"], {})

    def _completed_run(self):
        interp, result = _run(PAYMENT_SRC, PAYLOAD)
        self.assertEqual(result["status"], "completed")
        return interp, result


# The registry's own Password sample — it matches SECRET_MARKERS ("s3cret"), so
# the differential's masking scan can see it if any channel leaks it.
MARKED_PAYLOAD = {"id": PAYLOAD["id"], "cardNumber": "s3cret-value",
                  "amountCents": 500}


def _observe_a(payload=None):
    doc = _doc(PAYMENT_SRC)
    p = dict(MARKED_PAYLOAD if payload is None else payload)
    return observe_mode_a(doc, "wf.approval", p,
                          _rows(p, entities=("entity.payment",)))


def _b_double(a):
    """A mode B observation stub (what-to-mock: stub the query side).

    Copies the classes mode B genuinely agrees on and carries mode B's real
    output shape for the masking surface: the binary emits only
    step/effect/status lines — it has no bindings channel.
    """
    return {"order": list(a["order"]), "effects": dict(a["effects"]),
            "status": a["status"],
            "text": "\n".join(["step 1 %s" % s for s in a["order"]]
                              + ["status %s" % a["status"]])}


class TestDifferentialMaskingSurface(unittest.TestCase):
    """F-9: masking PASS must mean every output channel was scanned."""

    def test_mode_a_observation_carries_the_masked_bindings_channel(self):
        a = _observe_a()
        self.assertIn("binding payment", a["text"])
        self.assertIn("***", a["text"])
        self.assertNotIn("s3cret", a["text"])
        self.assertEqual(a["bindings"]["payment"]["cardNumber"], "***")

    def test_a_masked_run_still_compares_equivalent(self):
        # Positive control (harness-reverse-controls): the widened surface must
        # not turn every honest run red.
        a = _observe_a()
        ok, report = compare_observations(a, _b_double(a))
        self.assertTrue(ok, "\n".join(report))
        for cls in ("PASS 1/4", "PASS 2/4", "PASS 3/4", "PASS 4/4"):
            self.assertTrue(any(cls in line for line in report), cls)
        self.assertIn("EQUIVALENT", report[-1])

    def test_a_leaked_binding_marker_fails_the_masking_class(self):
        # Negative control, unit level: a doctored observation whose bindings
        # line carries the raw secret must flip exactly the masking class.
        a = _observe_a()
        doctored = dict(a, text=a["text"]
                        + '\nbinding payment {"cardNumber": "s3cret-value"}')
        ok, report = compare_observations(doctored, _b_double(a))
        self.assertFalse(ok)
        self.assertTrue(any("FAIL 4/4" in line for line in report))
        self.assertIn("DIVERGENT", report[-1])

    def test_an_unmasked_runtime_channel_is_detected_end_to_end(self):
        # Negative control, end to end: switch masking off via fixture patch
        # (NOT by weakening the implementation) and require the real
        # observe_mode_a -> compare path to go red on its own.
        clean_b = _b_double(_observe_a())
        with mock.patch("lnpl.interp.MASKED_TYPES", ()):
            leaked = _observe_a()
        self.assertIn("s3cret", leaked["text"])
        ok, report = compare_observations(leaked, clean_b)
        self.assertFalse(ok)
        self.assertTrue(any("FAIL 4/4" in line for line in report))

    def test_empty_bindings_add_no_lines_and_stay_equivalent(self):
        # Boundary: a workflow that binds nothing must not grow the surface.
        doc = _doc(NO_READ_SRC)
        a = observe_mode_a(doc, "wf.approval", dict(PAYLOAD),
                           _rows(PAYLOAD, entities=("entity.payment",)))
        self.assertNotIn("binding ", a["text"])
        ok, report = compare_observations(a, _b_double(a))
        self.assertTrue(ok, "\n".join(report))
        self.assertTrue(any("PASS 4/4" in line for line in report))


def _write_only_names(node, out=None):
    """Every property name whose schema says `writeOnly: true`, recursively."""
    if out is None:
        out = set()
    if isinstance(node, dict):
        for props in [node["properties"]] if isinstance(
                node.get("properties"), dict) else []:
            for name, schema in props.items():
                if isinstance(schema, dict) and schema.get("writeOnly") is True:
                    out.add(name)
        for value in node.values():
            _write_only_names(value, out)
    elif isinstance(node, list):
        for item in node:
            _write_only_names(item, out)
    return out


class TestOpenApiWriteOnlyAlignment(unittest.TestCase):
    """F-8: the document may not promise more safety than the runtime delivers.

    `writeOnly: true` says the value never appears in a response; these tests
    pin the generated contract to the actual run output so the two cannot
    drift apart again.
    """

    def test_the_contract_names_the_masked_field(self):
        # Guards vacuity (tests-that-cannot-fail): if the generator ever stops
        # emitting writeOnly, the alignment test below would pass over an empty
        # set — this one goes red instead.
        collected = _write_only_names(generate(_doc(PAYMENT_SRC)))
        self.assertIn("cardNumber", collected)

    def test_write_only_fields_never_appear_raw_in_the_run_output(self):
        collected = _write_only_names(generate(_doc(PAYMENT_SRC)))
        interp, result = _run(PAYMENT_SRC, PAYLOAD)
        dump = json.dumps({"result": result, "trace": interp.trace.to_dict()},
                          default=repr)
        self.assertTrue(collected)
        for name in collected:
            self.assertNotIn(PAYLOAD[name], dump,
                             "writeOnly field %r reached the output" % name)

    def test_fields_the_contract_exposes_stay_verbatim(self):
        # Boundary/negative control: alignment must not over-mask what the
        # contract deliberately leaves readable.
        collected = _write_only_names(generate(_doc(PAYMENT_SRC)))
        self.assertNotIn("amountCents", collected)
        interp, result = _run(PAYMENT_SRC, PAYLOAD)
        dump = json.dumps({"result": result, "trace": interp.trace.to_dict()},
                          default=repr)
        self.assertIn('"amountCents": 500', dump)


if __name__ == "__main__":
    unittest.main()
