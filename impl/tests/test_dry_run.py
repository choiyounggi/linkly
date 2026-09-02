"""`lnpl run --dry-run` (issue #165): a zero-effect static preview of a
workflow's execution plan — step order, guard evaluation points, declared
policy application points — derived only from the compiled IR. No backend,
network, cache, or clock is ever opened; no `Interpreter` is constructed.
"""

import contextlib
import io
import json
import os
import unittest
from unittest import mock

from lnpl import cli

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGIN = os.path.join(REPO, "examples", "login.lnpl")
GUARDED = os.path.join(REPO, "examples", "guarded.lnpl")


def run_cli_split(argv):
    """Drive `cli.main(argv)`, keeping stdout and stderr apart (mirrors
    test_cli_diagnostics.py's helper)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class DryRunJsonShapeTest(unittest.TestCase):
    """Normal: `--dry-run --json` prints exactly the dry-run shape — no
    `result`/`trace`, which would mislead a caller into treating this as an
    executed run (D5)."""

    def test_shape_has_workflow_plan_declared_policies_and_no_result_or_trace(self):
        rc, out, err = run_cli_split(["run", LOGIN, "--dry-run", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(set(doc.keys()), {"workflow", "plan", "declared_policies"})
        self.assertEqual(doc["workflow"], "wf.login")
        self.assertGreater(len(doc["plan"]), 0)


class DryRunGuardWalkTest(unittest.TestCase):
    """Normal: the walked plan's `kind` values match the guarded fixture's
    real structure — two top-level steps, then two guards each wrapping one
    step."""

    def test_guard_entries_carry_mode_condition_and_wrapped_step(self):
        rc, out, err = run_cli_split(["run", GUARDED, "--dry-run", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        kinds = [entry["kind"] for entry in doc["plan"]]
        self.assertEqual(kinds, ["step", "step", "guard", "guard"])

        guards = [entry for entry in doc["plan"] if entry["kind"] == "guard"]
        self.assertEqual(len(guards), 2)
        for guard in guards:
            self.assertEqual(guard["mode"], "when")
            self.assertIsNotNone(guard["condition"])
            self.assertIsNone(guard["count"])
            self.assertEqual(len(guard["children"]), 1)
            self.assertEqual(guard["children"][0]["kind"], "step")


class DryRunDiagnosticsAreCompileTimeOnlyTest(unittest.TestCase):
    """Contract: dry-run's diagnostics come from compilation only — no
    runtime diagnostics can exist because no `Interpreter` ever runs."""

    def test_dry_run_diagnostics_match_a_plain_compile(self):
        _, _, compile_err = run_cli_split(["compile", LOGIN])
        _, _, dry_run_err = run_cli_split(["run", LOGIN, "--dry-run"])
        # Both reports are the same set of compile-time findings, modulo the
        # differing command-name framing `_emit_diagnostics` never adds
        # (neither command names itself in the diagnostic lines).
        self.assertIn("unknown-verb", dry_run_err)
        self.assertEqual(
            compile_err.count("warning:") + compile_err.count("info:"),
            dry_run_err.count("warning:") + dry_run_err.count("info:"))


class DryRunOpensNoBackendTest(unittest.TestCase):
    """Boundary/regression: `--dry-run` never opens a backend — the
    zero-effect guarantee (D4), proven by making the backend opener explode
    if it is ever called."""

    def test_dry_run_never_calls_open_backend(self):
        with mock.patch.object(cli, "_open_backend",
                                side_effect=AssertionError(
                                    "_open_backend must not be called under --dry-run")):
            rc, out, err = run_cli_split(["run", LOGIN, "--dry-run", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["workflow"], "wf.login")


class DryRunUnknownWorkflowTest(unittest.TestCase):
    """Error: an unknown `--workflow` id under `--dry-run` takes the same
    `_select_workflow` rejection path a normal run already uses — dry-run
    does not get its own, different error handling."""

    def test_unknown_workflow_id_is_rejected_the_same_way_as_a_normal_run(self):
        rc_dry, out_dry, err_dry = run_cli_split(
            ["run", LOGIN, "--dry-run", "--workflow", "no.such.workflow"])
        rc_normal, out_normal, err_normal = run_cli_split(
            ["run", LOGIN, "--workflow", "no.such.workflow"])
        self.assertEqual(rc_dry, rc_normal)
        self.assertEqual(err_dry, err_normal)
        self.assertEqual(out_dry, out_normal)


if __name__ == "__main__":
    unittest.main()
