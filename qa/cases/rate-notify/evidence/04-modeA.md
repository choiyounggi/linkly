# 04 — mode A 가드 양방향 실행 (Task 04)

명령(공통): `.venv/bin/lnpl run qa/cases/rate-notify/rate-notify.lnpl --payload qa/cases/rate-notify/payloads/rN.json --json`
raw: `evidence/raw/modeA-rN.json` / `.stderr`. 전 런 종료 코드는 아래 표.

## 1차 실행 (emit 매달린 참조로 6/7 실패 — F-기록)

첫 소스(`emit notification`)의 R1~R7 실행에서 **r6만 rc=0, 나머지 rc=1**:

```
failed_step= emit notification
reason= EventEmit references undeclared event 'event.notification'
```

- 컴파일(0 error)·validate_ir(PASS)를 통과한 매달린 이벤트 참조가 **런타임에만** 터졌다.
- r6은 presence 가드가 emit을 스킵해서 **통과** — 가드가 자주 스킵되는 경로라면
  이 오류는 프로덕션까지 잠복한다(가드 스킵이 오류를 가리는 실증).
- 우회(내 .lnpl 안에서만): `emit notification` → `emit notificationSent` (시도 2).
  emit 목적어는 **이벤트 이름의 camelCase**로 써야 id(`event.notification.sent`)로
  해석된다 — 이 규칙은 verbs.md·grammar.md 어디에도 문서화돼 있지 않다.
- → FINDINGS F-2 (major).

## 2차 실행 (수정 후) — 전 런 rc=0

| Run | payload 요지 | status | 실행 스텝 | skipped |
|-----|--------------|--------|-----------|---------|
| R1 | value 150, ack 1 | completed | validate, find, **create**, **emit** | [] |
| R2 | value 50, ack 1 | completed | validate, find, emit | [guard.1] |
| R3 | value **100**, ack 1 | completed | validate, find, emit | [guard.1] |
| R4 | value 0, ack 1 | completed | validate, find, emit | [guard.1] |
| R5 | value -5, ack 1 | completed | validate, find, emit | [guard.1] |
| R6 | value 150, ack 1, prior 有 | completed | validate, find, create | [guard.2] |
| R7 | value 150, **ack 0** | completed | validate, find, create, emit, **read ×16** | [] |

## 가드별 양방향 대조 (D5 — 갈리지 않으면 F-blocker)

| 가드 | 참 런 | 거짓 런 | 참 신호 (인용) | 거짓 신호 (인용) | 갈렸는가 |
|------|-------|---------|----------------|------------------|----------|
| guard.1 `when measurement.value > 100` | R1 | R2 | steps에 `create notification` 존재, skipped=[] | steps에 create 부재, `skipped=['wf.report.guard.1']` | **Y** |
| guard.2 `when priorNotification missing` | R1 | R6 | steps에 `emit notificationSent` 존재 | steps에 emit 부재, `skipped=['wf.report.guard.2']` | **Y** |
| guard.3 `until measurement.acknowledged > 0` | R1 (즉시 성립) | R7 (미성립) | `read measurement` 0회 실행(스텝 목록에 부재) | `read measurement` **16회** + trace `{"level": "WARN", "message": "until loop hit round cap", "guard": "wf.report.guard.3", "rounds": 16, "reason": "round_cap"}` | **Y** |

**판정: 세 가드 모두 실제로 평가된다. 무음 통과(항상 참) 없음.** RFC-0008 §2의
payload 필드 추출 기반 평가가 mode A에서 동작함을 실측 확인 (시드 행 = payload
복사본 경유, RFC-0012 실행 스코프).

## 경계값 실측 (minimum-case-set: 정확한 한계·0·음수)

- **value=100 (임계값과 정확히 같음, R3): guard.1 스킵 → `>`는 배제(exclusive) 경계.**
- value=0 (R4): 스킵 — 0이 특수 취급되지 않고 일반 비교로 처리됨.
- value=-5 (R5): 스킵 — 음수도 정상 비교(파싱·평가 오류 없음).

## until 경계 관찰

- `timeout 3s` 선언 상태에서 R7의 중단 사유는 `reason="round_cap"` —
  16라운드가 3s 데드라인보다 먼저 도달(라운드당 ~6ms). RFC-0008 §2.2의
  이중 경계 중 라운드 경계 작동 확인. 시간 경계(`reason="deadline"`)는
  이 케이스에서 미관측(도달 불가능한 조합 — F 아님, 커버리지 갭으로 기록).
- R1(조건 즉시 성립): 피가드 항목 0회 실행 — "참이 될 때까지 반복"의
  0회 반복 케이스 확인. 단, skipped 목록에 guard.3이 **표기되지 않음** —
  0라운드 until과 스킵된 when의 관측 신호가 비대칭 (F-후보, info).

## 기타 관찰

- `run --json` 결과에 저장소 행 수(rows) 신호가 없다 (result keys:
  bindings/steps/skipped/… 뿐). rows 단언은 spec 러너로만 가능 — T07에서 측정.
- 시도 집계: payload 작성 1회, 실행 2회(1차 실패는 emit 참조 — payload 문제 아님).
