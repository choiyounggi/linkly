"""Diagnostics reach the user, on the right stream (issues #36, #38).

A diagnostic nobody sees is the bug it was written to fix, so this file drives
the real `cli.main([...])` path rather than the functions under it.

Two properties matter as much as the text. First, diagnostics go to **stderr**:
`lnpl compile` writes the IR document to stdout when `-o` is absent, so a
diagnostic on stdout would corrupt the artifact — the tests below parse stdout
as JSON to prove it stayed clean. Second, the **exit code does not move**: a
descriptive step is a legitimate way to write LNPL (the golden `login.lnpl` uses
three), so this reports without rejecting.
"""

import contextlib
import io
import json
import os
import shutil
import unittest

from lnpl import cli
from lnpl.diagnostics import SEVERITY_OF

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGIN = os.path.join(REPO, "examples", "login.lnpl")
TMP = os.path.join(REPO, ".claude", "tmp", "cli-diagnostics")

# No service clause and every verb inside VERB_LEXICON: nothing to report.
CLEAN_SOURCE = """
entity User
    field
        id UUID
workflow Login
    validate input
"""

# Issue #52 fixtures. `on schedule daily` is a legitimate declaration whose
# UNENFORCED status is permanent by design (RFC-0016; issue #26 owns the
# executor), so it emits `declared-not-enforced` — grade `info`. Nothing the
# author can edit removes that line, which is why gating on it made #45 and #49
# mutually exclusive.
SCHEDULE_ONLY = """
service Rollup

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    read Report
"""

# The contrast: `frobnicate` is outside VERB_LEXICON, so the step derives no
# Effect and silently does nothing — grade `warning`, and editing removes it.
TYPO_ONLY = """
entity Report
    field
        id UUID

workflow GetReport
    read Report
    frobnicate Report
"""

# Both grades in one module, so a threshold has something to separate.
SCHEDULE_AND_TYPO = """
service Rollup

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    read Report
    frobnicate Report
"""

# The same schedule declaration with a spec block, so `spec --run` reaches the
# gate instead of exiting 1 on "no spec block found".
SCHEDULE_WITH_SPEC = """
service Rollup

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    read Report
    spec
        given
            valid report
        when
            get report
        expect
            completed
"""

# Unenforced declarations and not a single step to run.
DECLARED_BUT_NO_WORKFLOW = """
entity User
    field
        id UUID
service LoginService
    policy
        rollback
    security
        jwt
"""

# Nothing to report at compile time; one diagnostic only once it RUNS.
RUNTIME_ONLY = """
entity User
    field
        id UUID
workflow Login
    authorize admin
"""

# One diagnostic from each producer, so the two must arrive as one report.
BOTH_PRODUCERS = """
entity User
    field
        id UUID
service LoginService
    security
        jwt
workflow Login
    authorize admin
    generate token
"""


def run_cli_split(argv):
    """Drive `cli.main(argv)`, keeping stdout and stderr apart."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def run_cli_usage_error(argv):
    """Same, for argv argparse rejects before dispatch — it raises SystemExit.

    Returns the exit code rather than a return value, because that is the only
    thing a shell sees either way: `2 = compile error, usage error, strict gate`
    is one class to a caller reading `$?`.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(argv)
        except SystemExit as exc:
            return exc.code, out.getvalue(), err.getvalue()
    raise AssertionError("expected a usage error for %r" % (argv,))


