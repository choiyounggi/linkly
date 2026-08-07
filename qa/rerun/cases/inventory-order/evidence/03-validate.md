# evidence/03-validate — IR 스키마 검증 (재측정 Task 03)

재시도 수: 0

```
$ .venv/bin/python scripts/validate_ir.py qa/rerun/cases/inventory-order/inventory-order.lir.json
# rc=0
PASS: qa/rerun/cases/inventory-order/inventory-order.lir.json
```

판정: PASS. RFC-0015 신규 노드(Assignment·Pipeline·값 표현식 가드)가 스키마
검증을 통과한다 — 원 실측과 동일 커맨드의 동형 재실행.
