# Runner evidence — i169 baseline RED (Task 03 산출물)

- 실행: workflow_dispatch, ref fix/i169-mutation-baseline-red (d8dbd9c)
- Run: https://github.com/choiyounggi/linkly/actions/runs/33701577052 (mutation-weekly 잡 — 운영 경로 그 자체, D5)
- baseline 판정: RED
- 실측: `Ran 3783 tests in 78.232s` / `FAILED (failures=26, errors=96, skipped=3)` — Task 01의 failure_summary가 표면화 (수정 전에는 verdict 한 줄뿐이었음)

## 로그에 보인 실패 (tail-40 창 안)
- `tests.test_repo_state.TestModeBToolchainIsRequired` 계열: "issue #35 regression cannot run: the MLIR/LLVM toolchain is missing" — **mutant 스위트 프로세스 안에서 `backend.toolchain_available()`가 False**
- `tests.test_repo_state.TestUnreproducibleRowsAreRefusedNotCompared.test_a_row_that_differs_from_the_payload_is_refused`: 'stock' not found in 'mode B toolchain unavailable — cannot compare...'
- `tests.test_repo_state.TestUnreproducibleRowsAreRefusedNotCompared.test_the_refusal_says_it_is_not_a_divergence`: 'reproduce' not found in 같은 메시지

## 교차 사실 (동일 브랜치, 동일 러너 세대)
- 잡의 LLVM 22 설치(clang-22·mlir-22-tools·libmlir-22-dev) 성공, 하네스 스텝 env에 `LNPL_LLVM_BIN: /usr/lib/llvm-22/bin` 존재 — 로그 실측
- PR #170 체크 전부 green, 특히 **modeb-linux(실제 체크아웃 + 같은 툴체인, test_repo_state만) pass** — 툴체인 해석 자체는 러너에서 동작

## 원인 판정 (코드 대조)
`impl/tests/test_backend.py:568` `TestLlvmBinOverride`:
- setUp은 `LNPL_LLVM_BIN`의 원래 값을 저장하지 않고, tearDown이 `os.environ.pop("LNPL_LLVM_BIN", None)`으로 **무조건 삭제** (587행)
- 러너에서는 툴체인이 오직 이 env로만 해석됨(브루 경로 없음, PATH에 mlir-opt 없음) → test_backend 이후에 도는 모든 mode-B 테스트가 unavailable로 실패 (26F+96E=122 ≈ mode-B 의존 테스트 무리)
- macOS에서는 `BREW_LLVM_BIN` 폴백·PATH가 가려서 비가시 — 스파이크가 green이었던 이유
- modeb-linux는 단일 모듈 실행이라 오염원이 함께 돌지 않음 — green이었던 이유

## Task 04 스윕 (os.environ 직접 변이 전수, grep 절단 없음 — 2026-09-03)
| 파일 | 사이트 | 판정 |
|------|--------|------|
| test_backend.py TestLlvmBinOverride | tearDown pop 무조건 삭제 | **결함 — 수리함** (저장·조건부 복원) |
| test_backend.py TestLlvmBinOverrideRestoresCallerEnv | addCleanup 조건부 복원 (신규 회귀 테스트) | 정상 |
| test_cli_backend.py set_env / test_cli_capability_http.py set_env·:271 | previous 저장 → addCleanup 조건부 복원 | 정상 |
| test_cli_config.py(2클래스)·test_config.py | dict(os.environ) 전체 백업 → clear+update 복원 | 정상 |
| test_jwt_issuer.py:199-203 · test_serve_backend.py:380-383 | previous 조건부 복원 | 정상 |
| test_wsgi.py:119-127 | 키 집합 저장·복원 | 정상 |
| test_kb_packs.py:413-416 · test_ops_surface.py:168-169 · test_wsgi.py:158·225 | addCleanup pop-only — 단 대상이 테스트 전용 픽스처 이름(LNPL_KB_PACK_FIXTURE_*, LNPL_TEST_*)으로 러너/사용자/스위트 내 다른 소비자가 설정·판독하지 않음 | 제외 (오염 벡터 아님, 근거 명시) |

## 재-dispatch 결과 (Task 04 이후, run 33702421111)
- https://github.com/choiyounggi/linkly/actions/runs/33702421111 — conclusion: cancelled (잡 timeout-minutes: 45, 01:08:12→01:53:31)
- 재-dispatch baseline 간접 판정: GREEN — RED baseline은 직전 런에서 81초 만에 rc=1로 종료했는데(00:56:49→00:58:10), 이번 하네스 스텝은 43분간 실행됨 = baseline·no-op 게이트를 통과해 full matrix에 진입한 유일한 경로. 직접 출력은 타임아웃 취소로 유실(출력이 파일로 리다이렉트되고 tail 스텝이 건너뜀) — 직접 관측은 다음 런에서.
- **새 결함 (repair round 2 대상)**: full matrix는 러너에서 77뮤테이션 × (트리 복사 + 스위트 ~78s) ≈ 110분 규모 — timeout-minutes: 45로는 구조적으로 불가능. 주간 잡은 baseline RED를 고쳐도 타임아웃으로 실패했을 것.

## 최종 dispatch (Task 06 이후, run 33715452170) — 수용 기준 충족
- https://github.com/choiyounggi/linkly/actions/runs/33715452170 — conclusion: **success** (~2시간 4분, 180분 예산 내)
- harness rc: 0 — rc 0은 "baseline (unmutated copy): GREEN" 인쇄 + no-op 컨트롤 생존 + 전 뮤테이션 caught를 모두 통과한 유일한 경로 (tail-40 창에는 말미만 보이며 말미 실측: "MUTATION CHECK: PASS — no-op control survived, and all 77 mutations caught by a failing test")
- mutation_report.py healthy 경로 진입: "No mutations survived this week's full run" — 주간 리포트 이슈 갱신 정상 동작
- issue #169 수용 기준: (1) hosted 러너 baseline green ✓ (2) full-matrix 잡 1회 green 관측 ✓

## 결론
수정 대상은 CI 배선이 아니라 **테스트의 env 복원 결함**. repair 라운드 결정: D9 (design.md 개정), Task 04.
잔여 리스크: 오염 제거 후 mode-B 무리가 러너에서 "처음으로 실제 실행"되므로 추가 실패가 드러날 수 있음 — 재-dispatch로 판정 (bounded, D6).
