"""Issue #35's end-to-end regression: the SHIPPED example, the SHIPPED entry points.

Issue #35 reported that `examples`-grade multi-entity work could not run at all:
a workflow that READS one entity and CREATES another failed in mode A under every
seed, and `lnpl diff` reported DIVERGENT. Its three completion criteria were

  1. the read-then-create workflow completes in mode A under the seed condition,
  2. `lnpl diff` on that same workflow reports EQUIVALENT,
  3. a regression test fixes it in place.

This module is (3), and it is deliberately the *outermost* of the three test
layers that now cover the issue:

  `test_golden.py::TestCheckoutExecution` runs `examples/checkout.lnpl` through
    the interpreter — mode A only, library level, no CLI.
  `test_backend.py::TestModeBSeedChannel` / `TestRepositoryDivergenceIsDetected`
    run the differential and its reverse controls — but on INLINE fixtures
    (`READ_THEN_CREATE`, `CHECKOUT_LIKE`, `retry_doc`) built inside that file.
  this module runs the COMMITTED `examples/checkout.lnpl` through
    `differential.verify` and through `cli.main`, which nothing else does.

That last gap is the one worth closing. `CHECKOUT_LIKE` is a hand-built lookalike
of the shipped example; if the two ever drift — a regenerated golden, an edited
guard, a renamed step — every existing test stays green while the artifact users
actually run stops being the artifact that was verified. The three commands below
are the exact three the issue used to demonstrate the bug, so a future regression
shows up where the report did:

    lnpl run  examples/checkout.lnpl                -> completed, exit 0
    lnpl diff examples/checkout.lnpl                -> EQUIVALENT, exit 0
    lnpl diff examples/checkout.lnpl --no-row       -> EQUIVALENT, exit 0

**This module never skips, on purpose.** The surrounding mode B tests guard on
`backend.toolchain_available()`, and copying that habit here would mean: on a
machine without LLVM, issue #35's mode B half evaporates and the suite still
prints OK. Mode B comparison is the *only* thing that catches half of this bug, so
a silent skip would leave the run clearing a dimension it never checked.
`differential.verify` already takes this stance for itself — it RAISES rather than
skipping when the toolchain is missing (`differential.py`, "Skipping the
comparison silently would let a divergence ship unnoticed") — and
`TestModeBToolchainIsRequired` below turns the absence into one loud, self-
diagnosing failure that names the install command instead of a quiet skip.

Assertion messages here are written as bug reports to whoever sees them next:
what was expected, what happened, and the command that reproduces it.
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest

from lnpl import backend, cli
from lnpl.differential import (DifferentialError, observe_mode_a, observe_mode_b,
                               verify)
from lnpl.interp import Interpreter, sample_payload
from lnpl.repo_policy import seeded_entities
from tests.fixtures import CHECKOUT_LNPL

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOW = "wf.checkout"
STEPS = ["validate product", "find product", "cache product", "create order"]

# `retry 3` in examples/checkout.lnpl: one initial attempt plus three retries. A
# read is idempotent, so a failing read emits one RepositoryCall span per attempt.
ATTEMPTS_ON_A_FAILING_READ = 4

REPRO_RUN = "lnpl run examples/checkout.lnpl"
REPRO_DIFF = "lnpl diff examples/checkout.lnpl"
REPRO_DIFF_NO_ROW = "lnpl diff examples/checkout.lnpl --no-row"


def compile_checkout():
    """The shipped example, compiled exactly as the CLI compiles it."""
    return cli.compile_source(CHECKOUT_LNPL)


def checkout_payload(document):
    """The payload the CLI synthesises when `--payload` is not given."""
    return sample_payload(cli._entities(document))


def run_cli(argv):
    """Drive `cli.main(argv)`; return (exit_code, captured stdout+stderr)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def _tmp_workdir(test):
    """A per-test build directory under the worktree, removed on teardown.

    `.claude/tmp`, never /tmp: repo policy, and the CLI's own `--workdir` default
    already points there.
    """
    base = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    path = tempfile.mkdtemp(prefix="lnpl-t4-", dir=base)
    test.addCleanup(shutil.rmtree, path, True)
    return path


