"""뮤테이션 하네스가 복사하는 트리가 테스트가 읽는 것을 전부 담는가.

`mutation_check.make_tree`는 `TREE_CONTENTS`에 열거된 최상위 항목만 복사해
뮤턴트 트리를 만든다. 테스트가 읽는 경로가 거기 빠지면 **77개 뮤턴트 전부가
같은 실패를 내고**, 잡힌 뮤테이션과 그냥 깨진 트리를 구별할 수 없게 된다.
`TREE_CONTENTS` 주석이 `mlir`/`CHARTER.md`를 두고 이미 겪었다고 적어 둔 일이다.

실제로 또 겪었다(2026-08-05, 실측): 플러그인 작업이 `plugins/`와
`.claude-plugin/`을 읽는 테스트를 추가했는데 `TREE_CONTENTS`를 갱신하지
않아, 뮤턴트 트리에서 81건 중 60건이 실패했다. 전체 스위트는 초록이었으므로
평범한 회귀 검사로는 보이지 않았다.

그래서 이 파일은 규칙을 고정한다: 테스트가 `os.path.join(REPO, "<name>", ...)`로
읽는 `<name>`은 `TREE_CONTENTS`에 있어야 한다.
"""
import ast
import glob
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TESTS_DIR = os.path.join(REPO, "impl", "tests")

sys.path.insert(0, TESTS_DIR)
from mutation_check import TREE_CONTENTS  # noqa: E402

# 복사 대상이 아니어도 되는 이름과 그 이유. 예외는 여기서만 늘린다.
EXEMPT = {
    # 테스트가 `os.makedirs(..., exist_ok=True)`로 직접 만든다. 복사 대상으로
    # 넣으면 워크트리와 빌드 산출물까지 뮤턴트마다 복제된다.
    ".claude",
    # 부재를 검증하는 음성 경로 (test_kb.py). 존재하면 그 테스트가 무의미해진다.
    "no-such-kb",
    # 같은 이유 (test_mcp_server.py): MCP 도구가 없는 파일을 크래시가 아니라
    # `isError`로 되돌리는지 보는 입력이다. 복사되면 파일이 생겨 그 테스트가
    # 검증하려던 경로를 타지 않는다.
    "no-such-file.lnpl",
}


# 레포 루트를 담는 관례적 이름. `test_packaging.py`는 `ROOT`를 쓴다.
ROOT_NAMES = ("REPO", "ROOT")


def repo_relative_roots(source, filename="<test>"):
    """레포 루트 기준 최상위 이름을 모은다.

    두 표기를 모두 본다 — 하나만 보면 다른 하나가 조용히 빠진다:
      os.path.join(REPO, "<name>", ...)     대부분의 테스트
      ROOT / "<name>"                        pathlib (test_packaging.py)

    실제로 pathlib 쪽을 놓쳐서 `pyproject.toml`이 복사 목록에서 빠졌고,
    뮤테이션 베이스라인이 RED가 되어 스윕 전체가 무의미해졌다(2026-08-05).
    """
    names = set()
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "join":
            args = node.args
            if args and isinstance(args[0], ast.Name) and args[0].id in ROOT_NAMES:
                if len(args) > 1 and isinstance(args[1], ast.Constant) \
                        and isinstance(args[1].value, str):
                    names.add(args[1].value)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if isinstance(node.left, ast.Name) and node.left.id in ROOT_NAMES \
                    and isinstance(node.right, ast.Constant) \
                    and isinstance(node.right.value, str):
                names.add(node.right.value)
    return names


def _sources():
    for path in sorted(glob.glob(os.path.join(TESTS_DIR, "*.py"))):
        with open(path, encoding="utf-8") as fh:
            yield path, fh.read()


