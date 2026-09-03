# Design — i169-mutation-baseline

## Decisions
| # | Decision | Choice | Wiki basis | Rejected alternative | Testability |
|---|----------|--------|------------|----------------------|-------------|
| D1 | baseline/no-op RED 진단 표면화 | run_suite가 (verdict, output) 튜플을 반환하도록 변경; main()은 baseline·no-op 비GREEN 시 스위트 출력의 FAIL:/ERROR: 요약줄 전부 + 말미 tail 80줄을 stdout에 인쇄. apply_and_run 내부 호출부 동조 수정. 외부 계약(mc.main()/mc.MUTATIONS/TREE_CONTENTS)은 불변 — run_suite는 이 저장소 내부에서만 호출됨(grep 실측: 소비자 0) | [no-wiki] | 모듈 전역에 마지막 출력 stash — 암묵 상태는 테스트·재사용 모두 나쁨 | tests.test_mutation_check 신규: baseline RED 픽스처에서 stdout에 FAIL: 줄 포함 단정 (R1) |
| D2 | full-matrix 수동 트리거 | mutation.yml on:에 workflow_dispatch 추가, mutation-weekly 잡 if를 schedule-또는-workflow_dispatch 조건으로 확장; mutation-pr 잡 if(pull_request)는 불변 | wiki/infrastructure/ci-cd/pipeline-structure.md | 별도 디버그 워크플로 신설 — 운영 경로와 다른 경로를 검증하게 됨 | tests.test_mutation_workflow 신규: 소스 텍스트에 workflow_dispatch 존재 + weekly if가 dispatch 포함 단정 (R2) |
| D3 | 트리거 변경 검증 방식 | test_mutation_workflow.py의 기존 소스 텍스트 계약 스타일 그대로 단정 추가 (파일 파싱, 실행 아님) | wiki/testing/quality/source-text-wiring-assertions.md | workflow를 실제 실행해 검증 — CI 왕복 필요, 단위 테스트 불가 | 추가된 테스트 자체가 rc로 검증 |
| D4 | RED 원인 확정 절차 | 수정 착수 전 러너 실측 필수: T1+T2 랜딩된 브랜치에서 gh workflow run "Mutation testing" --ref로 full-matrix 실행 → D1 진단 출력으로 실패 집합 확정. macOS 스파이크는 CI-충실 조건에서 green이므로(analysis.md Spikes) 로컬 추정으로 수정하지 않는다 | wiki/debugging/methodology/reproduce-first.md | 유력 후보(mode-B unskip 무리)를 추정 수정 — 오진 시 무의미한 변경이 main에 쌓임 | dispatch 런 로그에 실패 테스트 이름이 찍히는지 (R1×R3) |
| D5 | 프로브 경로 충실도 | 진단·검증 모두 운영 경로 그 자체(mutation-weekly 잡, workflow_dispatch 이벤트)로 수행 — 별도 축소 재현 잡을 만들지 않음 | wiki/debugging/methodology/probe-path-vs-operation-path.md | ubuntu docker 로컬 재현 — 러너 이미지·PATH·툴체인 구성이 달라 스파이크 충실도 결함 재발 | dispatch 런이 mutation-weekly 잡 이름으로 실행됐는지 런 로그로 확인 |
| D6 | 수정 완료 판정 | 실패 집합 확정 후의 수정은 wiki-plan Phase B/C repair 라운드로 결정하고(이 문서 개정), 같은 dispatch 경로 full-matrix 1회 green이 수용 기준 (issue #169 수용 기준 그대로) | wiki/debugging/methodology/verify-the-fix.md | 이 라운드에서 수정 내용까지 선결정 — 근거 없는 결정은 rule zero 위반이 아니라 오히려 추측 | dispatch 런 green + baseline (unmutated copy): GREEN 출력 (R3) |
| D7 | 이 PR 자체의 mutation-pr 잡 | 변경 파일(mutation_check.py·mutation.yml·테스트)은 앵커 파일이 아니므로 zero-anchor 스킵(#168) 경로 — 의도된 동작으로 수용 | wiki/infrastructure/ci-cd/changed-files-only-gates.md | 이 PR에서 mutation-pr로 baseline 검증 시도 — 스킵되므로 불가능, dispatch가 유일 경로 | scripts/mutation_scope_select.py 수동 실행 → "no anchor intersects" (Constraints에 실측 기록) |
| D8 | 진단 출력의 위치 | 하네스 stdout에 직접 인쇄 (mutation_report.py 파서 통과 확인 필수 — rc=1 baseline 경로는 이미 harness-integrity fault로 처리되므로 추가 줄은 verdict 파싱에 영향 없음을 T1에서 테스트로 고정) | wiki/testing/quality/harness-reverse-controls.md | 별도 로그 파일로 빼기 — CI 로그에서 한 번에 안 보임, 아티팩트 업로드 단계 추가 필요 | tests.test_mutation_report 기존 + T1 신규 테스트 rc=0 (R4) |

## Repair round 1 (Task 03 증거 기반 — D6의 계획된 재진입, 2026-09-03)
| # | Decision | Choice | Wiki basis | Rejected alternative | Testability |
|---|----------|--------|------------|----------------------|-------------|
| D9 | baseline RED 원인 수정 | TestLlvmBinOverride(impl/tests/test_backend.py)가 setUp에서 LNPL_LLVM_BIN 원래 값을 저장하고 tearDown에서 조건부 복원하도록 수정 (pop 무조건 삭제 → 저장·복원). 같은 오염 패턴(os.environ 직접 변이 후 미복원)을 impl/tests 전체에서 스윕해 동일 수리 | wiki/testing/data/test-data-and-isolation.md | CI에서 mode-B 무리를 격리 실행(모듈별 프로세스 분리) — 오염을 고치지 않고 우회하는 것, 로컬 전체 스위트에도 같은 잠복 결함이 남음 | 신규 회귀 테스트: 센티널 LNPL_LLVM_BIN 설정 → TestLlvmBinOverride 프로그램 실행 → env가 센티널로 복원됨 단정; 최종 판정은 재-dispatch full-matrix (R3) |

## Repair round 2 (재-dispatch 실측 기반 — 2026-09-03)
| # | Decision | Choice | Wiki basis | Rejected alternative | Testability |
|---|----------|--------|------------|----------------------|-------------|
| D10 | weekly 잡 시간 예산 | mutation-weekly의 timeout-minutes를 45→180으로 상향 (실측: 뮤테이션당 트리복사+스위트 ~85-90초 × 77 ≈ 110분 + baseline·컨트롤·셋업, 1.5x 마진). mutation-pr(diff-scoped, 20분)은 불변 | wiki/infrastructure/ci-cd/pipeline-structure.md | 매트릭스 샤딩/테스트 선별 — 하네스 구조 변경으로 범위 초과, 주간 1회 잡에 110분은 수용 가능한 비용 | test_mutation_workflow에 weekly 블록 timeout-minutes: 180 소스 텍스트 단정; 최종은 재-dispatch green (R3) |

## Repair round 3 (full-matrix 완주 실측 기반 — 2026-09-03)
| # | Decision | Choice | Wiki basis | Rejected alternative | Testability |
|---|----------|--------|------------|----------------------|-------------|
| D11 | stale anchor 4건 재고정 | run 33705681024 실측: 73/77 caught, 4건 [stale anchor] — 로컬 대조로 main 코드 드리프트임을 확인(러너 특이 아님). MUTATIONS의 4개 튜플을 현재 코드의 리터럴 텍스트로 재고정하되 각 뮤테이션의 의미(테스트하는 규칙)는 보존; 재고정 후 4건 각각을 apply_and_run 직접 실행으로 caught(RED) 검증 | wiki/testing/quality/harness-reverse-controls.md | 4건을 MUTATIONS에서 삭제 — 그 규칙들의 뮤테이션 커버리지가 사라짐, fail-closed가 잡은 진짜 드리프트를 지우는 것 | 로컬 apply_and_run 4건 RED + 최종 dispatch full-matrix green (R3) |

## Review
VERDICT: PASS
FINDINGS:
- [D1] Wiki basis `[no-wiki]` — advisory: `wiki/testing/quality/harness-reverse-controls.md`가 인접 영역을 다루나, `[no-wiki]`는 허용값이고 근거는 코드 직접 확인으로 검증됨 (advisory)
- [R1-R4] 네 Requirements 전부 Decision 커버 확인 (R1→D1, R2→D2, R3→D4/D6, R4→D8)
- [D2-D8] non-`[no-wiki]` 위키 경로 7건 전부 실재 확인
- [D1/D8] mutation_report.py 파서 정규식이 unittest FAIL:/ERROR: 줄과 충돌 불가, rc=1 무설명 경로는 기존 HARNESS-INTEGRITY FAULT로 수렴 — 주장 성립 확인
- [D1] run_suite 외부 소비자 0건 grep 확인
- [D2/D3] mutation.yml 현재 트리거·if·워크플로 name("Mutation testing") 실측 일치; 기존 소스 텍스트 테스트와 충돌 없음
- Constraints: 앵커 불변·브랜치 보호 위반 없음; 각 Rejected alternative 실질적 사유 확인
SUMMARY: 요구 커버리지·위키 근거·핵심 사실 주장 전부 코드 대조로 확인, blocking 없음. PASS.
