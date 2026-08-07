"""Issue #44: the skip signal in the mode A/B differential check.

RFC-0008 §5 already requires the skip set and the `until` round count to be
compared, inside RFC-0004's execution-order class rather than as a fifth class.
This module is the control set for that comparison: a doctored pair proving it
goes red without any toolchain, and end-to-end runs proving the two modes really
do observe the same skips.

The comparison is on a per-STEP projection. Mode A records one entry per guard
(carrying every step the guard owns); mode B can only reconstruct a skip as
"planned but never printed", which is per step. Flattening mode A's record to
per-step entries makes the two sides directly comparable without either one
having to guess how the other groups its records.
"""

import os
import shutil
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.differential import _normalise_skips, compare_observations
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows, row_key
from tests.fixtures import CHECKOUT_LNPL, UNTIL_COUNTER, guarded_source

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NEEDS_TOOLS = unittest.skipUnless(
    backend.toolchain_available(),
    "MLIR/LLVM toolchain not installed (brew install llvm)")

USER = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
        "email": "user@example.com"}


def _observation(order, skips):
    """A minimal observation pair member — only what the four classes read."""
    return {"order": list(order),
            "effects": {name: [] for name in order},
            "status": "completed",
            "skips": skips,
            "text": "\n".join(["step %s" % n for n in order] + ["status completed"])}


class TestNormaliseSkips(unittest.TestCase):
    """The projection both modes are compared on."""

    def test_a_guard_record_becomes_one_entry_per_step(self):
        records = [{"guard": "wf.w.guard.1", "mode": "when",
                    "condition": "token missing",
                    "steps": ["cache user", "load user"], "rounds": None}]
        self.assertEqual(
            _normalise_skips(records),
            [{"mode": "when", "condition": "token missing",
              "step": "cache user", "rounds": None},
             {"mode": "when", "condition": "token missing",
              "step": "load user", "rounds": None}])

    def test_the_guard_node_id_is_dropped(self):
        # Mode B's stdout has no IR node ids, so a comparison keyed on one could
        # never pass. Dropping it here is what makes the two modes comparable.
        records = [{"guard": "wf.w.guard.1", "mode": "when", "condition": "x > 0",
                    "steps": ["s"], "rounds": None}]
        self.assertNotIn("guard", _normalise_skips(records)[0])

    def test_an_until_record_keeps_its_round_count(self):
        records = [{"guard": "wf.w.guard.1", "mode": "until",
                    "condition": "counter >= 10",
                    "steps": ["step Loop"], "rounds": 0}]
        self.assertEqual(_normalise_skips(records),
                         [{"mode": "until", "condition": "counter >= 10",
                           "step": "step Loop", "rounds": 0}])

    def test_no_records_project_to_no_entries(self):
        self.assertEqual(_normalise_skips([]), [])

    def test_a_guard_owning_no_step_projects_to_no_entries(self):
        # Boundary: a record whose subtree held no WorkflowStep contributes
        # nothing rather than an entry with a missing step name.
        records = [{"guard": "wf.w.guard.1", "mode": "when", "condition": "x > 0",
                    "steps": [], "rounds": None}]
        self.assertEqual(_normalise_skips(records), [])


