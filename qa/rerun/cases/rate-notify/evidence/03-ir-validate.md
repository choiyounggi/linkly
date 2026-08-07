# 03 — lir 생성과 IR 검증 (T3)

```
$ .venv/bin/lnpl compile qa/rerun/cases/rate-notify/rate-notify.lnpl -o qa/rerun/cases/rate-notify/rate-notify.lir.json   # rc=0
$ .venv/bin/python scripts/validate_ir.py qa/rerun/cases/rate-notify/rate-notify.lir.json   # rc=0
PASS: qa/rerun/cases/rate-notify/rate-notify.lir.json
```

- 원 실측과 동일하게 lower/validate 무마찰(재시도 0).
- IR 구조 확인: Guard 노드 3개(`wf.report.guard.1` when 비교식 /
  `guard.2` when presence / `guard.3` until) — 원 lir와 동형.
- 주의(guard-true-path-coverage §3): validate PASS는 참조 해석의 증거가 아니다 —
  참조 거부는 02-compile.md의 심은-참조 probe가 컴파일 단계에서 직접 확인했다.
- raw: raw/validate.txt.
