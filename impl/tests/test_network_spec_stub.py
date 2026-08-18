"""Issue #64/#76 / RFC-0027 §7 — `given call <target> returns <status>`, the
spec stub form. Scope is Task 05: `GIVEN_FORMS`/`_check_given` classification,
`_network_stubs_from_given`, and `run_manifest` wiring a per-case
`FakeNetworkDriver` — end to end, success and failure both verified
deterministically through `spec`.
"""

import unittest

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import (GIVEN_FORMS, SpecError, _check_given,
                       _network_stubs_from_given, extract, run_manifest)

CHARGE_CARD_SOURCE = """capability postgres

entity Order
    field
        id UUID
        failureCode Integer

service Checkout
    policy
        timeout 5s

workflow ChargeCard
    find order
    call PaymentGateway as paymentResult
    when paymentResult.status == 200
        update order
    when paymentResult.status != 200
        set order.failureCode to paymentResult.code
    spec
        given
            stored Order id 1
            call PaymentGateway returns 200
        when
            chargeCard
        expect
            completed
            result paymentResult.status == 200

    spec
        given
            stored Order id 1
            call PaymentGateway returns 500 body.code 42
        when
            chargeCard
        expect
            completed
            result paymentResult.status == 500
            result order.failureCode == 42

    spec
        given
            stored Order id 1
        when
            chargeCard
        expect
            completed
            result paymentResult.status == 200
"""


def compile_and_extract(source, module="m"):
    decls = parse(source)
    doc = lower(decls, module).to_document()
    return doc, extract(decls, module)


class GivenFormsClassificationTest(unittest.TestCase):

    def test_the_forms_are_registered(self):
        keys = [k for k, _f, _d in GIVEN_FORMS]
        self.assertIn("network-stub", keys)
        self.assertIn("network-stub-body", keys)

    def test_a_bare_status_stub_classifies(self):
        form, parts = _check_given("call PaymentGateway returns 500", ())
        self.assertEqual(form, "network-stub")
        self.assertEqual(parts, ("PaymentGateway", "500"))

    def test_a_body_field_stub_classifies(self):
        form, parts = _check_given(
            "call PaymentGateway returns 500 body.code 42", ())
        self.assertEqual(form, "network-stub-body")
        self.assertEqual(parts, ("PaymentGateway", "500", "code", "42"))

    def test_a_non_integer_status_is_refused(self):
        with self.assertRaises(SpecError):
            _check_given("call PaymentGateway returns ok", ())

    def test_a_malformed_body_clause_is_refused(self):
        with self.assertRaises(SpecError):
            _check_given("call PaymentGateway returns 500 code 42", ())

    def test_an_empty_body_key_is_refused(self):
        with self.assertRaises(SpecError):
            _check_given("call PaymentGateway returns 500 body. 42", ())

    def test_wrong_token_count_is_refused(self):
        with self.assertRaises(SpecError):
            _check_given("call PaymentGateway returns", ())


class StubTableAssemblyTest(unittest.TestCase):

    def test_a_bare_stub_becomes_status_with_empty_body(self):
        stubs = _network_stubs_from_given(["call PaymentGateway returns 500"])
        self.assertEqual(stubs, {"PaymentGateway": (500, {})})

    def test_a_body_stub_merges_into_the_same_target(self):
        stubs = _network_stubs_from_given([
            "call PaymentGateway returns 500",
            "call PaymentGateway returns 500 body.code 42",
        ])
        self.assertEqual(stubs, {"PaymentGateway": (500, {"code": 42})})

    def test_two_targets_stay_independent(self):
        stubs = _network_stubs_from_given([
            "call PaymentGateway returns 200",
            "call ShippingApi returns 503",
        ])
        self.assertEqual(stubs, {"PaymentGateway": (200, {}),
                                 "ShippingApi": (503, {})})

    def test_no_network_given_lines_is_an_empty_table(self):
        self.assertEqual(_network_stubs_from_given(["stored Order id 1"]), {})


class RunManifestEndToEndTest(unittest.TestCase):
    """DoD: success and failure paths both deterministically verified through
    `given call <target> returns <status>`."""

    def setUp(self):
        self.doc, self.manifest = compile_and_extract(CHARGE_CARD_SOURCE)

    def test_the_success_case_passes(self):
        passed, failed, lines = run_manifest(
            {"spec_version": "0.1", "module": "m",
             "cases": [self.manifest["cases"][0]]}, self.doc)
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2)

    def test_the_5xx_case_passes_and_the_body_field_flows_through_set(self):
        passed, failed, lines = run_manifest(
            {"spec_version": "0.1", "module": "m",
             "cases": [self.manifest["cases"][1]]}, self.doc)
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 3)

    def test_an_unstubbed_target_defaults_to_200(self):
        passed, failed, lines = run_manifest(
            {"spec_version": "0.1", "module": "m",
             "cases": [self.manifest["cases"][2]]}, self.doc)
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2)

    def test_empty_repository_does_not_contradict_a_network_stub(self):
        """Unlike `stored`, a network stub is not repository state — the
        existing `stored`/`empty repository` contradiction check must not
        fire for it (RFC-0027 §7)."""
        from lnpl.spec import _validate_given
        decls = parse(CHARGE_CARD_SOURCE)
        _validate_given(["empty repository", "call PaymentGateway returns 200"],
                        decls, "")  # must not raise


if __name__ == "__main__":
    unittest.main()
