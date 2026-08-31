"""`.github/workflows/release.yml`의 배선 단언 — GitHub Actions는 로컬에서
실행할 수 없으므로, 워크플로 파일의 **소스 텍스트**에 대해 단언한다
(issue #154).

이 파일은 YAML을 실행하지 않는다. `release` 잡이 하드코딩된
"See CHANGELOG.md for details."로 되돌아가거나 `--notes-file` 배선이
조용히 사라지는 회귀를 잡는 것이 목적이다.
"""
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RELEASE_YML_PATH = os.path.join(REPO, ".github", "workflows", "release.yml")


def _read():
    with open(RELEASE_YML_PATH, encoding="utf-8") as fh:
        return fh.read()


class ReleaseNotesWiringTest(unittest.TestCase):
    def test_uses_notes_file_flag(self):
        self.assertIn("--notes-file", _read())

    def test_hardcoded_placeholder_notes_are_gone(self):
        self.assertNotIn("See CHANGELOG.md for details.", _read())

    def test_calls_changelog_section_script(self):
        self.assertIn("scripts/changelog_section.py", _read())


if __name__ == "__main__":
    unittest.main()
