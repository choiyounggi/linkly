"""`scripts/mutation_scope_select.py`의 선별 로직 단언 (issue #166).

`select()`만 직접 호출한다 — `main()`을 실제 파일로 부르면 25분+ 걸리는
진짜 뮤테이션 하네스가 돈다. 여기서는 그 경로를 절대 타지 않는다.
"""
import importlib.util
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(REPO, "scripts", "mutation_scope_select.py")

_spec = importlib.util.spec_from_file_location("mutation_scope_select", SCRIPT_PATH)
mutation_scope_select = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutation_scope_select)

FAKE_MUTATIONS = [
    ("l1", "lnpl/a.py", "x", "y"),
    ("l2", "lnpl/b.py", "x", "y"),
]


class SelectNormalTest(unittest.TestCase):
    """정상 케이스: 변경 파일과 앵커가 교차하는 항목만 남는다."""

    def test_select_returns_matching_mutation_only(self):
        result = mutation_scope_select.select(["impl/lnpl/a.py"], FAKE_MUTATIONS)
        self.assertEqual(result, [FAKE_MUTATIONS[0]])


class SelectBoundaryTest(unittest.TestCase):
    """경계값 케이스: 빈 변경 파일 목록은 빈 결과를 낸다."""

    def test_select_empty_changed_files_returns_empty(self):
        result = mutation_scope_select.select([], FAKE_MUTATIONS)
        self.assertEqual(result, [])


class SelectNoMatchTest(unittest.TestCase):
    """에러/경계값 케이스: 앵커에 없는 파일만 바뀌면 아무것도 선택되지 않는다."""

    def test_select_unrelated_file_returns_empty(self):
        result = mutation_scope_select.select(["impl/lnpl/nope.py"], FAKE_MUTATIONS)
        self.assertEqual(result, [])


class MainEmptyArgvTest(unittest.TestCase):
    """정상 케이스: 인자 없이 main()을 부르면 하네스를 import/실행하지 않고 스킵한다."""

    def test_main_no_args_skips_without_importing_harness(self):
        sys.modules.pop("tests.mutation_check", None)
        rc = mutation_scope_select.main([])
        self.assertEqual(rc, 0)
        self.assertNotIn("tests.mutation_check", sys.modules)


if __name__ == "__main__":
    unittest.main()
