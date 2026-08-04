"""RFC-0008 G10 / issue #3: `until` must mean the same thing in both modes.

Mode A stops repeating once the condition holds. Mode B unrolled the loop to
`_UNTIL_ROUND_CAP` and emitted the body unconditionally, so it behaved as though
the condition never became true — a static answer to a runtime question. The
committed golden scenario hid it: no golden program uses `until` with a condition
that can hold, so `verify()` reported EQUIVALENT while a one-line payload change
did not.

Nothing in the IR mutates a condition field during a run, so the condition is
constant for the whole workflow: mode A therefore runs either 0 rounds or the cap.
These tests pin mode B to the same two outcomes, and to mode A directly.

Tests needing the MLIR/LLVM toolchain skip when it is absent rather than passing
vacuously.
"""

import os
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows
from tests.fixtures import UNTIL_COUNTER as SRC

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = os.path.join(REPO, ".claude", "tmp")

HAS_TOOLS = backend.toolchain_available()
NEEDS_TOOLS = unittest.skipUnless(
    HAS_TOOLS, "MLIR/LLVM toolchain not installed (brew install llvm)")

CAP = backend._UNTIL_ROUND_CAP


def _rounds(observed):
    return sum(1 for name in observed["order"] if "Loop" in name)


def _rows(payload):
    """A seeded store in the shape `FakeRepository` actually reads.

    These seeds were written as `{entity_id: row}` before Wave 1 keyed each
    entity's table (`{entity_id: {row_key: row}}`, issue #35). `UNTIL_COUNTER`
    has no `RepositoryCall`, so the stale shape never mattered here — it would
    have mattered the moment someone added one, as a row the repository could
    not find. Built from `repo_policy` so it tracks the one seeding rule.
    """
    return default_rows(lower(parse(SRC), "t").to_document(), "wf.w", payload)


@NEEDS_TOOLS
class TestUntilModeEquivalence(unittest.TestCase):
    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        self.workdir = tempfile.mkdtemp(prefix="lnpl-until-", dir=TMP)
        self.doc = lower(parse(SRC), "t").to_document()

    def _both(self, counter):
        payload = {"counter": counter}
        a = differential.observe_mode_a(self.doc, "wf.w", payload,
                                       _rows(payload))
        b = differential.observe_mode_b(self.doc, "wf.w", self.workdir,
                                        payload=payload)
        return _rounds(a), _rounds(b)

    def test_condition_false_runs_the_cap_in_both_modes(self):
        """Control: the case that already agreed must keep agreeing."""
        a, b = self._both(0)
        self.assertEqual(a, CAP)
        self.assertEqual(b, a)

    def test_condition_just_below_the_bound_runs_the_cap_in_both_modes(self):
        """Boundary: 9 against `>= 10` is still false."""
        a, b = self._both(9)
        self.assertEqual(a, CAP)
        self.assertEqual(b, a)

    def test_condition_true_at_the_bound_runs_no_rounds_in_both_modes(self):
        """Boundary: 10 satisfies `>= 10`, so neither mode may run the body."""
        a, b = self._both(10)
        self.assertEqual(a, 0)
        self.assertEqual(b, a, "mode B ran the unrolled body although the "
                               "`until` condition already held")

    def test_condition_far_past_the_bound_runs_no_rounds_in_both_modes(self):
        a, b = self._both(100)
        self.assertEqual(a, 0)
        self.assertEqual(b, a)

    def test_differential_reports_equivalent_once_the_condition_holds(self):
        """The gap the golden scenario hid: verify() must go green here too."""
        payload = {"counter": 100}
        ok, report = differential.verify(
            self.doc, "wf.w", payload, _rows(payload),
            self.workdir)
        self.assertTrue(ok, "\n".join(report))

    def test_differential_still_reports_equivalent_below_the_bound(self):
        """Control: the previously-passing payload must not regress."""
        payload = {"counter": 0}
        ok, report = differential.verify(
            self.doc, "wf.w", payload, _rows(payload),
            self.workdir)
        self.assertTrue(ok, "\n".join(report))


if __name__ == "__main__":
    unittest.main()
