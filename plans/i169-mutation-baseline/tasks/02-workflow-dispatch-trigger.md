# Task 02: mutation.yml에 workflow_dispatch 트리거를 추가한다

## Objective
`gh workflow run "Mutation testing" --ref <branch>`로 mutation-weekly(full-matrix) 잡을 수동 실행할 수 있다. mutation-pr 잡의 동작은 불변.

## Wiki pages (read these first, only these)
- wiki/infrastructure/ci-cd/pipeline-structure.md — use for: 트리거 추가가 잡 구조를 바꾸지 않게 하는 원칙
- wiki/testing/quality/source-text-wiring-assertions.md — use for: 워크플로 소스 텍스트 단정 스타일

## Inputs
- .github/workflows/mutation.yml (on: pull_request + schedule; mutation-weekly if: github.event_name == 'schedule')
- impl/tests/test_mutation_workflow.py (기존 소스 텍스트 계약 테스트)
- Decisions that bind you: D2, D3

## Steps
1. `impl/tests/test_mutation_workflow.py`에 테스트 클래스 `DispatchTriggerTest` 추가 (Red 먼저):
   - 정상: mutation.yml 텍스트에 `workflow_dispatch:` 존재 단정
   - 정상: mutation-weekly 잡 블록의 if 줄에 `schedule`과 `workflow_dispatch` 둘 다 포함 단정 (기존 `_job_block` 패턴 재사용 — 클래스 내 동일 헬퍼 복사 허용)
   - 경계값/회귀: mutation-pr 잡 블록의 if 줄은 `pull_request`만 참조하고 `workflow_dispatch`를 포함하지 않음 단정 (dispatch가 PR 잡을 깨우면 diff 없는 이벤트에서 base.sha 참조가 깨진다)
2. `.github/workflows/mutation.yml` 수정:
   - `on:` 블록에 `workflow_dispatch:` 추가 (schedule 아래, 빈 값)
   - mutation-weekly의 `if: github.event_name == 'schedule'` → `if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'`
   - 그 외 어떤 줄도 변경 금지 (continue-on-error 부재, rc 캡처 배선, 툴체인 순서 등 기존 계약 보존)
3. 테스트 Green 확인.

## Deliverables
- .github/workflows/mutation.yml (수정)
- impl/tests/test_mutation_workflow.py (수정)

## Verify
- PYTHONPATH=impl .venv/bin/python -m unittest tests.test_mutation_workflow -q → rc 0
- covers: R2, R4

## Out of scope
- 하네스 파이썬 코드 (Task 01), dispatch 실행·관측 (Task 03)
- weekly 잡의 report/issue 갱신 단계 변경 금지 (dispatch 실행도 같은 경로를 그대로 탄다 — D5)