class TestCheckoutRunsInModeA(unittest.TestCase):
    """Issue #35 criterion 1, on the shipped file through the CLI's own derivation.

    `test_golden.py` proves the interpreter completes this workflow. What is
    proven here is that the seed the *CLI* hands it — `cli._repo_rows`, the code
    path `lnpl run` actually executes — is the seed that makes it complete, and
    that the command exits 0 when it does.
    """

    def setUp(self):
        self.doc = compile_checkout()
        self.payload = checkout_payload(self.doc)
        self.rows = cli._repo_rows(self.doc, self.payload, WORKFLOW)

    def test_the_shipped_example_completes_under_the_default_seed(self):
        interp = Interpreter(self.doc, repo_rows=self.rows)
        result = interp.run_workflow(WORKFLOW, self.payload)

        self.assertEqual(
            result["status"], "completed",
            "issue #35 regression: expected the shipped read-then-create example "
            "to complete under the CLI's default seed; got status=%r, failed at "
            "step %r. Reproduce with `%s`."
            % (result["status"], result["failed_step"], REPRO_RUN))
        self.assertEqual(
            [s["step"] for s in result["steps"]], STEPS,
            "issue #35 regression: expected all four steps of examples/checkout.lnpl "
            "to run in declared order; a short list means the workflow stopped early. "
            "Reproduce with `%s`." % REPRO_RUN)
        self.assertEqual(
            result["skipped"], [],
            "issue #35 regression: the default payload sets stock=1 so `when stock "
            "> 0` is taken; nothing should be skipped, but %r was. Reproduce with "
            "`%s`." % (result["skipped"], REPRO_RUN))

    def test_it_completes_because_only_the_read_entity_is_seeded(self):
        # The reason, asserted separately from the result. Issue #35's defect was
        # seeding EVERY declared entity, which made `create order` conflict on
        # every run; a silent widening of the seed rule has to fail here rather
        # than pass quietly somewhere else.
        self.assertEqual(
            seeded_entities(self.doc, WORKFLOW), {"entity.product"},
            "issue #35 regression: the seed rule is role-based — only entities the "
            "workflow READS are seeded. Product is read, Order is create-only. A "
            "different set here means the rule widened back to the defect the "
            "issue reports.")
        self.assertEqual(
            set(self.rows), {"entity.product"},
            "issue #35 regression: `cli._repo_rows` must materialise rows for the "
            "read entity only; got tables for %s. Reproduce with `%s`."
            % (sorted(self.rows), REPRO_RUN))
        self.assertNotIn(
            "entity.order", self.rows,
            "issue #35 regression: seeding entity.order makes `create order` hit an "
            "'already exists' conflict on every run — this IS the bug the issue "
            "reports. Reproduce with `%s`." % REPRO_RUN)

    def test_lnpl_run_exits_zero_on_the_shipped_example(self):
        code, out = run_cli(["run", CHECKOUT_LNPL])

        self.assertEqual(
            code, 0,
            "issue #35 regression: `%s` must exit 0; it exited %d. Output:\n%s"
            % (REPRO_RUN, code, out))
        self.assertIn(
            "completed", out,
            "issue #35 regression: `%s` exited 0 but did not report a completed "
            "workflow. Output:\n%s" % (REPRO_RUN, out))

    def test_lnpl_run_no_row_exits_nonzero_and_names_the_failing_step(self):
        # The error case at this level, and the control for the test above: an
        # empty store must still fail, so a `run` that exits 0 unconditionally
        # cannot pass both tests.
        code, out = run_cli(["run", CHECKOUT_LNPL, "--no-row"])

        self.assertEqual(
            code, 1,
            "issue #35 regression: `%s --no-row` starts with an empty repository, so "
            "`find product` finds nothing and the run must fail with exit 1; it "
            "exited %d. Output:\n%s" % (REPRO_RUN, code, out))
        self.assertIn(
            "failed at: find product", out,
            "issue #35 regression: `%s --no-row` must fail AT `find product` — the "
            "read, not the create. A different failing step means the seed rule or "
            "the store lookup changed. Output:\n%s" % (REPRO_RUN, out))


