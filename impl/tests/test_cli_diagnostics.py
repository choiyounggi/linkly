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
        self.assertEqual(err.strip().splitlines()[-1], "6 warning(s), 0 error(s)")

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
        self.assertEqual(err.strip().splitlines()[-1], "1 warning(s), 0 error(s)")

    def test_run_reports_compile_time_and_run_time_findings_together(self):
        path = self._write("both.lnpl", BOTH_PRODUCERS)
        rc, _, err = run_cli_split(["run", path])
        self.assertEqual(rc, 0)
        self.assertIn("security jwt", err)                 # compile time
        self.assertIn("generate", err)                     # compile time
        self.assertIn("authorization-not-verified", err)   # run time
        # One report, one summary — not two reports stapled together.
        self.assertEqual(err.count("warning(s)"), 1)
        self.assertEqual(err.strip().splitlines()[-1], "3 warning(s), 0 error(s)")

    def test_compile_of_the_same_module_omits_only_the_runtime_finding(self):
        path = self._write("both.lnpl", BOTH_PRODUCERS)
        _, _, err = run_cli_split(["compile", path])
        self.assertIn("security jwt", err)
        self.assertIn("generate", err)
        self.assertNotIn("authorization-not-verified", err)
        self.assertEqual(err.strip().splitlines()[-1], "2 warning(s), 0 error(s)")

    def test_the_runtime_diagnostic_stays_off_stdout_and_off_the_trace(self):
        path = self._write("rt.lnpl", RUNTIME_ONLY)
        _, out, err = run_cli_split(["run", path, "--json"])
        self.assertIn("authorization-not-verified", err)
        self.assertNotIn("authorization-not-verified", out)
        payload = json.loads(out)
        self.assertNotIn("authorization-not-verified", json.dumps(payload["trace"]))
        # The span attribute the interpreter always wrote is still there.
        self.assertIn("admin", json.dumps(payload["trace"]))


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
        self.assertIn("2 warning(s), 0 error(s)", err)

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
