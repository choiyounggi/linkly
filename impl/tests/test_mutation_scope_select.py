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


class MainEmptySelectionTest(unittest.TestCase):
    """경계 케이스: 변경 파일은 있으나 교차 앵커가 0건이면 하네스의 main()을
    호출하지 않고 rc=0으로 스킵한다 — 판정 대상이 없는데 baseline(전체
    스위트)을 돌리는 것은 낭비이고, 러너 환경의 무관한 red를 PR에 뒤집어
    씌운다(PR #167 실측)."""

    def test_main_zero_intersection_skips_the_harness(self):
        import tests.mutation_check as mc
        original_main = mc.main

        def _must_not_run():
            raise AssertionError("harness main() must not run on empty selection")

        mc.main = _must_not_run
        try:
            rc = mutation_scope_select.main(
                ["rfcs/0001-semantic-ir.md"])  # 어떤 뮤테이션 앵커와도 교차하지 않는 실존 파일
            self.assertEqual(rc, 0)
        finally:
            mc.main = original_main


if __name__ == "__main__":
    unittest.main()
