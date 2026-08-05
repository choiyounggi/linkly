# evidence/02-parse-lower — parse + IR lower (Task 04)

재시도 수: 0 (이 단계 자체는 1회 통과; .lnpl 저작 반복 3회는 evidence/01 참조)

```
$ .venv/bin/lnpl compile qa/cases/inventory-order/inventory-order.lnpl \
    -o qa/cases/inventory-order/inventory-order.lir.json
# rc=0
warning: declared-measured-only [perf.order] performance response — declared but measured: measured and reported per run, but an over-budget run is not blocked
1 warning(s), 0 error(s)
wrote qa/cases/inventory-order/inventory-order.lir.json (20 nodes)
```

판정: PASS (parse·lower 동시 수행 — `lnpl compile`이 두 단계를 한 명령으로 묶음).
경고 1건은 의도된 서술 선언(evidence/01 §남은 진단 판정).
