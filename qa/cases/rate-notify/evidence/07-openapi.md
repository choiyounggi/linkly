# 07 — OpenAPI 생성 (Task 06)

## 실행

```
$ .venv/bin/lnpl openapi qa/cases/rate-notify/rate-notify.lnpl -o qa/cases/rate-notify/rate-notify.openapi.json
wrote qa/cases/rate-notify/rate-notify.openapi.json (1 path(s))
rc=0    (stderr: 없음 — raw/openapi-stderr.txt 비어 있음)
```

시도 1회.

## 존재 확인 (인용)

```
openapi: 3.1.0
paths: ['/rate-notify-service/report']
schemas: ['Measurement', 'Notification']
```

- 엔티티 2종 스키마와 workflow Report의 경로가 모두 반영됨. PASS.
- 스키마 내용 정합성 심사는 이 케이스의 측정 범위 밖(계획 Out of scope).