class TestGoldenScenarioDiagnostics(unittest.TestCase):
    """`examples/login.lnpl` carries three unknown verbs and three declarations."""

    def test_compile_reports_all_six_and_still_succeeds(self):
        rc, out, err = run_cli_split(["compile", LOGIN])
        self.assertEqual(rc, 0)
        self.assertEqual(err.count("unknown-verb"), 3)
        self.assertEqual(err.count("declared-not-enforced"), 2)
        self.assertEqual(err.count("declared-measured-only"), 1)

    def test_compile_ends_with_the_summary_line(self):
        _, _, err = run_cli_split(["compile", LOGIN])
        self.assertEqual(err.strip().splitlines()[-1],
                         "3 info, 3 warning(s), 0 error(s)")

    def test_compile_names_each_out_of_lexicon_verb(self):
        _, _, err = run_cli_split(["compile", LOGIN])
        for verb in ("generate", "audit", "return"):
            self.assertIn(verb, err)

    def test_compile_names_each_unenforced_declaration(self):
        _, _, err = run_cli_split(["compile", LOGIN])
        for declaration in ("security jwt", "policy rollback", "performance response"):
            self.assertIn(declaration, err)

    def test_compile_does_not_report_the_enforced_declarations(self):
        # `retry`, `timeout` and `cache` are genuinely enforced; naming them
        # would be a false alarm and would make the report worthless.
        _, _, err = run_cli_split(["compile", LOGIN])
        for enforced in ("policy retry", "policy timeout", "performance cache"):
            self.assertNotIn(enforced, err)

    def test_stdout_stays_a_parseable_ir_document(self):
        # The whole reason diagnostics go to stderr: `compile` without `-o`
        # writes the artifact to stdout.
        _, out, err = run_cli_split(["compile", LOGIN])
        doc = json.loads(out)
        self.assertEqual(doc["module"], "login")
        self.assertEqual(doc["lir_version"], "0.1")
        self.assertNotIn("unknown-verb", out)
        self.assertTrue(err, "diagnostics must still have been emitted")

    def test_run_reports_the_same_diagnostics_and_still_succeeds(self):
        rc, _, err = run_cli_split(["run", LOGIN])
        self.assertEqual(rc, 0)
        self.assertEqual(err.count("unknown-verb"), 3)
        self.assertIn("security jwt", err)

    def test_run_json_keeps_stdout_machine_readable(self):
        rc, out, err = run_cli_split(["run", LOGIN, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertIn("result", payload)
        self.assertIn("trace", payload)
        self.assertEqual(payload["result"]["status"], "completed")
        self.assertIn("unknown-verb", err)

    def test_diagnostics_do_not_enter_the_trace(self):
        # Mode A/B equivalence covers log levels; mode B cannot emit these.
        _, out, _ = run_cli_split(["run", LOGIN, "--json"])
        payload = json.loads(out)
        self.assertNotIn("unknown-verb", json.dumps(payload["trace"]))
        self.assertNotIn("authorization-not-verified", json.dumps(payload["trace"]))


class TestSilenceWhenThereIsNothingToReport(unittest.TestCase):
    """The boundary that keeps the report meaningful."""

    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        self.source = os.path.join(TMP, "clean.lnpl")
        with open(self.source, "w", encoding="utf-8") as fh:
            fh.write(CLEAN_SOURCE)

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_compile_of_a_clean_module_prints_nothing_to_stderr(self):
        rc, out, err = run_cli_split(["compile", self.source])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        # ...and it really did compile something.
        self.assertEqual(json.loads(out)["module"], "clean")

    def test_run_of_a_clean_module_prints_nothing_to_stderr(self):
        rc, _, err = run_cli_split(["run", self.source])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")

    def test_no_summary_line_is_printed_when_there_are_no_diagnostics(self):
        _, _, err = run_cli_split(["compile", self.source])
        self.assertNotIn("warning(s)", err)


class TestRunMergesBothProducers(unittest.TestCase):
    """`run` reports compile-time AND run-time findings as one report.

    The interesting case is a module that is clean at compile time and only
    reports once a step executes: `compile` must stay silent while `run` speaks,
    which is provable only if the merge in `cmd_run` actually happens.
    """

    def setUp(self):
        os.makedirs(TMP, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def _write(self, name, source):
        path = os.path.join(TMP, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source)
        return path

    def test_compile_is_silent_for_a_module_whose_only_finding_is_runtime(self):
        rc, _, err = run_cli_split(["compile", self._write("rt.lnpl", RUNTIME_ONLY)])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")

    def test_run_reports_the_runtime_diagnostic_the_compiler_could_not_see(self):
        # Delete the merge in `cmd_run` and this is the test that goes red.
        rc, _, err = run_cli_split(["run", self._write("rt.lnpl", RUNTIME_ONLY)])
        self.assertEqual(rc, 0)
        self.assertIn("authorization-not-verified", err)
        self.assertIn("admin", err)
        self.assertEqual(err.strip().splitlines()[-1],
                         "1 info, 0 warning(s), 0 error(s)")

    def test_run_reports_compile_time_and_run_time_findings_together(self):
        path = self._write("both.lnpl", BOTH_PRODUCERS)
        rc, _, err = run_cli_split(["run", path])
        self.assertEqual(rc, 0)
        self.assertIn("security jwt", err)                 # compile time
        self.assertIn("generate", err)                     # compile time
        self.assertIn("authorization-not-verified", err)   # run time
        # One report, one summary — not two reports stapled together.
        self.assertEqual(err.count("warning(s)"), 1)
        self.assertEqual(err.strip().splitlines()[-1],
                         "2 info, 1 warning(s), 0 error(s)")

    def test_compile_of_the_same_module_omits_only_the_runtime_finding(self):
        path = self._write("both.lnpl", BOTH_PRODUCERS)
        _, _, err = run_cli_split(["compile", path])
        self.assertIn("security jwt", err)
        self.assertIn("generate", err)
        self.assertNotIn("authorization-not-verified", err)
        self.assertEqual(err.strip().splitlines()[-1],
                         "1 info, 1 warning(s), 0 error(s)")

    def test_the_runtime_diagnostic_stays_out_of_the_result_and_the_trace(self):
        """Since #52 the record rides on stdout — but only in its own key.

        The original form of this test asserted the code appeared nowhere in
        stdout at all. `run --json` now publishes the diagnostics deliberately
        (r3 F-8), so the assertion moved to where the risk actually is: the
        `result` and `trace` objects are consumed as the run's own output, and a
        diagnostic leaking into either would be the artifact corruption that put
        diagnostics on stderr in the first place.
        """
        path = self._write("rt.lnpl", RUNTIME_ONLY)
        _, out, err = run_cli_split(["run", path, "--json"])
        self.assertIn("authorization-not-verified", err)
        payload = json.loads(out)
        self.assertNotIn("authorization-not-verified", json.dumps(payload["result"]))
        self.assertNotIn("authorization-not-verified", json.dumps(payload["trace"]))
        # ...and it is present exactly once, in the channel built for it.
        self.assertEqual([d["code"] for d in payload["diagnostics"]],
                         ["authorization-not-verified"])
        # The span attribute the interpreter always wrote is still there.
        self.assertIn("admin", json.dumps(payload["trace"]))


class TestStrictExitGate(unittest.TestCase):
    """`--strict` turns "reported but exited 0" into a machine-checkable gate.

    Issue #45 t3 F-8: a warning that only reaches stderr cannot gate CI, because
    the only thing CI reliably reads is the exit code — parsing stderr is not a
    contract. `--strict` promotes a *clean* exit (rc 0) carrying diagnostics to
    rc 2, reusing the existing "rejected" code. It never masks a non-zero rc,
    and it never changes the stderr text, so the default mode is untouched.

    Exit contract (consumed by #44 and #50):
      0 = success (under --strict, also means zero diagnostics)
      1 = run/spec failure    2 = compile error, usage error, strict gate
      3 = runtime error       4 = backend error
    """

    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        self.clean = os.path.join(TMP, "clean.lnpl")
        with open(self.clean, "w", encoding="utf-8") as fh:
            fh.write(CLEAN_SOURCE)
        # One unknown-verb diagnostic, and a read that fails on an empty repo.
        self.failing = os.path.join(TMP, "runfail.lnpl")
        with open(self.failing, "w", encoding="utf-8") as fh:
            fh.write("entity User\n    field\n        id UUID\n"
                     "workflow Login\n    ponder existence\n    read user\n")

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    # ---- the gate fires -----------------------------------------------------
    def test_compile_strict_exits_2_when_a_diagnostic_was_reported(self):
        rc, out, err = run_cli_split(["compile", LOGIN, "--strict"])
        self.assertEqual(rc, 2)
        self.assertEqual(err.count("unknown-verb"), 3)
        self.assertEqual(err.strip().splitlines()[-1],
                         "3 info, 3 warning(s), 0 error(s)")
        # The artifact on stdout is still the artifact.
        self.assertEqual(json.loads(out)["module"], "login")

    def test_run_strict_exits_2_when_a_diagnostic_was_reported(self):
        rc, _, err = run_cli_split(["run", LOGIN, "--strict"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown-verb", err)

    def test_spec_strict_exits_2_when_a_diagnostic_was_reported(self):
        rc, out, err = run_cli_split(["spec", LOGIN, "--run", "--strict"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown-verb", err)
        self.assertIn("spec:", out)      # the manifest still ran
        self.assertIn("0 failed", out)   # ...and rc 2 came from the gate, not a failure

    def test_spec_strict_gates_the_manifest_dump_without_run(self):
        """`spec` without --run writes the manifest to stdout and returns 0."""
        rc, out, err = run_cli_split(["spec", LOGIN, "--strict"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown-verb", err)
        self.assertTrue(json.loads(out)["cases"], "the manifest still reached stdout")

    def test_spec_strict_gates_the_manifest_file_without_run(self):
        """`spec -o <path>` without --run writes a file and returns 0."""
        out_path = os.path.join(TMP, "manifest.json")
        rc, out, err = run_cli_split(["spec", LOGIN, "-o", out_path, "--strict"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown-verb", err)
        self.assertIn("wrote", out)
        with open(out_path, encoding="utf-8") as fh:
            self.assertTrue(json.load(fh)["cases"], "the manifest was still written")

    def test_spec_strict_does_not_overwrite_a_failing_manifest(self):
        """rc 1 means a spec case failed — the gate must not hide that as 2."""
        source = os.path.join(TMP, "specfail.lnpl")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write("entity User\n    field\n        id UUID\n"
                     "workflow Login\n    ponder existence\n    validate input\n"
                     "    spec\n        given\n            valid user\n"
                     "        when\n            login\n"
                     "        expect\n            completed\n            steps 99\n")
        plain_rc, plain_out, _ = run_cli_split(["spec", source, "--run"])
        strict_rc, strict_out, err = run_cli_split(["spec", source, "--run", "--strict"])
        self.assertEqual(plain_rc, 1)
        self.assertEqual(strict_rc, 1)
        self.assertIn("1 failed", strict_out)
        self.assertEqual(plain_out, strict_out, "--strict changes only the exit code")
        self.assertIn("unknown-verb", err)

    # ---- the default mode does not move ------------------------------------
    def test_without_strict_the_exit_code_and_stderr_are_unchanged(self):
        plain_rc, _, plain_err = run_cli_split(["compile", LOGIN])
        strict_rc, _, strict_err = run_cli_split(["compile", LOGIN, "--strict"])
        self.assertEqual(plain_rc, 0)
        self.assertEqual(strict_rc, 2)
        self.assertEqual(plain_err, strict_err,
                         "--strict changes the exit code, never the report")

    def test_run_without_strict_still_exits_0(self):
        rc, _, _ = run_cli_split(["run", LOGIN])
        self.assertEqual(rc, 0)

    # ---- boundary: nothing to report ---------------------------------------
    def test_strict_on_a_clean_module_exits_0(self):
        rc, _, err = run_cli_split(["compile", self.clean, "--strict"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")

    def test_strict_run_on_a_clean_module_exits_0(self):
        rc, _, err = run_cli_split(["run", self.clean, "--strict"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")

    # ---- priority: a real failure is never masked --------------------------
    def test_strict_does_not_overwrite_a_failing_run(self):
        """rc 1 means the run failed; promoting it to 2 would lose that."""
        plain_rc, _, _ = run_cli_split(["run", self.failing, "--no-row"])
        strict_rc, _, err = run_cli_split(["run", self.failing, "--no-row", "--strict"])
        self.assertEqual(plain_rc, 1)
        self.assertEqual(strict_rc, 1)
        self.assertIn("unknown-verb", err)

    def test_strict_does_not_overwrite_a_run_with_no_workflow(self):
        source = os.path.join(TMP, "no-workflow.lnpl")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(DECLARED_BUT_NO_WORKFLOW)
        rc, _, err = run_cli_split(["run", source, "--strict"])
        self.assertEqual(rc, 1)
        self.assertIn("no workflow to run", err)


class TestStrictLevelSelection(unittest.TestCase):
    """`--strict=<level>` picks which grades gate (issue #52).

    The defect this closes: `--strict` fired on *any* diagnostic, so a program
    carrying a legitimate `on schedule daily` declaration returned rc 2 on every
    run — #45's gate and #49's schedule declaration could not both be used
    (qa/rerun r3 N-4; the same shape as r1 N-1 and r4 N-1 for a `performance`
    budget). The grade ladder gives the caller a threshold, exactly as
    Kubernetes makes field validation a per-request `Ignore|Warn|Strict` choice
    rather than one global switch.

    Bare `--strict` is unchanged: it already shipped in v0.3.0, and quietly
    loosening a live CI gate is worse than leaving the ergonomics opt-in.
    """

    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        # r3 N-4's reproduction: an intended declaration, nothing else.
        self.schedule = os.path.join(TMP, "schedule.lnpl")
        with open(self.schedule, "w", encoding="utf-8") as fh:
            fh.write(SCHEDULE_ONLY)
        # The contrast: a verb outside the lexicon, which the gate must keep.
        self.typo = os.path.join(TMP, "typo.lnpl")
        with open(self.typo, "w", encoding="utf-8") as fh:
            fh.write(TYPO_ONLY)
        # Both at once, so a threshold has something to separate.
        self.mixed = os.path.join(TMP, "mixed.lnpl")
        with open(self.mixed, "w", encoding="utf-8") as fh:
            fh.write(SCHEDULE_AND_TYPO)
        self.clean = os.path.join(TMP, "clean.lnpl")
        with open(self.clean, "w", encoding="utf-8") as fh:
            fh.write(CLEAN_SOURCE)

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    # ---- r3 N-4: the mutual exclusion is gone ------------------------------
    def test_a_schedule_declaration_passes_the_warning_gate(self):
        """The whole point of #52: rc 2 -> rc 0 without deleting the report."""
        rc, _, err = run_cli_split(["compile", self.schedule, "--strict=warning"])
        self.assertEqual(rc, 0)
        # The grade changed what gates, not what is said.
        self.assertIn("declared-not-enforced", err)
        self.assertIn("event schedule", err)
        self.assertIn("info:", err)

    def test_the_same_declaration_still_gates_under_the_bare_flag(self):
        """Before/after in one test: the flag that shipped keeps its meaning."""
        bare_rc, _, _ = run_cli_split(["compile", self.schedule, "--strict"])
        warn_rc, _, _ = run_cli_split(["compile", self.schedule, "--strict=warning"])
        self.assertEqual(bare_rc, 2)
        self.assertEqual(warn_rc, 0)

    def test_the_warning_gate_still_catches_a_typo(self):
        """The negative control: a threshold that passed everything is no gate."""
        rc, _, err = run_cli_split(["compile", self.typo, "--strict=warning"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown-verb", err)

    def test_a_mixed_module_gates_on_its_highest_grade(self):
        rc, _, err = run_cli_split(["compile", self.mixed, "--strict=warning"])
        self.assertEqual(rc, 2)
        self.assertIn("declared-not-enforced", err)
        self.assertIn("unknown-verb", err)

    # ---- bare --strict is byte-identical to --strict=info -------------------
    def test_bare_strict_is_the_info_threshold(self):
        for source in (self.schedule, self.typo, self.mixed, self.clean):
            bare = run_cli_split(["compile", source, "--strict"])
            info = run_cli_split(["compile", source, "--strict=info"])
            self.assertEqual(bare[0], info[0], source)
            self.assertEqual(bare[2], info[2], source)

    def test_the_level_never_changes_the_report(self):
        _, _, plain_err = run_cli_split(["compile", self.mixed])
        _, _, warn_err = run_cli_split(["compile", self.mixed, "--strict=warning"])
        self.assertEqual(plain_err, warn_err,
                         "--strict selects an exit code, it never edits stderr")

    # ---- the threshold reaches every command that has the flag -------------
    def test_run_honours_the_level(self):
        bare_rc, _, _ = run_cli_split(["run", self.schedule, "--strict"])
        warn_rc, _, _ = run_cli_split(["run", self.schedule, "--strict=warning"])
        self.assertEqual(bare_rc, 2)
        self.assertEqual(warn_rc, 0)

    def test_spec_honours_the_level(self):
        # `spec` needs a spec block, or it exits 1 before the gate is reached —
        # and rc 1 is a real failure the gate must never repaint as 2.
        source = os.path.join(TMP, "schedule-spec.lnpl")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(SCHEDULE_WITH_SPEC)
        bare_rc, _, _ = run_cli_split(["spec", source, "--run", "--strict"])
        warn_rc, out, _ = run_cli_split(["spec", source, "--run", "--strict=warning"])
        self.assertEqual(bare_rc, 2)
        self.assertEqual(warn_rc, 0)
        self.assertIn("0 failed", out)   # rc 0 is a pass, not an absent run

    # ---- boundary ----------------------------------------------------------
    def test_no_diagnostics_exits_0_at_every_level(self):
        for level in ("--strict", "--strict=info", "--strict=warning",
                      "--strict=error"):
            rc, _, err = run_cli_split(["compile", self.clean, level])
            self.assertEqual(rc, 0, level)
            self.assertEqual(err, "", level)

    def test_the_error_level_gates_on_nothing_today(self):
        """D2a: `error` is a reserved rung, and the help text says so.

        Without the help line a caller could put `--strict=error` in CI and
        believe they had a gate. The pairing is the point, so both halves are
        asserted here.
        """
        rc, _, err = run_cli_split(["compile", self.mixed, "--strict=error"])
        self.assertEqual(rc, 0)
        self.assertIn("unknown-verb", err)      # still reported, just not gating

    def test_the_help_text_says_the_error_level_matches_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit):
                cli.main(["compile", "--help"])
        helptext = out.getvalue()
        self.assertIn("--strict", helptext)
        self.assertIn("error", helptext)
        self.assertIn("reserved", helptext)

    # ---- error ------------------------------------------------------------
    def test_an_unknown_level_is_rejected_naming_the_accepted_set(self):
        code, out, err = run_cli_usage_error(["compile", self.typo,
                                              "--strict=bogus"])
        self.assertEqual(code, 2)
        for level in ("info", "warning", "error"):
            self.assertIn(level, err)
        self.assertIn("bogus", err)
        # A usage error must not look like a successful compile.
        self.assertEqual(out, "")

    def test_the_flag_before_the_source_is_rejected_with_a_correction(self):
        """`--strict src.lnpl` swallows the path as the level (nargs="?").

        argparse's own `choices=` message would list the grades and leave the
        author staring at a path that is obviously not one, so the rejection
        says what to write instead. Without this the shape reads as the
        unrelated "the following arguments are required: source".
        """
        code, out, err = run_cli_usage_error(["compile", "--strict", self.typo])
        self.assertEqual(code, 2)
        self.assertIn("--strict=", err)
        self.assertIn("after the source", err)
        self.assertEqual(out, "")


class TestRunJsonDiagnosticsChannel(unittest.TestCase):
    """`run --json` carries the diagnostics as data (issue #52, r3 F-8).

    CI could gate on the exit code once `--strict` existed, but reading *which*
    diagnostics fired meant regexing stderr, and the message is explicitly not a
    stable interface. The records already have machine-readable fields, so the
    JSON mode emits them instead of asking anyone to parse prose.

    `compile` and `spec` deliberately do not carry them: their stdout is the IR
    document and the manifest, and a diagnostics key would corrupt the artifact
    — which is the same reason diagnostics went to stderr in the first place.
    """

    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        self.clean = os.path.join(TMP, "clean.lnpl")
        with open(self.clean, "w", encoding="utf-8") as fh:
            fh.write(CLEAN_SOURCE)

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_the_json_payload_carries_every_reported_diagnostic(self):
        rc, out, err = run_cli_split(["run", LOGIN, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        # Same count and same order as the human report, which is the claim
        # that makes the two channels one fact rather than two.
        reported = [line for line in err.strip().splitlines()
                    if not line.endswith("error(s)")]
        self.assertEqual(len(payload["diagnostics"]), len(reported))
        self.assertEqual([d["code"] for d in payload["diagnostics"]],
                         [line.split(": ", 1)[1].split(" ", 1)[0]
                          for line in reported])

    def test_every_record_carries_the_six_fields(self):
        # RFC-0024 added `line` (int or null) alongside the original five.
        _, out, _ = run_cli_split(["run", LOGIN, "--json"])
        for record in json.loads(out)["diagnostics"]:
            self.assertEqual(set(record),
                             {"code", "severity", "where", "subject", "message",
                              "line"})

    def test_the_serialised_grade_agrees_with_the_table(self):
        # The serialisation is derived, not restated: if it ever hardcoded a
        # grade this is the assertion that catches the drift.
        _, out, _ = run_cli_split(["run", LOGIN, "--json"])
        for record in json.loads(out)["diagnostics"]:
            self.assertEqual(record["severity"], SEVERITY_OF[record["code"]])

    def test_both_producers_reach_the_payload(self):
        """Compile-time and run-time findings are one list, as on stderr."""
        source = os.path.join(TMP, "both.lnpl")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(BOTH_PRODUCERS)
        _, out, _ = run_cli_split(["run", source, "--json"])
        codes = [d["code"] for d in json.loads(out)["diagnostics"]]
        self.assertIn("unknown-verb", codes)                 # from lowering
        self.assertIn("authorization-not-verified", codes)   # from the run

    def test_a_clean_module_carries_an_empty_list_not_a_missing_key(self):
        """Boundary: a consumer must never branch on the key's existence."""
        _, out, err = run_cli_split(["run", self.clean, "--json"])
        payload = json.loads(out)
        self.assertIn("diagnostics", payload)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(err, "")

    def test_the_existing_keys_are_untouched(self):
        _, out, _ = run_cli_split(["run", LOGIN, "--json"])
        payload = json.loads(out)
        self.assertIn("result", payload)
        self.assertIn("trace", payload)
        self.assertEqual(payload["result"]["status"], "completed")

    def test_without_json_the_records_stay_off_stdout(self):
        """Human mode must not gain a JSON blob."""
        _, out, err = run_cli_split(["run", LOGIN])
        self.assertNotIn('"severity"', out)
        self.assertIn("unknown-verb", err)

    def test_compile_stdout_stays_the_ir_document(self):
        """The asymmetry is deliberate — the artifact must not grow a key."""
        _, out, _ = run_cli_split(["compile", LOGIN])
        self.assertNotIn("diagnostics", json.loads(out))


class TestUnaffectedBehaviour(unittest.TestCase):
    def setUp(self):
        os.makedirs(TMP, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_compile_to_a_file_still_writes_the_artifact(self):
        target = os.path.join(TMP, "login.lir.json")
        rc, out, err = run_cli_split(["compile", LOGIN, "-o", target])
        self.assertEqual(rc, 0)
        with open(target, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["module"], "login")
        self.assertIn("wrote", out)
        # The diagnostics still appear, on the other stream.
        self.assertIn("unknown-verb", err)

    def test_spec_still_succeeds_and_stays_quiet(self):
        # `spec` is not one of the two commands that report diagnostics; the
        # widened `_compile` tuple must not have broken its unpacking.
        rc, out, _ = run_cli_split(["spec", LOGIN, "--run"])
        self.assertEqual(rc, 0)
        self.assertIn("spec:", out)

    def test_openapi_still_succeeds(self):
        rc, out, _ = run_cli_split(["openapi", LOGIN])
        self.assertEqual(rc, 0)
        self.assertIn("openapi", json.loads(out))

    def test_run_still_reports_when_there_is_no_workflow_to_run(self):
        # An unenforced declaration is a fact about the declaration, not about
        # a step: `run` must not drop the report on its way out.
        source = os.path.join(TMP, "no-workflow.lnpl")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(DECLARED_BUT_NO_WORKFLOW)
        rc, _, err = run_cli_split(["run", source])
        self.assertEqual(rc, 1)
        self.assertIn("no workflow to run", err)
        self.assertIn("security jwt", err)
        self.assertIn("policy rollback", err)
        self.assertIn("2 info, 0 warning(s), 0 error(s)", err)

    def test_compile_reports_the_same_module_that_run_could_not_execute(self):
        source = os.path.join(TMP, "no-workflow.lnpl")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(DECLARED_BUT_NO_WORKFLOW)
        rc, _, err = run_cli_split(["compile", source])
        self.assertEqual(rc, 0)
        self.assertIn("security jwt", err)
        self.assertIn("policy rollback", err)

    def test_a_missing_source_file_still_raises(self):
        # Pinning the pre-existing contract: the CLI does not swallow this into
        # a diagnostic.
        with self.assertRaises(FileNotFoundError):
            run_cli_split(["compile", os.path.join(TMP, "no-such.lnpl")])


if __name__ == "__main__":
    unittest.main()


# A policy gate: the guard decides whether the order is created. Free of any
# other diagnostic, so `--strict`'s rc is attributable to the skip alone.
GUARDED_ORDER = """
entity Order
    field
        id UUID
        stock Integer
workflow PlaceOrder
    validate order
    when stock > 0
    create order
"""


class TestGuardSkipIsReported(unittest.TestCase):
    """Issue #44 (t1 F-5, t2 F-6): a guard that rejected the work must not look
    like a run that did all of it.

    The three outcomes get three signals: clean (rc 0, nothing said), rejected
    (rc 0, but the first output line and a diagnostic both say so; rc 2 under
    `--strict`), failed (rc 1). An exit-code-only caller could previously not
    tell the first two apart at all.
    """

    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        self.src = os.path.join(TMP, "order.lnpl")
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write(GUARDED_ORDER)
        self.rejected = self._payload("rejected.json", stock=0)
        self.accepted = self._payload("accepted.json", stock=1)

    def _payload(self, name, **fields):
        path = os.path.join(TMP, name)
        body = dict(fields, id="3f2504e0-4f89-41d3-9a0c-0305e82c3301")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        return path

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    # ---- rejection: the signal exists --------------------------------------
    def test_the_first_output_line_says_a_step_was_skipped(self):
        rc, out, _err = run_cli_split(["run", self.src, "--payload", self.rejected])
        self.assertEqual(rc, 0, "a skip is not a failure (plan D1)")
        first = out.splitlines()[0]
        self.assertIn("-> completed", first)
        self.assertIn("(1 step(s) skipped by guard)", first)

    def test_the_detail_line_names_the_condition_and_the_step(self):
        _rc, out, _err = run_cli_split(["run", self.src, "--payload", self.rejected])
        self.assertIn("skipped by `when stock > 0`: create order", out)

    def test_a_diagnostic_reports_the_skip_on_stderr(self):
        _rc, _out, err = run_cli_split(["run", self.src, "--payload", self.rejected])
        self.assertIn("guard-skipped-steps", err)
        self.assertIn("create order", err)
        self.assertIn("stock > 0", err)

    def test_json_output_carries_the_manifest(self):
        _rc, out, _err = run_cli_split(
            ["run", self.src, "--payload", self.rejected, "--json"])
        result = json.loads(out)["result"]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["skipped"],
                         [{"guard": "wf.place.order.guard.1", "mode": "when",
                           "condition": "stock > 0",
                           "steps": ["create order"], "rounds": None}])

    # ---- the contrast: success is distinguishable --------------------------
    def test_the_accepted_run_says_nothing_about_skips(self):
        rc, out, err = run_cli_split(["run", self.src, "--payload", self.accepted])
        self.assertEqual(rc, 0)
        first = out.splitlines()[0]
        self.assertNotIn("skipped", first)
        self.assertNotIn("guard-skipped-steps", err)
        self.assertIn("create order", out, "the guarded step actually ran")

    def test_the_two_runs_differ_in_their_first_line(self):
        # The completion criterion in its most literal form: success and
        # rejection must be distinguishable from the top-level signal alone.
        import re

        def header(out):
            # Strip the volatile tail (duration, correlation id); what remains
            # is the part a caller could branch on.
            return re.sub(r"\(\d+ms, correlation_id=[^)]*\)", "",
                          out.splitlines()[0]).strip()

        _rc, rejected_out, _ = run_cli_split(
            ["run", self.src, "--payload", self.rejected])
        _rc, accepted_out, _ = run_cli_split(
            ["run", self.src, "--payload", self.accepted])
        self.assertEqual(header(accepted_out), "workflow PlaceOrder -> completed")
        self.assertEqual(header(rejected_out),
                         "workflow PlaceOrder -> completed  "
                         "(1 step(s) skipped by guard)")
        self.assertNotEqual(header(rejected_out), header(accepted_out),
                            "t1 F-5 / t2 F-6: before this change both runs "
                            "printed the identical header, so a caller could "
                            "not tell a rejected order from a fulfilled one.")

    # ---- the hard gate -----------------------------------------------------
    def test_strict_promotes_a_rejected_run_to_rc_2(self):
        rc, _out, _err = run_cli_split(
            ["run", self.src, "--payload", self.rejected, "--strict"])
        self.assertEqual(rc, 2, "issue #45's existing gate: a run that reported "
                                "a diagnostic is not a clean exit under --strict")

    def test_strict_leaves_an_accepted_run_at_rc_0(self):
        # The control: the gate must fire on the skip, not on the workflow.
        rc, _out, _err = run_cli_split(
            ["run", self.src, "--payload", self.accepted, "--strict"])
        self.assertEqual(rc, 0)

    # ---- boundary: a workflow with no guard is untouched -------------------
    def test_a_guardless_run_prints_the_unchanged_first_line(self):
        path = os.path.join(TMP, "plain.lnpl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(CLEAN_SOURCE)
        rc, out, err = run_cli_split(["run", path])
        self.assertEqual(rc, 0)
        first = out.splitlines()[0]
        self.assertNotIn("skipped", first)
        self.assertEqual(first.count("("), 1,
                         "the guardless first line must keep its original shape")
        self.assertEqual(err, "")
