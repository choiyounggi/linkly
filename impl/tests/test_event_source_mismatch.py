"""`event-source-mismatch` / `event-source-orphaned` — a declared event source
and its `emit` are never checked against each other (issue #98).

`event <E> on <Entity> <op>` reads as a claim: "E is the event for `<op>
<entity>`." Nothing verified that claim against the workflow that actually
`emit`s E. A guard that skips `create order` still lets an unguarded `emit
orderPlaced` beside it fire — the source declaration becomes a lie at runtime
with no signal at compile time:

    when product.stock >= input.quantity
    create order
    set product.stock to product.stock - input.quantity
    update product
    emit orderPlaced

RFC-0002's rule is the same one RFC-0023 already made visible for state
changes — a guard owns only the next item — applied here to the *coupling*
between a create/update/delete step and the event it is supposed to source.
The two remedies (`references/grammar.md`'s own prescription) are unchanged:
repeat the guard line before the `emit`, or wrap both under one `parallel`
block.

Two grades, same RFC-0021 question (does editing the program make it go
away?):
  * `<op> <entity>` runs, but not in the emit's guard scope -> `event-source-
    mismatch` (`warning`) — moving one under the other's guard silences it.
  * `<op> <entity>` never runs in the workflow at all -> `event-source-
    orphaned` (`info`) — the source declaration is accurate only as a
    statement of intent; no local edit removes it short of restructuring the
    workflow or dropping the source/emit.

An event with no `on` source (`event X` alone) is untouched — issue #98 §3.
"""
import contextlib
import glob
import io
import os
import shutil
import tempfile
import unittest

from lnpl import cli
from lnpl.diagnostics import CODES, SEVERITY_OF
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_ROOT = os.path.join(REPO, ".claude", "tmp")

MISMATCH = "event-source-mismatch"
ORPHANED = "event-source-orphaned"

# The issue's own reproduction: a guard owns `create order`, but `emit
# orderPlaced` sits unguarded right after the steps the guard does own.
ISSUE_REPRO = """entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

event OrderPlaced on Order create

workflow PlaceOrder
    validate product
    find product
    when product.stock >= input.quantity
    create order
    set product.stock to product.stock - input.quantity
    update product
    emit orderPlaced
"""

# Remedy 1 (references/grammar.md): repeat the guard line before the `emit`.
# Two distinct Guard nodes, same mode+condition — same protection either way.
FIXED_BY_REPEATING_THE_GUARD = """entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

event OrderPlaced on Order create

workflow PlaceOrder
    validate product
    find product
    when product.stock >= input.quantity
    create order
    when product.stock >= input.quantity
    emit orderPlaced
"""

# Remedy 2: wrap both under one `parallel` block, so one Guard owns them both.
FIXED_BY_A_PARALLEL_BLOCK = """entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

event OrderPlaced on Order create

workflow PlaceOrder
    validate product
    find product
    when product.stock >= input.quantity
    parallel
    create order
    emit orderPlaced
    merge
"""

# Two guards, two unrelated conditions — `create` and `emit` are each
# "guarded", but not by the same protection, so they can diverge at runtime.
# (This is the exact shape `qa/cases/rate-notify/rate-notify.lnpl` ships with.)
MISMATCHED_GUARDS = """entity Measurement
    field
        id UUID
        value Integer

entity Notification
    field
        id UUID
        priorNotification UUID

event NotificationSent on Notification create

workflow Report
    validate measurement
    find measurement
    when measurement.value > 100
    create notification
    when priorNotification missing
    emit notificationSent
"""

# `event X` alone: no `on` source. The emit is free — issue #98 §3.
SOURCELESS_EVENT = """entity Order
    field
        id UUID
        quantity Integer

event OrderPlaced

workflow PlaceOrder
    validate order
    create order
    emit orderPlaced
"""

# `<op> <entity>` never runs in this workflow at all — the source is
# descriptive only.
MISSING_OP_STEP = """entity Order
    field
        id UUID
        quantity Integer

event OrderPlaced on Order create

workflow NotifyOnly
    validate order
    emit orderPlaced
"""

# Neither guarded — unconditional top level, so create and emit always run
# together. No mismatch, no orphan.
UNGUARDED_TOGETHER = """entity Order
    field
        id UUID
        quantity Integer

event OrderPlaced on Order create

workflow PlaceOrder
    validate order
    create order
    emit orderPlaced
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


class TheCodesAreRegistered(unittest.TestCase):

    def test_both_codes_exist(self):
        self.assertIn(MISMATCH, CODES)
        self.assertIn(ORPHANED, CODES)

    def test_mismatch_is_a_warning(self):
        # RFC-0021: fixed by editing the program (move the emit) -> warning.
        self.assertEqual(SEVERITY_OF[MISMATCH], "warning")

    def test_orphaned_is_info(self):
        # No local edit removes it short of restructuring — same logic as
        # `declared-not-enforced`.
        self.assertEqual(SEVERITY_OF[ORPHANED], "info")


class TheIssueReproFiresMismatch(unittest.TestCase):
    """DoD 1: the issue's own repro reports exactly one `event-source-mismatch`."""

    def test_it_fires_exactly_once(self):
        found = diagnose(ISSUE_REPRO, MISMATCH)
        self.assertEqual(len(found), 1, [d.subject for d in found])

    def test_it_names_the_emit_line_and_both_remedies(self):
        found = diagnose(ISSUE_REPRO, MISMATCH)[0]
        self.assertEqual(found.where, "line 20")
        self.assertEqual(found.line, 20)
        self.assertIn("Repeat the guard line", found.message)
        self.assertIn("parallel", found.message)

    def test_it_reports_nothing_for_orphaned(self):
        # The op step does run — just not in scope. Only mismatch applies.
        self.assertEqual(diagnose(ISSUE_REPRO, ORPHANED), [])


