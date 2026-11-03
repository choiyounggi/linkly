"""`scripts/diff_coverage.py`의 diff 파싱·집계·출력·입력 오류 단언 (issue #247).

입력은 전부 합성값이다(실측 coverage.json을 고정값으로 쓰지 않는다).
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(REPO, "scripts", "diff_coverage.py")
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")

_spec = importlib.util.spec_from_file_location("diff_coverage", SCRIPT_PATH)
diff_coverage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diff_coverage)

FAKE_PATH = "impl/lnpl/fake_mod.py"
FAKE_TOTALS = {"covered_lines": 3, "num_statements": 4,
               "covered_branches": 1, "num_branches": 2}
FAKE_FILES = {FAKE_PATH: {"executed_lines": [1, 2, 11], "missing_lines": [12]}}
FAKE_DIFF = ("diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n"
             "@@ -10,0 +11,3 @@\n+x = 1\n+y = 2\n+# note\n" % ((FAKE_PATH,) * 4))


class ParseAddedLinesTest(unittest.TestCase):
    def test_hunks_give_added_line_numbers(self):
        text = FAKE_DIFF + "@@ -30 +32 @@\n+z = 3\n"
        self.assertEqual(diff_coverage.parse_added_lines(text), {FAKE_PATH: [11, 12, 13, 32]})

    def test_deletion_only_hunk_adds_nothing(self):
        text = "+++ b/%s\n@@ -5,2 +4,0 @@\n" % FAKE_PATH
        self.assertEqual(diff_coverage.parse_added_lines(text), {})

    def test_dev_null_and_non_python_targets_are_ignored(self):
        text = "+++ /dev/null\n@@ -1,3 +0,0 @@\n+++ b/README.md\n@@ -1 +1 @@\n"
        self.assertEqual(diff_coverage.parse_added_lines(text), {})

    def test_quoted_path_is_unquoted(self):
        text = '+++ "b/impl/lnpl/a b.py"\n@@ -0,0 +1 @@\n'
        self.assertEqual(diff_coverage.parse_added_lines(text), {"impl/lnpl/a b.py": [1]})

    def test_empty_diff_gives_empty_map(self):
        """경계값: 빈 diff."""
        self.assertEqual(diff_coverage.parse_added_lines(""), {})


class DiffRowsTest(unittest.TestCase):
    def test_comment_lines_are_not_executable(self):
        rows = diff_coverage.diff_rows({FAKE_PATH: [11, 12, 13]}, FAKE_FILES)
        self.assertEqual(rows, [{"path": FAKE_PATH, "status": "measured", "changed": 2,
                                 "covered": 1, "missed": [12]}])

    def test_file_absent_from_coverage_is_unmeasured(self):
        rows = diff_coverage.diff_rows({"impl/lnpl/new_mod.py": [1]}, FAKE_FILES)
        self.assertEqual(rows[0]["status"], "unmeasured")

    def test_file_entry_without_line_lists_is_an_input_error(self):
        with self.assertRaises(diff_coverage.InputError):
            diff_coverage.diff_rows({FAKE_PATH: [1]}, {FAKE_PATH: {}})


class RenderTest(unittest.TestCase):
    def test_totals_lines(self):
        self.assertEqual(diff_coverage.totals_lines(FAKE_TOTALS), [
            "- Line coverage: 75.00% (3/4 statements)",
            "- Branch coverage: 50.00% (1/2 branches)",
        ])

    def test_zero_statements_and_missing_branch_keys_read_na(self):
        self.assertEqual(diff_coverage.totals_lines({"covered_lines": 0, "num_statements": 0}), [
            "- Line coverage: n/a (0 statements measured)",
            "- Branch coverage: n/a (not measured; run coverage with --branch)",
        ])

    def test_ranges_compress_consecutive_lines(self):
        self.assertEqual(diff_coverage.ranges([12, 13, 20]), "12-13, 20")
        self.assertEqual(diff_coverage.ranges([]), "-")


def _tmpdir(test):
    os.makedirs(CLAUDE_TMP, exist_ok=True)
    path = tempfile.mkdtemp(prefix="diff-coverage-", dir=CLAUDE_TMP)
    test.addCleanup(shutil.rmtree, path, True)
    return path


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = diff_coverage.main(argv)
    return rc, out.getvalue(), err.getvalue()


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmpdir(self)
        self.cov = _write(os.path.join(self.tmp, "coverage.json"),
                          json.dumps({"totals": FAKE_TOTALS, "files": FAKE_FILES}))

    def test_report_with_diff(self):
        diff = _write(os.path.join(self.tmp, "pr.diff"), FAKE_DIFF)
        rc, out, _ = _main(["--coverage-json", self.cov, "--diff", diff])
        self.assertEqual(rc, 0)
        self.assertIn("| %s | 2 | 1 | 12 |" % FAKE_PATH, out)
        self.assertIn("Diff coverage: 50.00% (1/2 changed executable lines)", out)

    def test_report_without_diff_has_no_diff_section(self):
        rc, out, _ = _main(["--coverage-json", self.cov])
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("## Coverage (advisory)\n"))
        self.assertNotIn("### Diff coverage", out)

    def test_empty_diff_says_no_measured_files_changed(self):
        """경계값: 아무 .py 줄도 더하지 않은 diff."""
        diff = _write(os.path.join(self.tmp, "pr.diff"), "")
        rc, out, _ = _main(["--coverage-json", self.cov, "--diff", diff])
        self.assertEqual(rc, 0)
        self.assertIn("No measured files changed: the diff adds 0 lines to .py files.", out)

    def test_missing_coverage_json_exits_2(self):
        rc, out, err = _main(["--coverage-json", os.path.join(self.tmp, "absent.json")])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("diff_coverage: error: cannot read coverage json"))

    def test_invalid_json_exits_2(self):
        _write(self.cov, "{not json")
        rc, _, err = _main(["--coverage-json", self.cov])
        self.assertEqual(rc, 2)
        self.assertIn("is not valid JSON", err)

    def test_missing_totals_key_exits_2(self):
        _write(self.cov, json.dumps({"totals": {"covered_lines": 1}, "files": {}}))
        rc, _, err = _main(["--coverage-json", self.cov])
        self.assertEqual(rc, 2)
        self.assertIn("lacks totals.num_statements", err)

    def test_missing_diff_file_exits_2(self):
        rc, _, err = _main(["--coverage-json", self.cov, "--diff", os.path.join(self.tmp, "absent.diff")])
        self.assertEqual(rc, 2)
        self.assertIn("cannot read diff", err)


if __name__ == "__main__":
    unittest.main()
