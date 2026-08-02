"""Mode B (native) and the mode A/B differential check.

RFC-0004 requires the equivalence check to include a **deliberate-mismatch case**
proving it can go red; `TestDivergenceIsDetected` is that case. Tests needing the
MLIR/LLVM toolchain skip when it is absent rather than passing vacuously.
"""

import json
import os
import shutil
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.lower import lower
from lnpl.parser import parse
from tests.fixtures import GUARDED, UNTIL_COUNTER, guarded_source

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN_IR = os.path.join(REPO, "examples", "login.lir.json")

PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
           "email": "user@example.com",
           "password": "s3cret-value",
           "createdAt": "2026-07-31T09:00:00Z"}

HAS_TOOLS = backend.toolchain_available()
NEEDS_TOOLS = unittest.skipUnless(
    HAS_TOOLS, "MLIR/LLVM toolchain not installed (brew install llvm)")


def golden():
    with open(GOLDEN_IR, encoding="utf-8") as fh:
        return json.load(fh)


def rows_for(doc):
    return {n["id"]: dict(PAYLOAD) for n in doc["nodes"] if n["kind"] == "Entity"}


class TestMlirEmission(unittest.TestCase):
    """Emission needs no toolchain — it is text generation."""

    def test_every_step_appears_in_declared_order(self):
        text = backend.emit_mlir(golden(), "wf.login")
        positions = [text.index('"%s\\00"' % name) for name in
                     ("validate input", "authenticate", "cache user",
                      "generate token", "audit login", "return token")]
        self.assertEqual(positions, sorted(positions))

    def test_effects_are_emitted_as_calls(self):
        text = backend.emit_mlir(golden(), "wf.login")
        self.assertEqual(text.count("@lnpl_effect"), 3 + 1)   # 3 call sites + 1 decl

    def test_repeat_guard_unrolls_to_a_constant_number_of_steps(self):
        src = guarded_source("repeat 3")
        doc = lower(parse(src), "t").to_document()
        text = backend.emit_mlir(doc, "wf.w")
        self.assertEqual(text.count("func.call @lnpl_step"), 1 + 3)

    def test_when_guard_becomes_a_runtime_branch(self):
        doc = lower(parse(GUARDED), "t").to_document()
        text = backend.emit_mlir(doc, "wf.w")
        self.assertIn("scf.if", text)

    def test_until_guard_emits_mlir(self):
        # RFC-0008 G10: until now compiles to MLIR (scf.while)
        src = guarded_source("until token exists")
        doc = lower(parse(src), "t").to_document()
        text = backend.emit_mlir(doc, "wf.w")
        # Verify until guard appears in the output (comment form for now)
        self.assertIn("until", text)

    def test_unknown_workflow_is_an_error(self):
        with self.assertRaises(backend.BackendError):
            backend.emit_mlir(golden(), "wf.nope")


