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
from lnpl.interp import MAX_STEP_ATTEMPTS as _MAX
from lnpl.interp import refinement_index, sample_payload
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import (READ_OPS, default_rows, repository_calls,
                              seeded_entities)
from lnpl.repo_policy import row_key
from tests.fixtures import (ALT_GUARD_APPROVE, CHECKOUT_LNPL, GUARD_ARITH,
                            GUARDED, PRICE_INVENTORY, UNTIL_COUNTER,
                            VALUE_INVENTORY, VALUE_PAYMENT, guarded_source)

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


# Seeds come from `repo_policy.default_rows(doc, workflow, payload)` — the one
# seeding rule (issue #35). It is called with the payload each run actually uses,
# never with the `PAYLOAD` constant by default: `row_key` derives from the run's
# payload, so seeding a `{}` run from `PAYLOAD` files the row under
# `entity.user#3f25…` while the read looks for `entity.user#-`.


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
                                         default_rows(doc, "wf.login", PAYLOAD),
                                         self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertIn("differential: EQUIVALENT", report[-1])

    def test_all_four_observable_classes_are_checked(self):
        doc = golden()
        _ok, report = differential.verify(doc, "wf.login", PAYLOAD,
                                          default_rows(doc, "wf.login", PAYLOAD),
                                          self.workdir)
        for n in ("1/4", "2/4", "3/4", "4/4"):
            self.assertTrue(any(n in line for line in report), n)

    def test_secrets_do_not_reach_either_mode_output(self):
        doc = golden()
        a = differential.observe_mode_a(doc, "wf.login", PAYLOAD,
                                        default_rows(doc, "wf.login", PAYLOAD))
        b = differential.observe_mode_b(doc, "wf.login", self.workdir)
        self.assertNotIn("s3cret", a["text"])
        self.assertNotIn("s3cret", b["text"])

    def test_presence_guard_with_key_absent_is_equivalent(self):
        """RFC-0008: Presence guard 'when field missing' with absent field.

        When the guarded field is absent from the payload, the condition evaluates
        to true, and both modes should execute the guarded step. The skip value is
        derived from the payload (issue #12), not supplied by the caller.
        """
        doc = lower(parse(GUARDED), "t").to_document()
        # Empty payload: token is missing, so 'token missing' is true, step runs
        ok, report = differential.verify(
            doc, "wf.w", {}, default_rows(doc, "wf.w", {}), self.workdir)
        self.assertTrue(ok, "\n".join(report))
        # Verify the guarded step actually ran
        b = differential.observe_mode_b(doc, "wf.w", self.workdir, payload={})
        self.assertIn("cache user", b["text"])

    def test_presence_guard_with_key_present_is_equivalent(self):
        """RFC-0008: Presence guard 'when field missing' with present field.

        When the guarded field is present in the payload, the condition evaluates
        to false, and both modes should skip the guarded step. The skip value is
        derived from the payload (issue #12), not supplied by the caller.
        """
        doc = lower(parse(GUARDED), "t").to_document()
        payload = {"token": "present"}  # token is present
        # With token present, 'token missing' is false, step is skipped
        ok, report = differential.verify(
            doc, "wf.w", payload, default_rows(doc, "wf.w", payload), self.workdir)
        self.assertTrue(ok, "\n".join(report))
        # Verify the guarded step was skipped (no cache effect)
        b = differential.observe_mode_b(doc, "wf.w", self.workdir, payload=payload)
        self.assertNotIn("cache user", b["text"])


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

    def _verify(self, doc, workflow, payload, rows):
        return differential.verify(doc, workflow, payload, rows, self.workdir)

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
                                  default_rows(doc, "wf.w", {}))
        self.assertTrue(ok, "\n".join(report))
        # And the guarded step really did run — otherwise the assertion above
        # would hold for a workflow that skipped the effect entirely.
        b = differential.observe_mode_b(doc, "wf.w", self.workdir)
        self.assertIn("cache user", b["text"])

    def test_reordered_backend_is_reported_as_divergent(self):
        doc = golden()
        rows = default_rows(doc, "wf.login", PAYLOAD)
        ok, _report = self._verify(doc, "wf.login", PAYLOAD, rows)
        self.assertTrue(ok, "baseline must be equivalent before the fault")

        original = self.original

        def reversed_order(nodes, ids, out):
            got = original(nodes, ids, [])
            out.extend(reversed(got))
            return out

        backend._steps_in_order = reversed_order
        ok, report = self._verify(doc, "wf.login", PAYLOAD, rows)
        self.assertFalse(ok, "a reversed backend must not compare as equivalent")
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)

    def test_dropped_effect_in_the_backend_is_reported_as_divergent(self):
        doc = golden()
        rows = default_rows(doc, "wf.login", PAYLOAD)
        ok, _report = self._verify(doc, "wf.login", PAYLOAD, rows)
        self.assertTrue(ok, "baseline must be equivalent before the fault")

        original = self.original

        def without_effects(nodes, ids, out):
            got = original(nodes, ids, [])
            for step, cond in got:
                stripped = {k: v for k, v in step.items() if k != "children"}
                out.append((stripped, cond))
            return out

        backend._steps_in_order = without_effects
        ok, report = self._verify(doc, "wf.login", PAYLOAD, rows)
        self.assertFalse(ok)
        self.assertTrue(any("FAIL 3/4" in line for line in report), report)

    def test_when_guard_removed_diverges(self):
        """A `when` guard that evaluates false must actually skip its step.

        The payload carries `token`, so `when token missing` is **false** and the
        guarded step is skipped. The skip value is derived from evaluating the
        condition against the payload (RFC-0008).

        The payload holds only fields `GUARDED`'s entity declares: masking is
        type-driven, so an undeclared `password` key would ride the seeded row
        into the bindings channel verbatim — and issue #43's widened masking
        surface rightly reports that as a leak, failing the baseline for a
        reason unrelated to the guard under test.
        """
        doc = lower(parse(GUARDED), "t").to_document()
        payload = {"id": PAYLOAD["id"], "email": PAYLOAD["email"],
                   "token": "present"}
        rows = default_rows(doc, "wf.w", payload)

        ok, _report = self._verify(doc, "wf.w", payload, rows)
        self.assertTrue(ok, "baseline must be equivalent before the fault")

        original = self.original

        def without_when(nodes, ids, out):
            for step, cond in original(nodes, ids, []):
                out.append((step, None)
                           if isinstance(cond, tuple) and cond[0] == "when"
                           else (step, cond))
            return out

        backend._steps_in_order = without_when
        ok, report = self._verify(doc, "wf.w", payload, rows)
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
        rows = default_rows(doc, "wf.w", payload)

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
        rows = default_rows(doc, "wf.w", payload)

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
class TestModeBEnforcesTheCacheTtlContract(unittest.TestCase):
    """Mode B now enforces RFC-0003's cache-TTL contract, as mode A always did.

    RFC-0003 requires every cache key to carry a TTL. Mode A enforces it — its
    `Cache.set` raises `RunError` when the budget is absent, so the run's status
    becomes `failed`. Mode B used to print the effect and complete, so a workflow
    whose `CacheAccess set` had no budget made the two modes disagree, and the
    differential said so (`FAIL 2/4 policy outcome — A=failed B=completed`). That
    standing divergence is why `GUARDED` was divergent before any test touched it,
    and why three deliberate-mismatch cases passed for months on a divergence none
    of them caused.

    Issue #9 closed the gap. Budget presence is a compile-time property of the
    owning service, so mode B stops at the first unbudgeted `CacheAccess set` and
    reports `failed` too, reaching the same observable outcome. Per the pin's own
    instruction, these assertions were **inverted** the moment mode B learned to
    enforce — they now assert the two modes AGREE (both refuse without a budget,
    both complete with one), not weakened away.
    """

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-ttl-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _doc(self, src):
        return lower(parse(src), "t").to_document()

    def test_the_differential_reports_equivalence_now_both_modes_refuse(self):
        """Inverted from the gap form (was `assertFalse(ok)` + `FAIL 2/4`).

        Both modes now fail on the budget-less workflow, so the differential is
        EQUIVALENT — and specifically on the policy-outcome axis (PASS 2/4), which
        is where a refused run shows up. A bare EQUIVALENT could be any agreeing
        pair, so the second half proves they agree by *failing*, not by running
        clean: mode A raises and mode B returns non-zero, both surfacing as
        `status failed`.
        """
        doc = self._doc(NO_TTL_CACHE)
        rows = default_rows(doc, "wf.w", {})
        ok, report = differential.verify(doc, "wf.w", {}, rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertTrue(any("PASS 2/4" in line for line in report), report)
        a = differential.observe_mode_a(doc, "wf.w", {}, rows)
        b = differential.observe_mode_b(doc, "wf.w", self.workdir, payload={})
        self.assertIn("status failed", a["text"])
        self.assertIn("status failed", b["text"])

    def test_both_modes_refuse_without_the_budget_and_complete_with_it(self):
        """Assert the pair in both modes — `status failed` alone would not be about
        the TTL, since any unrelated failure produces the same string. The budget
        is the only variable, and now BOTH modes track it (mode B used to complete
        the budget-less run regardless).
        """
        no_ttl, ttl = self._doc(NO_TTL_CACHE), self._doc(TTL_CACHE)
        a_without = differential.observe_mode_a(
            no_ttl, "wf.w", {}, default_rows(no_ttl, "wf.w", {}))
        a_with = differential.observe_mode_a(
            ttl, "wf.w", {}, default_rows(ttl, "wf.w", {}))
        b_without = differential.observe_mode_b(
            no_ttl, "wf.w", self.workdir, payload={})
        b_with = differential.observe_mode_b(
            ttl, "wf.w", self.workdir, payload={})
        self.assertIn("status failed", a_without["text"])
        self.assertIn("status completed", a_with["text"])
        self.assertIn("status failed", b_without["text"])
        self.assertIn("status completed", b_with["text"])

    def test_adding_a_ttl_budget_makes_the_two_modes_agree(self):
        """Control. Without this, the two tests above could be about anything."""
        doc = self._doc(TTL_CACHE)
        ok, report = differential.verify(
            doc, "wf.w", {}, default_rows(doc, "wf.w", {}), self.workdir)
        self.assertTrue(ok, "\n".join(report))

    def test_effects_after_the_unbudgeted_set_are_not_emitted(self):
        """A step's effects run in order; mode A stops AT the cache set (its span
        holds the effects up to and including it, none after). Mode B must truncate
        the failing step's effects there too — otherwise a multi-effect step makes
        mode B emit an effect mode A never reached, and the differential diverges on
        a workflow the modes actually agree on. Here an Authorization is appended
        AFTER the cache set; neither mode may report it."""
        doc = self._doc(NO_TTL_CACHE)
        cache_set = next(n for n in doc["nodes"]
                         if n["kind"] == "CacheAccess" and n.get("operation") == "set")
        step = next(n for n in doc["nodes"]
                    if n["kind"] == "WorkflowStep"
                    and cache_set["id"] in n.get("children", []))
        doc["nodes"].append({"kind": "Authorization",
                             "id": step["id"] + ".after", "requirement": "x"})
        step["children"] = list(step.get("children", [])) + [step["id"] + ".after"]
        rows = default_rows(doc, "wf.w", {})
        a = differential.observe_mode_a(doc, "wf.w", {}, rows)
        b = differential.observe_mode_b(doc, "wf.w", self.workdir, payload={})
        self.assertNotIn("Authorization", a["effects"].get(step["name"], []))
        self.assertNotIn("Authorization", b["effects"].get(step["name"], []))
        self.assertEqual(a["effects"], b["effects"])
        self.assertEqual(a["status"], "failed")
        self.assertEqual(b["status"], "failed")


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


class TestVersionPin(unittest.TestCase):
    """RFC-0004 OQ①: mlir/llvm.pin is the single machine-read version source.

    The version literal lives in exactly one committed file, and something reads
    it. There is no CI in this repo, so the reader is this test plus the toolchain
    helper — the "선언이 둘이면 갈라진다" principle held with one declaration.
    """

    def test_pin_parses_to_a_dotted_version(self):
        version = backend.pinned_llvm_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_malformed_pin_raises_backend_error(self):
        tmpdir = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(tmpdir, exist_ok=True)
        original = backend.LLVM_PIN_PATH
        for bad in ("clang 1.2.3\n", "22.1.8\n", "llvm 1 2\n", "\n"):
            fd, path = tempfile.mkstemp(dir=tmpdir, suffix=".pin")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(bad)
            backend.LLVM_PIN_PATH = path
            try:
                with self.assertRaises(backend.BackendError):
                    backend.pinned_llvm_version()
            finally:
                backend.LLVM_PIN_PATH = original
                os.remove(path)

    def test_pin_matches_installed_toolchain(self):
        if not backend.toolchain_available():
            self.skipTest("MLIR/LLVM toolchain not installed")
        version = backend.pinned_llvm_version()
        out = backend._run([backend.tool("mlir-opt"), "--version"],
                           "version pin check")
        self.assertIn(version, out)


class _FakeProc:
    """Stand-in for `subprocess.CompletedProcess`, for monkeypatching
    `backend.subprocess.run` without shelling out to a real `xcrun`."""

    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestLlvmBinOverride(unittest.TestCase):
    """`LNPL_LLVM_BIN` (issue #104): a directory override `tool()` must prefer
    over the hardcoded `BREW_LLVM_BIN` keg-only path — same discovery-order
    contract as the diagnostic hooks' `$LNPL_BIN`.
    """

    def setUp(self):
        tmp_root = os.path.join(REPO, ".claude", "tmp")
        self.override_dir = tempfile.mkdtemp(prefix="lnpl-llvmbin-", dir=tmp_root)
        self.brew_dir = tempfile.mkdtemp(prefix="lnpl-brewbin-", dir=tmp_root)
        self._original_brew_bin = backend.BREW_LLVM_BIN
        # 호출자의 값을 저장해 tearDown이 복원한다 — pop으로 지우기만 하면
        # LNPL_LLVM_BIN으로만 툴체인이 해석되는 환경(GitHub 러너)에서 이후의
        # 모든 mode-B 테스트가 toolchain unavailable로 죽는다 (issue #169).
        self._original_llvm_bin = os.environ.get("LNPL_LLVM_BIN")
        backend.BREW_LLVM_BIN = self.brew_dir
        self._write_executable(self.override_dir, "toolx")
        self._write_executable(self.brew_dir, "toolx")

    def tearDown(self):
        backend.BREW_LLVM_BIN = self._original_brew_bin
        shutil.rmtree(self.override_dir, ignore_errors=True)
        shutil.rmtree(self.brew_dir, ignore_errors=True)
        if self._original_llvm_bin is None:
            os.environ.pop("LNPL_LLVM_BIN", None)
        else:
            os.environ["LNPL_LLVM_BIN"] = self._original_llvm_bin

    def _write_executable(self, dirpath, name):
        path = os.path.join(dirpath, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, 0o755)
        return path

    def test_lnpl_llvm_bin_override_wins_over_the_homebrew_fallback(self):
        os.environ["LNPL_LLVM_BIN"] = self.override_dir
        found = backend.tool("toolx")
        self.assertEqual(found, os.path.join(self.override_dir, "toolx"))

    def test_empty_lnpl_llvm_bin_is_treated_as_unset(self):
        os.environ["LNPL_LLVM_BIN"] = ""
        found = backend.tool("toolx")
        self.assertEqual(found, os.path.join(self.brew_dir, "toolx"))

    def test_missing_tool_error_names_the_llvm_bin_override(self):
        os.environ["LNPL_LLVM_BIN"] = self.override_dir
        with self.assertRaises(backend.BackendError) as ctx:
            backend.tool("no-such-tool-xyz")
        self.assertIn("LNPL_LLVM_BIN", str(ctx.exception))


class TestLlvmBinOverrideRestoresCallerEnv(unittest.TestCase):
    """issue #169: 위 클래스가 호출자의 `LNPL_LLVM_BIN`을 파괴하면 안 된다.

    GitHub 러너에서는 툴체인이 오직 이 변수로만 해석된다(브루 폴백 경로 없음,
    PATH에 mlir-opt 없음). tearDown이 원래 값을 복원하지 않고 pop만 하면,
    test_backend 이후에 도는 모든 mode-B 테스트가 "toolchain unavailable"로
    죽는다 — mutation baseline RED(failures=26/errors=96, run 33701577052)의
    실측 원인. macOS에서는 브루 폴백이 가려서 보이지 않는다.
    """

    def _run_override_suite(self):
        import io
        suite = unittest.TestLoader().loadTestsFromTestCase(TestLlvmBinOverride)
        return unittest.TextTestRunner(stream=io.StringIO()).run(suite)

    def test_a_set_value_survives_the_override_suite(self):
        original = os.environ.get("LNPL_LLVM_BIN")
        if original is None:
            self.addCleanup(os.environ.pop, "LNPL_LLVM_BIN", None)
        else:
            self.addCleanup(os.environ.__setitem__, "LNPL_LLVM_BIN", original)
        os.environ["LNPL_LLVM_BIN"] = "SENTINEL-DIR"
        result = self._run_override_suite()
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(os.environ.get("LNPL_LLVM_BIN"), "SENTINEL-DIR",
                         "TestLlvmBinOverride가 호출자의 LNPL_LLVM_BIN을 "
                         "복원하지 않았다 — 러너에서 이후의 모든 mode-B "
                         "테스트가 toolchain unavailable로 죽는 오염이다.")

    def test_an_unset_variable_stays_unset(self):
        original = os.environ.pop("LNPL_LLVM_BIN", None)
        if original is not None:
            self.addCleanup(os.environ.__setitem__, "LNPL_LLVM_BIN", original)
        result = self._run_override_suite()
        self.assertTrue(result.wasSuccessful())
        self.assertIsNone(os.environ.get("LNPL_LLVM_BIN"),
                          "미설정이던 변수가 실행 후 생겨났다")


class TestIsysrootFlags(unittest.TestCase):
    """S7 (issue #104): `-isysroot`, computed via `xcrun`, is what lets the S7
    clang invocation survive a machine whose CommandLineTools SDK differs from
    the one baked into the homebrew clang bottle at build time (the exact
    failure this machine reproduces without the fix). `xcrun` is monkeypatched
    here so these cases run without shelling out; the real end-to-end
    `lnpl build --run` on this machine is the separate integration check.
    """

    def setUp(self):
        self._original_platform = backend.sys.platform
        self._original_run = backend.subprocess.run

    def tearDown(self):
        backend.sys.platform = self._original_platform
        backend.subprocess.run = self._original_run

    def test_darwin_adds_isysroot_from_xcrun(self):
        backend.sys.platform = "darwin"
        sdk_dir = tempfile.mkdtemp(prefix="lnpl-sdk-",
                                   dir=os.path.join(REPO, ".claude", "tmp"))
        try:
            backend.subprocess.run = lambda *a, **k: _FakeProc(0, sdk_dir + "\n")
            self.assertEqual(backend._isysroot_flags(), ["-isysroot", sdk_dir])
        finally:
            shutil.rmtree(sdk_dir, ignore_errors=True)

    def test_non_darwin_adds_no_isysroot(self):
        backend.sys.platform = "linux"
        self.assertEqual(backend._isysroot_flags(), [])

    def test_xcrun_failure_raises_backend_error_with_hints(self):
        backend.sys.platform = "darwin"
        backend.subprocess.run = lambda *a, **k: _FakeProc(
            1, "", "xcrun: error: SDK \"macosx\" cannot be located")
        with self.assertRaises(backend.BackendError) as ctx:
            backend._isysroot_flags()
        message = str(ctx.exception)
        self.assertIn("xcrun", message)
        self.assertIn("LNPL_LLVM_BIN", message)

    def test_xcrun_reports_a_sdk_path_that_does_not_exist(self):
        backend.sys.platform = "darwin"
        backend.subprocess.run = lambda *a, **k: _FakeProc(
            0, "/nonexistent/sdk/path\n")
        with self.assertRaises(backend.BackendError) as ctx:
            backend._isysroot_flags()
        message = str(ctx.exception)
        self.assertIn("xcrun", message)
        self.assertIn("LNPL_LLVM_BIN", message)


class TestDiffCliWiring(unittest.TestCase):
    """`cmd_diff` wires argparse into `differential.verify`. The suite otherwise
    calls `verify` directly, so a signature drift between the CLI and the function
    (e.g. a stale `skip=` kwarg) went unnoticed until the command crashed on every
    invocation. These tests exercise the CLI path itself.
    """

    from argparse import Namespace

    LOGIN = os.path.join(REPO, "examples", "login.lnpl")

    def _args(self, **over):
        base = dict(source=self.LOGIN, workflow=None,
                    workdir=os.path.join(REPO, ".claude", "tmp", "diff-cli-test"),
                    payload=None, no_row=False)
        base.update(over)
        return self.Namespace(**base)

    def test_arg_wiring_has_no_stale_kwargs(self):
        """Regression: cmd_diff must not pass a kwarg verify() rejects. This binds
        even without the toolchain — a bad kwarg raises TypeError at call time,
        before verify() can gate on toolchain availability."""
        from lnpl import cli, differential
        try:
            cli.cmd_diff(self._args())
        except TypeError as exc:
            self.fail("cmd_diff passes an argument verify() rejects: %s" % exc)
        except differential.DifferentialError:
            pass  # toolchain absent — the arg binding still succeeded, which is the point

    @NEEDS_TOOLS
    def test_login_diff_returns_zero(self):
        from lnpl import cli
        self.assertEqual(cli.cmd_diff(self._args()), 0)

    @NEEDS_TOOLS
    def test_payload_flag_is_honored(self):
        """A payload whose entity fields differ from the default must be read from
        the file, not silently replaced by DEFAULT_PAYLOAD."""
        from lnpl import cli
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(PAYLOAD, fh)
            path = fh.name
        try:
            self.assertEqual(cli.cmd_diff(self._args(payload=path)), 0)
        finally:
            os.unlink(path)


# --- issue #35 Wave 2: mode B's repository-outcome derivation -----------------
#
# Two-entity fixtures, inline: `examples/checkout.*` is t3's this wave, so these
# cannot depend on it. `Product` is READ and `Order` is only CREATED — the two
# roles `repo_policy`'s role-based seed tells apart, and the pair a single-entity
# example can never exercise.

READ_THEN_CREATE = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
entity Order
    field
        id UUID
        total Money
service CheckoutService
workflow Checkout
    find product
    create order
"""

# Read and create the SAME entity. The seed rule seeds what the workflow reads,
# so `entity.product` starts with a row and the create conflicts — a conflict
# reachable under the DEFAULT policy, with no extra seed input.
SAME_ENTITY = READ_THEN_CREATE.replace("    create order\n",
                                       "    create product\n")

# No RepositoryCall at all — the zero-call boundary.
NO_REPO = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
service CheckoutService
workflow Checkout
    validate product
"""

# Create-only: nothing is read, so nothing is seeded and the create inserts.
CREATE_ONLY = """
capability postgres
entity Order
    field
        id UUID
        total Money
service CheckoutService
workflow Checkout
    create order
"""


def checkout_doc(src):
    return lower(parse(src), "checkout").to_document()


def op_names(ops):
    return [op["name"] for op in ops]


class TestModeBDerivesRepositoryOutcomes(unittest.TestCase):
    """Mode B reaches the repository outcome statically (issue #35).

    No toolchain: these read the op stream `_lnpl_ops` builds, which is where the
    derivation lives. Gating them on the toolchain would let the whole class skip
    silently on a machine without LLVM — the failure mode that hid this bug.
    """

    def test_read_then_create_completes_under_the_default_seed(self):
        attrs, ops = backend._lnpl_ops(checkout_doc(READ_THEN_CREATE),
                                       "wf.checkout")
        self.assertEqual(op_names(ops), ["find product", "create order"])
        self.assertNotIn("lnpl.terminal_status", attrs)
        self.assertEqual([len(op["effects"]) for op in ops], [1, 1])

    def test_an_unseeded_read_fails_and_truncates_at_that_step(self):
        attrs, ops = backend._lnpl_ops(checkout_doc(READ_THEN_CREATE),
                                       "wf.checkout", seeded=frozenset())
        self.assertEqual(op_names(ops), ["find product"])
        self.assertEqual(attrs["lnpl.terminal_status"], "failed")
        # Inclusive of the failing effect, exclusive of everything after it.
        self.assertEqual([e["kind"] for e in ops[0]["effects"]],
                         ["RepositoryCall"])

    def test_a_create_on_a_seeded_entity_conflicts(self):
        attrs, ops = backend._lnpl_ops(checkout_doc(SAME_ENTITY), "wf.checkout")
        self.assertEqual(op_names(ops), ["find product", "create product"])
        self.assertEqual(attrs["lnpl.terminal_status"], "failed")
        self.assertEqual([e["kind"] for e in ops[-1]["effects"]],
                         ["RepositoryCall"])

    def test_an_earlier_create_makes_a_later_create_conflict(self):
        """The `created` accumulation, not just the seed set: `create order`
        twice conflicts on the second, because the first inserted the only key
        this run can address (repo_policy's single-key invariant)."""
        src = READ_THEN_CREATE.replace("    create order\n",
                                       "    create order\n    create order\n")
        attrs, ops = backend._lnpl_ops(checkout_doc(src), "wf.checkout")
        self.assertEqual(attrs["lnpl.terminal_status"], "failed")
        self.assertEqual(len(op_names(ops)), 3)

    def test_a_workflow_with_no_repository_call_is_unaffected(self):
        attrs, ops = backend._lnpl_ops(checkout_doc(NO_REPO), "wf.checkout",
                                       seeded=frozenset())
        self.assertEqual(op_names(ops), ["validate product"])
        self.assertNotIn("lnpl.terminal_status", attrs)

    def test_a_create_only_workflow_inserts_rather_than_conflicting(self):
        """The boundary the issue is about: an entity the workflow only creates
        is not seeded, so the create inserts. Seeding it — the pre-Wave-1
        behavior — made this `failed` under every seed."""
        attrs, ops = backend._lnpl_ops(checkout_doc(CREATE_ONLY), "wf.checkout")
        self.assertEqual(op_names(ops), ["create order"])
        self.assertNotIn("lnpl.terminal_status", attrs)

    def test_a_guarded_repository_call_never_forces_a_failure(self):
        """D8: a guarded effect may not be reached, so it must not fail the run
        statically. `when total missing` in front of the read means mode B leaves
        it alone even with nothing seeded."""
        src = READ_THEN_CREATE.replace("    find product\n",
                                       "    when total missing\n    find product\n")
        attrs, _ops = backend._lnpl_ops(checkout_doc(src), "wf.checkout",
                                        seeded=frozenset())
        self.assertNotIn("lnpl.terminal_status", attrs)

    def test_the_derived_outcome_matches_mode_a_on_a_read_miss(self):
        """The derivation is only worth anything if it agrees with the mode it is
        derived to match. Mode A is run here with an empty store — the same seed
        condition mode B is given — and its trace is compared to mode B's ops."""
        d = checkout_doc(READ_THEN_CREATE)
        payload = sample_payload([n for n in d["nodes"] if n["kind"] == "Entity"])
        a = differential.observe_mode_a(d, "wf.checkout", payload, {})
        attrs, ops = backend._lnpl_ops(d, "wf.checkout", seeded=frozenset())
        self.assertEqual(a["status"], "failed")
        self.assertEqual(op_names(ops), a["order"])
        self.assertEqual({op["name"]: [e["kind"] for e in op["effects"]]
                          for op in ops}, a["effects"])


# Issue #48: a refinement facet (`PositiveInteger`, min 1) on the SECOND entity,
# behind a `validate order` step. Mode B derives the validation outcome at build
# time from the payload it is specialised against, exactly as it derives
# repository outcomes from the seed (issue #35).
VALIDATED_ORDER = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
entity Order
    field
        id UUID
        quantity PositiveInteger
service OrderService
    policy
        retry 1
workflow PlaceOrder
    validate order
    create order
"""


class TestModeBDerivesValidationOutcomes(unittest.TestCase):
    """Mode B reaches the validation outcome statically (issue #48).

    No toolchain, same as the repository-outcome class: the derivation lives in
    the op stream `_lnpl_ops` builds.
    """

    def _doc(self):
        return checkout_doc(VALIDATED_ORDER)

    def _payload(self, **overrides):
        doc = self._doc()
        payload = sample_payload([n for n in doc["nodes"]
                                  if n["kind"] == "Entity"],
                                 refinement_index(doc))
        payload.update(overrides)
        for name, value in list(overrides.items()):
            if value is ...:
                del payload[name]
        return doc, payload

    def test_a_facet_violating_payload_fails_at_the_validate_step(self):
        doc, payload = self._payload(quantity=0)
        attrs, ops = backend._lnpl_ops(doc, "wf.place.order", payload=payload)
        self.assertEqual(op_names(ops), ["validate order"])
        self.assertEqual(attrs["lnpl.terminal_status"], "failed")
        # retry 1 -> two attempts, one copy of the failing effect per attempt.
        self.assertEqual([e["kind"] for e in ops[0]["effects"]],
                         ["Validation", "Validation"])

    def test_a_valid_payload_completes(self):
        doc, payload = self._payload(quantity=1)
        attrs, ops = backend._lnpl_ops(doc, "wf.place.order", payload=payload)
        self.assertEqual(op_names(ops), ["validate order", "create order"])
        self.assertNotIn("lnpl.terminal_status", attrs)

    def test_a_missing_required_field_fails(self):
        doc, payload = self._payload(quantity=...)
        attrs, ops = backend._lnpl_ops(doc, "wf.place.order", payload=payload)
        self.assertEqual(attrs["lnpl.terminal_status"], "failed")
        self.assertEqual(op_names(ops), ["validate order"])

    def test_no_payload_derives_the_sample_and_completes(self):
        # D6: `payload=None` means the same derived sample mode A's default run
        # uses (cli.cmd_run) — valid by construction, so nothing fails.
        attrs, ops = backend._lnpl_ops(self._doc(), "wf.place.order")
        self.assertEqual(op_names(ops), ["validate order", "create order"])
        self.assertNotIn("lnpl.terminal_status", attrs)

    def test_the_derived_outcome_matches_mode_a_on_a_facet_violation(self):
        """Anti-drift: the derivation must agree with the mode it models —
        status, step order, and per-attempt effect replication."""
        doc, payload = self._payload(quantity=0)
        a = differential.observe_mode_a(doc, "wf.place.order", payload, {})
        attrs, ops = backend._lnpl_ops(doc, "wf.place.order", payload=payload)
        self.assertEqual(a["status"], "failed")
        self.assertEqual(attrs["lnpl.terminal_status"], "failed")
        self.assertEqual(op_names(ops), a["order"])
        self.assertEqual({op["name"]: [e["kind"] for e in op["effects"]]
                          for op in ops}, a["effects"])


RETRY_TMPL = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
entity Order
    field
        id UUID
        total Money
service CheckoutService
%(policy)s
workflow Checkout
%(lead)s    find product
    create order
"""


def retry_doc(retry=None, timeout=None, lead=0):
    rules = []
    if retry is not None:
        rules.append("        retry %d" % retry)
    if timeout is not None:
        rules.append("        timeout %s" % timeout)
    policy = "    policy\n" + "\n".join(rules) + "\n" if rules else ""
    return checkout_doc(RETRY_TMPL % {
        "policy": policy,
        "lead": "".join("    validate product\n" for _ in range(lead))})


# `(timeout, lead)` cells where mode A's workflow deadline is exhausted before the
# repository call is reached — 20 lead steps cost 100ms, the whole `100ms` budget.
# Mode B models no workflow timeout (a gap that predates this task, pinned by
# `test_a_workflow_deadline_stops_mode_a_before_the_repository_call`), so those
# cells have no attempt count to compare. Listed, not detected: an exclusion the
# sweep discovered for itself could grow to cover a real regression.
DEADLINE_STARVED = {("100ms", 20)}


class TestModeBDerivesRetryAttempts(unittest.TestCase):
    """A retried failure repeats its effect span, and mode B must repeat it too.

    `interp._run_step` re-runs every effect the step owns on each attempt, and
    `_run_effect` appends the child span BEFORE the raise — so mode A's failing
    step holds one copy of the failing prefix per attempt. RFC-0004 §실행 모드와
    semantic equivalence puts that inside the contract twice: observable 2 is
    "정책 집행 결과 — retry 판정" and observable 3 is "관측성 신호 — trace 구조
    (step = span)". Emitting one copy makes `lnpl diff` report FAIL 3/4 on every
    retried repository failure.

    The attempt count is not `retry + 1`: `_retryable` also gates on the remaining
    deadline, so the backoff schedule and the clock both matter. The sweep below
    is the anti-drift device for the mirrored copy of that model — it compares the
    derivation against mode A rather than against a restatement of the rule.
    """

    def _derived(self, document, seeded=frozenset()):
        _attrs, ops = backend._lnpl_ops(document, "wf.checkout", seeded=seeded)
        return len(ops[-1]["effects"])

    def _observed(self, document, step, seeded_rows=None):
        payload = sample_payload([n for n in document["nodes"]
                                  if n["kind"] == "Entity"])
        rows = (default_rows(document, "wf.checkout", payload)
                if seeded_rows == "default" else {})
        return len(differential.observe_mode_a(
            document, "wf.checkout", payload, rows)["effects"][step])

    def test_derived_attempts_match_mode_a_across_the_policy_matrix(self):
        compared = 0
        for retry in (None, 0, 1, 3, 5):
            for timeout in (None, "3s", "1s", "500ms", "100ms"):
                for lead in (0, 2, 20):
                    if (timeout, lead) in DEADLINE_STARVED:
                        continue
                    with self.subTest(retry=retry, timeout=timeout, lead=lead):
                        d = retry_doc(retry=retry, timeout=timeout, lead=lead)
                        self.assertEqual(self._derived(d),
                                         self._observed(d, "find product"))
                    compared += 1
        # A sweep that silently stopped sweeping would pass. Pin the cell count so
        # the exclusion list cannot quietly widen.
        self.assertEqual(compared, 5 * 5 * 3 - len(DEADLINE_STARVED) * 5)

    def test_derived_attempts_match_mode_a_at_the_attempt_ceiling(self):
        """The matrix above tops out at `retry 5`, so it never reaches the ceiling.

        `MAX_STEP_ATTEMPTS` is the one bound that does not read `retry`, which is
        exactly why the mirror can lose it without any existing cell noticing.
        No `timeout` here on purpose: with a deadline the deadline gate fires
        first and the ceiling is never the bound under comparison.
        """
        for retry in (_MAX - 2, _MAX - 1, _MAX, _MAX * 2):
            with self.subTest(retry=retry):
                d = retry_doc(retry=retry, timeout=None, lead=0)
                derived, observed = self._derived(d), self._observed(d, "find product")
                self.assertEqual(derived, observed)
                self.assertEqual(observed, min(retry + 1, _MAX),
                                 "the ceiling is a backstop, not a clamp on "
                                 "budgets below it")

    def test_a_workflow_deadline_stops_mode_a_before_the_repository_call(self):
        """Characterises a gap this task does NOT close, and validates the
        exclusion above rather than trusting it.

        Mode B models no workflow `timeout`: `_lnpl_ops` emits every op regardless
        of how much of the budget the earlier steps consumed. Mode A stops the run
        the moment the deadline is exhausted, which for these cells happens before
        the repository call is ever reached — so there is no attempt count to
        compare. The two modes still disagree on observable 1 here, exactly as they
        did before this task; closing it is the timeout analogue of what issue #9
        did for the cache budget, and belongs to its own change.

        This test goes red the day mode B learns to model the deadline. That is the
        point: it should, and whoever does it should delete this.
        """
        for timeout, lead in sorted(DEADLINE_STARVED):
            with self.subTest(timeout=timeout, lead=lead):
                d = retry_doc(retry=3, timeout=timeout, lead=lead)
                payload = sample_payload([n for n in d["nodes"]
                                          if n["kind"] == "Entity"])
                a = differential.observe_mode_a(d, "wf.checkout", payload, {})
                _attrs, ops = backend._lnpl_ops(d, "wf.checkout",
                                                seeded=frozenset())
                self.assertEqual(a["status"], "failed")
                self.assertNotIn("find product", a["effects"])
                self.assertIn("find product", [op["name"] for op in ops])
                self.assertLess(len(a["order"]), len(ops))

    def test_retry_three_without_a_deadline_gives_four_attempts(self):
        self.assertEqual(self._derived(retry_doc(retry=3)), 4)

    def test_no_policy_and_retry_zero_both_give_a_single_attempt(self):
        self.assertEqual(self._derived(retry_doc()), 1)
        self.assertEqual(self._derived(retry_doc(retry=0)), 1)

    def test_a_tight_deadline_cuts_the_attempts_short(self):
        """Boundary: the deadline gate, not the attempt cap, is what stops it."""
        self.assertEqual(self._derived(retry_doc(retry=3, timeout="500ms")), 3)
        self.assertEqual(self._derived(retry_doc(retry=3, timeout="100ms")), 1)

    def test_the_attempt_count_depends_on_where_the_failure_happens(self):
        """The case a `retry + 1` model gets wrong, and a clock-less deadline
        model gets wrong too: same policy, different position in the workflow.
        Each preceding step advances the interpreter clock 5ms, which moves the
        failure across a backoff boundary."""
        near = retry_doc(retry=5, timeout="400ms", lead=0)
        far = retry_doc(retry=5, timeout="400ms", lead=20)
        self.assertEqual(self._derived(near), 3)
        self.assertEqual(self._derived(far), 2)
        self.assertEqual(self._derived(near), self._observed(near, "find product"))
        self.assertEqual(self._derived(far), self._observed(far, "find product"))

    def test_a_create_conflict_is_never_retried(self):
        """RFC-0003 §멱등 판정: `create` is non-idempotent, so the retry gate
        refuses it however large the budget. One attempt, not four."""
        src = SAME_ENTITY.replace("service CheckoutService\n",
                                  "service CheckoutService\n    policy\n"
                                  "        retry 3\n")
        d = checkout_doc(src)
        _attrs, ops = backend._lnpl_ops(d, "wf.checkout")
        self.assertEqual(len(ops[-1]["effects"]), 1)
        self.assertEqual(self._observed(d, "create product", "default"), 1)

    def test_a_retried_cache_failure_repeats_without_the_read_miss_cost(self):
        """The cache path shares the scan, so it shares the multiplicity. Its
        per-attempt clock cost differs from a read miss (`Cache.set` raises
        without advancing), which only a case with a retry budget can catch."""
        src = NO_TTL_CACHE.replace("service S\n",
                                   "service S\n    policy\n        retry 2\n")
        d = lower(parse(src), "t").to_document()
        _attrs, ops = backend._lnpl_ops(d, "wf.w")
        payload = {}
        observed = differential.observe_mode_a(
            d, "wf.w", payload, default_rows(d, "wf.w", payload))["effects"]
        self.assertEqual(len(ops[-1]["effects"]), 3)
        self.assertEqual(len(ops[-1]["effects"]), len(observed["cache user"]))


# The shape t3's `examples/checkout.lnpl` lands with this wave: `retry 3`, an
# UNGUARDED read, a GUARDED create. Kept inline — t3 is the single producer of
# `examples/checkout.*` and this file must not depend on it.
CHECKOUT_LIKE = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
entity Order
    field
        id UUID
        total Money
service CheckoutService
    policy
        retry 3
workflow Checkout
    find product
    when stock > 0
    create order
"""


@NEEDS_TOOLS
class TestModeBSeedChannel(unittest.TestCase):
    """The seed condition reaches both modes, and they agree on the outcome.

    `seeded` carries the seed *condition* — which entities start with a row — not
    a materialised store. Mode A is handed the same condition as rows and mode B
    derives its own answer from the set, so neither reads the other's result.
    """

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-seed-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _payload(self, document):
        return sample_payload([n for n in document["nodes"]
                               if n["kind"] == "Entity"])

    def test_read_then_create_is_equivalent_under_the_default_seed(self):
        """The issue: this workflow could not succeed under any seed. It now
        completes, and the two modes agree that it does."""
        d = checkout_doc(READ_THEN_CREATE)
        payload = self._payload(d)
        ok, report = differential.verify(
            d, "wf.checkout", payload,
            default_rows(d, "wf.checkout", payload), self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertIn("differential: EQUIVALENT", report[-1])
        self.assertTrue(any("PASS 2/4" in line for line in report), report)
        a = differential.observe_mode_a(
            d, "wf.checkout", payload, default_rows(d, "wf.checkout", payload))
        self.assertEqual(a["status"], "completed")

    def test_an_unseeded_read_makes_both_modes_fail_the_same_way(self):
        """EQUIVALENT alone could be any agreeing pair, so this proves they agree
        by FAILING: same status, same order, same per-step effects."""
        d = checkout_doc(READ_THEN_CREATE)
        payload = self._payload(d)
        ok, report = differential.verify(d, "wf.checkout", payload, {},
                                         self.workdir, seeded=frozenset())
        self.assertTrue(ok, "\n".join(report))
        a = differential.observe_mode_a(d, "wf.checkout", payload, {})
        b = differential.observe_mode_b(d, "wf.checkout", self.workdir,
                                        payload=payload, seeded=frozenset())
        self.assertEqual(a["status"], "failed")
        self.assertEqual(b["status"], "failed")
        self.assertEqual(a["order"], ["find product"])
        self.assertEqual(b["order"], a["order"])
        self.assertEqual(b["effects"], a["effects"])

    def test_a_create_conflict_makes_both_modes_fail_at_the_create(self):
        d = checkout_doc(SAME_ENTITY)
        payload = self._payload(d)
        rows = default_rows(d, "wf.checkout", payload)
        ok, report = differential.verify(d, "wf.checkout", payload, rows,
                                         self.workdir)
        self.assertTrue(ok, "\n".join(report))
        a = differential.observe_mode_a(d, "wf.checkout", payload, rows)
        b = differential.observe_mode_b(d, "wf.checkout", self.workdir,
                                        payload=payload)
        self.assertEqual(a["status"], "failed")
        self.assertEqual(b["status"], "failed")
        self.assertEqual(a["order"][-1], "create product")
        self.assertEqual(b["order"], a["order"])
        self.assertEqual(b["effects"], a["effects"])

    def test_a_facet_violating_payload_is_equivalent_and_fails_both_modes(self):
        """Issue #48, the payload channel: `observe_mode_b` hands the payload to
        `build`, so `lnpl diff --payload` with a facet-violating payload sees
        BOTH modes refuse — EQUIVALENT by agreeing to fail, never a divergence
        where only mode A validates."""
        d = checkout_doc(VALIDATED_ORDER)
        payload = sample_payload([n for n in d["nodes"]
                                  if n["kind"] == "Entity"],
                                 refinement_index(d))
        payload["quantity"] = 0
        rows = default_rows(d, "wf.place.order", payload)
        ok, report = differential.verify(d, "wf.place.order", payload, rows,
                                         self.workdir)
        self.assertTrue(ok, "\n".join(report))
        a = differential.observe_mode_a(d, "wf.place.order", payload, rows)
        b = differential.observe_mode_b(d, "wf.place.order", self.workdir,
                                        payload=payload)
        self.assertEqual(a["status"], "failed")
        self.assertEqual(b["status"], "failed")
        self.assertEqual(a["order"], ["validate order"])
        self.assertEqual(b["order"], a["order"])
        self.assertEqual(b["effects"], a["effects"])

    def test_the_checkout_shape_agrees_seeded_and_unseeded(self):
        """The cross-task path: `retry 3`, unguarded read, guarded create — what
        `lnpl diff` and `lnpl diff --no-row` will run against t3's example. The
        unseeded run must truncate at the read carrying FOUR effects, one per
        attempt, which is the case a single-attempt model gets wrong."""
        d = checkout_doc(CHECKOUT_LIKE)
        payload = self._payload(d)

        ok, report = differential.verify(
            d, "wf.checkout", payload,
            default_rows(d, "wf.checkout", payload), self.workdir)
        self.assertTrue(ok, "\n".join(report))

        ok, report = differential.verify(d, "wf.checkout", payload, {},
                                         self.workdir, seeded=frozenset())
        self.assertTrue(ok, "\n".join(report))
        b = differential.observe_mode_b(d, "wf.checkout", self.workdir,
                                        payload=payload, seeded=frozenset())
        self.assertEqual(b["status"], "failed")
        self.assertEqual(b["order"], ["find product"])
        self.assertEqual(b["effects"]["find product"], ["RepositoryCall"] * 4)

    def test_a_seed_that_contradicts_the_rows_is_refused(self):
        """Two copies of one fact own a synchronization bug. Mode A's rows and
        mode B's seed condition disagreeing is a wiring mistake, and left silent
        it would be indistinguishable from a real divergence — the defect issue
        #12 removed for the skip flag."""
        d = checkout_doc(READ_THEN_CREATE)
        payload = self._payload(d)
        with self.assertRaises(differential.DifferentialError) as ctx:
            differential.verify(d, "wf.checkout", payload,
                                default_rows(d, "wf.checkout", payload),
                                self.workdir, seeded=frozenset())
        self.assertIn("entity.product", str(ctx.exception))

    def test_the_golden_scenario_does_not_regress(self):
        """Control. login reads `entity.user`, so the default seed keeps it
        completing exactly as before the repository derivation existed."""
        doc = golden()
        ok, report = differential.verify(
            doc, "wf.login", PAYLOAD,
            default_rows(doc, "wf.login", PAYLOAD), self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertIn("differential: EQUIVALENT", report[-1])


@NEEDS_TOOLS
class TestRepositoryDivergenceIsDetected(unittest.TestCase):
    """The repository derivation must not make the differential unable to fail.

    A derivation that quietly copied mode A's answer would turn every comparison
    green, which is worse than the bug it replaced: `lnpl diff` would become
    structurally incapable of reporting DIVERGENT. Each case here follows the
    established order — require EQUIVALENT on the unmutated workflow FIRST, so a
    later red is attributable to the fault rather than to a standing divergence,
    then apply exactly one mode-B-only fault and require a specific FAIL class.
    """

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-repodiv-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))
        self.doc = checkout_doc(READ_THEN_CREATE)
        self.payload = sample_payload([n for n in self.doc["nodes"]
                                       if n["kind"] == "Entity"])
        self.rows = default_rows(self.doc, "wf.checkout", self.payload)
        self.original_steps = backend._steps_in_order
        self.original_read_ops = backend.READ_OPS
        self.original_attempts = backend._failure_attempts

    def tearDown(self):
        backend._steps_in_order = self.original_steps
        backend.READ_OPS = self.original_read_ops
        backend._failure_attempts = self.original_attempts
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _verify(self, rows=None, seeded=None):
        return differential.verify(self.doc, "wf.checkout", self.payload,
                                   self.rows if rows is None else rows,
                                   self.workdir, seeded=seeded)

    def test_mode_b_missing_the_read_failure_is_reported_as_divergent(self):
        """The fault this feature could ship: mode B failing to notice that a
        read has nothing to find. Mode A still fails; mode B completes; the
        comparison must say so on the policy-outcome axis."""
        ok, report = self._verify(rows={}, seeded=frozenset())
        self.assertTrue(ok, "baseline must be equivalent before the fault: %s"
                            % "\n".join(report))

        backend.READ_OPS = ()      # mode B stops recognising reads

        ok, report = self._verify(rows={}, seeded=frozenset())
        self.assertFalse(ok, "mode B missing the read failure must diverge")
        self.assertTrue(any("FAIL 2/4" in line for line in report), report)

    def test_mode_b_losing_the_attempt_count_is_reported_as_divergent(self):
        """The other half of the derivation, and the one a plausible-looking
        implementation gets wrong: the failing step's effects must repeat once
        per attempt. Collapsing them to one is invisible on a workflow without a
        retry budget, which is why this runs on `retry 3`."""
        doc = retry_doc(retry=3)
        payload = sample_payload([n for n in doc["nodes"]
                                  if n["kind"] == "Entity"])

        ok, report = differential.verify(doc, "wf.checkout", payload, {},
                                         self.workdir, seeded=frozenset())
        self.assertTrue(ok, "baseline must be equivalent before the fault: %s"
                            % "\n".join(report))

        backend._failure_attempts = lambda *args, **kwargs: 1

        ok, report = differential.verify(doc, "wf.checkout", payload, {},
                                         self.workdir, seeded=frozenset())
        self.assertFalse(ok, "mode B emitting one attempt where mode A made "
                             "four must diverge")
        self.assertTrue(any("FAIL 3/4" in line for line in report), report)

    def test_a_reordered_backend_still_diverges_on_a_repository_workflow(self):
        """The generic control, run on the workflow this task added. The earlier
        reorder case uses the golden scenario, which has no create at all."""
        ok, report = self._verify()
        self.assertTrue(ok, "baseline must be equivalent before the fault: %s"
                            % "\n".join(report))

        original = self.original_steps

        def reversed_order(nodes, ids, out):
            out.extend(list(reversed(original(nodes, ids, []))))
            return out

        backend._steps_in_order = reversed_order
        ok, report = self._verify()
        self.assertFalse(ok, "a reordered mode B must diverge")
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)

    def test_effects_after_the_failing_repository_call_are_not_emitted(self):
        """The boundary a one-effect-per-step workflow cannot test.

        The grammar gives each `WorkflowStep` a single effect, so a multi-effect
        step is built here directly — an `Authorization` appended AFTER the read.
        Mode A's failing step holds the effects up to and INCLUDING the read and
        none after it, once per attempt; a truncation off by one in either
        direction shows up as a different effect list. `retry 3` makes this cover
        the multiplicity and the cut at the same time.
        """
        d = retry_doc(retry=3)
        read = next(n for n in d["nodes"]
                    if n["kind"] == "RepositoryCall" and n["operation"] == "read")
        step = next(n for n in d["nodes"]
                    if n["kind"] == "WorkflowStep"
                    and read["id"] in n.get("children", []))
        d["nodes"].append({"kind": "Authorization", "id": step["id"] + ".after",
                           "requirement": "x"})
        step["children"] = list(step["children"]) + [step["id"] + ".after"]

        payload = sample_payload([n for n in d["nodes"] if n["kind"] == "Entity"])
        a = differential.observe_mode_a(d, "wf.checkout", payload, {})
        b = differential.observe_mode_b(d, "wf.checkout", self.workdir,
                                        payload=payload, seeded=frozenset())
        self.assertEqual(a["effects"][step["name"]], ["RepositoryCall"] * 4)
        self.assertEqual(b["effects"], a["effects"])
        self.assertNotIn("Authorization", b["effects"][step["name"]])
        self.assertEqual(a["status"], "failed")
        self.assertEqual(b["status"], "failed")


