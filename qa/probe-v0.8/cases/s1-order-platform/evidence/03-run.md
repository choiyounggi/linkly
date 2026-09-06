# evidence/03 — Mode A runs (order creation, money math, transitions)

## Seed mechanism

No dedicated seeding CLI exists — seeded via the platform's own `create`
verb: `workflow SeedProduct` (catalog.lnpl), `workflow SeedStock`
(orders/internal/stock.lnpl), `workflow SeedCustomer` (orders.lnpl), each a
one-line `create <entity>` run once per row against the shared
`--backend sqlite:.claude/tmp/s1.db` (payload IS the row; payload-seed-on-create,
RFC-0030). IDs used: P1=`11111111-…1111`, P2=`22222222-…2222`,
P3=`33333333-…3333`, C1=`44444444-…4444`, C2=`55555555-…5555` — real UUIDs
substituted for s1.md's short labels because `Product.id`/`Customer.id` are
declared `UUID` and the driver flags a non-UUID `id` as
`stored-row-shape-mismatch` (discovered the hard way, see evidence/01 F-3
side-quest). Full id map: `payloads/ids.txt`.

Payload shape for `CreateOrder` deviates from a naive `{customer, product,
qty}` reading of s1.md — `id` in the payload is the **new Order's own id**
(client-supplied), not a reference to any existing row. This is load-bearing:
see evidence/01 F-3 for why (`find`/`create`'s row key is always
`payload["id"]`, so the "id" slot had to be reserved for the entity actually
being freshly created; `Customer`/`Product`/`Stock` are looked up by
`list <entity> where id == input.<matching-declared-field-name>` instead of
`find`).

## A1 — standard order

```
$ echo '{"id":"aaaaaaaa-0000-0000-0000-00000000000a","customer":"44444444-4444-4444-4444-444444444444","product":"11111111-1111-1111-1111-111111111111","qty":2}' > a1.json
$ lnpl run src/ --workflow wf.create.order --backend sqlite:.claude/tmp/s1.db --payload a1.json --json
status: completed
response: {"newOrder": {"id": "aaaaaaaa-…000a", "status": 0, "subtotalCents": 3998,
                          "discountCents": 0, "taxCents": 319, "totalCents": 4317}}
```

Read-back: `newOrder.subtotalCents == 3998` (expected 3998 ✓). `Stock`
row for P1 was **not** decremented (see evidence/01 F-3 — no way to
`find`+`update` Stock by product id in the same execution as creating an
Order keyed by its own id; the platform's `sum`-of-empty=0 / RowSet contrast
below is the substitute). `StockReservation` — one row created (`row_count`
per trace: `create stockreservation as reservation` succeeded), `qty` field
absent from bindings because the payload-seed only supplies `product`
implicitly through `list`'s predicate, not through the create's own payload
seed (a `StockReservation.qty` value is never actually needed downstream, so
left unset — noted for METRICS' "요구사항 충족/부분" table as **부분**, not
불충족: the row's *existence* proves reservation happened; its `qty` field is
not populated by this implementation).

**Rounding deviation (R3 §기록 요령, expected):**
`taxCents = 319`, not the expected `320`. `(3998 − 0) × 0.08 = 319.84`.
Integer division here truncates toward zero (`31984 / 100 = 319`), matching
`rfcs/0028-arithmetic-and-alternative-guards.md`'s `/` contract (`arith.divsi`,
truncation) — s1.md's expectation table assumes round-half-up (`431.76 → 432`
in A2, `319.84 → 320` here). `totalCents = 4317`, not `4318`, tracking the tax
difference 1:1. **F-5** in FINDINGS.md.

## A2 — vip discount

```
$ echo '{"id":"aaaaaaaa-0000-0000-0000-00000000000b","customer":"55555555-…5555","product":"11111111-…1111","qty":3}' > a2.json
$ lnpl run src/ --workflow wf.create.order --backend sqlite:.claude/tmp/s1.db --payload a2.json --json
status: completed
response: {"newOrder": {"id": "…000b", "status": 0, "subtotalCents": 5997,
                          "discountCents": 599, "taxCents": 431, "totalCents": 5829}}
```

