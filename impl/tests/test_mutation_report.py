"""`scripts/mutation_report.py`의 SURVIVED/STALE/HANG 분류 + fail-closed 단언
(issue #166)."""
import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(REPO, "scripts", "mutation_report.py")
MUTATION_CHECK_PATH = os.path.join(REPO, "impl", "tests", "mutation_check.py")

_spec = importlib.util.spec_from_file_location("mutation_report", SCRIPT_PATH)
mutation_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutation_report)

SURVIVED_STDOUT = (
    "  CAUGHT   R1: something                                          RED\n"
    "\nMUTATION CHECK: FAIL — 2 of 5 mutation(s) not cleanly caught:\n"
    "  - R2: rule one [SURVIVED — no test asserts this rule]\n"
    "  - R3: rule two [SURVIVED — no test asserts this rule]\n"
)
STALE_STDOUT = (
    "\nMUTATION CHECK: FAIL — 1 of 5 mutation(s) not cleanly caught:\n"
    "  - R4: rule four [stale anchor]\n"
)
HANG_STDOUT = (
    "\nMUTATION CHECK: FAIL — 1 of 5 mutation(s) not cleanly caught:\n"
    "  - R5: rule five [hangs instead of failing]\n"
)
EMPTY_STDOUT = "MUTATION CHECK: PASS — no-op control survived, and all 5 mutations caught by a failing test\n"


class ParseSurvivedTest(unittest.TestCase):
    """정상 케이스: SURVIVED 라인 2개는 survived 버킷에 담기고 harness_ok는 True."""

    def test_two_survived_lines(self):
        result = mutation_report.parse(SURVIVED_STDOUT)
        self.assertEqual(len(result["survived"]), 2)
        self.assertTrue(result["harness_ok"])


class ParseStaleTest(unittest.TestCase):
    """에러/경계값 케이스: STALE 라인 1개는 harness_ok를 False로 만든다."""

    def test_one_stale_line(self):
        result = mutation_report.parse(STALE_STDOUT)
        self.assertEqual(len(result["stale"]), 1)
        self.assertFalse(result["harness_ok"])


class ParseHangTest(unittest.TestCase):
    """경계값 케이스: HANG 라인 1개도 harness_ok를 False로 만든다."""

    def test_one_hang_line(self):
        result = mutation_report.parse(HANG_STDOUT)
        self.assertEqual(len(result["hang"]), 1)
        self.assertFalse(result["harness_ok"])


class ParseEmptyTest(unittest.TestCase):
    """정상 케이스: 분류 대상 라인이 없으면 모든 버킷이 비고 harness_ok는 True."""

    def test_no_classified_lines(self):
        result = mutation_report.parse(EMPTY_STDOUT)
        self.assertEqual(result["survived"], [])
        self.assertEqual(result["stale"], [])
        self.assertEqual(result["hang"], [])
        self.assertTrue(result["harness_ok"])


class FormatIssueBodyTest(unittest.TestCase):
    """정상 케이스: 빈 survived는 정형 문장을, 1건 이상은 라벨을 포함한다."""

    def test_empty_survived_sentence(self):
        body = mutation_report.format_issue_body({"survived": []})
        self.assertIn("No mutations survived", body)

    def test_one_survived_label_present(self):
        body = mutation_report.format_issue_body({"survived": ["R2: rule one"]})
        self.assertIn("R2: rule one", body)


class FailClosedTest(unittest.TestCase):
    """fail-closed(D14) 단언: 설명되지 않은 nonzero rc는 실패로 처리된다."""

    def _run_main(self, argv, stdin_text):
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(stdin_text)
        try:
            with redirect_stdout(io.StringIO()):
                return mutation_report.main(argv)
        finally:
            sys.stdin = old_stdin

    def test_unexplained_rc_fails(self):
        rc = self._run_main(["--rc", "1"], "")
        self.assertEqual(rc, 1)

    def test_rc_explained_by_survived_passes(self):
        rc = self._run_main(["--rc", "1"], SURVIVED_STDOUT)
        self.assertEqual(rc, 0)

    def test_zero_rc_empty_stdin_passes(self):
        rc = self._run_main(["--rc", "0"], "")
        self.assertEqual(rc, 0)


class SuffixDriftGuardTest(unittest.TestCase):
    """D15: 파서가 쓰는 접미사 리터럴이 mutation_check.py 소스에 실제로 있는지 확인."""

    def test_suffix_literals_exist_in_source(self):
        with open(MUTATION_CHECK_PATH, encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn(" [SURVIVED — no test asserts this rule]", source)
        self.assertIn(" [stale anchor]", source)
        self.assertIn(" [hangs instead of failing]", source)


if __name__ == "__main__":
    unittest.main()
