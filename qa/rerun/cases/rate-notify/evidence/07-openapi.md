# 07 — openapi (T6)

```
$ .venv/bin/lnpl openapi qa/rerun/cases/rate-notify/rate-notify.lnpl -o qa/rerun/cases/rate-notify/rate-notify.openapi.json   # rc=0
```

- rc=0, 유효 JSON (`json.load` 통과), paths: `/rate-notify-service/report` — 원 동형.
- 재시도 0 (원 동일). raw: raw/openapi.txt.
