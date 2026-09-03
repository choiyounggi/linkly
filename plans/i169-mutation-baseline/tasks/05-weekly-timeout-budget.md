# Task 05: weekly 잡의 시간 예산을 실측 기반으로 상향한다

## Objective
mutation-weekly 잡이 full matrix(~110분 실측 규모)를 완주할 수 있다: timeout-minutes 45→180. mutation-pr 잡의 20분 예산은 불변. 재-dispatch에서 잡이 타임아웃 없이 종료하고 baseline GREEN이 직접 관측된다.

## Wiki pages (read these first, only these)
- wiki/infrastructure/ci-cd/pipeline-structure.md — use for: 예산 변경이 잡 구조·fail-closed 배선을 건드리지 않게
- wiki/debugging/methodology/verify-the-fix.md — use for: 같은 경로 재실행으로 검증

## Inputs
- runner-evidence.md "재-dispatch 결과" — 타임아웃 실측 근거
- Decisions that bind you: D10, D5, D6

## Steps
1. Red: test_mutation_workflow.py에 `WeeklyTimeoutBudgetTest` 추가 — weekly 블록에 `timeout-minutes: 180` 존재 단정(정상), mutation-pr 블록은 `timeout-minutes: 20` 유지 단정(경계/회귀).
2. mutation.yml의 mutation-weekly `timeout-minutes: 45` → `180` (그 외 불변).
3. Green 확인, 커밋·push, `gh workflow run "Mutation testing" --ref fix/i169-mutation-baseline-red` 재실행, 완주 관측 → runner-evidence.md 추기.

## Deliverables
- .github/workflows/mutation.yml (1줄)
- impl/tests/test_mutation_workflow.py (테스트 클래스 1개)
- plans/i169-mutation-baseline/runner-evidence.md (최종 런 결과 추기)

## Verify
- PYTHONPATH=impl .venv/bin/python -m unittest tests.test_mutation_workflow -q → rc 0
- 재-dispatch run: 잡 conclusion이 cancelled가 아니고, 로그에 "baseline (unmutated copy): GREEN" 직접 관측
- covers: R3

## Out of scope
- 매트릭스 샤딩·테스트 선별 등 하네스 성능 개선
- 새로 드러나는 mutant 판정(SURVIVED 등) 대응 — 주간 리포트 경로의 정상 업무