class TestModeBToolchainIsRequired(unittest.TestCase):
    """The sentinel that replaces `skipUnless` in this module.

    Every other mode B test in the suite is wrapped in
    `@unittest.skipUnless(backend.toolchain_available(), ...)`. Doing that here
    would mean the machine without LLVM runs issue #35's regression, silently
    drops the half of it that only mode B can catch, and prints OK. This test
    makes that machine say so out loud, once, with the fix attached — the whole
    cost of the no-skip decision is contained in this one failure message.
    """

    def test_the_mode_b_toolchain_is_present_because_issue_35_needs_it(self):
        self.assertTrue(
            backend.toolchain_available(),
            "issue #35 regression cannot run: the MLIR/LLVM toolchain is missing, so "
            "mode B cannot be built and `lnpl diff` cannot be compared. This module "
            "deliberately does NOT skip — half of issue #35 (mode B modelling "
            "repository outcomes) is catchable ONLY by the mode A/B comparison, and "
            "a skipped regression would report OK while checking nothing.\n"
            "Fix:\n"
            "  brew install llvm\n"
            "  export PATH=\"/opt/homebrew/opt/llvm/bin:$PATH\"\n"
            "  SDK=\"$(xcrun --show-sdk-path)\"\n"
            "  export CPATH=\"$SDK/usr/include\" LIBRARY_PATH=\"$SDK/usr/lib\"")


