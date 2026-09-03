"""`.github/workflows/mutation.yml`의 잡 배선 단언 (issue #166).

GitHub Actions는 로컬에서 실행할 수 없으므로 워크플로 파일의 **소스 텍스트**에
대해 단언한다(`test_modeb_linux_ci.py`와 같은 패턴). 핵심 회귀: PR 잡에
`continue-on-error`를 쓰지 않는 것(D12), 두 잡 모두 하네스 전에 툴체인을
설치하는 것(D11), 빈 변경 파일 배열을 안전하게 처리하는 것(D9/D10), 주간 잡의
fail-closed 배선(D14), 그리고 뮤테이션 잡이 절대 required check가 될 수 없다는
것(브랜치 보호 스크립트와의 교차 확인).
"""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MUTATION_YML_PATH = os.path.join(REPO, ".github", "workflows", "mutation.yml")
BRANCH_PROTECTION_SCRIPT_PATH = os.path.join(
    REPO, "scripts", "setup_branch_protection.sh"
)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class JobKeysPresentTest(unittest.TestCase):
    """정상 케이스: 두 잡 키가 모두 존재한다."""

    def test_mutation_pr_job_present(self):
        self.assertIn("mutation-pr:", _read(MUTATION_YML_PATH))

    def test_mutation_weekly_job_present(self):
        self.assertIn("mutation-weekly:", _read(MUTATION_YML_PATH))


class NoContinueOnErrorTest(unittest.TestCase):
    """경계값/회귀 케이스(D12): continue-on-error가 파일 전체에 없다."""

    def test_no_continue_on_error_anywhere(self):
        self.assertNotIn("continue-on-error", _read(MUTATION_YML_PATH))


class ToolchainBeforeHarnessTest(unittest.TestCase):
    """정상 케이스(D11): 두 잡 모두 하네스 호출 전에 툴체인을 설치한다."""

    def _job_block(self, text, job_key, next_job_key=None):
        start = text.index(job_key)
        end = text.index(next_job_key, start) if next_job_key else len(text)
        return text[start:end]

    def test_mutation_pr_installs_toolchain_before_selector(self):
        text = _read(MUTATION_YML_PATH)
        block = self._job_block(text, "mutation-pr:", "mutation-weekly:")
        apt_idx = block.index("apt.llvm.org")
        bin_idx = block.index("LNPL_LLVM_BIN")
        selector_idx = block.index("mutation_scope_select.py")
        self.assertLess(apt_idx, selector_idx)
        self.assertLess(bin_idx, selector_idx)

    def test_mutation_weekly_installs_toolchain_before_harness(self):
        text = _read(MUTATION_YML_PATH)
        block = self._job_block(text, "mutation-weekly:")
        apt_idx = block.index("apt.llvm.org")
        bin_idx = block.index("LNPL_LLVM_BIN")
        harness_idx = block.index("mutation_check.py")
        self.assertLess(apt_idx, harness_idx)
        self.assertLess(bin_idx, harness_idx)


class ArrayFormChangedFilesTest(unittest.TestCase):
    """경계값 케이스(D10): CHANGED는 배열 전개로만 쓰이고 bare 보간은 없다."""

    def test_array_expansion_present(self):
        self.assertIn('"${CHANGED[@]}"', _read(MUTATION_YML_PATH))

    def test_no_bare_changed_interpolation(self):
        text = _read(MUTATION_YML_PATH)
        # bare "$CHANGED" (not "${CHANGED[@]}" or "${#CHANGED[@]}") must not appear
        self.assertIsNone(re.search(r"(?<!\{)\$CHANGED(?!\[)", text))


class CrossFileNotRequiredCheckTest(unittest.TestCase):
    """에러/경계값 케이스(D12 교차 확인): 브랜치 보호 스크립트의 필수 체크
    목록에 mutation 잡이 절대 들어가지 않는다."""

    def test_branch_protection_checks_exclude_mutation(self):
        text = _read(BRANCH_PROTECTION_SCRIPT_PATH)
        checks_line = re.search(r'CHECKS=\'(.+)\'', text).group(1)
        self.assertNotIn("mutation", checks_line)
        for context in (
            "gate (py3.11)", "gate (py3.12)", "gate (py3.13)", "lint (ruff)",
        ):
            self.assertIn(context, checks_line)


