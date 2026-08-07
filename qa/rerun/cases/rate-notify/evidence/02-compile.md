# 02 — compile + F-2 심은-참조 probe + F-7 실동작 (T3)

## 본 소스 컴파일

```
$ .venv/bin/lnpl compile qa/rerun/cases/rate-notify/rate-notify.lnpl   # rc=0
warning: declared-measured-only [perf.rate.notify] performance response — declared but measured: …
1 warning(s), 0 error(s)
```

- rc=0, 의도된 경고 1건 — 원 실측과 동일(첫 컴파일 통과, 재시도 0).
- **F-11 관찰**: 경고는 여전히 노드 id(`[perf.rate.notify]`)로만 지칭 —
  파일:라인 위치 정보 없음. 원 관찰과 동일(잔존 후보). 단 아래 F-2 에러는
  `workflow Report:` 구성명을 앞세워 원보다 맥락이 한 단계 늘었다.
- raw: raw/compile.txt, raw/compile-o.txt.

## F-2 심은 매달린 참조 probe (D4 — guard-true-path-coverage edge 행)

probe: `probes/f2-undeclared-event.lnpl` = 본 소스에서 `emit notificationSent` →
`emit notification` 1토큰 교체(원 1차 실측의 실수 재현).

```
$ .venv/bin/lnpl compile probes/f2-undeclared-event.lnpl   # rc=2
compile error: workflow Report: `emit`/`publish` references 'event.notification',
which is not a declared event (declared: event.notification.sent)
```

- **처음 거부된 단계 = compile** (원: compile rc=0 → validate PASS → 런타임 rc=1).
- 진단이 선언된 이벤트 목록(`declared: event.notification.sent`)을 제시 —
  원 F-2의 "emit 목적어→이벤트 id 합성 규칙이 어느 문서에도 없다"는 보조 마찰도
  이 후보 목록으로 실질 완화(정답이 진단에 나온다).
- 가드 스킵 경로 잠복 위험(원 r6 rc=0 통과) 자체가 소멸 — 실행 전에 죽는다.
- **판정 후보: 해소** — validate/run 단계 probe는 불필요(컴파일이 먼저 거부).

## F-7 실동작 (probes/f7-eq.lnpl)

```
$ .venv/bin/lnpl compile probes/f7-eq.lnpl   # rc=0 (경고 1, 에러 0)
```

- `when measurement.value == 100`이 컴파일 통과 — grammar.md 31행 정본화
  (01-authoring.md)와 실동작 일치. raw: raw/compile-f7-eq.txt.
