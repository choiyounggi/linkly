"""임시 디렉터리 위생 — 테스트가 만든 것은 테스트가 지운다.

이 파일이 존재하는 이유(실측): `.claude/tmp`에 998개 / 43MB가 쌓여 있었고,
그중 686개가 `lnpl-g8-*`, 306개가 `lnpl-until-*`이었다. 두 테스트 클래스가
`setUp`에서 `tempfile.mkdtemp`를 부르고 `tearDown`을 두지 않아, 실행할 때마다
빌드 산출물이 워크트리에 영구히 쌓였다. 나머지 네 파일은 이미 정리하고 있었다 —
관례는 있었고 두 곳이 빠뜨린 것이다.

그래서 여기서 고치는 것은 그 두 곳이 아니라 **관례 자체**다. 두 가지를 강제한다:

1. `mkdtemp` 호출 지점마다 정리가 붙어 있을 것 (`tearDown` 또는 `addCleanup`).
2. `mkdtemp`가 `dir=`를 반드시 넘길 것 — 기본값은 시스템 임시 디렉터리이고,
   이 레포는 `/tmp`·`$TMPDIR`에 쓰지 않는다(보안 정책; EDR이 악성으로 탐지한다).
   `dir=`를 빠뜨린 호출은 조용히 `/tmp`로 새어 나간다.
"""
import ast
import glob
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TESTS_DIR = os.path.join(REPO, "impl", "tests")


def _calls_named(node, name):
    """이 노드 아래에서 `<something>.name(...)` 호출이 하나라도 있는가."""
    return any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == name
               for n in ast.walk(node))


def _mkdtemp_calls(node):
    return [n for n in ast.walk(node)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "mkdtemp"]


def leaking_scopes(source, filename="<test>"):
    """정리 없이 `mkdtemp`를 부르는 스코프의 이름 목록.

    스코프는 **가장 가까운 감싸는 class**다. class 밖(모듈 레벨 헬퍼 함수)이면
    그 함수가 스코프다. 두 형태 모두 이 레포에 실재하므로 둘 다 받아준다:
      - class + `tearDown`      (test_backend.py)
      - class + `addCleanup`    (test_golden.py)
      - 헬퍼 함수 + `addCleanup` (test_repo_state.py `_tmp_workdir`)
    """
    tree = ast.parse(source, filename=filename)
    leaks, claimed = [], set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        calls = _mkdtemp_calls(node)
        if not calls:
            continue
        claimed.update(id(c) for c in calls)
        has_teardown = any(isinstance(n, ast.FunctionDef) and n.name == "tearDown"
                           for n in node.body)
        if not (has_teardown or _calls_named(node, "addCleanup")):
            leaks.append(node.name)

    # class에 속하지 않은 나머지 호출은 감싸는 함수가 책임진다.
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        calls = [c for c in _mkdtemp_calls(node) if id(c) not in claimed]
        if not calls:
            continue
        claimed.update(id(c) for c in calls)
        if not _calls_named(node, "addCleanup"):
            leaks.append(node.name)

    return leaks


def mkdtemp_without_dir(source, filename="<test>"):
    """`dir=`를 넘기지 않는 `mkdtemp` 호출의 줄 번호 목록."""
    tree = ast.parse(source, filename=filename)
    return [c.lineno for c in _mkdtemp_calls(tree)
            if not any(kw.arg == "dir" for kw in c.keywords)]


def _test_sources():
    for path in sorted(glob.glob(os.path.join(TESTS_DIR, "*.py"))):
        with open(path, encoding="utf-8") as fh:
            yield path, fh.read()


class TempDirCleanupTest(unittest.TestCase):
    """정상 경로 — 레포 전수 검사."""

    def test_every_mkdtemp_scope_cleans_up(self):
        offenders = []
        for path, source in _test_sources():
            for scope in leaking_scopes(source, path):
                offenders.append("%s:%s" % (os.path.basename(path), scope))
        self.assertEqual(offenders, [],
                         "정리 없이 mkdtemp를 부르는 스코프가 있다. tearDown에서 "
                         "shutil.rmtree(..., ignore_errors=True)를 부르거나 "
                         "addCleanup을 등록하라: %s" % offenders)

    def test_every_mkdtemp_pins_its_parent_directory(self):
        offenders = []
        for path, source in _test_sources():
            for line in mkdtemp_without_dir(source, path):
                offenders.append("%s:%d" % (os.path.basename(path), line))
        self.assertEqual(offenders, [],
                         "dir= 없는 mkdtemp는 시스템 임시 디렉터리로 샌다. 이 "
                         "레포는 .claude/tmp만 쓴다(보안 정책): %s" % offenders)

    def test_the_repo_actually_has_mkdtemp_call_sites(self):
        # 위 두 검사가 "대상이 0건이라 통과"하는 잠자는 테스트가 되지 않게 고정한다.
        total = sum(len(_mkdtemp_calls(ast.parse(src))) for _, src in _test_sources())
        self.assertGreaterEqual(total, 8, "mkdtemp 호출을 못 찾았다 — 검사가 무의미하다")


