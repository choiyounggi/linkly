"""`scripts/setup_branch_protection.sh`의 --check(읽기 전용) 모드 단언 (issue #166).

이 스크립트는 이 태스크에서 절대 실제로 `gh api` PUT을 호출하지 않는다 —
`--check`는 원하는 페이로드를 stdout에 출력할 뿐 아무것도 바꾸지 않는다.
실제 적용은 코디네이터가 Gate 2 이후 사람 확인을 받고 별도로 실행한다.
"""
import os
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(REPO, "scripts", "setup_branch_protection.sh")

REQUIRED_CONTEXTS = [
    "gate (py3.11)",
    "gate (py3.12)",
    "gate (py3.13)",
    "lint (ruff)",
]
MODEB_CONTEXT = "modeb-linux (test_repo_state under real mode B)"


def _run(args):
    return subprocess.run(
        [SCRIPT_PATH] + args,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )


class ScriptSyntaxTest(unittest.TestCase):
    """정상 케이스: 스크립트가 존재하고 문법이 유효하며 실행 가능하다."""

    def test_bash_syntax_check(self):
        result = subprocess.run(
            ["bash", "-n", SCRIPT_PATH], capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK))


class CheckModeDefaultTest(unittest.TestCase):
    """정상 케이스: --check는 실측 gh api 호출 없이 페이로드만 출력한다."""

    def test_check_exits_zero(self):
        result = _run(["--check"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_contains_all_default_contexts(self):
        result = _run(["--check"])
        for context in REQUIRED_CONTEXTS:
            self.assertIn(context, result.stdout)

    def test_check_excludes_modeb_by_default(self):
        result = _run(["--check"])
        self.assertNotIn(MODEB_CONTEXT, result.stdout)

    def test_check_never_calls_gh(self):
        result = _run(["--check"])
        self.assertNotIn("gh api", result.stdout)


class IncludeModebFlagTest(unittest.TestCase):
    """경계값 케이스: --include-modeb 조합 시 modeb-linux가 목록에 추가된다."""

    def test_check_include_modeb_adds_context(self):
        result = _run(["--check", "--include-modeb"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(MODEB_CONTEXT, result.stdout)
        for context in REQUIRED_CONTEXTS:
            self.assertIn(context, result.stdout)


class UnknownFlagTest(unittest.TestCase):
    """에러 케이스: 알 수 없는 플래그는 비정상 종료한다."""

    def test_unknown_flag_exits_nonzero(self):
        result = _run(["--bogus"])
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
