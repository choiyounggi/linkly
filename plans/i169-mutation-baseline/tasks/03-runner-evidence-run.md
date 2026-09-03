# Task 03: 러너에서 실측해 baseline RED의 실패 집합을 확정한다

## Objective
Task 01+02가 랜딩된 ref에서 mutation-weekly 잡을 workflow_dispatch로 실행해, hosted 러너의 baseline 실패 테스트 목록(진단 출력)을 `plans/i169-mutation-baseline/runner-evidence.md`에 기록한다. 이 태스크는 수정하지 않는다 — 증거 수집이 산출물이다.

## Wiki pages (read these first, only these)
- wiki/debugging/methodology/reproduce-first.md — use for: 수정 전 재현 우선 원칙
- wiki/debugging/methodology/probe-path-vs-operation-path.md — use for: 운영 경로 그 자체로 관측해야 하는 이유

## Inputs
- Task 01 산출물: 진단이 표면화된 impl/tests/mutation_check.py
- Task 02 산출물: workflow_dispatch가 추가된 .github/workflows/mutation.yml
- Decisions that bind you: D4, D5, D7

## Steps
1. 브랜치 `fix/i169-mutation-baseline-red`에 Task 01+02 커밋, push, PR 생성 (main 브랜치 보호 — 직접 push 금지).
2. `gh workflow run "Mutation testing" --ref fix/i169-mutation-baseline-red` 실행. 422("workflow_dispatch 트리거 없음")로 거부되면: PR의 required check green 확인 후 먼저 merge하고 main에서 dispatch (mutation 잡은 required check가 아님 — D7).
3. `gh run watch` 또는 폴링으로 완료 대기(최대 45분 timeout). baseline이 이번에도 RED면 잡은 fail-closed로 실패하는 것이 정상 — 실패 자체가 아니라 로그의 진단 출력이 산출물.
4. `gh run view <id> --log`에서 "Run full mutation matrix" 스텝의 tail-40 출력(FAIL:/ERROR: 줄 포함)을 추출해 `plans/i169-mutation-baseline/runner-evidence.md`에 기록: 실행 ref/sha, run URL, baseline 판정, 실패 테스트 전체 목록, 관찰된 패턴(예: 전부 mode-B 모듈인지).
5. 실패 집합이 비어 있고 baseline GREEN이면(환경이 그새 바뀐 경우) 그 사실을 기록 — 수용 기준 R3 충족 여부를 판정해 보고.

## Deliverables
- plans/i169-mutation-baseline/runner-evidence.md (신규)
- 브랜치 + PR (Task 01+02 포함)

## Verify
- runner-evidence.md에 run URL과 baseline 판정, (RED인 경우) 실패 테스트 이름 1개 이상이 기록되어 있다 — 체크리스트 검증
- covers: R3 (관측 절차 확립; green 판정 자체는 수정 라운드 후 재실행에서)

## Out of scope
- 실패 원인 수정 — 증거 확정 후 wiki-plan Phase B/C repair 라운드(Task 04+)에서 결정한다 (D6)