# A guarded repository call that CAN fail, in both directions the rule has.
# Built from the sources above rather than written out again, so the shape being
# guarded stays the shape those tests already pin.
#
# `SAME_ENTITY` reads and creates `entity.product`, so the seed writes it and the
# create conflicts; guarding that create is the case mode B cannot reproduce.
GUARDED_CONFLICT = SAME_ENTITY.replace(
    "    create product\n", "    when stock > 0\n    create product\n")
# The read side: guarding `find product` makes it a miss whenever the seed is
# empty, which is the seed `--no-row` produces.
GUARDED_MISS = READ_THEN_CREATE.replace(
    "    find product\n", "    when stock > 0\n    find product\n")


def calls_with_guards(document, workflow_id):
    """`(guarded, step name, entity, operation)` per RepositoryCall, in declared
    order — `repository_calls` plus the two facts it drops.

    Pinned to that function by
    `test_the_scan_walks_exactly_the_shared_derivations_calls`, so this cannot
    quietly walk a different set of calls than the seed policy does.
    """
    nodes = {n["id"]: n for n in document["nodes"]}
    workflow = nodes.get(workflow_id)
    entries = []

    def walk(ids, guarded):
        for node_id in ids:
            node = nodes.get(node_id)
            if node is None:
                continue
            if node["kind"] == "WorkflowStep":
                for child_id in node.get("children", []):
                    child = nodes.get(child_id)
                    if child is not None and child["kind"] == "RepositoryCall":
                        entries.append((guarded, node["name"], child["entity"],
                                        child["operation"]))
            else:
                # Guard, Concurrency, Pipeline. Only a Guard makes what it holds
                # uncertain, and that matches `_lnpl_ops`, which skips exactly the
                # ops carrying a `guard_mode` — `when`, `until` and `repeat` alike.
                walk(node.get("children", []), guarded or node["kind"] == "Guard")

    walk((workflow or {}).get("children", []), False)
    return entries


