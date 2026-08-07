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
import shutil
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows, seeded_entities
from tests.fixtures import REPEAT_EFFECT_LOOP, until_effect_source
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

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

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


@NEEDS_TOOLS
class TestUntilRepeatedStepObservation(unittest.TestCase):
    """Issue #51 / RFC-0018: a step name repeated by a guard must fold the same
    way in both modes.

    The class above compares ROUND COUNTS, which is why it stayed green through
    this defect. What diverged is the per-name EFFECT map: `observe_mode_a` used
    a dict comprehension (last occurrence wins) while `observe_mode_b`
    accumulates, so a loop whose guarded step carries an effect produced
    `['RepositoryCall']` against `['RepositoryCall'] * 16` even though both modes
    ran the same 17 steps.

    Issue #51 reported this as "mode B runs to the round cap when the condition
    already holds at entry". That is not what happens — the native binary emits
    exactly one `step` line on the entry-true path — so the entry-true case here
    is a no-regression control, not a reproduction.
    """

    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        self.workdir = tempfile.mkdtemp(prefix="lnpl-until-eff-", dir=TMP)

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _observe(self, source, budget):
        """Both modes' observations of `source` at `token.retryBudget = budget`."""
        doc = lower(parse(source), "t").to_document()
        payload = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
                   "retryBudget": budget}
        rows = default_rows(doc, "wf.repro", payload)
        seeded = seeded_entities(doc, "wf.repro")
        a = differential.observe_mode_a(doc, "wf.repro", payload, rows)
        b = differential.observe_mode_b(doc, "wf.repro", self.workdir,
                                        payload=payload, seeded=seeded)
        return a, b

    def _assert_cap_rounds_agree(self, condition, budget):
        """The loop ran the cap in both modes, and both report the same effects."""
        a, b = self._observe(until_effect_source(condition), budget)
        self.assertEqual(b["effects"]["read token"], ["RepositoryCall"] * CAP,
                         "mode B did not run the unrolled body %d times" % CAP)
        self.assertEqual(a["effects"], b["effects"],
                         "the two modes ran the same %d steps but folded the "
                         "repeated step's effects differently" % len(a["order"]))

    def test_entry_false_eq_gives_both_modes_the_same_effect_multiset(self):
        self._assert_cap_rounds_agree("token.retryBudget == 0", 9)

    def test_entry_false_lt_gives_both_modes_the_same_effect_multiset(self):
        self._assert_cap_rounds_agree("token.retryBudget < 1", 9)

    def test_entry_false_gt_gives_both_modes_the_same_effect_multiset(self):
        self._assert_cap_rounds_agree("token.retryBudget > 5", 0)

    def test_entry_true_runs_no_rounds_in_both_modes(self):
        """Control: the path issue #51 named. It already agreed and must stay so."""
        a, b = self._observe(until_effect_source("token.retryBudget == 0"), 0)
        self.assertEqual(a["order"], ["find token"])
        self.assertEqual(b["order"], a["order"])
        self.assertEqual(a["skips"], b["skips"])
        self.assertEqual(a["skips"][0]["rounds"], 0,
                         "a zero-round `until` must record rounds=0 (RFC-0014)")

    def test_differential_is_equivalent_on_the_issue_51_reproduction(self):
        """The reproduction from issue #51's body, on the path that diverges."""
        a, b = self._observe(until_effect_source("token.retryBudget == 0"), 9)
        ok, report = differential.compare_observations(a, b)
        self.assertTrue(ok, "\n".join(report))

    def test_repeat_guard_folds_the_same_way(self):
        """The defect is repetition, not `until` — `repeat` repeats a name too."""
        a, b = self._observe(REPEAT_EFFECT_LOOP, 0)
        self.assertEqual(b["effects"]["read token"], ["RepositoryCall"] * 3)
        self.assertEqual(a["effects"], b["effects"])


class TestRepeatedStepFoldDetectsRealDivergence(unittest.TestCase):
    """RFC-0018 accumulates instead of overwriting so that a REAL divergence in
    a repeated step still reddens class 3/4.

    Overwriting would have made the two modes agree by discarding evidence: a
    mode that skipped fifteen of sixteen repository calls folds to the same
    one-element list as a mode that made all sixteen. These are the seeded
    divergences that prove the class discriminates.

    Deliberately NOT `@NEEDS_TOOLS`. `compare_observations` is a pure function,
    so this control must run — and can run — on a machine with no MLIR/LLVM. A
    control that skips itself where the toolchain is missing is not a control.
    """

    @staticmethod
    def _observation(effects):
        """A minimal observation whose only interesting field is `effects`."""
        return {"order": ["s"] * CAP, "effects": {"s": effects},
                "status": "completed", "skips": [], "text": ""}

    def _assert_only_class_3_reddens(self, a_effects, b_effects):
        ok, report = differential.compare_observations(
            self._observation(a_effects), self._observation(b_effects))
        self.assertFalse(ok, "\n".join(report))
        # "3/4 went red" must be distinguishable from "everything went red":
        # the other three classes are identical by construction here.
        failed = sorted(line.split(" ")[1] for line in report
                        if line.startswith("FAIL"))
        self.assertEqual(failed, ["3/4"], "\n".join(report))
        return report

    def test_a_dropped_effect_in_one_round_still_reddens_class_3(self):
        """Mode B made fifteen of the sixteen repository calls."""
        self._assert_only_class_3_reddens(["RepositoryCall"] * CAP,
                                          ["RepositoryCall"] * (CAP - 1))

    def test_a_changed_effect_kind_reddens_class_3(self):
        """Same count, one round's effect is the wrong kind."""
        self._assert_only_class_3_reddens(
            ["RepositoryCall"] * CAP,
            ["RepositoryCall"] * (CAP - 1) + ["NetworkCall"])

    def test_identical_repeated_effects_pass_class_3(self):
        """Positive control: the check is not simply always red."""
        effects = ["RepositoryCall"] * CAP
        ok, report = differential.compare_observations(
            self._observation(effects), self._observation(list(effects)))
        self.assertTrue(ok, "\n".join(report))
        self.assertTrue(any(line.startswith("PASS 3/4") for line in report),
                        "\n".join(report))


if __name__ == "__main__":
    unittest.main()