class TestSkipDivergenceIsDetected(unittest.TestCase):
    """The negative control: the execution-order class must go red on a skip
    the other mode does not report. No toolchain needed — the observations are
    supplied directly, the way `TestDifferentialMaskingSurface` does for the
    masking class.
    """

    SKIP = [{"mode": "when", "condition": "product.stock > 0",
             "step": "create order", "rounds": None}]

    def test_a_skip_only_mode_a_reports_fails_the_order_class(self):
        a = _observation(["find product"], self.SKIP)
        b = _observation(["find product"], [])
        ok, report = compare_observations(a, b)
        self.assertFalse(ok, "\n".join(report))
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)
        self.assertIn("DIVERGENT", report[-1])

    def test_the_failure_report_names_both_sides_skips(self):
        a = _observation(["find product"], self.SKIP)
        b = _observation(["find product"], [])
        _ok, report = compare_observations(a, b)
        line = next(l for l in report if "FAIL 1/4" in l)
        self.assertIn("create order", line,
                      "the report must name the skip that differs, not just "
                      "say the class failed")

    def test_a_differing_round_count_fails_the_order_class(self):
        # RFC-0008 §5 names the `until` round count as its own comparison item.
        a = _observation(["a"], [{"mode": "until", "condition": "c >= 10",
                                  "step": "b", "rounds": 0}])
        b = _observation(["a"], [{"mode": "until", "condition": "c >= 10",
                                  "step": "b", "rounds": 3}])
        ok, report = compare_observations(a, b)
        self.assertFalse(ok)
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)

    def test_matching_skips_keep_the_order_class_green(self):
        # Positive control: sharpening the class must not redden honest runs.
        a = _observation(["find product"], self.SKIP)
        b = _observation(["find product"], list(self.SKIP))
        ok, report = compare_observations(a, b)
        self.assertTrue(ok, "\n".join(report))
        self.assertTrue(any("PASS 1/4" in line for line in report), report)
        self.assertIn("EQUIVALENT", report[-1])

    def test_an_absent_skips_key_reads_as_no_skips(self):
        # Boundary: an observation built before this key existed must compare
        # as "nothing was skipped" rather than as a divergence against [].
        a = _observation(["s"], [])
        b = _observation(["s"], [])
        del b["skips"]
        ok, _report = compare_observations(a, b)
        self.assertTrue(ok)


class TestBothModesObserveTheSameSkips(unittest.TestCase):
    """End to end: the two modes really do agree, on inputs where a guard is
    false. `testing-quality-differential-run-agreement`: the default input never
    reaches the guard's false side, so it certifies nothing about this class.
    """

    def setUp(self):
        tmp = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(tmp, exist_ok=True)
        self.workdir = tempfile.mkdtemp(prefix="lnpl-skip-", dir=tmp)

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _checkout(self, stock):
        from lnpl.interp import refinement_index, sample_payload
        with open(CHECKOUT_LNPL, encoding="utf-8") as fh:
            doc = lower(parse(fh.read()), "checkout").to_document()
        payload = sample_payload([n for n in doc["nodes"] if n["kind"] == "Entity"],
                                 refinement_index(doc))
        payload["stock"] = stock
        return doc, payload

    def test_mode_a_reports_the_skip_on_the_forcing_input(self):
        # Mode A side alone, so the claim below is not resting on the toolchain.
        doc, payload = self._checkout(stock=0)
        a = differential.observe_mode_a(doc, "wf.checkout", payload,
                                        default_rows(doc, "wf.checkout", payload))
        self.assertEqual(a["skips"],
                         [{"mode": "when", "condition": "product.stock > 0",
                           "step": "create order", "rounds": None}])

    @NEEDS_TOOLS
    def test_a_false_when_is_equivalent_across_the_two_modes(self):
        doc, payload = self._checkout(stock=0)
        rows = default_rows(doc, "wf.checkout", payload)
        ok, report = differential.verify(doc, "wf.checkout", payload, rows,
                                         self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertTrue(any("1 skip" in line for line in report), report)

    @NEEDS_TOOLS
    def test_the_guard_true_run_reports_no_skip_in_either_mode(self):
        # The forcing input's control: same workflow, guard taken.
        doc, payload = self._checkout(stock=1)
        rows = default_rows(doc, "wf.checkout", payload)
        ok, report = differential.verify(doc, "wf.checkout", payload, rows,
                                         self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertTrue(any("0 skip" in line for line in report), report)

    @NEEDS_TOOLS
    def test_an_until_that_never_loops_is_equivalent_across_the_modes(self):
        doc = lower(parse(UNTIL_COUNTER), "t").to_document()
        payload = {"counter": 100}
        rows = default_rows(doc, "wf.w", payload)
        ok, report = differential.verify(doc, "wf.w", payload, rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))
        b = differential.observe_mode_b(doc, "wf.w", self.workdir,
                                        payload=payload, seeded=None)
        self.assertEqual(b["skips"],
                         [{"mode": "until", "condition": "counter >= 10",
                           "step": "step Loop", "rounds": 0}],
                         "a 0-round until must produce exactly one record in "
                         "mode B too, not one per unrolled round")

    @NEEDS_TOOLS
    def test_an_unguarded_workflow_reports_no_skips_in_either_mode(self):
        # Boundary: the workflows that have no guard at all must be untouched.
        doc = lower(parse(guarded_source("when token missing")), "t").to_document()
        for node in doc["nodes"]:
            if node["id"] == "wf.w":
                node["children"] = [c for c in node["children"]
                                    if not c.startswith("wf.w.guard")]
        payload = dict(USER, token="present")
        rows = {"entity.user": {row_key("entity.user", payload): dict(payload)}}
        ok, report = differential.verify(doc, "wf.w", payload, rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))
        a = differential.observe_mode_a(doc, "wf.w", payload, rows)
        self.assertEqual(a["skips"], [])

    # A step name that appears both inside the guard and outside it. Matching
    # ran-vs-planned by NAME lets the unguarded occurrence mask the guarded one,
    # so mode B reports no skip while mode A reports one.
    DUPLICATE_NAME = """
capability postgres
entity User
    field
        id UUID
        email Email
        token Text
service S
workflow W
    load user
    when token missing
    load user
"""

    @NEEDS_TOOLS
    def test_a_step_name_repeated_outside_the_guard_does_not_mask_the_skip(self):
        doc = lower(parse(self.DUPLICATE_NAME), "t").to_document()
        payload = dict(USER, token="present")           # `token missing` is false
        rows = {"entity.user": {row_key("entity.user", payload): dict(payload)}}

        a = differential.observe_mode_a(doc, "wf.w", payload, rows)
        self.assertEqual(a["skips"],
                         [{"mode": "when", "condition": "token missing",
                           "step": "load user", "rounds": None}],
                         "precondition: mode A sees the guarded occurrence skipped")

        ok, report = differential.verify(doc, "wf.w", payload, rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))
        b = differential.observe_mode_b(doc, "wf.w", self.workdir,
                                        payload=payload, seeded=None)
        self.assertEqual(b["skips"], a["skips"],
                         "mode B must identify the skipped op by its index; "
                         "the identically named step that DID run must not "
                         "mask it.")


