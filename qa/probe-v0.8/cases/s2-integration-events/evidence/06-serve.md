# 06-serve — notifier `lnpl serve`

## 명령

```
$ lnpl serve src/notifier/notifier.lnpl \
    --host 127.0.0.1 --port 0 \
    --backend sqlite:.claude/tmp/s2-notifier-store.db \
    --network http --endpoint 'Hook=http://127.0.0.1:36095/hook' \
    --log-format json
serving qa/probe-v0.8/cases/s2-integration-events/src/notifier/notifier.lnpl on
http://127.0.0.1:36102 (mode A, backend=sqlite, jwt=presence-checked)
```

`consume by`가 있는 `event OrderPlaced`가 자동으로 `POST /-/events/order-placed`
라우트를 낸다(RFC-0040 §4) — 별도 route 선언 없이 event 선언만으로 열림.

## 요청/응답 (relay가 실제로 찌른 것 — evidence/08 참고)

```
$ curl -X POST http://127.0.0.1:36102/-/events/order-placed \
    -d '{"specversion":"1.0","id":"outbox-1","source":"orders",
         "type":"OrderPlaced","data":{"id":"o-1","totalUsd":10}}'
→ 200 (relay가 acked 1 emission으로 확인)
```

접속 로그(`--log-format json`, 1행):
```
{"correlation_id": "req-b977c0fcddcb", "method": "POST",
 "path": "/-/events/order-placed", "workflow": null, "status": 200,
 "duration_ms": 8.598, "skipped": [], "diagnostics": [],
 "trace_id": "89962e1175d44148aee91c20386b1eed",
 "span_id": "bcc6b81a9e204893"}
```

**관측**: `workflow` 필드가 `null`이다 — 일반 워크플로 POST 라우트의 접속
로그는 이 필드에 실행된 워크플로 노드 id를 싣지만(§Reference), 이벤트
인입 라우트(`/-/events/<slug>`)는 실제로 `wf.notify.order`를 실행했음에도
이 필드을 채우지 않는다. correlation 추적 시 "이 요청이 어느 워크플로를
돌렸는지"를 로그 한 줄만으로 알 수 없다 — R9 관련 F-항목 후보(축 ops/diag).

## 종료

```
$ kill <serve-pid>; ps aux | grep 'lnpl serve'  →  (no output, 정상 종료)
```
