"""Issue #46 [5]: the QA probes' 3-scenario specs, restored and passing.

The 2026-08-05 production probe (qa/REPORT.md) had to replace the DoD's
normal+error+boundary spec minimum with F-records in three of four cases,
because the runner could not express them (t1 F-7/F-8, t2 F-10/F-11/F-12,
t4 F-4/F-5/F-12). These tests re-author those exact scenarios — the module
bodies are copies of the committed qa/cases fixtures (qa/ is read-only), the
spec blocks are the ones the probes tried and had to abandon — and require
them to run as three independent, all-green cases each.

Two deliberate deviations from the probes' first attempts, both measured:
- t4's `no priorNotification` line is omitted — given's field scope is the
  input entity (F-6), owned by #44/#47, not #46.
- step counts are the OBSERVED executed-step semantics the probes pinned
  (t4 evidence/08 시도 2: "steps 의미론은 관측 확정 — 실행된 스텝 수").
"""

import unittest

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import extract, run_manifest

T1_INVENTORY = """
capability postgres
entity Product
    field
        id UUID
        name Text
        stock Integer
        price Money
entity Order
    field
        id UUID
        quantity PositiveInteger
        status OrderStatus
        placedAt DateTime
refine OrderStatus of Text
    enum created confirmed
event OrderConfirmed on Order create
service OrderService
    policy
        retry 3
        timeout 3s
    performance
        response < 50ms
workflow PlaceOrder
    validate order
    find product
    when product.stock > 0
    create order
    when product.stock > 0
    update product
    spec
        given
            valid order
        when
            place order
        expect
            completed
            steps 4
            rows Order 1
            effects 4
            effects complete
    spec
        given
            empty repository
        when
            place order
        expect
            failed
            attempts 4
    spec
        given
            stored Product stock 0
        when
            place order
        expect
            completed
            rows Order 0
"""

T2_PAYMENT = """
capability postgres
capability jwt
entity Payment
    field
        id UUID
        cardNumber Password
        amount Money
        amountCents Integer
        ageDays Integer
        createdAt DateTime
entity Refund
    field
        id UUID
        paymentId UUID
        amount Money
        amountCents Integer
        requestedAt DateTime
event RefundIssued on Refund create
service PaymentService
    policy
        retry 2
        timeout 3s
    security
        jwt
        encrypt cardNumber
workflow Approval
    validate payment
    find payment
    when payment.amountCents <= 1000000
    update payment
    spec
        given
            valid payment
        when
            approval
        expect
            completed
            steps 3
    spec
        given
            amountCents 1000001
        when
            approval
        expect
            completed
            steps 2
workflow RefundRequest
    validate refund
    find payment
    when payment.ageDays <= 30
    create refund
    spec
        given
            empty repository
        when
            refund request
        expect
            failed
            attempts 3
"""

T4_RATE_NOTIFY = """
capability postgres
entity Measurement
    field
        id UUID
        value Integer
        acknowledged Integer
entity Notification
    field
        id UUID
        priorNotification UUID
        sentAt DateTime
event NotificationSent on Notification create
service RateNotifyService
    policy
        retry 3
        timeout 3s
    performance
        response < 50ms
workflow Report
    validate measurement
    find measurement
    when measurement.value > 100
    create notification
    when priorNotification missing
    emit notificationSent
    until measurement.acknowledged > 0
    read measurement
    spec
        given
            valid measurement
            id 3f2504e0-4f89-41d3-9a0c-0305e82c3301
            value 150
            acknowledged 1
        when
            report
        expect
            completed
            steps 4
            slo met
            rows Notification 1
    spec
        given
            empty repository
        when
            report
        expect
            failed
            attempts 4
    spec
        given
            value 100
            acknowledged 1
        when
            report
        expect
            completed
            rows Notification 0
"""


def run(src, module):
    decls = parse(src)
    doc = lower(decls, module).to_document()
    manifest = extract(decls, module)
    return manifest, run_manifest(manifest, doc)


class TestT4RateNotifyRestored(unittest.TestCase):
    """The probe's only spec-stage FAIL (scorecard spec row = FAIL) — the
    repair's headline: the same three blocks now run and pass."""

    def test_three_blocks_extract_as_three_cases(self):
        manifest, _ = run(T4_RATE_NOTIFY, "rate-notify")
        self.assertEqual([c["name"] for c in manifest["cases"]],
                         ["Report spec 1", "Report spec 2", "Report spec 3"])

    def test_all_scenarios_pass(self):
        _, (passed, failed, lines) = run(T4_RATE_NOTIFY, "rate-notify")
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 8)

    def test_the_boundary_scenario_actually_discriminates(self):
        # value 100 must close the `> 100` guard: flip the boundary given to
        # 101 and the suppression assertion (rows Notification 0) must fail —
        # a boundary spec that passes either way asserts nothing.
        src = T4_RATE_NOTIFY.replace("            value 100",
                                     "            value 101")
        _, (_passed, failed, lines) = run(src, "rate-notify")
        self.assertGreater(failed, 0, lines)
        self.assertTrue(any("Report spec 3" in l and l.startswith("FAIL")
                            for l in lines), lines)


class TestT1InventoryOrderRestored(unittest.TestCase):
    def test_three_blocks_extract_as_three_cases(self):
        manifest, _ = run(T1_INVENTORY, "inventory-order")
        self.assertEqual(len(manifest["cases"]), 3)

    def test_all_scenarios_pass(self):
        # Block 3 is the pair that was impossible: `stored Product stock 0`
        # (declared name, F-8) next to block 2's `empty repository` (F-7's
        # "contradict each other" was the merged-block artifact).
        _, (passed, failed, lines) = run(T1_INVENTORY, "inventory-order")
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 9)


class TestT2PaymentRefundRestored(unittest.TestCase):
    def test_specs_stay_per_workflow(self):
        manifest, _ = run(T2_PAYMENT, "payment-refund")
        self.assertEqual([c["name"] for c in manifest["cases"]],
                         ["Approval spec 1", "Approval spec 2",
                          "RefundRequest spec"])

    def test_all_scenarios_pass(self):
        # The boundary block (amountCents 1000001 alone) is t2 F-11's
        # "inexpressible" case: field-wise merge + Integer coercion make it
        # runnable without any Money literal syntax.
        _, (passed, failed, lines) = run(T2_PAYMENT, "payment-refund")
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 6)


if __name__ == "__main__":
    unittest.main()
