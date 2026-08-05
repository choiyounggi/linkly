# 02 — compile 진단 (Task 02)

## 실행

```
$ .venv/bin/lnpl compile qa/cases/rate-notify/rate-notify.lnpl
rc=0
```

시도 1회. stderr 전문: `evidence/raw/compile-attempt-1.txt`,
stdout(IR): `evidence/raw/compile-attempt-1.stdout.txt`.

## stderr 진단 전문 (인용)

```
warning: declared-measured-only [perf.rate.notify] performance response — declared but measured: measured and reported per run, but an over-budget run is not blocked
1 warning(s), 0 error(s)
```

## 진단 판정 (lnpl-verify 규율: 항목별 의도 여부)

| 진단 | 판정 | 사유 |
|------|------|------|
| `declared-measured-only` perf response | **의도됨** | 계획 D11 — slo 관측 신호를 얻기 위한 서술적 선언. declarations.md 집행 매트릭스와 일치 |

unknown-verb 0건 — 동사 5개(validate/find/create/emit/read) 전부 사전 내.

## 진단 메시지 품질 평가 (측정 규율 2)

- **좋은 점**: 진단 코드(`declared-measured-only`)·대상 노드 id(`perf.rate.notify`)·
  "측정만 하고 차단하지 않는다"는 행동 설명까지 1줄에 담김. 조치 가능성 높음.
- **아쉬운 점**: **파일:라인 위치 정보가 없다** — 노드 id로만 지칭하므로 소스가
  길어지면 역추적 비용 발생 (F-후보, minor).
- SKILL.md 경고대로 진단은 stderr + exit 0 — 리다이렉트 없이 파이프만 보면 유실됨.
  이 함정은 문서에 명시돼 있어 사전 인지 가능(마찰 아님, 문서 품질 양호).

## 파싱된 가드 3개 (stdout IR에서 인용 — T03에서 정식 대조)

```json
{"kind": "Guard", "id": "wf.report.guard.1", "children": ["wf.report.step.3"], "mode": "when",  "condition": "measurement.value > 100"}
{"kind": "Guard", "id": "wf.report.guard.2", "children": ["wf.report.step.4"], "mode": "when",  "condition": "priorNotification missing"}
{"kind": "Guard", "id": "wf.report.guard.3", "children": ["wf.report.step.5"], "mode": "until", "condition": "measurement.acknowledged > 0"}
```

전부 RFC-0008 §4 정규화 형식과 일치.

## 관찰 (F-후보)

`emit notification` 스텝의 EventEmit 노드가 `"event": "event.notification"`을
참조하는데, 선언된 Event 노드 id는 `event.notification.sent`(NotificationSent)다.
즉 **emit이 존재하지 않는 노드 id를 가리킨다** — 이벤트 이름(`NotificationSent`)이
아니라 목적어 명사(`notification`)로 id를 합성하는 것으로 보인다. 컴파일 진단은
이를 잡지 않았다(0 error). validate_ir(T03)와 런타임(T04)이 잡는지 관찰.
