"""`scripts/ci_test_suite.py`가 `ci.yml` `gate` 잡과 같은 모듈 집합을 고르는가 (issue #247).

coverage 잡은 gate의 heredoc을 감쌀 수 없어(`coverage run`은 스크립트 경로를 받는다)
같은 선택 규칙을 스크립트로 되풀이한다. gate 쪽 값은 ci.yml 텍스트에서 따로 읽는다.
`main()`을 실제 impl/tests에 부르지 않는다 — 전체 스위트가 돈다.
"""
import ast
import contextlib
import importlib.util
import io
import os
import re
import shutil
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(REPO, "scripts", "ci_test_suite.py")
CI_YML_PATH = os.path.join(REPO, ".github", "workflows", "ci.yml")
TESTS_DIR = os.path.join(REPO, "impl", "tests")
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")

_spec = importlib.util.spec_from_file_location("ci_test_suite", SCRIPT_PATH)
ci_test_suite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_test_suite)


def _gate_job():
    with open(CI_YML_PATH, encoding="utf-8") as fh:
        text = fh.read()
    start = text.index("\n  gate:\n")
    return text[start:text.index("\n  modeb-linux:\n", start)]


class GateParityTest(unittest.TestCase):
    """정상 케이스: 스크립트의 규칙이 gate heredoc의 규칙과 같다."""

    def test_excluded_set_matches_the_gate_heredoc(self):
        match = re.search(r"^\s*EXCLUDED = (\{.*\})\s*$", _gate_job(), re.M)
        self.assertIsNotNone(match, "gate heredoc has no EXCLUDED line")
        self.assertEqual(ast.literal_eval(match.group(1)), ci_test_suite.EXCLUDED)

    def test_gate_heredoc_keeps_the_same_file_rule(self):
        self.assertIn('fname.startswith("test_") and fname.endswith(".py")', _gate_job())

    def test_real_selection_drops_only_the_excluded_module(self):
        files = os.listdir(TESTS_DIR)
        expected = sorted(f[:-3] for f in files if f.startswith("test_") and f.endswith(".py"))
        expected.remove("test_repo_state")
        self.assertEqual(ci_test_suite.selected_modules(files), expected)


class SelectionTest(unittest.TestCase):
    def test_fixture_listing_keeps_test_modules_only(self):
        listing = ["test_b.py", "test_a.py", "test_repo_state.py", "helper.py",
                   "test_c.txt", "mutation_check.py"]
        self.assertEqual(ci_test_suite.selected_modules(listing), ["test_a", "test_b"])

    def test_empty_listing_selects_nothing(self):
        """경계값: 빈 목록."""
        self.assertEqual(ci_test_suite.selected_modules([]), [])


class EmptySuiteTest(unittest.TestCase):
    """에러 케이스: 고를 모듈이 0개면 통과가 아니라 exit 1이다."""

    def test_main_on_a_directory_without_tests_returns_1(self):
        os.makedirs(CLAUDE_TMP, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix="ci-test-suite-", dir=CLAUDE_TMP)
        self.addCleanup(shutil.rmtree, tmp, True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ci_test_suite.main(tests_dir=tmp)
        self.assertEqual(rc, 1)
        self.assertIn("ci_test_suite: 0 test modules under", out.getvalue())


if __name__ == "__main__":
    unittest.main()