class TestCheckoutIsEquivalentInBothModes(unittest.TestCase):
    """Issue #35 criterion 2, on the shipped file under BOTH seed conditions.

    `test_backend.py` proves the seed condition reaches mode B and that the two
    modes agree — on fixtures it builds itself. This class runs the same
    comparison against `examples/checkout.lnpl` as committed, which is what
    `lnpl diff` runs and what the issue reported on.

    EQUIVALENT on its own is a weak claim: two modes that both do nothing agree
    perfectly. So each case also pins WHAT they agreed on — the completed order
    for the seeded run, and the shared failure at the same step, with the same
    per-attempt effects, for the empty one.
    """

    def setUp(self):
        self.workdir = _tmp_workdir(self)
        self.doc = compile_checkout()
        self.payload = checkout_payload(self.doc)
        self.rows = cli._repo_rows(self.doc, self.payload, WORKFLOW)

    def test_the_default_seed_compares_equivalent(self):
        ok, report = verify(self.doc, WORKFLOW, self.payload, self.rows,
                            self.workdir)

        self.assertTrue(
            ok,
            "issue #35 regression: `%s` must report EQUIVALENT on the shipped "
            "example. Report:\n%s" % (REPRO_DIFF, "\n".join(report)))
        self.assertEqual(
            report[-1], "differential: EQUIVALENT",
            "issue #35 regression: the verdict line changed. Report:\n%s"
            % "\n".join(report))
        for axis in ("PASS 1/4", "PASS 2/4", "PASS 3/4", "PASS 4/4"):
            self.assertTrue(
                any(line.startswith(axis) for line in report),
                "issue #35 regression: RFC-0004 names four observables and all four "
                "must be compared; %s is missing, so the verdict covers less than it "
                "claims. Report:\n%s" % (axis, "\n".join(report)))

        # ... and agreement on the RIGHT state, not merely on some state.
        a = observe_mode_a(self.doc, WORKFLOW, self.payload, self.rows)
        self.assertEqual(
            a["status"], "completed",
            "issue #35 regression: the two modes agreed, but on status=%r rather "
            "than completed. Reproduce with `%s`." % (a["status"], REPRO_DIFF))
        self.assertEqual(
            a["order"], STEPS,
            "issue #35 regression: the two modes agreed, but on %r rather than the "
            "four declared steps. Reproduce with `%s`." % (a["order"], REPRO_DIFF))

    def test_the_empty_store_compares_equivalent_by_failing_the_same_way(self):
        ok, report = verify(self.doc, WORKFLOW, self.payload, {}, self.workdir,
                            seeded=frozenset())

        self.assertTrue(
            ok,
            "issue #35 regression: `%s` must report EQUIVALENT. Report:\n%s"
            % (REPRO_DIFF_NO_ROW, "\n".join(report)))

        # A matching verdict alone would not prove this. With an empty store both
        # modes must FAIL, and fail at the same step, with the same effects —
        # mode B derives that statically from the seed condition, so a mode B that
        # simply completed would also produce a verdict, just not this one.
        a = observe_mode_a(self.doc, WORKFLOW, self.payload, {})
        b = observe_mode_b(self.doc, WORKFLOW, self.workdir, payload=self.payload,
                           seeded=frozenset())

        self.assertEqual(
            a["status"], "failed",
            "issue #35 regression: with an empty repository `find product` has "
            "nothing to read, so mode A must fail; got %r. Reproduce with `%s`."
            % (a["status"], REPRO_DIFF_NO_ROW))
        self.assertEqual(
            b["status"], "failed",
            "issue #35 regression: mode B must derive the same failure from the seed "
            "condition; got %r. A completed mode B here is the original defect — the "
            "backend not modelling repository state at all. Reproduce with `%s`."
            % (b["status"], REPRO_DIFF_NO_ROW))
        self.assertEqual(
            a["order"], ["validate product", "find product"],
            "issue #35 regression: mode A must stop AT the failing read — validation "
            "then the read, nothing after it; got %r." % (a["order"],))
        self.assertEqual(
            b["order"], a["order"],
            "issue #35 regression: the modes must truncate at the same step.\n"
            "  mode A: %s\n  mode B: %s\nReproduce with `%s`."
            % (a["order"], b["order"], REPRO_DIFF_NO_ROW))
        self.assertEqual(
            b["effects"], a["effects"],
            "issue #35 regression: the modes must emit the same effects per step.\n"
            "  mode A: %s\n  mode B: %s\nReproduce with `%s`."
            % (a["effects"], b["effects"], REPRO_DIFF_NO_ROW))

    def test_the_empty_store_repeats_the_read_once_per_retry_attempt(self):
        # The subtlest part of the fix, and the one a plausible implementation
        # gets wrong: mode B has to reproduce the per-ATTEMPT effect spans, not
        # just the fact of a failure. `retry 3` turns one failing read into four
        # RepositoryCall spans; a single-attempt model still fails at the right
        # step with the right status and only differs here, on axis 3/4.
        a = observe_mode_a(self.doc, WORKFLOW, self.payload, {})
        b = observe_mode_b(self.doc, WORKFLOW, self.workdir, payload=self.payload,
                           seeded=frozenset())
        expected = ["RepositoryCall"] * ATTEMPTS_ON_A_FAILING_READ

        self.assertEqual(
            a["effects"]["find product"], expected,
            "issue #35 regression: `retry 3` in examples/checkout.lnpl means one "
            "initial attempt plus three retries, and a read is idempotent, so mode A "
            "must emit %d RepositoryCall spans on the failing read; got %r."
            % (ATTEMPTS_ON_A_FAILING_READ, a["effects"]["find product"]))
        self.assertEqual(
            b["effects"]["find product"], expected,
            "issue #35 regression: mode B must derive the same %d per-attempt spans "
            "from the seed condition; got %r. Collapsing them to one is invisible on "
            "status and on execution order — it shows up only here, and only on a "
            "workflow with a retry budget. Reproduce with `%s`."
            % (ATTEMPTS_ON_A_FAILING_READ, b["effects"]["find product"],
               REPRO_DIFF_NO_ROW))

    def test_a_seed_condition_that_contradicts_the_rows_is_refused(self):
        # Error case. Mode A is handed materialised rows and mode B a seed
        # condition, so one fact reaches the comparison twice. A caller that seeds
        # one and not the other produces a real disagreement that is really a
        # wiring mistake — and a DIVERGENT report that means something else.
        with self.assertRaises(DifferentialError) as ctx:
            verify(self.doc, WORKFLOW, self.payload, self.rows, self.workdir,
                   seeded=frozenset())

        message = str(ctx.exception)
        self.assertIn(
            "entity.product", message,
            "issue #35 regression: the refusal must NAME the entity the two seed "
            "inputs disagree about, so the caller can find the wiring mistake; got "
            "%r." % message)
        self.assertIn(
            "seed inputs disagree", message,
            "issue #35 regression: the refusal must say the inputs disagree rather "
            "than surfacing as a divergence; got %r." % message)

    def test_stock_zero_takes_the_guard_false_branch_in_both_modes(self):
        # Boundary case: `when stock > 0`. 0 is the limit itself and the sample's
        # 1 is one past it, so the two together span the guard. The guarded item
        # is the CREATE, which makes this the interesting interaction — the false
        # branch is the only path where the repository call never happens at all.
        self.assertEqual(
            self.payload["stock"], 1,
            "the default sample payload must take the guard (stock=1, one past the "
            "limit); if it changed, this boundary no longer brackets `stock > 0`.")
        payload = dict(self.payload)
        payload["stock"] = 0
        rows = cli._repo_rows(self.doc, payload, WORKFLOW)

        ok, report = verify(self.doc, WORKFLOW, payload, rows, self.workdir)
        self.assertTrue(
            ok,
            "issue #35 regression: at the guard's boundary (stock=0) the modes must "
            "still agree. Report:\n%s" % "\n".join(report))

        a = observe_mode_a(self.doc, WORKFLOW, payload, rows)
        b = observe_mode_b(self.doc, WORKFLOW, self.workdir, payload=payload)
        for mode, seen in (("A", a), ("B", b)):
            self.assertEqual(
                seen["status"], "completed",
                "issue #35 regression: a false guard skips the create; the workflow "
                "still completes. Mode %s reported %r." % (mode, seen["status"]))
            self.assertNotIn(
                "create order", seen["order"],
                "issue #35 regression: `when stock > 0` is false at stock=0, so mode "
                "%s must not run `create order`; its order was %r."
                % (mode, seen["order"]))
            self.assertEqual(
                seen["order"], ["validate product", "find product", "cache product"],
                "issue #35 regression: mode %s must run the three unguarded steps and "
                "stop; got %r." % (mode, seen["order"]))

    def test_lnpl_diff_exits_zero_under_both_seed_conditions(self):
        # The entry point the issue actually used, asserted on its exit code —
        # a library call returning ok=True says nothing about what `lnpl diff`
        # reports to a shell.
        for argv, repro in ((["diff", CHECKOUT_LNPL, "--workdir", self.workdir],
                             REPRO_DIFF),
                            (["diff", CHECKOUT_LNPL, "--no-row",
                              "--workdir", self.workdir], REPRO_DIFF_NO_ROW)):
            with self.subTest(command=repro):
                code, out = run_cli(argv)
                self.assertEqual(
                    code, 0,
                    "issue #35 regression: `%s` must exit 0; it exited %d. "
                    "Output:\n%s" % (repro, code, out))
                self.assertIn(
                    "differential: EQUIVALENT", out,
                    "issue #35 regression: `%s` exited 0 without reporting "
                    "EQUIVALENT. Output:\n%s" % (repro, out))


