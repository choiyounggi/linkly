# evidence/06-differential — mode A vs mode B 동치 검사 (Task 05)

재시도 수: 0

```
$ .venv/bin/lnpl diff qa/cases/inventory-order/inventory-order.lnpl --workdir .claude/tmp/lnpl-diff
# rc=0
PASS 1/4 execution order — 4 step(s): validate order -> find product -> create order -> update product
PASS 2/4 policy outcome — status=completed
PASS 3/4 observability signals — 4 effect(s) per step match
PASS 4/4 masking — no secret marker in either mode's output
differential: EQUIVALENT
```

판정: PASS — EQUIVALENT (4/4). mlir-opt/mlir-translate/clang 전부 존재하여 skip 없음.
주: diff 하네스는 자체 시드로 가드 통과 경로(4스텝)를 구동한다 — 수동 mode B에서
`--field` 키를 틀렸을 때의 2스텝 경로와 혼동하지 말 것(evidence/05 시도 1).
