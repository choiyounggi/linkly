"""`--log-level info|warn|error` (issue #165): controls which trace levels
`lnpl run`/`lnpl trigger`'s human output shows. Default `warn`, byte-compatible
with behaviour before this flag existed — `_print_human` filtered
`entry["level"] in ("WARN", "ERROR")` before, which is exactly what rank
`>= _LEVEL_RANK["warn"]` still selects.
"""

import contextlib
import io
import os
import unittest

from lnpl import cli

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGIN = os.path.join(REPO, "examples", "login.lnpl")
WORKDIR = os.path.join(REPO, ".claude", "tmp", "log-level")

NORMAL_SRC = """service Rollup

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    read report
"""


def run_cli_split(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _write(name, text):
    os.makedirs(WORKDIR, exist_ok=True)
    path = os.path.join(WORKDIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _trace_lines(out):
    return [line for line in out.splitlines()
            if line.strip().startswith(("INFO", "WARN", "ERROR"))]


class DefaultLogLevelIsByteCompatibleTest(unittest.TestCase):
    """Normal/regression: a bare `lnpl run` (no `--log-level`) is
    byte-identical to explicitly passing `--log-level warn` — locking in that
    the new flag's default changes nothing about prior behaviour."""

    def test_bare_run_matches_explicit_warn(self):
        _, out_bare, err_bare = run_cli_split(["run", LOGIN, "--no-row"])
        _, out_warn, err_warn = run_cli_split(
            ["run", LOGIN, "--no-row", "--log-level", "warn"])
        self.assertEqual(out_bare, out_warn)
        self.assertEqual(err_bare, err_warn)


class InfoLevelShowsMoreTest(unittest.TestCase):
    """Normal: `--log-level info` shows at least one trace line the default
    (`warn`) omits — the unconditional `INFO workflow start` entry."""

    def test_info_adds_the_workflow_start_line(self):
        _, out_default, _ = run_cli_split(["run", LOGIN])
        _, out_info, _ = run_cli_split(["run", LOGIN, "--log-level", "info"])
        self.assertNotIn("workflow start", out_default)
        self.assertIn("workflow start", out_info)
        self.assertGreater(len(_trace_lines(out_info)), len(_trace_lines(out_default)))


class ErrorLevelShowsFewerOrEqualTest(unittest.TestCase):
    """Boundary: `--log-level error` shows no more trace lines than the
    default — `--no-row` forces retries (WARN) and a final failure (ERROR),
    so `error` strictly drops the WARN lines here."""

    def test_error_level_drops_warn_lines_kept_by_default(self):
        _, out_default, _ = run_cli_split(["run", LOGIN, "--no-row"])
        _, out_error, _ = run_cli_split(["run", LOGIN, "--no-row", "--log-level", "error"])
        default_lines = _trace_lines(out_default)
        error_lines = _trace_lines(out_error)
        self.assertLessEqual(len(error_lines), len(default_lines))
        self.assertTrue(all(line.strip().startswith("ERROR") for line in error_lines))
        self.assertTrue(any(line.strip().startswith("WARN") for line in default_lines))


class UnknownLogLevelIsRejectedTest(unittest.TestCase):
    """Error: `--log-level bogus` is an argparse usage error (nonzero exit),
    same class as any other invalid `choices=` flag."""

    def test_bogus_log_level_exits_nonzero(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["run", LOGIN, "--log-level", "bogus"])
        self.assertNotEqual(caught.exception.code, 0)
        self.assertIn("--log-level", err.getvalue())


class TriggerAlsoWidensTest(unittest.TestCase):
    """Contract (D6): `--log-level` is not `run`-only — `trigger` gets the
    same flag and the same widening."""

    def test_trigger_log_level_info_also_shows_workflow_start(self):
        src = _write("rollup.lnpl", NORMAL_SRC)
        _, out_default, _ = run_cli_split(
            ["trigger", src, "--schedule", "event.daily.rollup"])
        _, out_info, _ = run_cli_split(
            ["trigger", src, "--schedule", "event.daily.rollup", "--log-level", "info"])
        self.assertNotIn("workflow start", out_default)
        self.assertIn("workflow start", out_info)


if __name__ == "__main__":
    unittest.main()
