# 06 — differential (T6)

명령: `.venv/bin/lnpl diff qa/rerun/cases/rate-notify/rate-notify.lnpl --payload qa/rerun/cases/rate-notify/payloads/rN.json --workdir .claude/tmp/lnpl-diff`
raw: `evidence/raw/diff-r{1,2,7}.txt`. workdir 제거 완료.

## 런별 verdict

| Run | 경로 | verdict | rc | 원 대비 |
|-----|------|---------|----|---------|
| r1 | 발화 경로 (create+emit, until 0라운드) | **EQUIVALENT** 4/4 | 0 | 원 동일 |
| r2 | 스킵 경로 (guard.1 스킵) | **EQUIVALENT** 4/4 | 0 | 원 동일 |
| r7 | until 반복 경로 (read ×16) | **DIVERGENT** (3/4 FAIL) | 1 | 원 미실행(자동화 후보 (a)) — **#51 재현** |

## r7 발산 상세 — #51 재현 (잔존, 추적 중; 원인 추적은 범위 밖)

- 갈라진 첫(유일) 검사 = **3/4 observability signals**. 1/4 execution order는
  **양 모드 20스텝 동일**로 PASS, 2/4 policy outcome도 PASS(status=completed).
- 인용: mode A 관측 맵 `'read measurement': ['RepositoryCall']`(1개) vs mode B
  `'read measurement': ['RepositoryCall' ×16]` — 같은 스텝 이름이 라운드마다
  반복될 때 A는 마지막 하나만 남기고 B는 전부 누적하는 관측기 비대칭.
  examples/guarded.lnpl 헤더 주석("원인은 until의 실행 의미가 아니라 차등
  관측기의 비대칭")과 정확히 일치.
- 실행 의미는 갈리지 않았다(1/4 PASS) — 발산은 관측기 층. F-판정 어휘로는
  "**잔존(#51 추적 중)**".

## EQUIVALENT 인용의 범위 한정 (D6 — differential-run-agreement)

양측이 모델링하는 상태:

| 차원 | mode A | mode B | 이 run에서 비교됐나 |
|------|--------|--------|---------------------|
| 가드 분기·실행 순서 | ✓ | ✓ (payload에서 자동 배선) | ✓ (r1·r2·r7) |
| 저장소 실패 경로 | ✓ (`--no-row`) | ✗ (KNOWN LIMITATION — guarded.lnpl 헤더) | ✗ — **미검** |
| `sentAt` DateTime 값 | ✓ | ✗ (differential이 DateTime을 0으로 강제 — RFC-0016 기지) | ✗ — **미검** |

따라서 r1·r2의 EQUIVALENT는 문자적으로 "**미모델 상태가 결과를 좌우하지 않는
입력에서 두 모드가 일치**"라는 좁은 주장으로 인용한다 — 저장소 실패·DateTime
차원의 동등성 증거가 아니다.
