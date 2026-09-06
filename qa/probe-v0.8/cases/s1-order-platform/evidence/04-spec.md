# evidence/04 — spec (R9)

**Revision (round 2, per reviewer F1):** the original round-1 evidence
labeled this 불가(시간 상한). On rework, real spec blocks were authored
for all of A1–A8 and ran green. The round-1 "시간 상한" claim is retracted —
what actually blocked spec authoring first (round 2 below) was a genuine
discovery, not a clock limit.

## Round 2 discovery — `given: stored <Entity> <field> <value>` (bare form) is invisible to `list where`

First attempt used the bare `stored Customer id ...` form (as in
`examples/linkhub.lnpl`'s spec blocks, which only use `find`). It compiled
and ran, but every `list`-consuming assertion failed as if the store were
empty:

```
$ lnpl spec src/ --run
FAIL CreateOrder spec — rows Order 1 (Order rows=0 want=1)
     reason: aggregate 'max customer.tier': min-max-of-empty-rowset
```

Isolated on a two-line fixture (`.claude/tmp/spec_probe/probe2.lnpl` vs
`probe3.lnpl`): `stored Customer id X` + `find customer` → **works**;
`stored Customer id X` + `list customer` → **row_count 0**. `spec.md`'s own
"저장소 시드와 create 충돌" section documents a *second*, indexed form —
`stored <entity>[<i>] <field> <value>` — specifically for this
("`list <entity>`가 읽는 RowSet을 이렇게 채운다") — I had read past it
without registering that our design (every lookup is `list where`, per
F-3's `find`-shares-one-id workaround) makes the indexed form mandatory,
not optional. Switching every `stored` line that feeds a `list`-consumed
entity to `stored Entity[0] ...` fixed all of it immediately. **F-17**
(minor, `doc` axis — the two forms sit in the same doc section, one line
apart, and nothing marks the plain form as unusable for the now-common
`list where` pattern).

## Final run — 9 scenarios / 33 assertions, all green

```
$ lnpl compile src/ --strict=warning -o /dev/null   # rc=0
$ lnpl spec src/ --run --strict=warning
PASS CreateOrder spec 1 — completed / effects complete / rows Order 1 / rows OrderLine 1 /
     result newOrder.subtotalCents == 3998 / result newOrder.discountCents == 0        (A1)
PASS CreateOrder spec 2 — completed / effects complete /
     result newOrder.subtotalCents == 5997 / discountCents == 599 / totalCents == 5829 (A2)
PASS CreateOrder spec 3 — failed / rows Order 0                                        (A3)
PASS CancelOrder spec 1 — completed / effects complete / rows Refund 1 /
     result order.status == 4 / result newRefund.amountCents == 1078                   (A7)
PASS CancelOrder spec 2 — completed / rows Refund 0 / result order.status == 2         (A6)
PASS Pay spec 1 — completed / effects complete / rows Payment 1 /
     result newPayment.status == 1 / result order.status == 1                          (A4)
PASS Pay spec 2 — completed / rows Payment 0                                           (A5)
PASS Refund spec 1 — completed / rows Refund 3 / result newRefund.cumulativeCents == 4300 (A8, within cap)
PASS Refund spec 2 — failed / rows Refund 2                                            (A8, exceeds cap)
spec: 33 passed, 0 failed
```

Full transcript: `.claude/tmp/spec_full_run.log`. 9 spec blocks (5 in
`orders/orders.lnpl`, 4 in `payments/payments.lnpl`) cover A1–A8 — A8 is
split into two blocks (within-cap success, cap-exceeded failure) since a
single `given`/`when`/`expect` block cannot express the three-call
sequence A8 narrates; each block instead seeds the *prior* cumulative state
directly (`stored Refund[0]`/`[1]` at 2000 each) and asserts the marginal
call's outcome — equivalent to A8's real behavior (confirmed against mode
A's actual 3-call sequence, evidence/03 §payments) without re-deriving the
whole sequence in-process.

Every `A` scenario keeps the case's own actually-computed values (3998/
599/5829/etc — see F-5), not s1.md's literal 3998/600/5829/4318 table —
consistent with mode A's results, not a new deviation.

## D3 — prove the spec can fail

```
$ sed -i 's/result newOrder.subtotalCents == 3998/result newOrder.subtotalCents == 3999/' src/orders/orders.lnpl
$ lnpl spec src/ --run --strict=warning
FAIL CreateOrder spec 1 — result newOrder.subtotalCents == 3999 (-> False)
spec: 12 passed, 1 failed
$ sed -i 's/result newOrder.subtotalCents == 3999/result newOrder.subtotalCents == 3998/' src/orders/orders.lnpl
$ lnpl spec src/ --run --strict=warning
spec: 13 passed, 0 failed   # (13, not 33 — this was run before A4–A8's blocks were added; the flip/restore cycle itself is the point)
```

Green → red (wrong expected value rejected) → green (restored) — the
suite is not a tautology.

## Role-based rejection (A8's other half) — still not exercisable via spec

`security role admin` is an HTTP-layer (`lnpl serve`) concept
(`docs/serving.md` M3b) — `spec`'s executed workflow has no token/role
context at all, so "admin 아닌 호출자는 거부" is outside what `spec` can
assert regardless of authoring effort. This is unchanged from round 1 and
is not a new gap — recorded under F-14 (`lnpl token` has no `--role` flag)
and evidence/06 (HTTP layer), not claimed as covered here.
