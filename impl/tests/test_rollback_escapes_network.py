"""`rollback-escapes-network` (warning) — issue #112.

RFC-0032 opens one transaction per `run_workflow` execution and rolls it back
on any failure, but that transaction only owns the writes (and outbox
registrations) the run made — a `NetworkCall` step (`call`/`request`) is
outside it. A service that declares `policy rollback` reads as "this undoes
itself on failure"; a workflow it owns with a `call`/`request` step in it
makes that a lie the compiler used to say nothing about. This diagnostic
closes that silence, the one place linkly's "declaration and enforcement
diverge, the machine says so" principle was still broken (RFC-0032 covers
repository writes only).

Issue #112's own binary judgement 2 is the negative control: a `NetworkCall`
with **no** `policy rollback` in scope must report zero diagnostics — without
that case this check is indistinguishable from one that always fires.
"""
import contextlib
import io
import os
import shutil
import tempfile
import unittest

from lnpl import cli
from lnpl.diagnostics import CODES, SEVERITY_OF, SEVERITIES
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_ROOT = os.path.join(REPO, ".claude", "tmp")

CODE = "rollback-escapes-network"

# Normal case: `policy rollback` on the owning service, one `call` step in
# the workflow it owns.
ONE_CALL_WITH_ROLLBACK = """entity Order
    field
        id UUID

service Checkout
    policy
        rollback

workflow Pay
    call PaymentGateway
"""

# Negative control 1 (issue #112 judgement 2): the service has a `policy`
# block, just not `rollback` — the check has to key on the specific rule
# name, not on "any policy at all".
CALL_WITHOUT_ROLLBACK = """entity Order
    field
        id UUID

service Checkout
    policy
        retry 3
        timeout 3s

workflow Pay
    call PaymentGateway
"""

# Negative control 2: `policy rollback` is declared, but the workflow it
# owns has no `NetworkCall` step at all — nothing escapes because nothing
# left the boundary.
ROLLBACK_WITHOUT_CALL = """entity Order
    field
        id UUID

service Checkout
    policy
        rollback

workflow Pay
    create order
"""

# D6: two `NetworkCall` steps under one rollback-declaring service -> one
# diagnostic per step, each naming its own line.
TWO_CALLS_WITH_ROLLBACK = """entity Order
    field
        id UUID

service Checkout
    policy
        rollback

workflow Pay
    call PaymentGateway
    call ShippingService
"""

# Boundary: a workflow with no preceding `service` declaration at all has no
# owner, so there is no `policy rollback` claim to contradict — 0
# diagnostics, no exception, even though the `call` step is right there.
CALL_WITH_NO_OWNING_SERVICE = """entity Order
    field
        id UUID

workflow Pay
    call PaymentGateway
"""


def diagnose(source, code, name="probe"):
    """`source`'s diagnostics for `code` — the compiler decides, not the test."""
    module = lower(parse(source), name)
    return list(module.diagnostics.by_code(code))