class MutationTreeCoversTestReadsTest(unittest.TestCase):
    """정상 경로 — 레포 전수 검사."""

    def test_every_repo_relative_root_is_copied_into_the_mutant_tree(self):
        missing = {}
        for path, source in _sources():
            for name in repo_relative_roots(source, path):
                if name in TREE_CONTENTS or name in EXEMPT:
                    continue
                missing.setdefault(name, []).append(os.path.basename(path))
        self.assertEqual(missing, {},
                         "뮤턴트 트리에 복사되지 않는 경로를 테스트가 읽는다. "
                         "mutation_check.TREE_CONTENTS에 추가하거나, 복사가 "
                         "불필요하면 EXEMPT에 이유와 함께 넣어라: %s" % missing)

    def test_plugin_directories_are_covered(self):
        # 이 파일을 낳은 회귀를 이름으로 고정한다.
        self.assertIn("plugins", TREE_CONTENTS)
        self.assertIn(".claude-plugin", TREE_CONTENTS)

    def test_pyproject_is_covered(self):
        # 두 번째 회귀: pathlib 표기를 스캔이 놓쳐 베이스라인이 RED가 됐다.
        self.assertIn("pyproject.toml", TREE_CONTENTS)

    def test_the_scan_actually_finds_references(self):
        # 대상 0건이라 통과하는 잠자는 테스트가 되지 않게 고정한다.
        total = set()
        for path, source in _sources():
            total |= repo_relative_roots(source, path)
        self.assertGreaterEqual(len(total), 6,
                                "REPO 상대 경로를 거의 못 찾았다 — 스캔이 무의미하다")

    def test_every_copied_name_exists_in_the_repo(self):
        # 오타로 넣은 이름은 조용히 아무것도 복사하지 않는다.
        for name in TREE_CONTENTS:
            self.assertTrue(os.path.exists(os.path.join(REPO, name)),
                            "TREE_CONTENTS의 %s가 레포에 없다" % name)


class ScanBehaviourTest(unittest.TestCase):
    """스캐너 자체가 정직한가 — 정상·부정·경계."""

    def test_finds_a_simple_reference(self):
        source = 'import os\np = os.path.join(REPO, "plugins", "lnpl")\n'
        self.assertEqual(repo_relative_roots(source), {"plugins"})

    def test_finds_multiple_distinct_roots(self):
        source = ('import os\n'
                  'a = os.path.join(REPO, "examples", "x.lnpl")\n'
                  'b = os.path.join(REPO, "scripts", "y.py")\n')
        self.assertEqual(repo_relative_roots(source), {"examples", "scripts"})

    def test_ignores_joins_not_rooted_at_repo(self):
        source = 'import os\np = os.path.join(OTHER, "plugins")\n'
        self.assertEqual(repo_relative_roots(source), set())

    def test_ignores_a_non_literal_first_segment(self):
        # os.path.join(REPO, name) 처럼 변수인 경우는 정적으로 알 수 없다.
        source = 'import os\np = os.path.join(REPO, name, "x")\n'
        self.assertEqual(repo_relative_roots(source), set())

    def test_ignores_a_bare_repo_join(self):
        source = 'import os\np = os.path.join(REPO)\n'
        self.assertEqual(repo_relative_roots(source), set())

    def test_finds_a_pathlib_reference(self):
        # test_packaging.py의 표기. 이걸 놓쳐서 pyproject.toml이 빠졌다.
        source = 'import pathlib\np = ROOT / "pyproject.toml"\n'
        self.assertEqual(repo_relative_roots(source), {"pyproject.toml"})

    def test_finds_a_pathlib_reference_rooted_at_repo(self):
        source = 'p = REPO / "AGENTS.md"\n'
        self.assertEqual(repo_relative_roots(source), {"AGENTS.md"})

    def test_ignores_division_that_is_not_a_path(self):
        self.assertEqual(repo_relative_roots("x = total / count\n"), set())

    def test_ignores_pathlib_rooted_at_something_else(self):
        self.assertEqual(repo_relative_roots('p = OTHER / "x.toml"\n'), set())

    def test_empty_source_finds_nothing(self):
        self.assertEqual(repo_relative_roots(""), set())

    def test_syntax_error_is_raised_not_swallowed(self):
        with self.assertRaises(SyntaxError):
            repo_relative_roots("def f(:\n")


if __name__ == "__main__":
    unittest.main()