@NEEDS_TOOLS
class TestNativeBuild(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-build-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_golden_compiles_to_a_runnable_binary(self):
        path = backend.build(golden(), "wf.login", self.workdir)
        self.assertTrue(os.access(path, os.X_OK))
        rc, lines = backend.run_binary(path)
        self.assertEqual(rc, 0)
        self.assertEqual(lines[-1], "status completed")

    def test_binary_reports_every_step(self):
        path = backend.build(golden(), "wf.login", self.workdir)
        _rc, lines = backend.run_binary(path)
        steps = [l for l in lines if l.startswith("step ")]
        self.assertEqual(len(steps), 6)

    def test_intermediates_are_kept_for_inspection(self):
        backend.build(golden(), "wf.login", self.workdir)
        for name in ("module.lnpl.mlir", "module.mlir", "module.llvm.mlir",
                     "module.ll"):
            self.assertTrue(os.path.isfile(os.path.join(self.workdir, name)), name)

    def test_when_guard_flag_skips_the_guarded_step_in_the_binary(self):
        doc = lower(parse(GUARDED), "t").to_document()
        path = backend.build(doc, "wf.w", self.workdir)
        _rc, ran = backend.run_binary(path, skip=False)
        _rc, skipped = backend.run_binary(path, skip=True)
        self.assertEqual(len([l for l in ran if l.startswith("step ")]), 2)
        self.assertEqual(len([l for l in skipped if l.startswith("step ")]), 1)


@NEEDS_TOOLS
class TestDifferential(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-diff-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_the_two_modes_are_equivalent_on_the_golden_scenario(self):
        doc = golden()
        ok, report = differential.verify(doc, "wf.login", PAYLOAD,
                                         rows_for(doc), self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertIn("differential: EQUIVALENT", report[-1])

    def test_all_four_observable_classes_are_checked(self):
        doc = golden()
        _ok, report = differential.verify(doc, "wf.login", PAYLOAD,
                                          rows_for(doc), self.workdir)
        for n in ("1/4", "2/4", "3/4", "4/4"):
            self.assertTrue(any(n in line for line in report), n)

    def test_secrets_do_not_reach_either_mode_output(self):
        doc = golden()
        a = differential.observe_mode_a(doc, "wf.login", PAYLOAD, rows_for(doc))
        b = differential.observe_mode_b(doc, "wf.login", self.workdir)
        self.assertNotIn("s3cret", a["text"])
        self.assertNotIn("s3cret", b["text"])


@NEEDS_TOOLS
class TestDivergenceIsDetected(unittest.TestCase):
    """RFC-0004's deliberate-mismatch requirement: the check must be able to fail.

    Every case here does the same three things, in this order: run the workflow
    **unpatched** and require EQUIVALENT, apply exactly one fault, then require
    the specific `FAIL n/4` class that fault produces.

    The baseline assertion is not ceremony. Three of these cases used to run
    against `GUARDED` while it was divergent on its own — its `cache user` had no
    TTL budget, so mode A refused and mode B did not (see `tests/fixtures.py`).
    They asserted `assertFalse(ok)` and `any("FAIL")`, both of which that standing
    divergence satisfied, so their patches could be deleted without the tests
    noticing. Two of the three could not have worked in any case: `GUARDED` has no
    `until`, so the two `until` faults were no-ops on it, and they now use
    `UNTIL_COUNTER`.

    Pinning the FAIL class matters for the same reason — a bare `any("FAIL")`
    accepts a divergence the test did not cause.
    """

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-div-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))
        self.original = backend._steps_in_order

    def tearDown(self):
        backend._steps_in_order = self.original
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _verify(self, doc, workflow, payload, rows, skip=False):
        return differential.verify(doc, workflow, payload, rows, self.workdir,
                                   skip=skip)

    def test_the_guarded_fixture_is_equivalent_with_its_guard_taken(self):
        """The baseline the other cases rest on, with `cache user` actually run.

        Every other case here either uses the golden workflow, `UNTIL_COUNTER`, or
        makes GUARDED's guard **false** — so none of them ever reaches
        `cache user`, and none would notice if the fixture lost the cache budget
        that makes mode A able to run it at all. Measured: without that budget
        this is `FAIL 2/4 policy outcome — A=failed B=completed`, which is the
        standing divergence three of these cases used to pass on.

        Empty payload, so `token missing` is true and the guarded step executes.
        """
        doc = lower(parse(GUARDED), "t").to_document()
        ok, report = self._verify(doc, "wf.w", {},
                                  {"entity.user": dict(PAYLOAD)})
        self.assertTrue(ok, "\n".join(report))
        # And the guarded step really did run — otherwise the assertion above
        # would hold for a workflow that skipped the effect entirely.
        b = differential.observe_mode_b(doc, "wf.w", self.workdir)
        self.assertIn("cache user", b["text"])

    def test_reordered_backend_is_reported_as_divergent(self):
        doc = golden()
        ok, _report = self._verify(doc, "wf.login", PAYLOAD, rows_for(doc))
        self.assertTrue(ok, "baseline must be equivalent before the fault")

        original = self.original

        def reversed_order(nodes, ids, out):
            got = original(nodes, ids, [])
            out.extend(reversed(got))
            return out

        backend._steps_in_order = reversed_order
        ok, report = self._verify(doc, "wf.login", PAYLOAD, rows_for(doc))
        self.assertFalse(ok, "a reversed backend must not compare as equivalent")
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)

    def test_dropped_effect_in_the_backend_is_reported_as_divergent(self):
        doc = golden()
        ok, _report = self._verify(doc, "wf.login", PAYLOAD, rows_for(doc))
        self.assertTrue(ok, "baseline must be equivalent before the fault")

        original = self.original

        def without_effects(nodes, ids, out):
            got = original(nodes, ids, [])
            for step, cond in got:
                stripped = {k: v for k, v in step.items() if k != "children"}
                out.append((stripped, cond))
            return out

        backend._steps_in_order = without_effects
        ok, report = self._verify(doc, "wf.login", PAYLOAD, rows_for(doc))
        self.assertFalse(ok)
        self.assertTrue(any("FAIL 3/4" in line for line in report), report)

    def test_when_guard_removed_diverges(self):
        """A `when` guard that evaluates false must actually skip its step.

        The payload carries `token`, so `when token missing` is **false** and the
        guarded step is skipped — `skip=True` tells mode B the same. With the
        guard satisfied instead, removing it would change nothing observable and
        this case would prove nothing, which is how it read before.
        """
        doc = lower(parse(GUARDED), "t").to_document()
        payload = dict(PAYLOAD, token="present")
        rows = {"entity.user": dict(PAYLOAD)}

        ok, _report = self._verify(doc, "wf.w", payload, rows, skip=True)
        self.assertTrue(ok, "baseline must be equivalent before the fault")

        original = self.original

        def without_when(nodes, ids, out):
            for step, cond in original(nodes, ids, []):
                out.append((step, None)
                           if isinstance(cond, tuple) and cond[0] == "when"
                           else (step, cond))
            return out

        backend._steps_in_order = without_when
        ok, report = self._verify(doc, "wf.w", payload, rows, skip=True)
        self.assertFalse(ok, "removing the when guard must diverge")
        # Both classes: an extra step is an order difference *and* an extra
        # effect. Asserting only one lets the other silently stop appearing.
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)
        self.assertTrue(any("FAIL 3/4" in line for line in report), report)

    def test_until_guard_removed_diverges(self):
        """`counter=100` satisfies `until counter >= 10`, so neither mode loops.

        Removing the guard makes mode B run the unrolled body anyway. This uses
        `UNTIL_COUNTER` because `GUARDED` has no `until` at all — against it this
        fault was a no-op and the case passed on an unrelated divergence.
        """
        doc = lower(parse(UNTIL_COUNTER), "t").to_document()
        payload = {"counter": 100}
        rows = {"entity.workflow": dict(payload)}

        ok, _report = self._verify(doc, "wf.w", payload, rows)
        self.assertTrue(ok, "baseline must be equivalent before the fault")

        original = self.original

        def without_until(nodes, ids, out):
            for step, cond in original(nodes, ids, []):
                out.append((step, None)
                           if isinstance(cond, tuple) and cond[0] == "until"
                           else (step, cond))
            return out

        backend._steps_in_order = without_until
        ok, report = self._verify(doc, "wf.w", payload, rows)
        self.assertFalse(ok, "removing the until guard must diverge")
        # Both classes, for the same reason as the `when` case above.
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)
        self.assertTrue(any("FAIL 3/4" in line for line in report), report)

    def test_until_round_cap_violation_diverges(self):
        """`counter=0` leaves the condition false, so both modes run the cap.

        Mode B unrolling to a different cap is then a visible step-count
        mismatch. Also `UNTIL_COUNTER`, for the same reason as above.
        """
        doc = lower(parse(UNTIL_COUNTER), "t").to_document()
        payload = {"counter": 0}
        rows = {"entity.workflow": dict(payload)}

        ok, _report = self._verify(doc, "wf.w", payload, rows)
        self.assertTrue(ok, "baseline must be equivalent before the fault")

        original = self.original

        def with_wrong_cap(nodes, ids, out):
            old_cap = backend._UNTIL_ROUND_CAP
            backend._UNTIL_ROUND_CAP = 8
            try:
                out.extend(original(nodes, ids, []))
            finally:
                backend._UNTIL_ROUND_CAP = old_cap
            return out

        backend._steps_in_order = with_wrong_cap
        ok, report = self._verify(doc, "wf.w", payload, rows)
        self.assertFalse(ok, "an unrolled cap that disagrees with mode A must diverge")
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)