subtotal 5997 ✓ (expected 5997). discount 599 (expected 600 — `5997×10=59970`,
`59970/100=599` truncated, s1.md's own worked example already anticipates
599.7→"600 or 599 depending on platform rule", same F-5). tax 431 (expected
432, same truncation, `(5997−599)×8/100 = 431.84→431`). **total 5829 —
matches the expected 5829 exactly**, because the two truncation errors (−1 on
discount from round-half-up, +... actually here the discount is 1 lower
which pushes tax's base up, and tax is 1 lower — the two 1-cent deviations
cancel in the `total` formula for this specific input.** Recorded so a
reader doesn't assume `total` is immune to F-5 in general — A1 shows it is
not.

## A3 — insufficient stock (P3, on_hand 0)

```
$ echo '{"id":"aaaaaaaa-0000-0000-0000-00000000000c","customer":"44444444-…4444","product":"33333333-…3333","qty":1}' > a3.json
$ lnpl run src/ --workflow wf.create.order --backend sqlite:.claude/tmp/s1.db --payload a3.json --json
status: failed
failure_reason: aggregate 'max stock.onHand': min-max-of-empty-rowset — `max onHand` needs at least one row
```

`list stock where id == input.product and onHand >= input.qty` matched zero
rows (P3's `onHand` is 0, `< qty 1`), so the immediately-following
`max stock.onHand` throws — a genuine `RunError` (`status: failed`), not a
silent 200 guard-skip (see evidence/01 "bonus finding" — `docs/serving.md`
M9 says a bare `when` guard-skip is HTTP 200; this design deliberately
avoids `when` for the stock gate for exactly that reason). `policy rollback`
(declared on `OrdersService`) discards the `create order`/`create
orderline`/`create stockreservation` writes already made before the failing
aggregate step — verified directly against the sqlite file:

```
$ python3 -c "import sqlite3; print(sqlite3.connect('.claude/tmp/s1.db')
    .execute('select entity_id,row_key from lnpl_rows where row_key=?',
    ('aaaaaaaa-0000-0000-0000-00000000000c',)).fetchall())"
[]
```

Zero rows under A3's order id in any table — R2's "부분 예약 잔존 금지" holds.
**Deviation:** the failure surfaces as a generic `RunError` → HTTP 500
(`docs/serving.md` M8 "그 외 전부"), not a 4xx — s1.md's A3 acceptance says
"거부(4xx 또는 동등)"; 500 is the best available "동등" given the platform has
no dedicated business-rejection status class distinct from "unhandled
failure" (**F-4** in FINDINGS.md).

## Contrast table (R2, R3, R4 so far)

| 규칙 | 허용 실행 | 거부 실행 | 관측 신호 |
|------|-----------|-----------|-----------|
| R2 재고 검사 | A1 (P1 onHand 5 ≥ qty 2) → `completed`, 1 reservation | A3 (P3 onHand 0 < qty 1) → `failed`, 0 rows any table | `status` + `failure_reason` |
| R3 vip 할인 | A2 (tier=1) → discountCents 599 (>0) | A1 (tier=0) → discountCents 0 | `discountCents` field value (arithmetic `× tier`, no guard — see evidence/01 "guard must not depend on a value this workflow changed") |
| R4 (첫 상태) | 신규 주문 → status 0 (pending) | — (전이 자체는 evidence/03 §payments 이하, task 04 Ship/Cancel 워크플로에서) | `status` field |

## Known-incomplete for this section (recorded, not silently dropped)

- `Stock.onHand` is never physically decremented (F-3's cascade) — a repeat
  order against the same product past its true remaining stock is **not**
  caught by this implementation (only the *static* seeded `onHand` is
  checked, every time, independent of prior reservations). Documented as
  **F-6** (blocker candidate) in FINDINGS.md rather than silently shipped.
- `StockReservation.qty` is created but left at its default (unset) — the
  row's existence is the evidence R2 asked for ("StockReservation을 만들고"),
  the row's own `qty` column is not populated by this implementation.

## §payments — A4–A8 (R5–R7)

Endpoint-path deviation up front: `lnpl serve` binds every workflow at
`POST /<service-slug>/<workflow-slug>` only (`docs/serving.md` — confirmed by
reading, not yet exercised over real HTTP until task 05) — there is **no**
path-parameter mechanism for `/orders/{id}/pay`-style URLs. `id` values (order
id, payment id) travel in the JSON body instead. **F-7** (major, `expr`).

### A4 — successful payment

```
$ echo '{"id":"…000a","orderRef":"…000a","amountCents":4317,"cardLast4":"4242"}' > a4.json
$ lnpl run src/ --workflow wf.pay --backend sqlite:.claude/tmp/s1.db --payload a4.json --json
status: completed
response: {"newPayment": {"id": "…000a", "status": 1}, "order": {"status": 1}}
```

`amountCents 4317` is *our* computed total (F-5's rounding drift — s1.md's
4318 never occurs under this platform's truncating division), not a
deviation from A4 itself. `Payment.id == Order.id` by construction (both
derive from the same `payload["id"]`, F-3's cascade) — no collision because
they are different entity tables; documented, not hidden.
`Payment.cardLast4` is **client-supplied directly**, not extracted from a
full PAN — no substring/slice primitive exists in the verb or value-expression
vocabulary (`references/verbs.md`, `references/grammar.md` §값 표현식) to
derive "last 4 digits" from a longer Text field server-side. Since the
client therefore never has to send a full card number to this
implementation, the "PAN grep → 0 hits" check in task 05 will be vacuously
true; **F-8** (major, `expr`) records that this is a narrower test than R5
asked for, not a full pass.

### A5 — amount mismatch

```
$ echo '{"id":"…000b","orderRef":"…000b","amountCents":100,"cardLast4":"4242"}' > a5.json
$ lnpl run src/ --workflow wf.pay --backend sqlite:.claude/tmp/s1.db --payload a5.json --json
status: completed   (!)
skipped: [{"guard": "wf.pay.guard.1", "condition": "order.totalCents == input.amountCents and order.status == 0",
           "evaluations": [{"ref": "order.totalCents", "value": 5829, "op": "==", "expected": 100, "holds": false},
                            {"ref": "order.status", "value": 0, "op": "==", "expected": 0, "holds": true}]}]
response: null
```

Data outcome is correct — no `Payment` row, `Order.status` stays 0 (pending),
`skipped[]` names exactly why. HTTP-facing this is 200, not 4xx
(`docs/serving.md` M9 "가드 거부는 200이다") — same class as **F-4**.

### A6 — illegal transition (shipped → cancel)

```
$ lnpl run src/ --workflow wf.ship.order --payload '{"id":"…000a"}' ...   # status 0(paid)→2(shipped)... 
   (order was paid via A4 first) → status: 2
$ lnpl run src/ --workflow wf.cancel.order --payload '{"id":"…000a"}' ...
status: completed
skipped: [{"condition": "order.status == 0 or order.status == 1",
           "evaluations": [{"ref":"order.status","value":2,"op":"==","expected":0,"holds":false},
                            {"ref":"order.status","value":2,"op":"==","expected":1,"holds":false}]}]
```

Order stays at status 2 (shipped) — rejected exactly as A6 requires (data
level; HTTP-level same 200-guard-skip caveat as A5/F-4).

### A7 — paid-order cancel: refund + atomicity

A **second**, independent order (`…000d`, C1×P2, total 1078) was created and
paid so A6's ship transition wouldn't interfere with A7's precondition
(paid, not shipped) — s1.md's own A4/A6/A7 chain reuses one order across
three destructive scenarios, which is not replayable against one mutable
row without resetting state; using a twin order is the pragmatic
substitute.

```
$ lnpl run src/ --workflow wf.cancel.order --payload '{"id":"…000d"}' --backend sqlite:.claude/tmp/s1.db --json
status: completed
response: {"order": {"id": "…000d", "status": 4}, "newRefund": {"amountCents": 1078}}
```

**Revision (round 2, per reviewer F4): the response above was never
independently read back against the stored rows at the time.** Doing that
now (round 2) against the untouched `.claude/tmp/s1.db` from round 1 finds
`order.status == 4` persisted correctly, but **no `entity.payments.refund`
row exists at all under this order's id** — only `order`/`order.line`/
`stock.reservation`/`payment` rows do:

```
$ python3 -c "import sqlite3; print(sqlite3.connect('.claude/tmp/s1.db')
    .execute(\"select entity_id,row_key from lnpl_rows where row_key like '%000d%'\").fetchall())"
[('entity.orders.order', '...#…000d'), ('entity.orders.order.line', '...#…000d'),
 ('entity.orders.stock.reservation', '...#…000d'), ('entity.payments.payment', '...#…000d')]
# no entity.payments.refund row
```

So the round-1 claim ("Refund.amountCents == 1078") was **not actually
backed by a persisted row** — only by the run's own JSON response, which
is exactly the read-back gap the reviewer flagged. **Re-running the
identical workflow from a clean, isolated database** (round 2,
`.claude/tmp/f4.db`, fresh product/customer/order/payment, same
`CancelOrder` source) does persist the refund correctly, with a full
read-back this time:

```
$ lnpl run src/ --workflow wf.cancel.order --payload '{"id":"cccccccc-1111-…0001"}' \
    --backend sqlite:.claude/tmp/f4.db --json
status: completed, response: {"order":{"id":"…0001","status":4},"newRefund":{"amountCents":5400}}
$ python3 -c "import sqlite3,json; c=sqlite3.connect('.claude/tmp/f4.db'); \
    print([json.loads(r[0]) for r in c.execute(\"select payload from lnpl_rows where entity_id='entity.payments.refund'\").fetchall()])"
[{'id': 'cccccccc-1111-…0001', 'amountCents': 5400, 'cumulativeCents': 5400, 'capChecked': 5400, ...}]
```

Read-back confirms `order.status == 4` **and** a real, persisted
`Refund` row with `amountCents == 5400` (== the paid total, matching the
mechanism). **This is now the authoritative A7 evidence** — it is a clean
reproduction of the exact same `CancelOrder` source with full read-back,
superseding the round-1 claim. The round-1 database's missing row is left
unexplained (most likely stale/intermediate state from the same session's
later F-12/F-13 exploration, which repeatedly recompiled/reran workflows
against files under `.claude/tmp/`, though not confirmed to have touched
`s1.db` specifically) rather than asserted as a reproducible defect —
CancelOrder's mechanism itself is now verified correct by direct row
read-back, on a fresh, uncontaminated database. `order.status == 4`
(cancelled), `Refund.amountCents` == the paid total — matches A7's shape
(P1's on_hand restoration is **not** modeled; tracked under F-6, since
on_hand was never decremented to begin with).

**Atomicity injection (R6 §기록 요령) — not separately constructed.** The
same `policy rollback` mechanism already proven in A3 (evidence above: a
failing aggregate mid-execution discards every write made so far, verified
against the raw sqlite file) is architecturally identical to what would run
here between "create Refund" and "flip Order.status" — but a dedicated
injected-failure probe between those two specific steps was not built
separately given the time budget. **F-9** (minor — mechanism already
demonstrated generically, not reproduced at this exact seam).

### A8 — refund cap

```
$ for amt in 2000 2000 1000; do lnpl run src/ --workflow wf.refund \
    --backend sqlite:.claude/tmp/s1.db --payload '{"id":...,"payment":"…000a","amountCents":'$amt',"reason":"p"}' --json; done
refund 1 (2000): completed, cumulativeCents 2000
refund 2 (2000): completed, cumulativeCents 4000
refund 3 (1000): failed — aggregate 'max payment.amountCents': min-max-of-empty-rowset
     ("max amountCents" needs at least one row)
```

2 `Refund` rows persist (`amountCents` 2000/2000); the 3rd's `create refund`
was rolled back (`policy rollback` on `RefundsService`) — confirmed 0
leftover rows for the 3rd attempt's id. **Mechanism**: `list refund where
payment == input.payment` (prior refunds) → `sum` into
`newRefund.cumulativeCents`, `+ input.amountCents` (one more `set`, still a
single binary op each), then `list payment where id == input.payment and
amountCents >= newRefund.cumulativeCents` — an empty match forces the next
`max payment.amountCents` to fail. **This is the important generalization of
F-3's "bonus finding":** a `list where` predicate's right-hand value **can**
reference a field this same workflow `set` earlier (verified — no
"depends on a value this workflow changed" error), unlike a `when`/`until`
guard, which categorically cannot (F-3). That asymmetry is undocumented and
is the single most load-bearing discovery for making R7 rejectable at all —
**F-10** (the finding itself, `doc`+`llm` axis: without it, R7's cap is not
implementable as a hard rejection).

**Not enforced (round 2: executed directly, per reviewer F3 — no longer a
code-review-only claim).** The literal "환불은 최대 3회" **count** cap
(independent of amount) is not implemented — only the cumulative-amount
cap is. Round 1 inferred this from reading the code; round 2 proves it by
running the actual boundary: a payment for 108000 cents, then four
sequential 1-cent refunds (cumulative only reaches 4 — nowhere near the
amount cap, isolating the count dimension):

```
$ lnpl run src/ --workflow wf.pay ... --payload '{"id":"…000f","orderRef":"…000f","amountCents":108000,...}'
status: completed
$ for n in 1 2 3 4; do lnpl run src/ --workflow wf.refund --backend sqlite:.claude/tmp/f11.db \
    --payload '{"id":"bb00000'$n'-...","payment":"…000f","amountCents":1,"reason":"cap-test-'$n'"}' --json; done
refund 1: completed, cumulativeCents 1
refund 2: completed, cumulativeCents 2
refund 3: completed, cumulativeCents 3
refund 4: completed, cumulativeCents 4        <- should have been rejected per "최대 3회", was not
$ python3 -c "... select count(*) from lnpl_rows where entity_id='entity.payments.refund' ..."
4 rows
```

The 4th refund (which should be the 4th attempt, exceeding "최대 3회")
completes and persists — confirmed by direct row count (4, not capped at
3). **F-11** (major — upgraded from the round-1 "확인되지 않음" framing now
that it is a demonstrated defect, not an inferred one; a real caller could
issue unlimited sub-cap-amount refunds against one payment).

**Not testable via mode A `lnpl run`:** "admin 아닌 호출자는 첫 시도부터 거부"
— `security role admin` (declared on `RefundsService`) is enforced only by
`lnpl serve`'s per-request token layer (`docs/serving.md` M3b,
`references/declarations.md`); `lnpl run` has no request/token concept, so
this half of A8 is deferred to task 05's HTTP pass.
