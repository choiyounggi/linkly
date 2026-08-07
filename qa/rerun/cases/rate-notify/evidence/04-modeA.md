# 04 — mode A 가드 양방향 실행 (T4)

명령(공통): `.venv/bin/lnpl run qa/rerun/cases/rate-notify/rate-notify.lnpl --payload qa/rerun/cases/rate-notify/payloads/rN.json --json`
raw: `evidence/raw/modeA-rN.json` / `.stderr`, `raw/run-help.txt`. **전 런 rc=0, 재시도 0**
(원 실측은 F-2로 1차 6/7 실패 → 수정 후 재실행 1회. 이번엔 T3에서 컴파일이 매달린
참조를 선거부하므로 그 실패 모드 자체가 도달 불가).

## 런별 결과 (실행 스텝 목록 기준 — D3)

| Run | payload 요지 | status | 실행 스텝 | skipped 레코드 |
|-----|--------------|--------|-----------|----------------|
| R1 | value 150, ack 1 | completed | validate, find, **create**, **emit** (4) | **guard.3 until rounds=0** |
| R2 | value 50, ack 1 | completed | validate, find, emit (3) | guard.1 when + guard.3 until rounds=0 |
| R3 | value **100**, ack 1 | completed | validate, find, emit (3) | guard.1 when + guard.3 rounds=0 |
| R4 | value 0, ack 1 | completed | validate, find, emit (3) | guard.1 when + guard.3 rounds=0 |
| R5 | value -5, ack 1 | completed | validate, find, emit (3) | guard.1 when + guard.3 rounds=0 |
| R6 | value 150, ack 1, prior 有 | completed | validate, find, create (3) | guard.2 when + guard.3 rounds=0 |
| R7 | value 150, **ack 0** | completed | validate, find, create, emit, **read ×16** (20) | [] |

## 가드별 양방향 대조

| 가드 | 참 런 | 거짓 런 | 참 신호 (인용) | 거짓 신호 (인용) | 갈렸는가 |
|------|-------|---------|----------------|------------------|----------|
| guard.1 `when measurement.value > 100` | R1 | R2 | steps에 `create notification` 존재 | create 부재 + skipped에 `{guard: wf.report.guard.1, mode: when, steps: ['create notification']}` | **Y** |
| guard.2 `when priorNotification missing` | R1 | R6 | steps에 `emit notificationSent` 존재 | emit 부재 + skipped에 guard.2 레코드 | **Y** |
| guard.3 `until measurement.acknowledged > 0` | R1 (즉시 성립) | R7 (미성립) | `read measurement` 0회 + **skipped에 `{guard: wf.report.guard.3, mode: until, rounds: 0}`** | `read measurement` 16회 + trace WARN `until loop hit round cap … reason: round_cap` | **Y** |

**판정: 세 가드 모두 실제로 평가된다. 무음 통과 없음** — 원 실측과 동일하게 유지.

## F-9 재검: 0라운드 until의 관측 대칭 — **반전**

- 원: R1의 skipped=[] — 0라운드 until 무표지(when 스킵과 비대칭).
- 재측정: R1 skipped에 `{"guard": "wf.report.guard.3", "mode": "until",
  "condition": "measurement.acknowledged > 0", "steps": ["read measurement"],
  "rounds": 0}` — **rounds 필드까지 갖춘 구조화 레코드**. when 스킵(rounds: null)과
  같은 목록에 대칭 표기.
- 나아가 stderr 진단도 대칭: R2에서
  `warning: guard-skipped-steps [wf.report.guard.1] …` 와
  `warning: guard-skipped-steps [wf.report.guard.3] measurement.acknowledged > 0 —
  the `until` guard did not run read measurement; the workflow still reports
  completed, so a caller reading only the status cannot tell this run from one
  that ran every step` (raw/modeA-r2.stderr) — until 스킵이 1급 진단이 됐다.
- `--strict`(run --help에 신설 확인): R2·R7 모두 **rc=2** (raw/modeA-r{2,7}-strict.*).
  주의: 이 소스는 perf 경고 1건이 상존해 rc=2가 스킵 진단만의 신호는 아니나,
  guard-skipped-steps 경고가 진단 집합에 포함되는 것은 stderr 원문으로 확인.

## F-10 재검: rows 신호

- R1 result 최상위 키: bindings / correlation_id / duration_ms / failed_step /
  failure_reason / skipped / slo_met / slo_ms / status / steps — **rows 없음**.
  원 대비 키가 늘었으나(correlation_id, failure_reason 등) 저장소 행 수 신호는
  여전히 부재. 잔존 후보 (rows 단언은 spec 러너 경유 — 08-spec.md에서 실측).

## 경계값 실측 (원 동형)

- R3 (value=100, 임계값 동일): guard.1 스킵 → `>` 배제(exclusive) 경계 — 원 동일.
- R4 (0) / R5 (-5): 스킵 — 0·음수 일반 비교 처리, 파싱·평가 오류 없음 — 원 동일.
- R7: round cap 16 (`reason: round_cap` WARN) — 원 동일. deadline 경계는 이번에도
  미도달(커버리지 갭 유지, F 아님).