NO_TTL_CACHE = """
capability postgres
capability redis
entity User
    field
        id UUID
        email Email
service S
workflow W
    load user
    cache user
"""

TTL_CACHE = NO_TTL_CACHE.replace(
    "service S\n", "service S\n    performance\n        cache 5m\n", 1)


@NEEDS_TOOLS
class TestModeBDoesNotEnforceTheCacheTtlContract(unittest.TestCase):
    """A known mode A/B gap, pinned so fixing GUARDED does not hide it.

    RFC-0003 requires every cache key to carry a TTL. Mode A enforces it — its
    `Cache.set` raises `RunError` when the budget is absent. Mode B does not
    enforce it at all: the generated C shim prints the effect and returns 0. So
    a workflow whose `CacheAccess set` has no budget really does make the two
    modes disagree, and the differential really does say so.

    This was not a hypothesis. It is why `GUARDED` was divergent before any test
    touched it, and why three deliberate-mismatch cases passed for months on a
    divergence none of them caused. Giving `GUARDED` a budget fixed those tests
    and would have made the gap invisible again; this class keeps it visible.

    **When this class goes red, mode B has learned to enforce the contract.**
    That is the signal to close issue #9 and invert these assertions — not to
    weaken them.
    """

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-ttl-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _doc(self, src):
        return lower(parse(src), "t").to_document()

    def test_the_differential_reports_the_disagreement(self):
        doc = self._doc(NO_TTL_CACHE)
        ok, report = differential.verify(
            doc, "wf.w", {}, {"entity.user": dict(PAYLOAD)}, self.workdir)
        self.assertFalse(ok)
        # The class, not merely falsity: the disagreement must be the policy
        # outcome, which is where a refused run shows up.
        self.assertTrue(any("FAIL 2/4" in line for line in report), report)

    def test_mode_a_refuses_only_when_the_budget_is_missing(self):
        """Assert the pair — `status failed` alone would not be about the TTL.

        `observe_mode_a` returns order, effects, status and text; the RunError
        message never reaches the caller. So a lone `status failed` is satisfied
        by any unrelated failure — a missing repository row produces exactly the
        same string. Running both sources makes the budget the only variable.
        """
        rows = {"entity.user": dict(PAYLOAD)}
        without = differential.observe_mode_a(
            self._doc(NO_TTL_CACHE), "wf.w", {}, rows)
        with_budget = differential.observe_mode_a(
            self._doc(TTL_CACHE), "wf.w", {}, rows)
        self.assertIn("status failed", without["text"])
        self.assertIn("status completed", with_budget["text"])

    def test_adding_a_ttl_budget_makes_the_two_modes_agree(self):
        """Control. Without this, the two tests above could be about anything."""
        doc = self._doc(TTL_CACHE)
        ok, report = differential.verify(
            doc, "wf.w", {}, {"entity.user": dict(PAYLOAD)}, self.workdir)
        self.assertTrue(ok, "\n".join(report))


class TestToolchainHonesty(unittest.TestCase):
    def test_missing_toolchain_raises_instead_of_silently_skipping(self):
        original = backend.toolchain_available
        backend.toolchain_available = lambda: False
        differential.backend.toolchain_available = lambda: False
        try:
            with self.assertRaises(differential.DifferentialError) as ctx:
                differential.verify(golden(), "wf.login", PAYLOAD, {}, self.workdir())
            self.assertIn("brew install llvm", str(ctx.exception))
        finally:
            backend.toolchain_available = original
            differential.backend.toolchain_available = original

    def workdir(self):
        return os.path.join(REPO, ".claude", "tmp", "unused")


if __name__ == "__main__":
    unittest.main()
