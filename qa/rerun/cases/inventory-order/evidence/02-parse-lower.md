# evidence/02-parse-lower — parse + IR lower (재측정 Task 03)

재시도 수: 0 (이 단계 자체는 1회 통과; .lnpl 저작 반복 3회는 evidence/01,
서술 선언 제거 1회는 evidence/04 참조)

```
$ .venv/bin/lnpl compile qa/rerun/cases/inventory-order/inventory-order.lnpl \
    -o qa/rerun/cases/inventory-order/inventory-order.lir.json
# rc=0  (최종 소스 기준 — 서술 선언 제거 후에는 경고 0건)
wrote qa/rerun/cases/inventory-order/inventory-order.lir.json (21 nodes)
```

원 실측과 차이: 원 IR 20노드(가드 리터럴·차감 없음) → 이번 21노드(Guard 1 +
Pipeline 1 + Assignment 1 포함; 서술 선언 perf.order 제거로 −1). 값 표현식이
IR에 원문 그대로 실린다(생존 계수는 evidence/01 §IR 생존 계수).

판정: PASS (parse·lower 동시 수행 — `lnpl compile`이 두 단계를 한 명령으로 묶음,
원 실측과 동일한 커맨드 형태).
