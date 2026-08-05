# evidence/04 — mode A 실행 + 마스킹 실측 (T05)

명령: `.venv/bin/lnpl run --workflow <id> [--payload <json>] --json qa/cases/payment-refund/payment-refund.lnpl`
원본: evidence/raw/run-*.{out,err}

## 실행 요약

| 실행 | rc | 결과 |
|------|----|------|
| wf.approval 시도 1 (Money 가드) | 1 | **raw Python traceback**: `TypeError: '<=' not supported between instances of 'dict' and 'int'` (interp.py:289) — Money 가드는 컴파일 통과 후 런타임 크래시, 도메인 진단 없음(F) |
| wf.approval 시도 2 (amountCents 폴백) | 0 | `completed`, steps 3 (validate/find/update) |
| wf.refund.request 시도 1 (`payment.createdAt <= 43200m`) | 3 | `runtime error: Cannot compare non-numeric payment.createdAt='2026-07-31T09:00:00Z' in condition …` — DateTime<=Duration은 컴파일 통과, 런타임 거부(F; 단 이번엔 도메인 진단) |
| wf.refund.request 시도 2 (`payment.ageDays <= 30` 폴백) | 0 | `completed` |

modeA 재시도 수: 워크플로당 2 (총 4실행 + 프로브 6실행).

## 마스킹 판정 (D5 — 3조건)

시료: 시드 값 `s3cret-value`(types.md Password 예시 — 합성값) 및 payload 주입 합성 카드번호 `4111111111111111`.

| D5 조건 | 실측 | 인용 (run-approval-amt1000001.out) |
|---------|------|------------------------------------|
| (a) Password 필드 마스킹 형태 | **trace 계층은 마스킹됨**: `"cardNumber": "***"` | 122행 |
| (b) 네거티브 컨트롤 | 같은 출력에서 `amountCents`·`amount`는 평문 → 검사가 변별력 있음 | bindings의 `"amountCents": 1000001` 등 |
| (c) 원문 grep 부재 | **실패 — result.bindings에 원문 노출**: `"cardNumber": "4111111111111111"` (30행). 시드 실행에서도 `s3cret-value` 1히트(run-approval-default.out 36행) | 30행 |

**판정: 부분 집행.** 타입 주도 마스킹은 실제로 존재하고 trace(관측/로그 채널)에는 적용되지만,
`result.bindings`(결과 페이로드 채널)는 우회한다 — 채널 하나가 새면 마스킹은 없는 것과 같다
(중앙 마스킹 원칙 위반, F-기록). 사람용 출력(--json 없음)은 필드 값을 아예 출력하지 않아 누출도 마스킹도 없음:
`grep -c s3cret-value` → json출력 1, human출력 0.

## 금액 경계값 프로브 (payload 주입, 한도 1,000,000센트)

payload에 전체 필드 필수(부분 payload는 `failed: missing required field 'id'` — 프로브에도 카드번호 제출 강제, F-후보).

| amountCents | rc | status | 가드 | 해석 |
|-------------|----|--------|------|------|
| 0 | 0 | completed | 통과 | **하한 부재의 런타임 증명** — 탈락한 `> 0` 가드 탓에 0원 결제 승인됨 |
| -1 | 0 | completed | 통과 | 음수 금액도 승인됨 (동일 원인) |
| 1000000 | 0 | completed | 통과 | 경계 포함(`<=`) 정확 |
| 1000001 | 0 | **completed** | `skipped=["wf.approval.guard.1"]` | **한도 초과인데 status=completed, rc=0** — 가드 false는 거부가 아니라 조용한 skip(INFO 로그 `"guard skipped the guarded item"`). 호출자는 성공으로 읽는다(F-major) |

## RFC-0004 관련 노트 (brief tacit)

마스킹은 RFC-0004가 명명한 관찰 가능 클래스 — mode A에서 trace 채널만 마스킹됨을 실측.
mode B와의 differential 마스킹 일치는 T06에서 비교.