def guarded_calls_that_can_fail(document, workflow_id, seeded=None):
    """The guarded repository calls whose failure mode B would have to reproduce.

    Consequence, not shape. A guard only meets the limitation if the call under it
    could actually fail, and "could fail" is `_lnpl_ops`' own conflict/miss rule
    applied to the ops that scan skips: a `create` fails iff its entity is already
    present (seeded, or created by an earlier call), a read fails iff it is not.
    Operations that are neither cannot fail, exactly as `_lnpl_ops` never sets
    `fail_at` for them.

    The inputs are the shared derivation — `seeded_entities` for what the seed
    writes, `calls_with_guards` for the declared order — and `seeded` mirrors
    `_lnpl_ops`' parameter of the same name, so the empty seed `--no-row` produces
    is expressible here too. Returns `[(step name, entity, operation)]`.
    """
    present = set(seeded_entities(document, workflow_id) if seeded is None
                  else seeded)
    risky = []
    for guarded, step, entity, operation in calls_with_guards(document, workflow_id):
        if operation in READ_OPS:
            can_fail = entity not in present
        elif operation == "create":
            can_fail = entity in present
            if not can_fail:
                present.add(entity)
        else:
            continue
        if guarded and can_fail:
            risky.append((step, entity, operation))
    return risky


