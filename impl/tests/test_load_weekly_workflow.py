"""`.github/workflows/load-weekly.yml`의 배선 단언 (issue #195).

GitHub Actions는 로컬에서 실행할 수 없으므로 워크플로 파일의 소스 텍스트에
대해 단언한다(`test_mutation_workflow.py`와 같은 패턴). 핵심: 이 잡은 절대
부하 수치를 주간으로 리포트만 하고 PR을 절대 막지 않는다 — `pull_request`
트리거가 없고, `continue-on-error`로 실패를 삼키지도 않으며, 브랜치 보호의
필수 체크 목록에 들어가지 않는다. PR 차단 게이트는 `test_perf_counters.py`다.
"""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOAD_YML_PATH = os.path.join(REPO, ".github", "workflows", "load-weekly.yml")
BRANCH_PROTECTION_SCRIPT_PATH = os.path.join(
    REPO, "scripts", "setup_branch_protection.sh"
)
WORKLOAD_PATH = os.path.join(REPO, "examples", "linkhub.lnpl")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _on_block(text):
    """The `on:` mapping only — a comment elsewhere may name any event."""
    start = text.index("\non:\n")
    end = text.index("\njobs:\n", start)
    return text[start:end]


class TriggerTest(unittest.TestCase):
    """정상 케이스: 주간 스케줄과 수동 트리거가 있다."""

    def test_weekly_schedule_present(self):
        self.assertIn('- cron: "0 7 * * 1"', _on_block(_read(LOAD_YML_PATH)))

    def test_workflow_dispatch_present(self):
        self.assertIn("workflow_dispatch:", _on_block(_read(LOAD_YML_PATH)))


class NeverOnAPullRequestTest(unittest.TestCase):
    """에러 케이스: PR/push로 깨어나지 않고, 실패를 삼키지 않는다."""

    def test_no_pull_request_or_push_trigger(self):
        block = _on_block(_read(LOAD_YML_PATH))
        self.assertNotIn("pull_request", block)
        self.assertNotIn("push", block)

    def test_no_continue_on_error_anywhere(self):
        self.assertNotIn("continue-on-error", _read(LOAD_YML_PATH))


class ReportOnlyWiringTest(unittest.TestCase):
    """정상/에러 케이스: 리포트는 실패해도 남고, 기동 실패는 하네스 결함이다."""

    def test_report_reaches_summary_and_artifact_even_on_failure(self):
        text = _read(LOAD_YML_PATH)
        self.assertIn('>> "$GITHUB_STEP_SUMMARY"', text)
        self.assertIn("uses: actions/upload-artifact@v7", text)
        self.assertEqual(2, text.count("if: always()"))

    def test_boot_failure_is_a_harness_fault_before_any_load(self):
        text = _read(LOAD_YML_PATH)
        fault = text.index("server did not boot")
        self.assertLess(fault, text.index("scripts/load_probe.py"))
        self.assertLess(fault, text.index("exit 1"))

    def test_probe_duration_comes_from_one_variable(self):
        text = _read(LOAD_YML_PATH)
        self.assertIn("DURATION=55", text)
        self.assertIn('--seconds "$DURATION"', text)


class BudgetAndPrivilegeTest(unittest.TestCase):
    """경계값 케이스: 시간 예산과 읽기 전용 토큰."""

    def test_timeout_budget(self):
        self.assertIn("timeout-minutes: 30", _read(LOAD_YML_PATH))

    def test_read_only_token(self):
        text = _read(LOAD_YML_PATH)
        self.assertIn("contents: read", text)
        self.assertIsNone(re.search(r":\s*write\b", text))


class WorkloadPinTest(unittest.TestCase):
    """경계값 케이스(교차 파일): 워크로드 파일이 실제로 있고 gunicorn이 고정돼 있다."""

    def test_workload_file_exists_and_gunicorn_is_pinned(self):
        text = _read(LOAD_YML_PATH)
        self.assertIn("LNPL_SOURCE: examples/linkhub.lnpl", text)
        self.assertTrue(os.path.isfile(WORKLOAD_PATH))
        self.assertIn("gunicorn==26.2.0", text)


class CrossFileNotRequiredCheckTest(unittest.TestCase):
    """경계값 케이스(교차 파일): 필수 체크 목록에 부하 잡이 없다."""

    def test_branch_protection_checks_exclude_load(self):
        text = _read(BRANCH_PROTECTION_SCRIPT_PATH)
        checks_line = re.search(r"CHECKS='(.+)'", text).group(1)
        self.assertNotIn("load", checks_line)
        for context in (
            "gate (py3.11)", "gate (py3.12)", "gate (py3.13)", "lint (ruff)",
        ):
            self.assertIn(context, checks_line)


if __name__ == "__main__":
    unittest.main()