class TestRanStepIndices(unittest.TestCase):
    """`backend.ran_step_indices` — which planned ops the binary printed.

    Indices, not names: `TestBothModesObserveTheSameSkips.DUPLICATE_NAME` is the
    workflow that makes the difference observable.
    """

    def test_step_lines_yield_their_indices(self):
        lines = ["step 1 validate product", "effect validate product Validation",
                 "step 2 find product", "status completed"]

        self.assertEqual(backend.ran_step_indices(lines), {"1", "2"})

    def test_a_step_name_containing_spaces_still_yields_one_index(self):
        self.assertEqual(backend.ran_step_indices(["step 7 step Loop"]), {"7"})

    def test_no_lines_yield_no_indices(self):
        self.assertEqual(backend.ran_step_indices([]), set())

    def test_effect_and_status_lines_alone_yield_no_indices(self):
        # Boundary: a binary whose guard skipped everything still prints these.
        lines = ["effect find product RepositoryCall", "status completed"]

        self.assertEqual(backend.ran_step_indices(lines), set())

    def test_a_malformed_step_line_is_not_counted(self):
        # `step` with no name is not the contract's shape; counting it would
        # credit a planned op as run and hide a real skip.
        self.assertEqual(backend.ran_step_indices(["step 3"]), set())


class TestRestoreSkips(unittest.TestCase):
    """`backend.restore_skips` — RFC-0014 §2.6's absence-as-observation.

    Pure: no toolchain, no build. The function's whole input is the compiled step
    plan plus the set of indices that printed, so a synthetic `ran_indices`
    exercises it at the level the logic actually lives at.
    """

    def _checkout(self, stock):
        from lnpl.interp import refinement_index, sample_payload
        with open(CHECKOUT_LNPL, encoding="utf-8") as fh:
            doc = lower(parse(fh.read()), "checkout").to_document()
        payload = sample_payload([n for n in doc["nodes"] if n["kind"] == "Entity"],
                                 refinement_index(doc))
        payload["stock"] = stock
        return doc, payload

    def _all_indices(self, doc, workflow_id, payload):
        return {str(e["index"])
                for e in backend.step_plan(doc, workflow_id, payload=payload)}

    def test_a_planned_guarded_step_that_never_printed_is_one_record(self):
        doc, payload = self._checkout(stock=0)
        # `create order` is plan index 4; the three unguarded steps printed.
        skips = backend.restore_skips(doc, "wf.checkout", {"1", "2", "3"},
                                     payload=payload)

        self.assertEqual(skips, [{"mode": "when",
                                  "condition": "product.stock > 0",
                                  "step": "create order", "rounds": None}])

    def test_a_guarded_step_that_printed_is_not_a_skip(self):
        # Positive control: the same plan, the guard taken.
        doc, payload = self._checkout(stock=1)
        ran = self._all_indices(doc, "wf.checkout", payload)

        self.assertEqual(backend.restore_skips(doc, "wf.checkout", ran,
                                               payload=payload), [])

    def test_an_absent_unguarded_step_is_not_a_skip(self):
        # Boundary: nothing printed at all. An unguarded step's absence means the
        # run stopped, not that a guard refused it — only guarded ops are skips.
        doc, payload = self._checkout(stock=0)
        skips = backend.restore_skips(doc, "wf.checkout", set(), payload=payload)

        self.assertEqual([s["step"] for s in skips], ["create order"])

    def test_a_zero_round_until_is_exactly_one_record(self):
        doc = lower(parse(UNTIL_COUNTER), "t").to_document()
        payload = {"counter": 100}
        # Plan: index 1 `step Start`, 2-17 the unrolled `step Loop`, 18 `step End`.
        skips = backend.restore_skips(doc, "wf.w", {"1", "18"}, payload=payload)

        self.assertEqual(skips, [{"mode": "until", "condition": "counter >= 10",
                                  "step": "step Loop", "rounds": 0}],
                         "rounds 2..N are unrolled copies; counting each absence "
                         "would report 16 skips against mode A's single record")

    def test_an_until_that_ran_every_round_is_not_a_skip(self):
        doc = lower(parse(UNTIL_COUNTER), "t").to_document()
        payload = {"counter": 0}
        ran = self._all_indices(doc, "wf.w", payload)

        self.assertEqual(backend.restore_skips(doc, "wf.w", ran,
                                               payload=payload), [])

    def test_a_workflow_with_no_guard_restores_no_skips(self):
        # Boundary: the unguarded workflows must be untouched by this reading.
        doc, payload = self._checkout(stock=0)
        for node in doc["nodes"]:
            if node["id"] == "wf.checkout":
                node["children"] = [c for c in node["children"]
                                    if not c.startswith("wf.checkout.guard")]

        self.assertEqual(backend.restore_skips(doc, "wf.checkout", set(),
                                               payload=payload), [])

    def test_the_restored_record_carries_exactly_the_comparable_fields(self):
        # The shape is the contract: `_normalise_skips` projects mode A onto
        # these four keys, so an extra key here would fail the comparison for a
        # reason RFC-0014 §2.4 says is not a behavioural difference.
        doc, payload = self._checkout(stock=0)
        skips = backend.restore_skips(doc, "wf.checkout", {"1", "2", "3"},
                                     payload=payload)

        self.assertEqual(sorted(skips[0]), ["condition", "mode", "rounds", "step"])

    def test_a_repeated_step_name_does_not_mask_the_guarded_occurrence(self):
        # The index-not-name rule, at the level it is implemented rather than
        # only end to end: `TestBothModesObserveTheSameSkips` covers this too,
        # but that test needs the toolchain and is skipped without it.
        # Plan: index 1 `load user` unguarded, index 2 `load user` under the
        # guard. Only the unguarded one printed. Matching on the NAME would find
        # `load user` among the ran steps and report no skip at all.
        doc = lower(parse(TestBothModesObserveTheSameSkips.DUPLICATE_NAME),
                    "t").to_document()
        skips = backend.restore_skips(doc, "wf.w", {"1"},
                                     payload={"token": "present"})

        self.assertEqual(skips, [{"mode": "when", "condition": "token missing",
                                  "step": "load user", "rounds": None}])

    def test_an_empty_plan_restores_nothing(self):
        # Negative control for the two positive cases above: with the plan
        # emptied, the same `ran_indices` must yield nothing. A restoration that
        # returned a constant would keep one of the three tests green and break
        # this one.
        from unittest import mock

        doc, payload = self._checkout(stock=0)
        with mock.patch.object(backend, "step_plan", return_value=[]):
            self.assertEqual(backend.restore_skips(doc, "wf.checkout",
                                                   {"1", "2", "3"},
                                                   payload=payload), [])
