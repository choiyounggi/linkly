"""Issue #46 [5]: the QA probes' 3-scenario specs, restored and passing.

The 2026-08-05 production probe (qa/REPORT.md) had to replace the DoD's
normal+error+boundary spec minimum with F-records in three of four cases,
because the runner could not express them (t1 F-7/F-8, t2 F-10/F-11/F-12,
t4 F-4/F-5/F-12). These tests re-author those exact scenarios — the module
bodies are copies of the committed qa/cases fixtures (qa/ is read-only), the
spec blocks are the ones the probes tried and had to abandon — and require
them to run as three independent, all-green cases each.

Deliberate deviations from the probes' first attempts, measured:
- step counts are the OBSERVED executed-step semantics the probes pinned
  (t4 evidence/08 시도 2: "steps 의미론은 관측 확정 — 실행된 스텝 수").
- issue #127 (RFC-0035 §D3): t2's `security` block dropped `encrypt
  cardNumber`. `encrypt` is no longer in the vocabulary at all, so the
  line cannot compile; qa/'s own `payment-refund.lnpl` is read-only and
  keeps it (a historical record), but this file's subject is the
  3-scenario spec restoration, not `encrypt` itself, so the line is
  dropped rather than migrated — `security jwt` alone still demonstrates
  the same "an unenforced declaration compiles cleanly" property.

Issue #54 closed the other one. This file used to say:

    t4's `no priorNotification` line is omitted — given's field scope is the
    input entity (F-6), owned by #44/#47, not #46.

That scope was the first declared entity, not "the input entity", and it also
blocked r1 N-4 (an input-field boundary spec) and r2 N-2 (a read-row guard that
could not be made true). The line is restored below as `no input.priorNotification`,
and the two re-measurement reproductions are pinned here alongside it.
"""

import unittest

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import SpecError, extract, run_manifest

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
    spec
        given
            input.quantity 0
        when
            place order
        expect
            failed
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
            no input.priorNotification
        when
            report
        expect
            completed
            rows Notification 0
"""


# r2 N-2, from the 2026-08-07 re-measurement (qa/rerun/cases/payment-refund,
# read-only — the module body is copied inline). The guard reads a stored row on
# one side and the input on the other, so contracting its TRUE path needs both
# axes. `%s` is the requested-at instant and `%d` the executed-step count the
# case expects, so one template gives both directions of the guard.
R2_REFUND_GUARD = """
capability postgres
entity Payment
    field
        id UUID
        amountCents Integer
        createdAt DateTime
entity Refund
    field
        id UUID
        paymentId UUID
        amountCents Integer
        requestedAt DateTime
workflow RefundRequest
    read payment
    when input.requestedAt - payment.createdAt <= 30d and input.amountCents <= payment.amountCents
    create refund
    spec
        given
            stored payment id 3f2504e0-4f89-41d3-9a0c-0305e82c3301
            stored payment amountCents 5
            stored payment createdAt 2026-07-31T09:00:00Z
            input.amountCents 3
            input.requestedAt %s
        when
            refund request
        expect
            completed
            steps %d
