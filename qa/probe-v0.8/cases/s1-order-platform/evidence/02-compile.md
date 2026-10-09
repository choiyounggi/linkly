# evidence/02 — Compile (--strict=warning)

## Final entity compile

```
$ .venv/bin/lnpl compile qa/probe-v0.8/cases/s1-order-platform/src/ --strict=warning \
    -o .claude/tmp/entities-strict.lir.json
wrote .claude/tmp/entities-strict.lir.json (9 nodes)
rc=0
```

No diagnostics on stderr. Node ids confirm namespace/visibility layout:

```
entity.catalog.category
entity.catalog.product
entity.orders.stock            <- orders/internal/stock.lnpl, folded into `orders` (RFC-0033)
entity.orders.customer
entity.orders.order
entity.orders.order.line
entity.orders.stock.reservation
entity.payments.payment
entity.payments.refund
```

## R1 — visibility violation probe

Setup: copied `src/` to `.claude/tmp/r1-probe-tree/` (scratch, outside the
graded case dir) and added `payments/violation.lnpl` (content saved verbatim
at `evidence/r1-violation.lnpl.txt`, per D9):

```lnpl
workflow PeekStock
    find stock
```

```
$ .venv/bin/lnpl compile .claude/tmp/r1-probe-tree/ -o .claude/tmp/r1-probe-tree-out.lir.json
compile error: line 2: `find stock` references 'Stock', declared `internal` to
namespace 'orders' — not visible from namespace 'payments' (RFC-0033 `internal/`
visibility)
rc=2
```

R1's "Stock가 orders 밖에서 참조되면 컴파일이 거부돼야 한다" is satisfied by
the platform's `internal/` directory-visibility mechanism (no extra code
needed on our side beyond the directory layout chosen in evidence/01).

Confirmed the real `src/` (untouched by the probe, which ran against a
separate copy) still compiles clean immediately after:

```
$ .venv/bin/lnpl compile qa/probe-v0.8/cases/s1-order-platform/src/ -o /dev/null
wrote /dev/null (9 nodes)
rc=0
```

## Verdict for R1 (entity/visibility half)

충족 — 코드베이스가 팀(네임스페이스)별로 분리되고 한 번에 컴파일되며,
`Stock`은 실제로 `orders` 밖에서 컴파일 거부된다. (워크플로/서비스 분리 실행
쪽 절반은 task 03~05에서 마저 검증한다.)
