# i169-mutation-baseline

Goal: mutation 하네스 baseline이 GitHub hosted 러너에서 RED가 되는 환경 불일치를 해소한다 (issue #169).
수용 기준: (1) baseline/no-op RED 시 하네스가 실패 증거를 인쇄, (2) full-matrix 잡을 workflow_dispatch로 수동 실행 가능, (3) hosted 러너에서 baseline green + full-matrix 잡 1회 green 관측.
Stack: Python 3.13 (unittest), GitHub Actions (ubuntu-latest), bash. 하네스: impl/tests/mutation_check.py.

## Decisions
| # | Decision | Choice | Wiki basis |
|---|----------|--------|------------|
| D1 | 진단 표면화 | run_suite → (verdict, output) 반환; baseline·no-op 비GREEN 시 FAIL:/ERROR: 요약 + tail 80줄 인쇄 | [no-wiki] |
| D2 | 수동 트리거 | mutation.yml on:에 workflow_dispatch 추가, weekly if를 schedule-또는-workflow_dispatch로 확장 | wiki/infrastructure/ci-cd/pipeline-structure.md |
| D3 | 트리거 검증 | test_mutation_workflow.py 소스 텍스트 단정 추가 | wiki/testing/quality/source-text-wiring-assertions.md |
| D4 | 원인 확정 | 러너 실측(dispatch) 전 수정 금지 | wiki/debugging/methodology/reproduce-first.md |
| D5 | 프로브 충실도 | 검증은 운영 경로(mutation-weekly 잡) 그 자체로 | wiki/debugging/methodology/probe-path-vs-operation-path.md |
| D6 | 완료 판정 | 실측 후 수정은 Phase B/C repair로 재계획; dispatch full-matrix 1회 green이 수용 기준 | wiki/debugging/methodology/verify-the-fix.md |
| D7 | 이 PR의 mutation-pr | zero-anchor 스킵(#168) — 의도된 동작 | wiki/infrastructure/ci-cd/changed-files-only-gates.md |
| D8 | 진단 출력 위치 | 하네스 stdout 직접 (mutation_report.py 파서와 충돌 없음 실측) | wiki/testing/quality/harness-reverse-controls.md |

## Size verdict
size: small

## Task order
| Task | Depends on | Parallel-ok |
|------|------------|-------------|
| 01-surface-baseline-diagnostics | — | parallel-ok (02와 파일 비중첩) |
| 02-workflow-dispatch-trigger | — | parallel-ok (01과 파일 비중첩) |
| 03-runner-evidence-run | 01, 02 | — |
| 04-restore-env-in-tests | 03 | — |

Task 03이 실패 집합을 확정하면, 수정 태스크(04+)는 wiki-plan Phase B/C repair 라운드에서 그 증거로 결정한다 (D4/D6 — 방치가 아니라 설계된 2단계). Repair round 1 (2026-09-03): 원인 = TestLlvmBinOverride의 LNPL_LLVM_BIN 미복원 → D9, Task 04.