"""

INSIDE_WINDOW = "2026-08-01T09:00:00Z"     # +1d  — guard true
OUTSIDE_WINDOW = "2026-10-31T09:00:00Z"    # +92d — guard false


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
    def test_every_block_extracts_as_its_own_case(self):
        manifest, _ = run(T1_INVENTORY, "inventory-order")
        self.assertEqual(len(manifest["cases"]), 4)

    def test_all_scenarios_pass(self):
        # Block 3 is the pair that was impossible: `stored Product stock 0`
        # (declared name, F-8) next to block 2's `empty repository` (F-7's
        # "contradict each other" was the merged-block artifact).
        _, (passed, failed, lines) = run(T1_INVENTORY, "inventory-order")
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 11)


class TestR1N4InputBoundarySpec(unittest.TestCase):
    """r1 N-4: the qty=0 boundary, back inside the language.

    The re-measurement had to push this one out to a runtime probe — `given
    quantity 0` was refused because `quantity` belongs to Order, the SECOND
    declared entity. Block 4 of T1_INVENTORY now expresses it as
    `input.quantity 0`, and the declared type is what rejects it: quantity is a
    PositiveInteger, so 0 fails validation rather than ordering nothing.
    """

    def test_the_boundary_block_runs_and_passes(self):
        _, (_passed, failed, lines) = run(T1_INVENTORY, "inventory-order")
        self.assertEqual(failed, 0, lines)
        self.assertTrue(any("PlaceOrder spec 4" in l and l.startswith("PASS")
                            for l in lines), lines)

    def test_zero_is_what_makes_it_fail_not_the_form(self):
        # The discriminating control: a quantity the type accepts must take the
        # same block to `completed`, so the FAIL above is the boundary talking
        # and not `input.quantity` being broken in general.
        src = T1_INVENTORY.replace("            input.quantity 0",
                                   "            input.quantity 1")
        _, (_passed, failed, lines) = run(src, "inventory-order")
        self.assertGreater(failed, 0, lines)
        self.assertTrue(any("PlaceOrder spec 4" in l and "failed" in l
                            and l.startswith("FAIL") for l in lines), lines)

    def test_the_pre_54_spelling_is_now_accepted_too(self):
        # RFC-0015 §G15.2 keeps the bare name a synonym; the probe's original
        # line must work as written.
        src = T1_INVENTORY.replace("            input.quantity 0",
                                   "            quantity 0")
        _, (_passed, failed, lines) = run(src, "inventory-order")
        self.assertEqual(failed, 0, lines)


class TestR2N2GuardTrueContract(unittest.TestCase):
    """r2 N-2: the read-row guard's TRUE path, contracted in the language.

    The re-measurement spent three retries here and settled for recording rc=1:
    `stored` seeded the row correctly, but the guard's other operand
    (`input.requestedAt`) lived on the second entity and had no given form. Both
    directions run here — a guard is only contracted when each side has been
    executed, and the assertion is on the executed-step count.
    """

    def test_the_guard_true_path_executes_the_guarded_step(self):
        _, (passed, failed, lines) = run(
            R2_REFUND_GUARD % (INSIDE_WINDOW, 2), "payment-refund")
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2)

    def test_the_guard_false_path_skips_it(self):
        _, (passed, failed, lines) = run(
            R2_REFUND_GUARD % (OUTSIDE_WINDOW, 1), "payment-refund")
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2)

    def test_the_two_directions_are_distinguishable(self):
        # Without this the pair above could both pass on a runner that ignored
        # the guard: expecting the guard-true step count on the guard-false
        # module must FAIL.
        _, (_passed, failed, lines) = run(
            R2_REFUND_GUARD % (OUTSIDE_WINDOW, 2), "payment-refund")
        self.assertEqual(failed, 1, lines)
        self.assertTrue(any("steps=1 want=2" in l for l in lines), lines)


class TestR4F6NoScope(unittest.TestCase):
    """r4 F-6: `no <field>` reaches a field outside the first entity.

    The line the probe had to delete is back in T4_RATE_NOTIFY's boundary block.
    `priorNotification` is a Notification field and the default payload never
    carried it, so the given asserts an absence the Presence guard depends on.
    """

    def test_the_restored_line_is_in_the_fixture(self):
        self.assertIn("no input.priorNotification", T4_RATE_NOTIFY)

    def test_the_scenario_still_passes_with_it(self):
        _, (passed, failed, lines) = run(T4_RATE_NOTIFY, "rate-notify")
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 8)

    def test_asserting_the_absence_does_not_change_the_outcome(self):
        # The point of the form here is documentation, not mutation: the field
        # was already absent, so removing the line must give the same result.
        without = T4_RATE_NOTIFY.replace(
            "\n            no input.priorNotification", "")
        _, (with_passed, with_failed, _l) = run(T4_RATE_NOTIFY, "rate-notify")
        _, (no_passed, no_failed, _l2) = run(without, "rate-notify")
        self.assertEqual((with_passed, with_failed), (no_passed, no_failed))

    def test_an_undeclared_name_is_still_refused(self):
        # The widening is to the declared union, not to anything at all.
        src = T4_RATE_NOTIFY.replace("no input.priorNotification",
                                     "no input.nosuchfield")
        with self.assertRaises(SpecError):
            run(src, "rate-notify")


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