class TestTheShippedExampleCanStillDiverge(unittest.TestCase):
    """The reverse control, at THIS level: the end-to-end path can still fail.

    Everything above asserts EQUIVALENT. A comparison that had become structurally
    incapable of reporting DIVERGENT — mode B copying mode A's answer, say — would
    satisfy every one of those tests while checking nothing. `test_backend.py` runs
    reverse controls on its own inline fixtures; these run them on the shipped
    example, so the artifact `lnpl diff` actually compares is the one proven
    discriminating.

    Each case follows the same order: require EQUIVALENT on the UNMUTATED document
    first, so a later red is attributable to the injected fault rather than to a
    standing divergence, then apply exactly one mode-B-only fault and require a
    SPECIFIC failing axis. A bare `assertFalse(ok)` would also pass if the modes
    had been disagreeing all along for an unrelated reason.
    """

    def setUp(self):
        self.workdir = _tmp_workdir(self)
        self.doc = compile_checkout()
        self.payload = checkout_payload(self.doc)
        self.rows = cli._repo_rows(self.doc, self.payload, WORKFLOW)
        # Captured here and restored in tearDown, which runs on failure too — a
        # test that dies mid-way must not leave a mutated backend for the rest of
        # the suite.
        self.original_steps = backend._steps_in_order
        self.original_failure_attempts = backend._failure_attempts

    def tearDown(self):
        backend._steps_in_order = self.original_steps
        backend._failure_attempts = self.original_failure_attempts

    def test_a_reordered_mode_b_diverges_on_the_shipped_example(self):
        ok, report = verify(self.doc, WORKFLOW, self.payload, self.rows,
                            self.workdir)
        self.assertTrue(
            ok,
            "the control has no reference point: examples/checkout.lnpl must "
            "compare EQUIVALENT before a fault is injected, or the red below "
            "proves nothing. Report:\n%s" % "\n".join(report))

        original = self.original_steps

        def reversed_order(nodes, ids, out):
            out.extend(list(reversed(original(nodes, ids, []))))
            return out

        backend._steps_in_order = reversed_order
        ok, report = verify(self.doc, WORKFLOW, self.payload, self.rows,
                            self.workdir)

        self.assertFalse(
            ok, "issue #35 regression: mode B emitting the shipped example's steps "
                "in reverse order must be reported as DIVERGENT. It was not, which "
                "means `%s` can no longer detect a mode B defect at all — every "
                "EQUIVALENT above is then worthless. Report:\n%s"
                % (REPRO_DIFF, "\n".join(report)))
        self.assertTrue(
            any(line.startswith("FAIL 1/4") for line in report),
            "issue #35 regression: a reordered mode B must fail on the EXECUTION "
            "ORDER axis specifically; failing on some other axis means the report "
            "misattributes the defect. Report:\n%s" % "\n".join(report))

    def test_mode_b_losing_the_per_attempt_spans_diverges_on_the_shipped_example(self):
        # The control that guards the 4-span assertion above. Collapsing the
        # per-attempt spans is the failure mode a plausible mode B ships with, and
        # it is invisible on every axis except observability signals.
        ok, report = verify(self.doc, WORKFLOW, self.payload, {}, self.workdir,
                            seeded=frozenset())
        self.assertTrue(
            ok,
            "the control has no reference point: `%s` must compare EQUIVALENT "
            "before a fault is injected. Report:\n%s"
            % (REPRO_DIFF_NO_ROW, "\n".join(report)))

        backend._failure_attempts = lambda *args, **kwargs: 1
        ok, report = verify(self.doc, WORKFLOW, self.payload, {}, self.workdir,
                            seeded=frozenset())

        self.assertFalse(
            ok, "issue #35 regression: mode B emitting ONE attempt where mode A "
                "made %d must be reported as DIVERGENT. Passing means the "
                "per-attempt derivation is no longer compared on the shipped "
                "example. Report:\n%s"
                % (ATTEMPTS_ON_A_FAILING_READ, "\n".join(report)))
        self.assertTrue(
            any(line.startswith("FAIL 3/4") for line in report),
            "issue #35 regression: a lost attempt count must fail on the "
            "OBSERVABILITY SIGNALS axis — status and execution order are identical "
            "either way, so any other axis means the comparison found something "
            "else. Report:\n%s" % "\n".join(report))


