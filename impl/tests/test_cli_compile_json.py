"""`lnpl compile --json` — a combined IR+diagnostics document on stdout (#133).

RFC-0021 fixed the diagnostic record at five keys (code/severity/where/subject/
message); RFC-0024 added a sixth, `line`. Issue #133 asks for those six keys to
reach automation without a human-oriented parser: `--json` prints exactly one
JSON document to stdout — the existing IR document (`lir_version`/`module`/
`nodes`) plus a `diagnostics` array of six-key records — and never the
`format_lines` prose `_emit_diagnostics` prints for every other `compile`
invocation. `--json` changes the channel only: exit code semantics (including
`--strict`'s gate) are unchanged (D4).
"""

import contextlib
import io
import json
import os
import unittest

from lnpl import cli

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGIN = os.path.join(REPO, "examples", "login.lnpl")
DIAG_KEYS = {"code", "severity", "where", "subject", "message", "line"}

# Verified by hand against a real `lnpl compile` run before writing any
# assertion here (dev-loop wiki: platforms/processes/parsing-cli-structured-
# output.md — confirm field paths against real output, never guess them):
# `examples/login.lnpl` emits exactly 2 info + 3 warning diagnostics, all
# carrying a real `line` number, over 19 IR nodes.
CLEAN_SRC = """
capability postgres
entity Payment
    field
        id UUID
        cardNumber Password
        amountCents Integer
service PaymentService
    policy
        retry 0
workflow Approval
    validate payment
    find payment
    when payment.amountCents <= 1000000
    update payment
"""

# A nameless `entity` is a ParseError (same fixture as
# test_serve.py::test_compile_error_is_rc_2) — a hard failure `_compile` raises
# before any IR document exists, distinct from a diagnostic on a compiled module.
BROKEN_SRC = "entity\n"


def _main(argv):
    """Drive `cli.main(argv)` with stdout/stderr captured separately."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class TestCliCompileJson(unittest.TestCase):
    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "cli-compile-json")
        os.makedirs(self.workdir, exist_ok=True)

    def _write(self, name, text):
        path = os.path.join(self.workdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    # ---- normal -------------------------------------------------------

    def test_clean_module_reports_an_empty_diagnostics_array(self):
        src = self._write("clean.lnpl", CLEAN_SRC)
        rc, out, err = _main(["compile", src, "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        doc = json.loads(out)
        self.assertEqual(set(doc.keys()),
                         {"lir_version", "module", "nodes", "diagnostics"})
        self.assertEqual(doc["diagnostics"], [])
        self.assertGreater(len(doc["nodes"]), 0)
        self.assertEqual(doc["module"], "clean")

    def test_json_output_has_no_human_readable_lines_mixed_in(self):
        # `format_lines` prose (e.g. "warning: unknown-verb") must never reach
        # stdout under --json — a single `json.loads` on the whole stream is
        # the proof; a stray human line would break the parse.
        rc, out, err = _main(["compile", LOGIN, "--json"])
        self.assertEqual(rc, 0)
        json.loads(out)  # raises ValueError if anything but one JSON doc is there
        self.assertNotIn("warning:", out)
        self.assertNotIn("info:", out)

    # ---- error (diagnostics) -------------------------------------------

    def test_real_example_reports_all_six_keys_with_mixed_severity(self):
        rc, out, err = _main(["compile", LOGIN, "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        diagnostics = doc["diagnostics"]
        self.assertGreaterEqual(len(diagnostics), 2)
        severities = {d["severity"] for d in diagnostics}
        self.assertIn("info", severities)
        self.assertIn("warning", severities)
        for d in diagnostics:
            self.assertEqual(set(d.keys()), DIAG_KEYS)
            self.assertIsInstance(d["line"], int)

    # ---- error (hard compile failure) -----------------------------------

    def test_compile_failure_emits_a_null_document_and_keeps_rc(self):
        src = self._write("broken.lnpl", BROKEN_SRC)
        rc_plain, out_plain, err_plain = _main(["compile", src])
        rc_json, out_json, err_json = _main(["compile", src, "--json"])
        self.assertEqual(rc_plain, rc_json)
        self.assertEqual(out_plain, "")  # unchanged: no --json, no stdout at all
        self.assertIn("compile error", err_plain)
        self.assertIn("compile error", err_json)
        doc = json.loads(out_json)
        self.assertEqual(doc, {"lir_version": None, "module": None,
                                "nodes": None, "diagnostics": []})

    # ---- boundary -------------------------------------------------------

    def test_empty_source_gives_an_empty_nodes_array_not_null(self):
        src = self._write("empty.lnpl", "")
        rc, out, err = _main(["compile", src, "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["nodes"], [])
        self.assertIsNotNone(doc["module"])
        self.assertEqual(doc["diagnostics"], [])

    def test_json_flag_does_not_change_exit_code(self):
        for extra in ([], ["--strict"], ["--strict=warning"]):
            with self.subTest(extra=extra):
                rc_plain, _, _ = _main(["compile", LOGIN] + extra)
                rc_json, _, _ = _main(["compile", LOGIN, "--json"] + extra)
                self.assertEqual(rc_plain, rc_json)

    def test_output_flag_still_writes_the_ir_file_stdout_stays_json_only(self):
        src = self._write("clean2.lnpl", CLEAN_SRC)
        out_path = os.path.join(self.workdir, "out.json")
        rc, out, err = _main(["compile", src, "--json", "-o", out_path])
        self.assertEqual(rc, 0)
        self.assertNotIn("wrote", out)
        doc = json.loads(out)
        self.assertIn("diagnostics", doc)
        with open(out_path, encoding="utf-8") as fh:
            file_doc = json.load(fh)
        self.assertNotIn("diagnostics", file_doc)


if __name__ == "__main__":
    unittest.main()