class GuardDetectsLeaksTest(unittest.TestCase):
    """가드 자체가 작동하는지 — 통과만으로는 잠자는 테스트와 구별되지 않는다."""

    LEAK = ("import tempfile\n"
            "class T:\n"
            "    def setUp(self):\n"
            "        self.d = tempfile.mkdtemp(prefix='x-', dir=TMP)\n")

    def test_detects_a_class_with_no_cleanup(self):
        self.assertEqual(leaking_scopes(self.LEAK), ["T"])

    def test_accepts_the_teardown_pattern(self):
        source = self.LEAK + ("    def tearDown(self):\n"
                              "        shutil.rmtree(self.d, ignore_errors=True)\n")
        self.assertEqual(leaking_scopes(source), [])

    def test_accepts_the_addcleanup_pattern(self):
        source = ("import tempfile\n"
                  "class T:\n"
                  "    def _mk(self):\n"
                  "        p = tempfile.mkdtemp(dir=TMP)\n"
                  "        self.addCleanup(shutil.rmtree, p, True)\n")
        self.assertEqual(leaking_scopes(source), [])

    def test_accepts_a_module_level_helper_with_addcleanup(self):
        source = ("import tempfile\n"
                  "def _tmp(test):\n"
                  "    p = tempfile.mkdtemp(dir=base)\n"
                  "    test.addCleanup(shutil.rmtree, p, True)\n"
                  "    return p\n")
        self.assertEqual(leaking_scopes(source), [])

    def test_detects_a_module_level_helper_without_cleanup(self):
        source = ("import tempfile\n"
                  "def _tmp():\n"
                  "    return tempfile.mkdtemp(dir=base)\n")
        self.assertEqual(leaking_scopes(source), ["_tmp"])

    def test_detects_a_mkdtemp_without_dir(self):
        source = "import tempfile\nd = tempfile.mkdtemp(prefix='x-')\n"
        self.assertEqual(mkdtemp_without_dir(source), [2])

    def test_accepts_a_mkdtemp_with_dir(self):
        source = "import tempfile\nd = tempfile.mkdtemp(prefix='x-', dir=TMP)\n"
        self.assertEqual(mkdtemp_without_dir(source), [])


class GuardBoundaryTest(unittest.TestCase):
    """경계값 — 빈 입력, 대상 없음, 중첩."""

    def test_empty_source_reports_nothing(self):
        self.assertEqual(leaking_scopes(""), [])
        self.assertEqual(mkdtemp_without_dir(""), [])

    def test_source_without_mkdtemp_reports_nothing(self):
        source = "class T:\n    def setUp(self):\n        self.x = 1\n"
        self.assertEqual(leaking_scopes(source), [])

    def test_a_class_is_not_blamed_twice_for_two_calls(self):
        source = ("import tempfile\n"
                  "class T:\n"
                  "    def a(self):\n"
                  "        return tempfile.mkdtemp(dir=TMP)\n"
                  "    def b(self):\n"
                  "        return tempfile.mkdtemp(dir=TMP)\n")
        self.assertEqual(leaking_scopes(source), ["T"])

    def test_a_method_inside_a_cleaning_class_is_not_reported_separately(self):
        # 메서드가 감싸는 class에 이미 tearDown이 있으면 메서드를 따로 걸지 않는다.
        source = ("import tempfile\n"
                  "class T:\n"
                  "    def _mk(self):\n"
                  "        return tempfile.mkdtemp(dir=TMP)\n"
                  "    def tearDown(self):\n"
                  "        shutil.rmtree(self.d, ignore_errors=True)\n")
        self.assertEqual(leaking_scopes(source), [])

    def test_syntax_error_is_raised_not_swallowed(self):
        with self.assertRaises(SyntaxError):
            leaking_scopes("class T(:\n")


if __name__ == "__main__":
    unittest.main()
