"""`scripts/check_version_sync.py`의 검사 로직 — 합성 입력으로만 검증한다.

issue #141: 루트 `pyproject.toml`의 `[project] version`과 각
`plugins/*/.claude-plugin/plugin.json`의 `.version`이 드리프트한 채 v0.6.0이
릴리스된 적이 있다. 이 스크립트는 그 재발을 막는다. 이 파일은 실제 레포가
지금 일치하는지도 함께 확인한다(DoD: 현 레포 exit 0) — 나머지는 임시
디렉터리로 합성한 입력으로 함수 자체의 정오만 검사한다.
"""
import io
import json
import os
import tempfile
import unittest
import contextlib
import importlib.util

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(REPO, "scripts", "check_version_sync.py")

_spec = importlib.util.spec_from_file_location("check_version_sync", SCRIPT_PATH)
cvs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cvs)


def write(path, content):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def pyproject_text(version="1.2.3"):
    return ('[project]\nname = "x"\nversion = "%s"\n' % version)


def plugin_json_text(version="1.2.3"):
    return json.dumps({"name": "x", "version": version})


class RootVersionTest(unittest.TestCase):
    def test_reads_the_project_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pyproject.toml")
            write(path, pyproject_text("9.9.9"))
            self.assertEqual(cvs.root_version(path), "9.9.9")

    def test_missing_project_version_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pyproject.toml")
            write(path, '[project]\nname = "x"\n')
            with self.assertRaises(cvs.VersionSyncError):
                cvs.root_version(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            cvs.root_version("/nonexistent-dir-for-test/pyproject.toml")


class PluginVersionTest(unittest.TestCase):
    def test_reads_the_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plugin.json")
            write(path, plugin_json_text("2.0.0"))
            version, error = cvs.plugin_version(path)
            self.assertEqual(version, "2.0.0")
            self.assertIsNone(error)

    def test_a_missing_file_is_reported_not_raised(self):
        version, error = cvs.plugin_version("/nonexistent-dir-for-test/plugin.json")
        self.assertIsNone(version)
        self.assertIsNotNone(error)

    def test_malformed_json_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plugin.json")
            write(path, "{not valid json")
            version, error = cvs.plugin_version(path)
            self.assertIsNone(version)
            self.assertIn("JSON", error)

    def test_missing_version_field_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plugin.json")
            write(path, json.dumps({"name": "x"}))
            version, error = cvs.plugin_version(path)
            self.assertIsNone(version)
            self.assertIn("version", error)


class CheckTest(unittest.TestCase):
    def test_all_versions_match_reports_no_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path = os.path.join(tmp, "pyproject.toml")
            write(pyproject_path, pyproject_text("1.0.0"))
            plugin_path = os.path.join(tmp, "plugin.json")
            write(plugin_path, plugin_json_text("1.0.0"))
            root, problems = cvs.check(pyproject_path, [plugin_path])
            self.assertEqual(root, "1.0.0")
            self.assertEqual(problems, [])

    def test_a_mismatched_plugin_is_reported_with_both_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path = os.path.join(tmp, "pyproject.toml")
            write(pyproject_path, pyproject_text("1.0.0"))
            plugin_path = os.path.join(tmp, "plugin.json")
            write(plugin_path, plugin_json_text("0.9.0"))
            root, problems = cvs.check(pyproject_path, [plugin_path])
            self.assertEqual(len(problems), 1)
            path, msg = problems[0]
            self.assertEqual(path, plugin_path)
            self.assertIn("0.9.0", msg)
            self.assertIn("1.0.0", msg)

    def test_a_missing_plugin_file_is_reported_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path = os.path.join(tmp, "pyproject.toml")
            write(pyproject_path, pyproject_text("1.0.0"))
            missing_path = os.path.join(tmp, "does-not-exist", "plugin.json")
            root, problems = cvs.check(pyproject_path, [missing_path])
            self.assertEqual(len(problems), 1)
            self.assertEqual(problems[0][0], missing_path)

    def test_an_explicitly_empty_plugin_list_reports_no_problems(self):
        """호출자가 `plugin_paths=[]`를 명시하면(단위 테스트가 주로 이렇게
        쓴다) 그 의도를 존중한다 — 검사할 대상이 없다는 뜻이지, 글롭이 실패한
        것이 아니다."""
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path = os.path.join(tmp, "pyproject.toml")
            write(pyproject_path, pyproject_text("1.0.0"))
            root, problems = cvs.check(pyproject_path, [])
            self.assertEqual(root, "1.0.0")
            self.assertEqual(problems, [])

    def test_a_default_discovery_that_finds_nothing_is_reported_as_a_problem(self):
        """issue #141 r1: `plugin_paths`를 아예 안 넘기면(=CI가 부르는 방식)
        `PLUGIN_GLOB`으로 발견한다. 그 글롭이 0건이면 — `plugins/` 경로가
        옮겨졌다든지 — 검사할 대상이 조용히 사라진 것이므로, 이것 자체가
        문제로 보고되어야 한다. 그렇지 않으면 버전 드리프트 게이트가 소리
        없이 통과해 버린다(v0.6.0에서 실제 발생했던 종류의 드리프트)."""
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path = os.path.join(tmp, "pyproject.toml")
            write(pyproject_path, pyproject_text("1.0.0"))
            original_glob = cvs.PLUGIN_GLOB
            cvs.PLUGIN_GLOB = os.path.join(tmp, "no-such-dir", "*", "plugin.json")
            try:
                root, problems = cvs.check(pyproject_path)
            finally:
                cvs.PLUGIN_GLOB = original_glob
            self.assertEqual(len(problems), 1)
            self.assertIn("0 plugin manifests", problems[0][1])


class MainTest(unittest.TestCase):
    def test_the_repository_itself_is_in_sync(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cvs.main()
        self.assertEqual(rc, 0, out.getvalue())

    def test_main_reports_a_mismatch_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path = os.path.join(tmp, "pyproject.toml")
            write(pyproject_path, pyproject_text("1.0.0"))
            plugin_path = os.path.join(tmp, "plugin.json")
            write(plugin_path, plugin_json_text("2.0.0"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cvs.main(pyproject_path=pyproject_path,
                              plugin_paths=[plugin_path])
            self.assertEqual(rc, 1)
            self.assertIn("2.0.0", out.getvalue())

    def test_main_exits_nonzero_when_default_discovery_finds_nothing(self):
        """CI가 실제로 부르는 경로(`plugin_paths` 인자 없음)로 끝까지 확인한다
        — check()만이 아니라 main()도 이 상황에서 exit 1인지."""
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path = os.path.join(tmp, "pyproject.toml")
            write(pyproject_path, pyproject_text("1.0.0"))
            original_glob = cvs.PLUGIN_GLOB
            cvs.PLUGIN_GLOB = os.path.join(tmp, "no-such-dir", "*", "plugin.json")
            try:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = cvs.main(pyproject_path=pyproject_path)
            finally:
                cvs.PLUGIN_GLOB = original_glob
            self.assertEqual(rc, 1)
            self.assertIn("0 plugin manifests", out.getvalue())


if __name__ == "__main__":
    unittest.main()