def run_cli_split(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class TheCodeIsRegistered(unittest.TestCase):

    def test_code_exists(self):
        self.assertIn(CODE, CODES)

    def test_it_is_a_warning(self):
        # RFC-0021: editing the program removes it (move the call out of the
        # rollback-declaring service's workflow, or drop the policy) ->
        # warning, same test as `unknown-verb`/`derived-never-assigned`.
        self.assertEqual(SEVERITY_OF[CODE], "warning")

    def test_warning_outranks_info_on_the_strict_ladder(self):
        self.assertGreater(SEVERITIES.index("warning"), SEVERITIES.index("info"))


class NormalCaseFiresOnce(unittest.TestCase):
    """One `call` under a rollback-declaring service -> exactly one diagnostic."""

    def test_it_fires_exactly_once(self):
        found = diagnose(ONE_CALL_WITH_ROLLBACK, CODE)
        self.assertEqual(len(found), 1, [d.subject for d in found])

    def test_it_is_graded_warning(self):
        found = diagnose(ONE_CALL_WITH_ROLLBACK, CODE)[0]
        self.assertEqual(found.severity, "warning")

    def test_it_names_the_call_line(self):
        found = diagnose(ONE_CALL_WITH_ROLLBACK, CODE)[0]
        # `call PaymentGateway` is line 10 of ONE_CALL_WITH_ROLLBACK.
        self.assertEqual(found.line, 10)
        self.assertEqual(found.where, "line 10")

    def test_message_names_the_workflow_and_the_step(self):
        found = diagnose(ONE_CALL_WITH_ROLLBACK, CODE)[0]
        self.assertIn("Pay", found.message)
        self.assertIn("policy rollback", found.message)
        self.assertIn("call PaymentGateway", found.message)
        self.assertIn("PaymentGateway", found.subject)


class NegativeControlNoRollbackReportsNothing(unittest.TestCase):
    """DoD / issue #112 judgement 2: `call` without `policy rollback` -> 0."""

    def test_zero_diagnostics(self):
        self.assertEqual(diagnose(CALL_WITHOUT_ROLLBACK, CODE), [])


class NegativeControlNoCallReportsNothing(unittest.TestCase):
    """`policy rollback` with no `NetworkCall` step in its workflow -> 0."""

    def test_zero_diagnostics(self):
        self.assertEqual(diagnose(ROLLBACK_WITHOUT_CALL, CODE), [])


class TwoCallsFireTwoDiagnostics(unittest.TestCase):
    """D6: each `NetworkCall` step under rollback gets its own diagnostic."""

    def test_two_diagnostics(self):
        found = diagnose(TWO_CALLS_WITH_ROLLBACK, CODE)
        self.assertEqual(len(found), 2, [d.subject for d in found])

    def test_they_name_different_lines(self):
        found = diagnose(TWO_CALLS_WITH_ROLLBACK, CODE)
        lines = sorted(d.line for d in found)
        self.assertEqual(len(set(lines)), 2, lines)
        # `call PaymentGateway` / `call ShippingService` are lines 10 and 11.
        self.assertEqual(lines, [10, 11])

    def test_they_name_different_subjects(self):
        found = diagnose(TWO_CALLS_WITH_ROLLBACK, CODE)
        subjects = sorted(d.subject for d in found)
        self.assertEqual(subjects, ["call PaymentGateway", "call ShippingService"])


class NoOwningServiceReportsNothing(unittest.TestCase):
    """Boundary: a workflow nothing declares `service` for has no owner —
    no `policy` exists to contradict, so this must stay silent, not raise."""

    def test_zero_diagnostics(self):
        self.assertEqual(diagnose(CALL_WITH_NO_OWNING_SERVICE, CODE), [])

    def test_no_exception_is_raised(self):
        # Redundant with the assertion above succeeding at all (an exception
        # would fail the test before the assertEqual runs), but states the
        # boundary's actual risk explicitly: `owner_of.get(...)` returning
        # `None` must not raise when indexed into `rollback_services`.
        try:
            diagnose(CALL_WITH_NO_OWNING_SERVICE, CODE)
        except Exception as exc:  # pragma: no cover - assertion is the point
            self.fail("diagnosing an unowned workflow raised %r" % exc)


class TestStrictWarningGate(unittest.TestCase):
    """`--strict=warning` gates on this diagnostic (rc 2); bare compile does not."""

    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.tmpdir = tempfile.mkdtemp(dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.repro = os.path.join(self.tmpdir, "t112_repro.lnpl")
        with open(self.repro, "w", encoding="utf-8") as fh:
            fh.write(ONE_CALL_WITH_ROLLBACK)
        self.clean = os.path.join(self.tmpdir, "t112_clean.lnpl")
        with open(self.clean, "w", encoding="utf-8") as fh:
            fh.write(CALL_WITHOUT_ROLLBACK)

    def test_strict_warning_fails_with_rc_2(self):
        rc, _, err = run_cli_split(["compile", self.repro, "--strict=warning"])
        self.assertEqual(rc, 2, err)
        self.assertIn(CODE, err)

    def test_without_strict_it_still_compiles_rc_0(self):
        rc, _, err = run_cli_split(["compile", self.repro])
        self.assertEqual(rc, 0, err)
        self.assertIn(CODE, err)

    def test_the_negative_control_file_never_fails_the_gate(self):
        rc, _, err = run_cli_split(["compile", self.clean, "--strict=warning"])
        self.assertEqual(rc, 0, err)
        self.assertNotIn(CODE, err)


if __name__ == "__main__":
    unittest.main()