class TheRemediesActuallyWork(unittest.TestCase):
    """The two fixes the message recommends must actually silence it."""

    def test_repeating_the_guard_line_silences_it(self):
        self.assertEqual(diagnose(FIXED_BY_REPEATING_THE_GUARD, MISMATCH), [])

    def test_wrapping_both_in_parallel_silences_it(self):
        self.assertEqual(diagnose(FIXED_BY_A_PARALLEL_BLOCK, MISMATCH), [])


class DifferentGuardsAreStillAMismatch(unittest.TestCase):
    """Being guarded is not enough — the *same* guard has to own both."""

    def test_two_unrelated_guards_fire_mismatch(self):
        found = diagnose(MISMATCHED_GUARDS, MISMATCH)
        self.assertEqual(len(found), 1, [d.subject for d in found])


class GuardedParallelReportsNothing(unittest.TestCase):
    """DoD 2: create+emit inside one guarded `parallel` block -> 0 diagnostics."""

    def test_no_mismatch(self):
        self.assertEqual(diagnose(FIXED_BY_A_PARALLEL_BLOCK, MISMATCH), [])

    def test_no_orphan(self):
        self.assertEqual(diagnose(FIXED_BY_A_PARALLEL_BLOCK, ORPHANED), [])


class SourcelessEventIsFree(unittest.TestCase):
    """Issue #98 §3: an event with no `on` source is never checked."""

    def test_no_mismatch(self):
        self.assertEqual(diagnose(SOURCELESS_EVENT, MISMATCH), [])

    def test_no_orphan(self):
        self.assertEqual(diagnose(SOURCELESS_EVENT, ORPHANED), [])


class MissingOpStepFiresOrphaned(unittest.TestCase):
    """The workflow emits E but never runs the op step E's source names."""

    def test_it_fires_exactly_once(self):
        found = diagnose(MISSING_OP_STEP, ORPHANED)
        self.assertEqual(len(found), 1, [d.subject for d in found])

    def test_it_names_the_emit_line(self):
        found = diagnose(MISSING_OP_STEP, ORPHANED)[0]
        self.assertEqual(found.line, 10)

    def test_it_reports_nothing_for_mismatch(self):
        # There is no op step at all, so "not the same scope" does not apply —
        # only orphaned does.
        self.assertEqual(diagnose(MISSING_OP_STEP, MISMATCH), [])


class UnguardedTogetherReportsNothing(unittest.TestCase):
    """Both unconditional at the top level -> they always run together."""

    def test_no_mismatch(self):
        self.assertEqual(diagnose(UNGUARDED_TOGETHER, MISMATCH), [])

    def test_no_orphan(self):
        self.assertEqual(diagnose(UNGUARDED_TOGETHER, ORPHANED), [])


class TestStrictWarningGate(unittest.TestCase):
    """DoD 3: `--strict=warning` gates on the issue repro (rc != 0)."""

    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.tmpdir = tempfile.mkdtemp(dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.repro = os.path.join(self.tmpdir, "t98_repro.lnpl")
        with open(self.repro, "w", encoding="utf-8") as fh:
            fh.write(ISSUE_REPRO)
        self.orphan = os.path.join(self.tmpdir, "t98_orphan.lnpl")
        with open(self.orphan, "w", encoding="utf-8") as fh:
            fh.write(MISSING_OP_STEP)

    def test_the_mismatch_repro_fails_the_strict_warning_gate(self):
        rc, _, err = run_cli_split(["compile", self.repro, "--strict=warning"])
        self.assertNotEqual(rc, 0)
        self.assertIn(MISMATCH, err)

    def test_the_mismatch_repro_still_compiles_rc_0_without_strict(self):
        rc, _, err = run_cli_split(["compile", self.repro])
        self.assertEqual(rc, 0, err)
        self.assertIn(MISMATCH, err)

    def test_the_orphan_only_file_does_not_fail_the_strict_warning_gate(self):
        # `info` sits below `warning` on the SEVERITIES ladder (RFC-0021) —
        # `--strict=warning` must not gate on it.
        rc, _, err = run_cli_split(["compile", self.orphan, "--strict=warning"])
        self.assertEqual(rc, 0, err)
        self.assertIn(ORPHANED, err)


class ShippedExamplesStaySilent(unittest.TestCase):
    """DoD 4: no shipped `examples/*.lnpl` reports either new code."""

    def test_no_shipped_example_reports_either_code(self):
        paths = sorted(glob.glob(os.path.join(REPO, "examples", "*.lnpl")))
        self.assertGreaterEqual(len(paths), 4, "예제를 하나도 못 찾으면 공허하다")
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            for code in (MISMATCH, ORPHANED):
                with self.subTest(example=os.path.basename(path), code=code):
                    found = diagnose(source, code, os.path.basename(path))
                    self.assertEqual(
                        found, [],
                        "%s reports %s — the corpus sweep must stay clean"
                        % (os.path.basename(path), code))


if __name__ == "__main__":
    unittest.main()
