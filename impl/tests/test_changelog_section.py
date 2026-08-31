"""`scripts/changelog_section.py`의 절 추출 로직 — 합성 CHANGELOG로 검증한다.

issue #154: `release.yml`이 발행하는 GitHub Release 본문이 하드코딩된
"See CHANGELOG.md for details."였다. 이 스크립트는 CHANGELOG.md의 해당 버전
절을 결정적으로 뽑아 release.yml이 그 사실을 그대로 재사용하게 한다. 이
파일은 함수 자체의 정오만 합성 입력으로 검사한다(실물 CHANGELOG 대조는
`test_real_changelog_section`에서 한 건만).
"""
import contextlib
import io
import os
import unittest
import importlib.util

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(REPO, "scripts", "changelog_section.py")
CHANGELOG_PATH = os.path.join(REPO, "CHANGELOG.md")

_spec = importlib.util.spec_from_file_location("changelog_section", SCRIPT_PATH)
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


# 세 절짜리 합성 CHANGELOG — 가운데 절 추출과 정상 경계를 검사한다.
FIXTURE = (
    "# Changelog\n"
    "\n"
    "## [Unreleased]\n"
    "\n"
    "## [0.3.0] — 2026-01-03\n"
    "\"Third quote theme.\" Extra prose after the quote.\n"
    "\n"
    "### Added\n"
    "- Feature C\n"
    "\n"
    "## [0.2.0] — 2026-01-02\n"
    "\"Second quote theme.\" More text.\n"
    "\n"
    "### Added\n"
    "- Feature B\n"
    "\n"
    "## [0.1.0] — 2026-01-01\n"
    "No quote theme here, just plain prose.\n"
    "\n"
    "### Added\n"
    "- Feature A\n"
)

# 마지막 절 뒤에 실물과 같은 모양의 참조식 링크 정의 블록이 붙는 합성
# CHANGELOG — "다음 `## [`가 없을 때 파일 끝까지가 아니라 링크 정의
# 블록 앞까지" 경계를 고정한다(r1 F1: 링크 정의가 없는 픽스처로는 이
# 경계를 검사할 수 없었다).
FIXTURE_WITH_LINK_DEFS = (
    "# Changelog\n"
    "\n"
    "## [0.2.0] — 2026-01-02\n"
    "\"Only theme.\" prose\n"
    "\n"
    "### Added\n"
    "- Feature B\n"
    "\n"
    "## [0.1.0] — 2026-01-01\n"
    "Body of the last section.\n"
    "\n"
    "### Added\n"
    "- Feature A\n"
    "\n"
    "[0.2.0]: https://example.com/releases/tag/v0.2.0\n"
    "[0.1.0]: https://example.com/releases/tag/v0.1.0\n"
)


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cs.main(argv)
    return rc, out.getvalue(), err.getvalue()


class ExtractSectionNormalTest(unittest.TestCase):
    def test_middle_section_body_excludes_title_and_next_header(self):
        body = cs.extract_section(FIXTURE, "0.2.0")
        self.assertEqual(
            body,
            '"Second quote theme." More text.\n\n### Added\n- Feature B')
        self.assertNotIn("## [0.1.0]", body)
        self.assertNotIn("## [0.2.0]", body)

    def test_v_prefix_and_bare_version_agree(self):
        self.assertEqual(
            cs.extract_section(FIXTURE, "v0.2.0"),
            cs.extract_section(FIXTURE, "0.2.0"))

    def test_title_uses_quoted_theme_verbatim(self):
        title = cs.extract_title("v0.2.0", FIXTURE, "v0.2.0")
        self.assertEqual(title, "linkly v0.2.0 — Second quote theme.")


class ExtractSectionBoundaryTest(unittest.TestCase):
    def test_theme_without_quotes_yields_title_with_no_dash(self):
        title = cs.extract_title("v0.1.0", FIXTURE, "0.1.0")
        self.assertEqual(title, "linkly v0.1.0")
        self.assertNotIn("—", title)

    def test_last_section_runs_to_end_of_file(self):
        body = cs.extract_section(FIXTURE_WITH_LINK_DEFS, "0.1.0")
        self.assertEqual(
            body, "Body of the last section.\n\n### Added\n- Feature A")
        self.assertFalse(any(line.startswith("[") for line in body.splitlines()),
                          "본문에 참조식 링크 정의 줄이 섞여 들어갔다: %r" % body)


class ExtractSectionErrorTest(unittest.TestCase):
    def test_missing_version_raises_with_available_list(self):
        with self.assertRaises(cs.SectionNotFound) as ctx:
            cs.extract_section(FIXTURE, "9.9.9")
        self.assertEqual(ctx.exception.available, ["0.3.0", "0.2.0", "0.1.0"])

    def test_unreleased_is_not_a_version_and_fails_like_missing(self):
        with self.assertRaises(cs.SectionNotFound) as ctx:
            cs.extract_section(FIXTURE, "Unreleased")
        self.assertEqual(ctx.exception.available, ["0.3.0", "0.2.0", "0.1.0"])


class MainCliTest(unittest.TestCase):
    def _write_changelog(self, tmp_dir, text):
        path = os.path.join(tmp_dir, "CHANGELOG.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_main_prints_body_and_exits_zero(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_changelog(tmp, FIXTURE)
            rc, out, err = _run(["0.2.0", "--changelog", path])
        self.assertEqual(rc, 0)
        self.assertIn("Second quote theme.", out)
        self.assertEqual(err, "")

    def test_main_missing_version_exits_1_with_empty_stdout(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_changelog(tmp, FIXTURE)
            rc, out, err = _run(["9.9.9", "--changelog", path])
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("0.3.0", err)
        self.assertIn("0.2.0", err)
        self.assertIn("0.1.0", err)


class RealChangelogTest(unittest.TestCase):
    def test_070_section_matches_repo_changelog(self):
        with open(CHANGELOG_PATH, encoding="utf-8") as fh:
            text = fh.read()
        body = cs.extract_section(text, "0.7.0")
        self.assertTrue(body.startswith('"The production-readiness release."'))
        self.assertIn("### Added", body)
        self.assertNotIn("## [0.6.0]", body)

    def test_last_real_section_excludes_link_definitions(self):
        # r1 F1: 파일의 마지막 버전 절(오늘은 0.1.0, 앞으로 바뀔 수 있으므로
        # 하드코딩하지 않고 _headers()로 계산한다)은 그 뒤에 붙는 263-270행의
        # 참조식 링크 정의 블록([x.y.z]: https://... x8)을 삼키면 안 된다.
        with open(CHANGELOG_PATH, encoding="utf-8") as fh:
            text = fh.read()
        headers = cs._headers(text)
        versions = [v for v, _start, _body in headers if cs.VERSION_RE.match(v)]
        last_version = versions[-1]
        body = cs.extract_section(text, last_version)
        self.assertNotIn("https://github.com/", body)


if __name__ == "__main__":
    unittest.main()
