"""measure_tokens.py tests (issue #142): determinism + boundary/error cases.

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
    "benchmarks/token/.venv/bin/pip install tiktoken fastapi httpx pytest)",
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
        # every edit task reports both sides
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


if __name__ == "__main__":
    unittest.main()
