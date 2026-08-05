# 03 — IR lower + validate_ir (Task 03)

## 실행

```
$ .venv/bin/lnpl compile qa/cases/rate-notify/rate-notify.lnpl -o qa/cases/rate-notify/rate-notify.lir.json
wrote qa/cases/rate-notify/rate-notify.lir.json (21 nodes)
lower-rc=0

$ .venv/bin/python scripts/validate_ir.py qa/cases/rate-notify/rate-notify.lir.json
PASS: qa/cases/rate-notify/rate-notify.lir.json
validate-rc=0
```

시도 각 1회. raw: `evidence/raw/lower-stderr.txt`, `evidence/raw/validate.txt`.

## Guard 노드 3개 — RFC-0008 §4 정규화 형식 대조

| id | mode | condition (IR 원문) | §4 형식 | 일치 |
|----|------|---------------------|---------|------|
| wf.report.guard.1 | when | `measurement.value > 100` | `<field> <comparator> <value>` | ✓ |
| wf.report.guard.2 | when | `priorNotification missing` | `<field> <exists\|missing>` | ✓ |
| wf.report.guard.3 | until | `measurement.acknowledged > 0` | `<field> <comparator> <value>` | ✓ |

가드 수 3 — 계획대로(폴백 미발동).

## 관찰 (F-후보 강화)

02-compile.md에서 발견한 매달린 참조 — EventEmit `"event": "event.notification"`
vs 실제 Event 노드 id `event.notification.sent` — 를 **validate_ir도 통과시켰다**
(PASS). 즉 IR 스키마 검증은 구조(스키마 형식)만 보고 **노드 간 id 참조 해석은
검사하지 않는다**. 런타임 거동은 T04에서 관찰.

## 추기 (Task 04에서 emit 수정 후 재생성)

`emit notification` → `emit notificationSent` 수정(04-modeA.md 참조) 후 동일
명령으로 재실행: `wrote … (21 nodes)` lower-rc=0, `PASS` validate-rc=0.
Guard 노드 3개는 수정과 무관하게 위 표 그대로다.
