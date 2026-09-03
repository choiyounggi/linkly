"""baseline/no-op RED 시 하네스가 실패 증거를 인쇄하는지의 계약 (issue #169).

GitHub hosted 러너에서 baseline이 RED였을 때 잡 로그에 남은 것은
"baseline (unmutated copy) is not green (RED)" 한 줄뿐이었다(run 33663504271
실측) — `run_suite`가 `capture_output=True`로 받은 스위트 출력을 버렸기
때문이다. 이 모듈은 그 출력이 stdout으로 표면화되는 것을 고정한다:
FAIL:/ERROR: 요약 줄 전부 + 출력 말미 tail. 동시에 그 진단 줄들이
`scripts/mutation_report.py`의 verdict 파서와 충돌하지 않는 것도 고정한다
(파서 정규식은 `- <label> [SURVIVED — ...]` 꼴만 집는다).
"""
import contextlib
import importlib.util
import io
import os
import unittest
from unittest import mock

import tests.mutation_check as mc

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REPORT_PATH = os.path.join(REPO, "scripts", "mutation_report.py")
_spec = importlib.util.spec_from_file_location("mutation_report", _REPORT_PATH)
mutation_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutation_report)

TAIL_LINES = 80

# unittest가 실제로 찍는 모양을 본뜬 픽스처: FAIL 줄은 tail 밖(앞쪽)에,
# 말미 요약은 tail 안에 있어야 두 수집 경로가 모두 검증된다.
FIXTURE_OUTPUT = "\n".join(
    ["FAIL: test_x (tests.test_backend.BackendTest.test_x)"]
    + ["ERROR: test_e (tests.test_golden.GoldenTest.test_e)"]
    + ["filler line %d" % i for i in range(200)]
    + ["FAILED (failures=1, errors=1)"]
)


class FailureSummaryTest(unittest.TestCase):
    """정상 케이스: FAIL:/ERROR: 줄과 말미 tail이 모두 요약에 들어간다."""

    def test_collects_fail_lines_outside_the_tail(self):
        summary = mc.failure_summary(FIXTURE_OUTPUT)
        self.assertIn("FAIL: test_x", summary)
        self.assertIn("ERROR: test_e", summary)

    def test_keeps_the_final_unittest_verdict_line(self):
        summary = mc.failure_summary(FIXTURE_OUTPUT)
        self.assertIn("FAILED (failures=1, errors=1)", summary)

    def test_output_is_bounded(self):
        # FAIL/ERROR 2줄 + tail 80줄 + 구분선 몇 줄을 넘으면 안 된다 — 진단이
        # CI 로그를 다시 삼켜버리는 역전을 막는 상한.
        summary = mc.failure_summary(FIXTURE_OUTPUT)
        self.assertLessEqual(len(summary.splitlines()), 2 + TAIL_LINES + 2)

    def test_empty_output_is_an_explicit_marker(self):
        # 경계값: 출력이 아예 없으면(HANG의 부분 포집 실패 등) 빈 문자열이
        # 아니라 명시 문구를 돌려줘야 로그에서 "요약이 안 찍혔다"와 구분된다.
        self.assertEqual(mc.failure_summary(""), "(no output captured)")
        self.assertEqual(mc.failure_summary("   \n  "), "(no output captured)")


class BaselineRedSurfacesDiagnosticsTest(unittest.TestCase):
    """에러 경로: baseline RED면 rc 1과 함께 실패 증거가 stdout에 찍힌다."""

    def _run_main_with_red_baseline(self):
        buf = io.StringIO()
        with mock.patch.object(mc, "make_tree", lambda dest: dest), \
             mock.patch.object(mc, "run_suite",
                               lambda root: ("RED", FIXTURE_OUTPUT)), \
             contextlib.redirect_stdout(buf):
            rc = mc.main()
        return rc, buf.getvalue()

    def test_rc_stays_1_and_fail_lines_reach_stdout(self):
        rc, out = self._run_main_with_red_baseline()
        self.assertEqual(rc, 1)
        self.assertIn("baseline (unmutated copy) is not green", out)
        self.assertIn("FAIL: test_x", out)
        self.assertIn("FAILED (failures=1, errors=1)", out)

    def test_diagnostics_do_not_leak_into_the_report_parser(self):
        # 진단 줄이 mutation_report.py의 SURVIVED/stale/hang 버킷으로 오파싱되면
        # 주간 잡의 fail-closed 판정이 뒤집힌다 — 전부 비어 있어야 한다.
        _, out = self._run_main_with_red_baseline()
        result = mutation_report.parse(out)
        self.assertEqual(result["survived"], [])
        self.assertEqual(result["stale"], [])
        self.assertEqual(result["hang"], [])


class NoopControlRedSurfacesDiagnosticsTest(unittest.TestCase):
    """에러 경로: no-op 컨트롤이 RED로 잡히면(하네스 고장 신호) 그 스위트
    출력도 같은 요약으로 찍힌다."""

    def test_control_failure_prints_the_suite_output(self):
        buf = io.StringIO()
        with mock.patch.object(mc, "make_tree", lambda dest: dest), \
             mock.patch.object(mc, "run_suite", lambda root: ("GREEN", "")), \
             mock.patch.object(mc, "apply_and_run",
                               lambda *a: ("RED", "", FIXTURE_OUTPUT)), \
             contextlib.redirect_stdout(buf):
            rc = mc.main()
        out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("no-op control did not survive", out)
        self.assertIn("FAIL: test_x", out)


if __name__ == "__main__":
    unittest.main()