def shipped_examples():
    """Every committed example, as `(basename, document)`."""
    import glob
    out = []
    for path in sorted(glob.glob(os.path.join(REPO, "examples", "*.lnpl"))):
        with open(path, encoding="utf-8") as fh:
            out.append((os.path.basename(path),
                        lower(parse(fh.read()),
                              os.path.basename(path)[:-5]).to_document()))
    return out


class TestGuardedRepositoryLimitationIsDocumented(unittest.TestCase):
    """D8 is a real limitation, so it is written down and its reach is measured
    rather than assumed.

    The reach is measured as a *consequence*, not a shape. `examples/checkout.lnpl`
    guards a `create` — that is issue #35's own reproduction shape and it is
    supposed to be there — so asking "does an example nest a `RepositoryCall`
    under a `Guard`?" now answers yes forever and stops measuring anything. The
    question that still has an answer is whether that guarded call *could fail*.
    """

    def test_the_limitation_is_recorded_next_to_the_derivation(self):
        with open(os.path.join(REPO, "impl", "lnpl", "backend.py"),
                  encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("KNOWN LIMITATION", source)
        self.assertIn("guard that IS taken at runtime", source)
        # "No shipped example hits it" stopped being true when t3 landed
        # `checkout.lnpl`; the comment has to name the example that does and say
        # why it is safe, and the two tests below check that reason for real.
        self.assertIn("examples/checkout.lnpl", source)
        self.assertIn("create-only", source)

    def test_the_scan_walks_exactly_the_shared_derivations_calls(self):
        """No second copy of the walk: dropping the guard flag and the step name
        from `calls_with_guards` must leave `repository_calls` exactly."""
        for name, document in shipped_examples():
            for wf in [n for n in document["nodes"] if n["kind"] == "Workflow"]:
                with self.subTest(example=name, workflow=wf["id"]):
                    self.assertEqual(
                        [(entity, operation) for _, _, entity, operation
                         in calls_with_guards(document, wf["id"])],
                        repository_calls(document, wf["id"]))

    def test_no_shipped_example_has_a_guarded_repository_call_that_can_fail(self):
        """Measures the limitation's reach instead of claiming it is small. Goes
        red the day an example ships a guarded call that could fail — the moment
        the limitation stops being theoretical.

        Both seeds the policy can produce are checked: the default role-based one
        and the empty one `diff --no-row` uses.
        """
        risky = []
        for name, document in shipped_examples():
            for wf in [n for n in document["nodes"] if n["kind"] == "Workflow"]:
                for seeded in (None, frozenset()):
                    risky += [(name, seeded, step) for step, _, _
                              in guarded_calls_that_can_fail(document, wf["id"],
                                                             seeded=seeded)]
        self.assertEqual(risky, [],
                         "a shipped example now hits the guarded-repository "
                         "limitation; mode B cannot reproduce its failure")

    def test_checkouts_guarded_create_is_safe_because_order_is_create_only(self):
        """The stated reason, asserted rather than assumed. `checkout.lnpl` does
        guard a `create` — it passes the check above only because `entity.order`
        is create-only, so no seed the policy can produce holds it, and it is
        created exactly once, so no earlier call holds it either."""
        with open(CHECKOUT_LNPL, encoding="utf-8") as fh:
            document = lower(parse(fh.read()), "checkout").to_document()
        guarded = [(step, entity, operation) for guarded, step, entity, operation
                   in calls_with_guards(document, "wf.checkout") if guarded]
        self.assertEqual(guarded, [("create order", "entity.order", "create")])
        self.assertNotIn("entity.order", seeded_entities(document, "wf.checkout"))
        self.assertEqual([call for call in repository_calls(document, "wf.checkout")
                          if call == ("entity.order", "create")],
                         [("entity.order", "create")])
        self.assertEqual(guarded_calls_that_can_fail(document, "wf.checkout"), [])

    def test_a_guarded_create_on_a_seeded_entity_is_reported(self):
        """The conflict direction: the workflow reads `product`, so the seed
        writes it and the guarded create would conflict if the guard were taken."""
        document = checkout_doc(GUARDED_CONFLICT)
        self.assertEqual(guarded_calls_that_can_fail(document, "wf.checkout"),
                         [("create product", "entity.product", "create")])

    def test_a_guarded_read_is_reported_only_under_the_seed_that_misses_it(self):
        """The miss direction, and the reason this is a consequence check: one
        document, two seeds, two verdicts. Under the default seed the read's own
        entity is seeded and nothing can fail; under `--no-row`'s empty seed the
        same guarded read is a miss."""
        document = checkout_doc(GUARDED_MISS)
        self.assertEqual(guarded_calls_that_can_fail(document, "wf.checkout"), [])
        self.assertEqual(
            guarded_calls_that_can_fail(document, "wf.checkout",
                                        seeded=frozenset()),
            [("find product", "entity.product", "read")])

    def test_documents_with_nothing_to_report_are_empty_not_absent(self):
        """Boundaries: a guardless workflow, a workflow with no repository call at
        all, and a workflow id that is not in the document."""
        self.assertEqual(
            guarded_calls_that_can_fail(checkout_doc(READ_THEN_CREATE),
                                        "wf.checkout"), [])
        self.assertEqual(
            guarded_calls_that_can_fail(checkout_doc(NO_REPO), "wf.checkout"), [])
        self.assertEqual(
            guarded_calls_that_can_fail(checkout_doc(READ_THEN_CREATE),
                                        "wf.missing"), [])


SCOPED_GUARD_SOURCE = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
service ShopService
    policy
        retry 0
workflow Checkout
    find product
    when product.stock > 0
    create order
"""


class TestScopedConditionFieldIdentifier(unittest.TestCase):
    """RFC-0012: a qualified reference reaches mode B as `product.stock`.

    A dot is legal in the logical name and in an MLIR SSA name, but not in a C
    identifier — `int64_t product.stock;` does not compile. One mangling function
    owns the translation and every emission point calls it, so the MLIR signature,
    the C declaration and the C call site cannot drift into an arity or name
    mismatch (which C linkage would surface as an uninitialised register rather
    than a link error).
    """

    def _doc(self):
        return lower(parse(SCOPED_GUARD_SOURCE), "shop").to_document()

    def test_the_logical_name_keeps_its_dot(self):
        # The logical name is what `--field NAME=VALUE`, the persisted field
        # order, and `run_binary`'s mapping all use. Mangling must not leak there.
        self.assertEqual(backend.condition_field_names(self._doc(), "wf.checkout"),
                         ["product.stock"])

    def test_the_c_shim_declares_a_legal_identifier(self):
        c_source = backend.runtime_c(["product.stock"])
        self.assertIn("int64_t product__stock", c_source)
        self.assertNotIn("int64_t product.stock", c_source,
                         "a dot is not legal in a C identifier, so emitting the "
                         "logical name verbatim would not compile.")

    def test_the_c_shim_passes_the_same_identifier_it_declared(self):
        c_source = backend.runtime_c(["product.stock"])
        self.assertIn("lnpl_run(skip, product__stock)", c_source,
                      "the declaration and the call must use one name; if they "
                      "drift the argument arrives uninitialised.")

    def test_the_c_shim_still_names_the_logical_field_for_a_reader(self):
        # The comment is the human-facing half — it should say what the operator
        # would type after `--field`.
        self.assertIn("product.stock", backend.runtime_c(["product.stock"]))

    def test_the_mlir_signature_uses_the_mangled_name(self):
        mlir = backend.emit_mlir(self._doc(), "wf.checkout")
        self.assertIn("%product__stock : i64", mlir)

    def test_the_mlir_comparison_reads_the_declared_parameter(self):
        mlir = backend.emit_mlir(self._doc(), "wf.checkout")
        self.assertIn("arith.cmpi sgt, %product__stock", mlir,
                      "the guard must compare against the parameter the "
                      "signature declares, not against an undeclared %product.stock.")

    # ---- boundary: an unqualified name must be untouched -------------------
    def test_a_bare_field_name_is_unchanged_by_mangling(self):
        self.assertEqual(backend._field_ident("counter"), "counter")

    def test_the_bare_c_shim_is_byte_identical_to_the_unmangled_form(self):
        # Every pre-RFC-0012 document has only bare condition fields, so this is
        # the regression guard for the committed golden MLIR files.
        self.assertIn("int64_t counter", backend.runtime_c(["counter"]))
        self.assertIn("lnpl_run(skip, counter)", backend.runtime_c(["counter"]))

    def test_an_empty_field_list_still_produces_a_shim(self):
        # Boundary: a workflow with no comparison guard at all.
        c_source = backend.runtime_c([])
        self.assertIn("int lnpl_run(int skip);", c_source)
        self.assertIn("lnpl_run(skip)", c_source)


if __name__ == "__main__":
    unittest.main()


class TestStepPlan(unittest.TestCase):
    """Issue #44: the compiled step plan, exposed so `observe_mode_b` can tell
    "this step was skipped" from "this step does not exist".

    Mode B's stdout prints only the steps that ran, so a skip is observable only
    as an absence — and an absence needs the plan to be read against. The plan
    comes from the same `_lnpl_ops` derivation `emit_mlir` renders, so it cannot
    describe a different workflow than the one that was compiled.
    """

    def test_a_when_guard_is_carried_with_its_condition(self):
        doc = lower(parse(guarded_source("when token missing")), "t").to_document()
        plan = backend.step_plan(doc, "wf.w")
        guarded = [op for op in plan if op["guard_mode"] is not None]
        self.assertEqual(len(guarded), 1)
        self.assertEqual(guarded[0]["guard_mode"], "when")
        self.assertEqual(guarded[0]["guard_condition"], "token missing")
        self.assertEqual(guarded[0]["name"], "cache user")

    def test_an_until_guard_is_unrolled_to_the_round_cap(self):
        doc = lower(parse(UNTIL_COUNTER), "t").to_document()
        plan = backend.step_plan(doc, "wf.w")
        rounds = [op["unroll_round"] for op in plan
                  if op["guard_mode"] == "until"]
        self.assertEqual(rounds, list(range(1, backend._UNTIL_ROUND_CAP + 1)))

    def test_an_unguarded_workflow_carries_no_guard_mode(self):
        plan = backend.step_plan(golden(), "wf.login")
        self.assertTrue(plan, "precondition: the golden workflow has steps")
        self.assertEqual([op["guard_mode"] for op in plan], [None] * len(plan))

    def test_the_plan_is_the_same_derivation_emit_mlir_renders(self):
        # Not a second derivation: every step the plan names must appear in the
        # emitted module, or the skip reconstruction would read a plan the
        # binary was never built from.
        doc = lower(parse(guarded_source("when token missing")), "t").to_document()
        text = backend.emit_mlir(doc, "wf.w")
        for op in backend.step_plan(doc, "wf.w"):
            self.assertIn("step %d: %s" % (op["index"], op["name"]), text)

    def test_a_workflow_with_no_steps_plans_nothing(self):
        # Boundary: an empty body is a legal document, and the reconstruction
        # must not assume at least one op.
        doc = lower(parse(guarded_source("when token missing")), "t").to_document()
        for node in doc["nodes"]:
            if node["id"] == "wf.w":
                node["children"] = []
        self.assertEqual(backend.step_plan(doc, "wf.w"), [])

    def test_an_unknown_workflow_is_refused(self):
        # Error case: the same refusal `_lnpl_ops` already makes, not a silent
        # empty plan that would read as "nothing was skipped".
        with self.assertRaises(backend.BackendError):
            backend.step_plan(golden(), "wf.nosuch")


class TestValueExpressionsCompile(unittest.TestCase):
    """RFC-0015 in mode B: both operands, arithmetic, and `and`, as MLIR.

    Text-level assertions on the emitted module, so they run without the
    toolchain; the differential class below is what proves the two modes agree
    about what that module does.
    """

    def test_both_sides_of_a_comparison_become_parameters(self):
        doc = lower(parse(VALUE_INVENTORY), "inv").to_document()
        self.assertEqual(backend.condition_field_names(doc, "wf.place.order"),
                         ["input.quantity", "product.stock"])

    def test_the_comparison_reads_two_registers_not_a_constant(self):
        doc = lower(parse(VALUE_INVENTORY), "inv").to_document()
        text = backend.emit_mlir(doc, "wf.place.order")
        self.assertIn("arith.cmpi sge, %product__stock, %input__quantity : i64",
                      text)

    def test_an_and_condition_folds_its_terms(self):
        doc = lower(parse(VALUE_PAYMENT), "pay").to_document()
        text = backend.emit_mlir(doc, "wf.approve")
        self.assertIn("arith.cmpi sgt,", text)
        self.assertIn("arith.cmpi sle,", text)
        self.assertIn("arith.andi", text)

    def test_arithmetic_is_emitted_before_the_comparison(self):
        source = VALUE_INVENTORY.replace(
            "when product.stock >= input.quantity",
            "when product.stock - input.quantity >= 0")
        doc = lower(parse(source), "inv").to_document()
        text = backend.emit_mlir(doc, "wf.place.order")
        self.assertIn("arith.subi %product__stock, %input__quantity : i64", text)
        subi = text.index("arith.subi")
        cmpi = text.index("arith.cmpi sge", subi)
        self.assertLess(subi, cmpi, "the difference must exist before it is compared")

    def test_an_assignment_reaches_the_module_as_an_effect(self):
        # Mode B models no repository, so the VALUE of the assignment is not
        # observable there (RFC-0015 §Differential Equivalence lists it as a
        # permitted difference). Its occurrence is.
        doc = lower(parse(VALUE_INVENTORY), "inv").to_document()
        text = backend.emit_mlir(doc, "wf.place.order")
        self.assertIn("Assignment", text)

    def test_a_condition_with_no_compiled_evaluator_still_falls_back(self):
        # Boundary: a Presence guard has no i64 parameter, so the run-level skip
        # flag stays the channel it was before RFC-0015.
        doc = lower(parse(guarded_source("when token missing")), "t").to_document()
        text = backend.emit_mlir(doc, "wf.w")
        self.assertIn("%skip", text)


@NEEDS_TOOLS
class TestValueExpressionModeEquivalence(unittest.TestCase):
    """The two modes on RFC-0015 programs, with the controls that make it evidence.

    Three things are asserted separately, because they are three claims:
      * the default input agrees (`test_*_agrees`),
      * the injected values actually reach the compiled guard (the control pair),
      * the comparison can still fail (the seeded divergence).
    """

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-value-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))
        self.original = backend._emit_condition

    def tearDown(self):
        backend._emit_condition = self.original
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _verify(self, doc, workflow, payload, rows=None):
        rows = default_rows(doc, workflow, payload) if rows is None else rows
        return differential.verify(doc, workflow, payload, rows, self.workdir)

    def _inventory(self, stock, quantity):
        doc = lower(parse(VALUE_INVENTORY), "inv").to_document()
        payload = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
                   "stock": stock, "quantity": quantity}
        rows = {"entity.product": {row_key("entity.product", payload):
                                   {"id": payload["id"], "stock": stock}}}
        return doc, payload, rows

    def test_a_field_on_the_right_agrees_in_both_directions(self):
        for stock, quantity in ((5, 2), (1, 2)):
            doc, payload, rows = self._inventory(stock, quantity)
            ok, report = self._verify(doc, "wf.place.order", payload, rows)
            self.assertTrue(ok, "stock=%d quantity=%d:\n%s"
                            % (stock, quantity, "\n".join(report)))

    def test_an_and_range_agrees_inside_and_outside_its_bounds(self):
        doc = lower(parse(VALUE_PAYMENT), "pay").to_document()
        for amount in (0, 1, 10000, 10001):
            payload = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
                       "amount": amount}
            ok, report = self._verify(doc, "wf.approve", payload)
            self.assertTrue(ok, "amount=%d:\n%s" % (amount, "\n".join(report)))

    def test_the_control_pair_flips_the_guarded_step(self):
        """The injected values must decide something before any of this counts.

        Uniform observations across a value matrix mean "lever not connected",
        not "behaviour stable" — so this pins the flip itself: the same program,
        two payloads, different executed-step lists.
        """
        doc, high, high_rows = self._inventory(5, 2)
        _doc, low, low_rows = self._inventory(1, 2)

        ran = differential.observe_mode_b(
            doc, "wf.place.order", self.workdir, payload=high,
            seeded=frozenset(["entity.product"]))
        skipped = differential.observe_mode_b(
            doc, "wf.place.order", self.workdir, payload=low,
            seeded=frozenset(["entity.product"]))
        self.assertIn("create order", ran["text"])
        self.assertNotIn("create order", skipped["text"],
                         "the compiled guard ignored the injected values — a "
                         "matrix run over them would measure nothing")

    def test_the_comparison_can_still_fail(self):
        """Seeded divergence: invert the emitted predicate, require a red.

        A differential check that has only ever printed EQUIVALENT is unmeasured,
        and RFC-0015 widened exactly the code this exercises.
        """
        doc, payload, rows = self._inventory(5, 2)
        ok, report = self._verify(doc, "wf.place.order", payload, rows)
        self.assertTrue(ok, "baseline must be equivalent before the fault")

        original = self.original

        def inverted(cond, idx, lines, negate):
            return original(cond, idx, lines, not negate)

        backend._emit_condition = inverted
        ok, report = self._verify(doc, "wf.place.order", payload, rows)
        self.assertFalse(ok, "an inverted guard must not compare as equivalent")
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)

    def test_the_forcing_input_where_the_repository_decides(self):
        """Mode B models no rows, so the default input cannot exercise that.

        Reported as its own verdict rather than folded into the agreement above:
        an empty seed is where the asymmetric dimension decides the outcome.
        """
        doc, payload, _rows = self._inventory(5, 2)
        ok, report = differential.verify(doc, "wf.place.order", payload, {},
                                         self.workdir, seeded=frozenset())
        self.assertTrue(ok, "empty-seed run:\n%s" % "\n".join(report))


class TestArithmeticAndAltGuardsCompile(unittest.TestCase):
    """Issue #93 / RFC-0028 in mode B, text-level (no toolchain required).

    `*`/`/` only ever reach `_emit_condition` (a guard's comparison) — an
    Assignment's expression is a marker string mode B never computes, exactly
    as `+`/`-` already were (RFC-0028 §Reference-level Specification/6).
    """

    def test_multiplication_in_an_assignment_is_only_a_marker(self):
        doc = lower(parse(PRICE_INVENTORY), "price").to_document()
        text = backend.emit_mlir(doc, "wf.place.order")
        self.assertIn("Assignment", text)
        self.assertNotIn("arith.muli", text,
                         "an Assignment's expression must not be computed — "
                         "mode B models no repository to write it into")

    def test_multiplication_in_a_guard_condition_is_emitted(self):
        doc = lower(parse(GUARD_ARITH), "arith").to_document()
        text = backend.emit_mlir(doc, "wf.check.ratio.mul")
        self.assertIn("arith.muli %product__stock, %input__factor : i64", text)

    def test_division_in_a_guard_condition_is_emitted_with_a_zero_check(self):
        doc = lower(parse(GUARD_ARITH), "arith").to_document()
        text = backend.emit_mlir(doc, "wf.check.ratio.div")
        self.assertIn("arith.divsi", text)
        self.assertIn("arith.cmpi eq", text)
        self.assertIn("%c0_i64", text,
                      "a zero constant must exist for the divisor to compare "
                      "against")


class TestAltGuardCompile(unittest.TestCase):
    """The alternative-guard OR-fold, text-level (no toolchain required)."""

    def test_the_alternative_ors_with_the_primary(self):
        doc = lower(parse(ALT_GUARD_APPROVE), "approve").to_document()
        text = backend.emit_mlir(doc, "wf.approve")
        self.assertIn("arith.ori", text)

    def test_a_presence_alternative_falls_back_to_the_skip_flag(self):
        # Boundary: if EITHER term has no compiled evaluator, the whole
        # alt-guard must fall back — computing only the compilable side would
        # silently under-evaluate the OR (RFC-0028 §Reference-level
        # Specification/6).
        source = ALT_GUARD_APPROVE.replace(
            "or input.amount <= 100", "or token exists")
        doc = lower(parse(source), "approve").to_document()
        text = backend.emit_mlir(doc, "wf.approve")
        # `%skip` alone is not evidence — it is a parameter on every compiled
        # module's signature regardless of whether any guard uses it. The
        # run-level check pattern (`_render_std`'s fallback branch) is what
        # actually proves the compiled guard is skip-flag-driven here.
        self.assertIn("arith.cmpi eq, %skip, %c0", text)
        self.assertNotIn("arith.ori", text)


@NEEDS_TOOLS
class TestArithmeticModeEquivalence(unittest.TestCase):
    """Mode A/B agreement on `*`/`/` in a guard condition (safe divisors)."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-arith-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _doc(self):
        return lower(parse(GUARD_ARITH), "arith").to_document()

    def _payload(self, stock, factor, threshold, divisor):
        return {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "stock": stock,
                "factor": factor, "threshold": threshold, "divisor": divisor}

    def test_multiplication_agrees_on_both_sides_of_the_threshold(self):
        doc = self._doc()
        for factor, threshold in ((3, 10), (3, 100)):
            payload = self._payload(5, factor, threshold, 1)
            rows = default_rows(doc, "wf.check.ratio.mul", payload)
            ok, report = differential.verify(doc, "wf.check.ratio.mul", payload,
                                             rows, self.workdir)
            self.assertTrue(ok, "factor=%d threshold=%d:\n%s"
                            % (factor, threshold, "\n".join(report)))

    def test_division_agrees_for_a_nonzero_divisor(self):
        doc = self._doc()
        for divisor, threshold in ((2, 2), (2, 3)):
            payload = self._payload(5, 1, threshold, divisor)
            rows = default_rows(doc, "wf.check.ratio.div", payload)
            ok, report = differential.verify(doc, "wf.check.ratio.div", payload,
                                             rows, self.workdir)
            self.assertTrue(ok, "divisor=%d threshold=%d:\n%s"
                            % (divisor, threshold, "\n".join(report)))

    def test_division_by_a_runtime_zero_does_not_crash_mode_b(self):
        """RFC-0028's documented boundary: mode B need not AGREE on a value
        failure (RFC-0015 §5, "값 차원은 모드 A가 단독으로 단언한다"), but it
        must not hit `arith.divsi`'s undefined behaviour either. This checks
        the weaker, correct claim — the binary still prints a status line —
        not that it reports `failed`.
        """
        doc = self._doc()
        payload = self._payload(5, 1, 1, 0)
        observed = differential.observe_mode_b(
            doc, "wf.check.ratio.div", self.workdir, payload=payload,
            seeded=seeded_entities(doc, "wf.check.ratio.div"))
        self.assertIsNotNone(observed["status"])


@NEEDS_TOOLS
class TestAltGuardModeEquivalence(unittest.TestCase):
    """Mode A/B agreement across every alt-guard branch (D5, issue #93)."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-altguard-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _verify(self, channel, amount):
        doc = lower(parse(ALT_GUARD_APPROVE), "approve").to_document()
        payload = {"id": "9e3f1b7a-2b3c-4d5e-8f9a-0b1c2d3e4f5a",
                  "channel": channel, "amount": amount}
        return differential.verify(doc, "wf.approve", payload, {}, self.workdir)

    def test_the_primary_branch_agrees(self):
        ok, report = self._verify(channel=1, amount=5000)
        self.assertTrue(ok, "\n".join(report))

    def test_the_alternative_branch_agrees(self):
        ok, report = self._verify(channel=2, amount=50)
        self.assertTrue(ok, "\n".join(report))

    def test_the_skip_branch_agrees(self):
        ok, report = self._verify(channel=2, amount=5000)
        self.assertTrue(ok, "\n".join(report))