# ---- RFC-0011 §G11.6: mode B reads the same scope mode A builds --------------

def scoped_checkout():
    """The shipped checkout document, asserted to carry the qualified guard.

    `examples/checkout.lnpl` now declares `when product.stock > 0` itself, so this
    reads the committed file rather than substituting a condition into it — the
    point of this module is that the SHIPPED artifact is the one verified. The
    assertion keeps that honest: if the example's guard is ever unqualified again,
    these tests fail instead of quietly re-qualifying it and passing.
    """
    doc = compile_checkout()
    guards = [n for n in doc["nodes"] if n["kind"] == "Guard"]
    assert [g.get("condition") for g in guards] == ["product.stock > 0"], (
        "examples/checkout.lnpl must carry the qualified guard for this module "
        "to be testing RFC-0011's scope; got %r"
        % [g.get("condition") for g in guards])
    return doc


class TestModeBResolvesTheSameScope(unittest.TestCase):
    """A qualified guard must decide the same way in both modes."""

    def setUp(self):
        self.doc = scoped_checkout()
        self.payload = checkout_payload(self.doc)
        self.workdir = _tmp_workdir(self)

    def test_the_default_seed_compares_equivalent_with_a_qualified_guard(self):
        rows = cli._repo_rows(self.doc, self.payload, WORKFLOW)
        ok, report = verify(self.doc, WORKFLOW, self.payload, rows, self.workdir)
        self.assertTrue(ok, "RFC-0011 G11.6: mode B derives `product.stock` from "
                            "the seed rule, so the two modes must still agree. "
                            "Report:\n%s" % "\n".join(report))

    def test_the_empty_store_compares_equivalent_with_a_qualified_guard(self):
        # `--no-row`: nothing is seeded, so nothing binds. Mode A's read fails
        # before the guard is reached and mode B models the same failure.
        ok, report = verify(self.doc, WORKFLOW, self.payload, {}, self.workdir,
                            seeded=frozenset())
        self.assertTrue(ok, "Report:\n%s" % "\n".join(report))

    def test_the_guard_boundary_agrees_in_both_modes(self):
        # stock=0 is the limit itself. Under the default seed the row is a copy
        # of the payload, so both modes see 0 and both close the guard.
        payload = dict(self.payload)
        payload["stock"] = 0
        rows = cli._repo_rows(self.doc, payload, WORKFLOW)
        ok, report = verify(self.doc, WORKFLOW, payload, rows, self.workdir)
        self.assertTrue(ok, "Report:\n%s" % "\n".join(report))
        for mode, seen in (("A", observe_mode_a(self.doc, WORKFLOW, payload, rows)),
                           ("B", observe_mode_b(self.doc, WORKFLOW, self.workdir,
                                                payload=payload))):
            self.assertNotIn("create order", seen["order"],
                             "mode %s must close the guard at stock=0" % mode)

    def test_mode_a_runtime_bindings_match_the_static_projection(self):
        # The invariant that keeps the two derivations from drifting: what mode A
        # binds at run time must equal what `seed_bindings` projects statically,
        # because mode B is handed the projection. If these ever diverge, mode B
        # is evaluating a guard against values mode A never saw.
        from lnpl.repo_policy import seed_bindings
        rows = cli._repo_rows(self.doc, self.payload, WORKFLOW)
        interp = Interpreter(self.doc, repo_rows=rows)
        result = interp.run_workflow(WORKFLOW, self.payload)
        projected = seed_bindings(self.doc, WORKFLOW, self.payload, None)
        self.assertEqual(result["bindings"], projected,
                         "mode A bound %r but the static projection mode B reads "
                         "says %r." % (result["bindings"], projected))

    def test_the_projection_is_empty_without_a_seed(self):
        # Boundary: `--no-row`. Nothing seeded means nothing bound.
        from lnpl.repo_policy import seed_bindings
        self.assertEqual(
            seed_bindings(self.doc, WORKFLOW, self.payload, frozenset()), {})

    def test_a_qualified_presence_guard_derives_the_same_skip_flag(self):
        from lnpl.differential import _derive_skip_from_payload
        from lnpl.interp import _condition_holds
        from lnpl.repo_policy import seed_bindings
        doc = compile_checkout()
        for node in doc["nodes"]:
            if node["kind"] == "Guard":
                node["condition"] = "product.name missing"
        bindings = seed_bindings(doc, WORKFLOW, self.payload, None)
        mode_a = _condition_holds("product.name missing", self.payload, bindings)
        skip = _derive_skip_from_payload(doc, WORKFLOW, self.payload, None)
        self.assertEqual(skip, not mode_a,
                         "the skip flag is the negation of mode A's verdict; a "
                         "qualified Presence guard must not change that.")
        self.assertTrue(skip, "the seeded row carries `name`, so `name missing` "
                              "is false and the guarded item is skipped.")