class FailClosedWiringTest(unittest.TestCase):
    """정상 케이스(D14): 주간 잡이 rc를 캡처하고 두 mutation_report.py 호출 모두
    --rc를 넘긴다."""

    def test_rc_captured_before_parse_step(self):
        text = _read(MUTATION_YML_PATH)
        rc_capture_idx = text.index("mutation_rc.txt")
        parse_step_idx = text.index("Parse + report")
        self.assertLess(rc_capture_idx, parse_step_idx)

    def test_both_report_invocations_pass_rc(self):
        text = _read(MUTATION_YML_PATH)
        count = text.count("mutation_report.py --rc")
        self.assertEqual(count, 2)


class DispatchTriggerTest(unittest.TestCase):
    """issue #169: full-matrix 잡의 수동 트리거 배선.

    수용 기준의 "hosted 러너에서 full-matrix 1회 green 관측"은 스케줄(월요일
    06:00 UTC)을 기다리지 않고 재현할 수 있어야 한다 — workflow_dispatch가
    mutation-weekly 잡을 깨우되, diff 전제(base.sha)가 있는 mutation-pr 잡은
    절대 깨우지 않는다.
    """

    def _job_block(self, text, job_key, next_job_key=None):
        start = text.index(job_key)
        end = text.index(next_job_key, start) if next_job_key else len(text)
        return text[start:end]

    def _if_line(self, block):
        return next(ln for ln in block.splitlines() if ln.strip().startswith("if:"))

    def test_workflow_dispatch_trigger_present(self):
        self.assertIn("workflow_dispatch:", _read(MUTATION_YML_PATH))

    def test_weekly_job_wakes_on_dispatch_and_schedule(self):
        text = _read(MUTATION_YML_PATH)
        if_line = self._if_line(self._job_block(text, "mutation-weekly:"))
        self.assertIn("schedule", if_line)
        self.assertIn("workflow_dispatch", if_line)

    def test_pr_job_does_not_wake_on_dispatch(self):
        # 경계값/회귀: dispatch 이벤트에는 pull_request.base.sha가 없다 —
        # mutation-pr 잡이 깨어나면 diff 산출 자체가 깨진다.
        text = _read(MUTATION_YML_PATH)
        if_line = self._if_line(
            self._job_block(text, "mutation-pr:", "mutation-weekly:"))
        self.assertIn("pull_request", if_line)
        self.assertNotIn("workflow_dispatch", if_line)


class WeeklyTimeoutBudgetTest(unittest.TestCase):
    """issue #169: full matrix의 시간 예산.

    러너 실측(run 33702421111): 뮤테이션당 트리 복사 + 스위트 ~85-90초 × 77
    ≈ 110분 — 45분 예산으로는 baseline이 green이어도 잡이 타임아웃으로
    취소된다(실측 43분 실행 후 취소). 180분 = 실측 1.5x 마진.
    """

    def _job_block(self, text, job_key, next_job_key=None):
        start = text.index(job_key)
        end = text.index(next_job_key, start) if next_job_key else len(text)
        return text[start:end]

    def test_weekly_budget_fits_the_measured_matrix(self):
        block = self._job_block(_read(MUTATION_YML_PATH), "mutation-weekly:")
        self.assertIn("timeout-minutes: 180", block)

    def test_pr_budget_is_unchanged(self):
        # 경계값/회귀: diff-scoped 잡은 소수 뮤테이션만 돌므로 20분 유지 —
        # weekly 예산 상향이 PR 잡으로 번지면 고장난 PR 잡이 20분 대신
        # 3시간을 붙들게 된다.
        block = self._job_block(_read(MUTATION_YML_PATH), "mutation-pr:",
                                "mutation-weekly:")
        self.assertIn("timeout-minutes: 20", block)


class EmptyChangedBranchTest(unittest.TestCase):
    """경계값 케이스(D9): 빈 변경 파일 분기가 선별기 호출보다 먼저 나온다."""

    def test_empty_branch_before_selector_invocation(self):
        text = _read(MUTATION_YML_PATH)
        empty_check_idx = text.index('-eq 0 ]')
        skip_echo_idx = text.index("mutation scope is empty, skipping")
        selector_idx = text.index("scripts/mutation_scope_select.py")
        self.assertLess(empty_check_idx, selector_idx)
        self.assertLess(skip_echo_idx, selector_idx)


if __name__ == "__main__":
    unittest.main()
