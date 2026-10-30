"""measure_tokens.py tests (issues #142, #251): determinism + boundary/error cases.

Loud-skip convention matches impl/tests/test_backend.py's NEEDS_TOOLS: this
benchmark's tiktoken is installed only in benchmarks/token/.venv, never in
the project's own dependencies (see ../PROTOCOL.md).
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import tiktoken  # noqa: F401

    import measure_tokens

    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

NEEDS_TIKTOKEN = unittest.skipUnless(
    HAS_TIKTOKEN,
    "tiktoken not installed — run from benchmarks/token/.venv "
    "(python3.13 -m venv benchmarks/token/.venv && "
    "benchmarks/token/.venv/bin/pip install tiktoken==0.14.0 fastapi httpx pytest)",
)

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "measure_tokens.py"


@NEEDS_TIKTOKEN
class MeasureTokensTest(unittest.TestCase):
    def test_two_runs_identical_stdout(self):
        # normal case: the CLI entry point is deterministic across runs
        run1 = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)], capture_output=True, text=True, check=True
        )
        run2 = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)], capture_output=True, text=True, check=True
        )
        self.assertEqual(run1.stdout, run2.stdout)
        self.assertNotEqual(run1.stdout, "")

    def test_output_has_expected_top_level_shape(self):
        report = measure_tokens.build_report()
        self.assertIn("source_tokens", report)
        self.assertIn("edit_tokens", report)
        self.assertIn("tiktoken_version", report)
        self.assertEqual(set(report["tokenizers"]), {"o200k_base", "cl100k_base"})
        # six scenarios, each measured on both sides
        self.assertEqual(len(measure_tokens.SCENARIOS), 6)
        self.assertEqual(set(report["source_tokens"]), set(measure_tokens.SCENARIOS))
        for scenario, sides in report["source_tokens"].items():
            self.assertEqual(set(sides), {"lnpl", "fastapi"}, scenario)
        # five edit kinds, every one reports both sides
        self.assertEqual(len(measure_tokens.EDIT_KINDS), 5)
        self.assertEqual(set(report["edit_tokens"]), set(measure_tokens.EDIT_KINDS))
        for task_name, sides in report["edit_tokens"].items():
            self.assertEqual(set(sides), {"lnpl", "fastapi"}, task_name)
        # the JSON encoder must not choke on the report (sort_keys, no NaN/inf)
        json.dumps(report, sort_keys=True)

    def test_edit_pair_with_no_changes_yields_zero_tokens(self):
        # boundary: identical before/after -> 0 added, 0 removed
        added, removed = measure_tokens.diff_lines("same\ntext\n", "same\ntext\n")
        self.assertEqual(added, [])
        self.assertEqual(removed, [])

    def test_measure_file_missing_path_raises(self):
        # error case: a nonexistent source path fails loudly, not silently
        encodings = {"o200k_base": tiktoken.get_encoding("o200k_base")}
        missing = measure_tokens.REPO_ROOT / "benchmarks" / "token" / "does_not_exist.lnpl"
        with self.assertRaises(FileNotFoundError):
            measure_tokens.measure_file(missing, encodings)

    def test_measure_text_empty_source_is_zero(self):
        # boundary: an empty source has no characters and no tokens
        encodings = {name: tiktoken.get_encoding(name) for name in measure_tokens.TOKENIZERS}
        self.assertEqual(
            measure_tokens.measure_text("", encodings),
            {"chars": 0, "chars_no_whitespace": 0, "tokens_o200k_base": 0, "tokens_cl100k_base": 0},
        )

    def test_every_scenario_path_exists(self):
        # normal case: every measured file is present, so a run never measures a stale path
        for scenario, sides in measure_tokens.SCENARIOS.items():
            for side, path in sides.items():
                self.assertTrue(path.is_file(), f"{scenario}/{side}: {path}")
        for kind, sides in measure_tokens.EDIT_TASKS.items():
            for side, (before, after) in sides.items():
                self.assertTrue(before.is_file(), f"{kind}/{side}: {before}")
                self.assertTrue(after.is_file(), f"{kind}/{side}: {after}")

    def test_extract_report_block_without_marker_raises(self):
        # error case: a REPORT without the generated block is rejected loudly
        with self.assertRaises(ValueError):
            measure_tokens.extract_report_block("no block here\n")

    def test_extract_report_block_returns_fenced_text(self):
        # normal case: the fenced JSON after the BEGIN marker comes back verbatim
        text = "x\n<!-- BEGIN measure_tokens.py output — y -->\n\n```json\n{\n  \"a\": 1\n}\n```\n"
        self.assertEqual(measure_tokens.extract_report_block(text), "{\n  \"a\": 1\n}\n")


if __name__ == "__main__":
    unittest.main()
