"""REPORT.md agreement check (issue #251): every published number comes from measure_tokens.py.

Loud skip as in test_measure_tokens.py: tiktoken lives only in
benchmarks/token/.venv.

Cases:
  test_report_block_matches_build_report  <- the BEGIN/END block equals one fresh run, byte for byte
  test_report_tables_match_build_report   <- every table row is generated from the same run; 12 / 10 rows exactly
"""

import os
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

REPORT_PATH = Path(__file__).resolve().parent.parent / "REPORT.md"
SIDES = ("lnpl", "fastapi")


def source_rows(report):
    rows = []
    for sid in measure_tokens.SCENARIOS:
        for side in SIDES:
            e = report["source_tokens"][sid][side]
            rows.append(
                f"| `{sid}` | `{e['path']}` | {e['chars']} | {e['chars_no_whitespace']} "
                f"| **{e['tokens_o200k_base']}** | **{e['tokens_cl100k_base']}** |"
            )
    return rows


def edit_rows(report):
    rows = []
    for kind in measure_tokens.EDIT_KINDS:
        for side in SIDES:
            e = report["edit_tokens"][kind][side]
            rows.append(
                f"| `{kind}` | `{side}` | {e['added_lines']} | {e['removed_lines']} "
                f"| **{e['edit_tokens_o200k_base']}** | **{e['edit_tokens_cl100k_base']}** |"
            )
    return rows


def section(text, title):
    lines = text.splitlines()
    start = lines.index(title) + 1
    end = next((n for n in range(start, len(lines)) if lines[n].startswith("## ")), len(lines))
    return lines[start:end]


@NEEDS_TIKTOKEN
class ReportBlockTest(unittest.TestCase):
    def setUp(self):
        self.text = REPORT_PATH.read_text(encoding="utf-8")
        self.report = measure_tokens.build_report()

    def test_report_block_matches_build_report(self):
        self.assertEqual(
            measure_tokens.extract_report_block(self.text),
            measure_tokens.render_json(self.report),
        )

    def test_report_tables_match_build_report(self):
        for title, rows, count in (
            ("## 소스 토큰 표", source_rows(self.report), 12),
            ("## 편집 토큰 표", edit_rows(self.report), 10),
        ):
            with self.subTest(section=title):
                body = section(self.text, title)
                for row in rows:
                    self.assertIn(row, body)
                self.assertEqual(sum(1 for line in body if line.startswith("| `")), count)


if __name__ == "__main__":
    unittest.main()