class TestUnreproducibleRowsAreRefusedNotCompared(unittest.TestCase):
    """RFC-0011 §G11.6: mode B projects rows from the seed rule, so a row whose
    content the rule cannot produce is outside what the comparison can mean.

    Comparing anyway would report a caller's wiring choice as a mode A/B
    divergence — the same false verdict `_check_seed_agreement` refuses for the
    seed SET. Refusing keeps a DIVERGENT report meaning what it says.
    """

    def setUp(self):
        self.doc = scoped_checkout()
        self.payload = checkout_payload(self.doc)
        self.workdir = _tmp_workdir(self)

    def _rows_with(self, **overrides):
        rows = cli._repo_rows(self.doc, self.payload, WORKFLOW)
        for table in rows.values():
            for row in table.values():
                row.update(overrides)
        return rows

    def test_a_row_that_differs_from_the_payload_is_refused(self):
        with self.assertRaises(DifferentialError) as caught:
            verify(self.doc, WORKFLOW, self.payload, self._rows_with(stock=0),
                   self.workdir)
        message = str(caught.exception)
        self.assertIn("stock", message,
                      "the refusal must NAME the field whose value the seed rule "
                      "cannot reproduce, so the caller can find it; got %r"
                      % message)
        self.assertIn("entity.product", message)

    def test_the_refusal_says_it_is_not_a_divergence(self):
        with self.assertRaises(DifferentialError) as caught:
            verify(self.doc, WORKFLOW, self.payload, self._rows_with(stock=0),
                   self.workdir)
        self.assertIn("reproduce", str(caught.exception),
                      "the message must explain that the row is unreproducible, "
                      "not report a disagreement between the modes.")

    def test_mode_a_alone_still_accepts_such_a_row(self):
        # The refusal belongs to the COMPARISON, not to mode A. Issue #37's own
        # proof runs mode A against exactly this input, so blocking it here would
        # break the thing this task exists to enable.
        rows = self._rows_with(stock=0)
        seen = observe_mode_a(self.doc, WORKFLOW, self.payload, rows)
        self.assertEqual(seen["status"], "completed")
        self.assertNotIn("create order", seen["order"],
                         "mode A reads the stored row (stock=0), so the guard "
                         "closes even though the payload's stock would open it.")

    def test_a_faithful_row_is_not_refused(self):
        # Control: the refusal must be about unreproducibility, not about
        # refusing every explicit row.
        rows = cli._repo_rows(self.doc, self.payload, WORKFLOW)
        ok, report = verify(self.doc, WORKFLOW, self.payload, rows, self.workdir)
        self.assertTrue(ok, "Report:\n%s" % "\n".join(report))


if __name__ == "__main__":
    unittest.main()
