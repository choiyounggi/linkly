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


def dunder_text(version="1.2.3"):
    return '__version__ = "%s"\n' % version


def marketplace_text(versions=("1.2.3", "1.2.3", "1.2.3")):
    return json.dumps({"plugins": [
        {"name": "plugin-%d" % i, "version": v}
        for i, v in enumerate(versions)
    ]})


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


class FourSiteCheckTest(unittest.TestCase):
    """issue #153: `check()`가 pyproject/`__version__`/plugin.json/marketplace
    네 종류를 전부 본다 — v0.7.0의 거짓 초록(pyproject.toml·plugin.json만
    올리고 `__version__`은 안 올렸는데 통과)을 재현 불가로 만든다.

    `dunder_path`/`marketplace_path`를 매번 명시적으로 넘긴다 — `None` 기본값은
    이 저장소의 실제 파일과 비교하는 경로라, 합성 root 버전과는 항상
    어긋나 버린다(check()의 `_resolve_sites` 규약)."""

    def _write_tree(self, tmp, pyproject_version="1.0.0",
                     plugin_versions=("1.0.0", "1.0.0", "1.0.0"),
                     dunder_version="1.0.0",
                     marketplace_versions=("1.0.0", "1.0.0", "1.0.0")):
        pyproject_path = os.path.join(tmp, "pyproject.toml")
        write(pyproject_path, pyproject_text(pyproject_version))

        plugin_paths = []
        for i, v in enumerate(plugin_versions):
            p = os.path.join(tmp, "plugin-%d.json" % i)
            write(p, plugin_json_text(v))
            plugin_paths.append(p)

        dunder_path = os.path.join(tmp, "__init__.py")
        write(dunder_path, dunder_text(dunder_version))

        marketplace_path = os.path.join(tmp, "marketplace.json")
        write(marketplace_path, marketplace_text(marketplace_versions))

        return pyproject_path, plugin_paths, dunder_path, marketplace_path

    def test_all_four_kinds_match_reports_no_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path, plugin_paths, dunder_path, marketplace_path = \
                self._write_tree(tmp)
            root, problems = cvs.check(pyproject_path, plugin_paths,
                                        dunder_path=dunder_path,
                                        marketplace_path=marketplace_path)
            self.assertEqual(root, "1.0.0")
            self.assertEqual(problems, [])

    def test_dunder_mismatch_is_reported_the_v0_7_0_false_green_repro(self):
        """v0.7.0에서 실제로 일어난 거짓 초록의 직접 재현: pyproject.toml과
        plugin.json 셋, marketplace 셋은 전부 올랐는데
        `impl/lnpl/__init__.py`의 `__version__`만 안 올랐다. 옛 스크립트는
        이걸 못 본다 — 새 스크립트는 문제 1건을 보고하고 main()은 1을
        돌려준다."""
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path, plugin_paths, dunder_path, marketplace_path = \
                self._write_tree(
                    tmp,
                    pyproject_version="0.7.0",
                    plugin_versions=("0.7.0", "0.7.0", "0.7.0"),
                    dunder_version="0.6.0",
                    marketplace_versions=("0.7.0", "0.7.0", "0.7.0"))
            root, problems = cvs.check(pyproject_path, plugin_paths,
                                        dunder_path=dunder_path,
                                        marketplace_path=marketplace_path)
            self.assertEqual(len(problems), 1)
            path, msg = problems[0]
            self.assertEqual(path, dunder_path)
            self.assertIn("0.6.0", msg)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cvs.main(pyproject_path, plugin_paths,
                               dunder_path=dunder_path,
                               marketplace_path=marketplace_path)
            self.assertEqual(rc, 1)

    def test_a_mismatched_marketplace_entry_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path, plugin_paths, dunder_path, marketplace_path = \
                self._write_tree(
                    tmp, marketplace_versions=("1.0.0", "0.5.0", "1.0.0"))
            root, problems = cvs.check(pyproject_path, plugin_paths,
                                        dunder_path=dunder_path,
                                        marketplace_path=marketplace_path)
            self.assertEqual(len(problems), 1)
            path, msg = problems[0]
            self.assertIn("plugin-1", path)
            self.assertIn("0.5.0", msg)

    def test_dunder_missing_assignment_is_reported_not_raised(self):
        """경계: `__version__` 대입 자체가 없다 — 예외가 아니라 사유
        문자열로 보고된다(`plugin_version`과 같은 규약)."""
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path, plugin_paths, dunder_path, marketplace_path = \
                self._write_tree(tmp)
            write(dunder_path, '"""no version assignment in this file."""\n')
            root, problems = cvs.check(pyproject_path, plugin_paths,
                                        dunder_path=dunder_path,
                                        marketplace_path=marketplace_path)
            self.assertEqual(len(problems), 1)
            path, msg = problems[0]
            self.assertEqual(path, dunder_path)
            self.assertIn("없음", msg)

    def test_empty_marketplace_plugins_array_is_reported(self):
        """경계: `.plugins`가 빈 배열이다 — issue #141 r1과 같은 이유로
        검사 대상이 조용히 사라진 것이므로 문제로 보고된다(D5)."""
        with tempfile.TemporaryDirectory() as tmp:
            pyproject_path, plugin_paths, dunder_path, marketplace_path = \
                self._write_tree(tmp)
            write(marketplace_path, json.dumps({"plugins": []}))
            root, problems = cvs.check(pyproject_path, plugin_paths,
                                        dunder_path=dunder_path,
                                        marketplace_path=marketplace_path)
            self.assertEqual(len(problems), 1)
            path, msg = problems[0]
            self.assertEqual(path, marketplace_path)


class VersionSitesRegistryTest(unittest.TestCase):
    def test_version_sites_covers_every_path_the_packaging_tests_hardcode(self):
        """결합(D7): `impl/tests/test_packaging.py`와
        `impl/tests/test_plugin_manifest.py`가 하드코딩한 버전 지점 4종이
        전부 `VERSION_SITES`에 등장하는지 — 목록이 갈라지면 이 테스트가
        빨개진다. 그 두 모듈은 수정하지 않는다(out of scope); 여기서는
        그것들이 하드코딩한 값과 같은 값을 독립적으로 재구성해 대조한다."""
        import glob as glob_mod
        import lnpl

        kinds = {kind: path for _, kind, path in cvs.VERSION_SITES}
        self.assertEqual(set(kinds),
                          {"toml", "dunder", "plugin_json", "marketplace"})

        # test_packaging.py: ROOT = pathlib.Path(__file__).resolve().parents[2]
        #                     path = ROOT / "pyproject.toml"
        self.assertEqual(kinds["toml"], os.path.join(REPO, "pyproject.toml"))

        # test_packaging.py: `import lnpl; ... lnpl.__version__` — the file
        # ast-parsed by `dunder_version` must be the same file that supplies
        # the imported package's __version__.
        self.assertEqual(os.path.abspath(lnpl.__file__), kinds["dunder"])

        # test_plugin_manifest.py: PLUGIN_JSON = REPO/plugins/lnpl/.claude-plugin/plugin.json
        plugin_json = os.path.join(REPO, "plugins", "lnpl",
                                    ".claude-plugin", "plugin.json")
        self.assertIn(plugin_json, sorted(glob_mod.glob(kinds["plugin_json"])))

        # test_plugin_manifest.py: MARKET = REPO/.claude-plugin/marketplace.json
        market = os.path.join(REPO, ".claude-plugin", "marketplace.json")
        self.assertEqual(kinds["marketplace"], market)


if __name__ == "__main__":
    unittest.main()
