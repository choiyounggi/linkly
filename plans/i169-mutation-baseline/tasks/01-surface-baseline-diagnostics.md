# Task 01: baseline/no-op RED 시 스위트 실패 출력을 표면화한다

## Objective
`impl/tests/mutation_check.py`가 baseline 또는 no-op 컨트롤에서 GREEN이 아닌 판정을 낼 때, 그 판정을 만든 스위트 실행의 실패 증거(unittest의 FAIL:/ERROR: 줄 전부 + 출력 말미 tail 80줄)를 stdout에 인쇄한다. 지금은 "baseline (unmutated copy) is not green (RED)" 한 줄뿐이다(run 33663504271 실측).

## Wiki pages (read these first, only these)
- wiki/testing/quality/harness-reverse-controls.md — use for: no-op 컨트롤 실패 경로도 같은 진단을 받아야 하는 이유(컨트롤 실패는 하네스 자체 고장 신호)
- wiki/testing/strategy/failing-test-first.md — use for: 테스트를 먼저 Red로 작성하는 순서

## Inputs
- impl/tests/mutation_check.py — run_suite(398-478행 부근: VENV_PY/PYTHON/run_suite/apply_and_run/main)
- Decisions that bind you: D1 (튜플 반환 + FAIL:/ERROR: 요약 + tail 80줄), D8 (stdout 직접 인쇄; mutation_report.py 파서 형식 `- <label> [SURVIVED — ...]` 류와 충돌하는 줄을 만들지 말 것)

## Steps
1. `impl/tests/test_mutation_diagnostics.py` 신규 작성 (Red 먼저). `PYTHONPATH=impl` 기준 `import tests.mutation_check as mc`. 케이스:
   - 정상: `mc.failure_summary("...FAIL: test_x (m.C)...\n<80줄 이상>\nFAILED (failures=1)")` → 반환 문자열에 "FAIL: test_x" 포함, 줄 수 ≤ (FAIL/ERROR 줄 수 + 80 + 헤더 몇 줄) 상한 단정
   - 경계값: 빈 출력 `mc.failure_summary("")` → 빈 문자열 또는 "(no output captured)" 류의 명시 문자열 (예외 없이)
   - 에러 경로(main): `unittest.mock.patch`로 `mc.make_tree`를 no-op, `mc.run_suite`가 `("RED", "FAIL: test_y (tests.test_z)\n...\nFAILED (failures=1)")`을 반환하게 하고 `mc.main()` 실행 → rc 1, stdout에 "baseline (unmutated copy) is not green"과 "FAIL: test_y" 둘 다 포함
   - 파서 무간섭: 위 stdout을 `scripts/mutation_report.py`의 `parse()`에 넣어 survived/stale/hang 전부 빈 리스트 단정
2. `impl/tests/mutation_check.py` 수정:
   - `failure_summary(output: str) -> str` 모듈 함수 신설: 입력에서 `FAIL: `/`ERROR: `로 시작하는 줄 전부 + 마지막 80줄을 합쳐 중복 제거 없이 반환(두 구간이 겹치면 tail만으로 충분한 경우 그대로 허용), 빈 입력이면 "(no output captured)" 반환
   - `run_suite`가 `(verdict, output)` 튜플을 반환하도록 변경 (output = proc.stdout + proc.stderr; TimeoutExpired 경로는 `("HANG", <포집 가능한 부분 출력 또는 빈 문자열>)`)
   - 내부 호출부 동조: `apply_and_run`의 `return run_suite(root), ""` → verdict만 꺼내 기존 계약 유지; `main()`의 baseline·no-op 경로에서 비GREEN이면 기존 메시지 인쇄 직후 `print(failure_summary(output))`
3. 기존 4개 mutation 테스트 모듈 + 신규 모듈 실행으로 Green 확인.

## Deliverables
- impl/tests/mutation_check.py (수정)
- impl/tests/test_mutation_diagnostics.py (신규)

## Verify
- PYTHONPATH=impl .venv/bin/python -m unittest tests.test_mutation_diagnostics tests.test_mutation_tree tests.test_mutation_scope_select tests.test_mutation_workflow tests.test_mutation_report -q → rc 0
- covers: R1, R4

## Out of scope
- mutation.yml 변경 (Task 02), 러너 실측·원인 수정 (Task 03+)
- MUTATIONS 앵커·TREE_CONTENTS·mc.main()/mc.MUTATIONS 외부 계약 변경 금지
