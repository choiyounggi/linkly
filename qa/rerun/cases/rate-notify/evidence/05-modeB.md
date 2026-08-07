# 05 — mode B (네이티브 컴파일·실행) (T5)

명령(공통): `.venv/bin/lnpl build qa/rerun/cases/rate-notify/rate-notify.lnpl --run --workdir .claude/tmp/lnpl-build <인자>`
raw: `evidence/raw/modeB-*.txt`, `raw/build-help.txt`. workdir는 태스크 종료 후 제거.

## F-3 재검: bare `--field` 이름 — **반전**

- help 문구가 바뀌었다(raw/build-help.txt): 원 "Fields the workflow does not
  compare on are ignored" → 현행 "**NAME must name a comparison-guard field of
  the workflow — one that does not is rejected, with the valid names listed.**"
- 실측(원 1차 실측의 실수 그대로 재현):

```
$ … --field value=150 --field acknowledged=1        # rc=2
error: --field name(s) acknowledged, value do not match any comparison-guard
field of workflow wf.report (valid: measurement.acknowledged, measurement.value,
priorNotification)
```

- 원: 무경고 exit=0, 전 필드 기본값 0 평가(5런 동일 거동). 재측정: **즉시 rc=2
  거부 + 유효 이름(dotted) 전체 목록 제시**. 오타·이름 불일치가 반대 분기
  무음 실행이 되는 경로 소멸. 판정 후보: **해소**. raw/modeB-bare.txt.

## 컨트롤 페어 (매트릭스 전 — override-control-pairs §1)

| 런 | 인자 (dotted) | create notification | rc |
|----|---------------|---------------------|----|
| ctrl-hi | measurement.value=150, measurement.acknowledged=1 | **실행** | 0 |
| ctrl-lo | measurement.value=50, measurement.acknowledged=1 | 부재 | 0 |

관측이 갈렸다 — 레버 연결 증명, 매트릭스 유효.

## when 계열 매트릭스 (dotted, 원 동형)

| Run | 인자 | create | emit | read 라운드 | mode A 대응 | 일치 |
|-----|------|--------|------|-------------|-------------|------|
| B1 (=ctrl-hi) | value=150, ack=1 | ✓ | ✓ | 0 | R1 | **Y** |
| B2 (=ctrl-lo) | value=50, ack=1 | ✗ (스킵) | ✓ | 0 | R2 | **Y** |
| B3 | value=100, ack=1 | ✗ (스킵) | ✓ | 0 | R3 (`>` 배제 경계) | **Y** |
| B5 | value=150, ack=1, `--skip` | ✓ | ✗ (스킵) | 0 | R6 | **Y** |

## until 계열 B4 (#51 주시 대상)

| Run | 인자 | create | emit | read 라운드 | mode A 대응 | 일치 |
|-----|------|--------|------|-------------|-------------|------|
| B4 | value=150, ack=0 | ✓ | ✓ | **16** (step 20까지, status completed, exit=0) | R7 (read ×16) | **Y** |

- 단독 실행에서는 mode A와 라운드 수·스텝 구성이 일치. #51(until 진입-참 mode B
  발산)은 **차등 관측기 경로**의 문제로, 06-differential.md의 diff 실측에서 별도
  기록한다(guarded.lnpl 헤더 주석: 원인은 실행 의미가 아니라 관측 맵의 스텝 이름
  중복 처리 비대칭).

## 가드별 양방향 대조 (mode B)

| 가드 | 참 런 | 거짓 런 | 신호가 갈렸는가 |
|------|-------|---------|-----------------|
| guard.1 비교식 | B1 (create 실행) | B2/B3 (create 부재) | **Y** |
| guard.2 presence | B1 (emit 실행) | B5 `--skip` (emit 부재) | **Y** |
| guard.3 until | B1 (read 0회) | B4 (read 16회) | **Y** |

**판정: mode B에서도 세 가드 모두 실제로 컴파일·평가된다** — 원 실측과 동일 유지.
경계 semantics(100 → 스킵)도 mode A와 동일. presence 다중 가드 개별 제어(--skip
단일 플래그)는 이 케이스로는 여전히 미검증 — 원과 같은 커버리지 갭.

시도 집계: bare-name 거부는 probe 의도 실행(F-3 측정 그 자체)이므로 재시도 아님 —
**재시도 0** (원: F-3로 1차 전 런 오평가 → dotted 재실행 = 재시도 1).
