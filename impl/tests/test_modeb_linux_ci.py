"""`.github/workflows/ci.yml`의 `modeb-linux` 잡 배선 단언 (issue #161).

GitHub Actions는 로컬에서 실행할 수 없으므로 워크플로 파일의 **소스
텍스트**에 대해 단언한다 (`test_release_workflow.py`와 같은 패턴). 핵심
회귀는: 캐싱을 도입하지 않는 것(D2, 실측상 직접 다운로드보다 느림),
버전을 하드코딩하지 않는 것(D1, `mlir/llvm.pin`에서만 파생), `gate` 잡의
기존 3-매트릭스 구조를 건드리지 않는 것(D7).
"""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CI_YML_PATH = os.path.join(REPO, ".github", "workflows", "ci.yml")
RELEASE_YML_PATH = os.path.join(REPO, ".github", "workflows", "release.yml")
RELEASING_MD_PATH = os.path.join(REPO, "docs", "RELEASING.md")
LLVM_PIN_PATH = os.path.join(REPO, "mlir", "llvm.pin")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class ModebLinuxJobExistsTest(unittest.TestCase):
    """정상 케이스: 잡이 존재하고 올바른 조각을 담고 있다."""

    def test_job_key_present(self):
        self.assertIn("modeb-linux:", _read(CI_YML_PATH))

    def test_job_runs_test_repo_state_under_mode_b(self):
        text = _read(CI_YML_PATH)
        self.assertIn("tests.test_repo_state", text)

    def test_job_derives_version_from_the_pin_file(self):
        text = _read(CI_YML_PATH)
        self.assertIn("mlir/llvm.pin", text)

    def test_job_exports_lnpl_llvm_bin(self):
        self.assertIn("LNPL_LLVM_BIN", _read(CI_YML_PATH))

    def test_gate_job_matrix_untouched(self):
        # D7: gate의 3-way 파이썬 매트릭스는 그대로 유지된다.
        text = _read(CI_YML_PATH)
        self.assertIn('python-version: ["3.11", "3.12", "3.13"]', text)


class NoApiCachingTest(unittest.TestCase):
    """에러 회귀 가드: D2 — actions/cache가 이 파일에 다시 들어오면 안 된다."""

    def test_no_cache_action_anywhere_in_ci_yml(self):
        self.assertIsNone(re.search(r"uses:\s*actions/cache", _read(CI_YML_PATH)))


class NoHardcodedLlvmVersionTest(unittest.TestCase):
    """경계값: 파싱 라인 밖에서 핀 값을 문자로 그대로 박아넣지 않았는가."""

    def test_pin_derived_major_matches_the_pin_file(self):
        pin_text = _read(LLVM_PIN_PATH)
        major = pin_text.split()[1].split(".")[0]
        self.assertTrue(major.isdigit(), "mlir/llvm.pin 형식이 예상과 다르다: %r" % pin_text)

        ci_text = _read(CI_YML_PATH)
        # 버전을 파생하는 awk/cut 줄 자체는 제외하고, 나머지 어디에도
        # 핀 메이저 버전이 리터럴로 박혀 있지 않아야 한다(D1).
        body_without_pin_parse_line = "\n".join(
            line for line in ci_text.splitlines() if "llvm.pin" not in line
        )
        self.assertNotIn(major, body_without_pin_parse_line,
                          "LLVM 메이저 버전(%s)이 하드코딩된 것으로 보인다" % major)


class ReleaseWorkflowLockstepTest(unittest.TestCase):
    """release.yml은 ci.yml과 같은 EXCLUDED 주석 재작성을 받는다 (D5)."""

    def test_release_yml_names_modeb_linux_as_the_real_coverage(self):
        self.assertIn("modeb-linux", _read(RELEASE_YML_PATH))

    def test_release_yml_excluded_line_still_present(self):
        # D7: gate/release 모두 자체 러너에는 여전히 툴체인이 없으므로,
        # EXCLUDED 자체를 지우면 안 된다 — 주석만 재작성한다.
        self.assertIn('EXCLUDED = {"test_repo_state"}', _read(RELEASE_YML_PATH))

    def test_ci_yml_excluded_line_still_present(self):
        self.assertIn('EXCLUDED = {"test_repo_state"}', _read(CI_YML_PATH))


class DocsUpdatedTest(unittest.TestCase):
    def test_releasing_md_names_modeb_linux(self):
        self.assertIn("modeb-linux", _read(RELEASING_MD_PATH))

    def test_releasing_md_no_longer_promises_bare_removal(self):
        self.assertNotIn("이 제외를 제거한다", _read(RELEASING_MD_PATH))


class LlvmPinFormatTest(unittest.TestCase):
    """mlir/llvm.pin 자체의 형식 계약 — 파싱 로직이 기대는 전제."""

    def test_pin_file_has_exactly_two_space_separated_fields(self):
        fields = _read(LLVM_PIN_PATH).split()
        self.assertEqual(len(fields), 2, "예상 형식: '<name> <version>'")

    def test_pin_version_has_a_numeric_major_component(self):
        version = _read(LLVM_PIN_PATH).split()[1]
        major = version.split(".")[0]
        self.assertTrue(major.isdigit(), "메이저 버전이 숫자가 아니다: %r" % major)


if __name__ == "__main__":
    unittest.main()
