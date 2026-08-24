"""Issue #78: `lnpl serve --log-format` / `--trace-exporter` are closed
tables at the CLI layer too — an unknown value stops the server before it
binds a socket (mirrors ServeCommandRejectionTest's own `--backend` case,
test_serve_backend.py)."""

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lnpl.cli import main

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORTEN = os.path.join(REPO, "examples", "shorten.lnpl")


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


class ServeObservabilityRejectionTest(unittest.TestCase):
    def test_error_an_unknown_log_format_stops_the_server_starting(self):
        rc, out, err = run_cli(["serve", SHORTEN, "--port", "0",
                                "--log-format", "yaml"])

        self.assertEqual(2, rc)
        self.assertIn("yaml", err)
        self.assertIn("text", err)
        self.assertIn("json", err)
        self.assertNotIn("serving", out)

    def test_error_an_unknown_trace_exporter_stops_the_server_starting(self):
        rc, out, err = run_cli(["serve", SHORTEN, "--port", "0",
                                "--trace-exporter", "otlp"])

        self.assertEqual(2, rc)
        self.assertIn("otlp", err)
        self.assertIn("stderr-json", err)
        self.assertNotIn("serving", out)

    def test_boundary_both_flags_omitted_is_not_itself_a_rejection(self):
        # Reaching a DIFFERENT, unrelated rejection (bad backend) proves
        # argparse accepted the omission of --log-format/--trace-exporter and
        # cmd_serve got past resolving them before failing elsewhere.
        rc, out, err = run_cli(["serve", SHORTEN, "--port", "0",
                                "--backend", "redis://x"])

        self.assertEqual(2, rc)
        self.assertIn("redis://x", err)
        self.assertNotIn("serving", out)


if __name__ == "__main__":
    unittest.main()
