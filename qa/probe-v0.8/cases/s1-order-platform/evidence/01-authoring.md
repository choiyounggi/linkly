# evidence/01 — Authoring rounds

Layout chosen (RFC-0031 다중 파일 컴파일 단위 + RFC-0033 네임스페이스): `src/`
has no `*.lnpl` directly under it → namespace-root layout. Each first-level
subdir is a namespace:

```
src/
  catalog/catalog.lnpl        # namespace catalog: Product, Category
  orders/orders.lnpl           # namespace orders: Customer, Order, OrderLine, StockReservation
  orders/internal/stock.lnpl   # orders/internal/ — Stock, visibility-scoped to orders (R1)
  payments/payments.lnpl       # namespace payments: Payment, Refund
```

`lnpl compile src/` merges all three namespaces into one unit — satisfies
R1's "한 번에 컴파일·실행" without inventing an `internal`/`use` keyword
(RFC-0031 §Alternatives rejected that).

## Rounds

- round 1: `lnpl compile src/` → rc=2, `field name 'on_hand' must be a lowercase word ... ^[a-z][a-zA-Z0-9]*$`.
  Why: field names may not contain `_` (grammar requires bare camelCase, undocumented in the domain prose of s1.md, which uses snake_case field names like `on_hand`, `card_last4`, `created_at`). Renamed every snake_case field to camelCase (`onHand`, `cardLast4`, `createdAt`, `unitPrice`→`unitPriceCents`, `line_total`→`lineTotalCents`).
- round 2: `lnpl compile src/` → rc=0 (9 entity nodes). Verified namespace ids via IR: `entity.orders.stock`, `entity.orders.order.line`, `entity.payments.payment`, etc. — internal/ folded `Stock` into the `orders` namespace as intended (RFC-0033).
- round 3: added a scratch `workflow MoneyProbe` (`find orderline` + `set orderline.lineTotal to orderline.unitPrice * orderline.qty`, both fields declared `Money`) to probe R3's money math → rc=2, `assignment target 'orderline.lineTotal' names 'orderline', which is not a declared entity`. Not the Money diagnostic expected — isolated further (round 3a-3g, see F-2 below) before reaching the actual Money-arithmetic diagnostic.
- round 3a-3g (isolated in `.claude/tmp/flat_probe/*.lnpl`, outside the case dir, per D9's exploratory-probe pattern — not part of the graded src/):
  - `find orderline` alone → rc=0 (binding is legal for reads).
  - `set orderline.qty to orderline.qty` (Integer field, still via bare `find`) → same "not a declared entity" error.
  - Control: single-word entity `Order`, `find order` + `set order.qty to order.qty` → rc=0.
  - `set OrderLine.qty` (PascalCase) → different error: `assignment target must be camelCase or binding.field`.
  - `find orderline as line` + `set line.qty` → same "not a declared entity" (find does not support `as` — confirmed against grammar.md, which only documents `as` for `create`/`insert`).
  - `create orderline as line` + `set line.qty to line.qty` → **rc=0**. `as`-bound create results are writable (RFC-0030); bare multi-word reads are not.
  - `create orderline as line` + `set line.lineTotal to line.unitPrice * line.qty` (Money target) → rc=2, the real Money-arithmetic diagnostic (quoted in evidence/02-compile.md and FINDINGS F-1).
  - This is F-2 (doc axis): grammar.md states "읽기 동사(`authenticate`/`load`/`find`/`read`)가 단일 행 바인딩을 만들고, `set`은 그 바인딩에 쓴다" without qualification, but empirically that only holds for **single-word** entity names (`order`); multi-word entities (`OrderLine`, `StockReservation`) reached via a bare read verb are rejected by `set`'s target resolver with "not a declared entity" — the document doesn't name this restriction. Workaround: never `find`+`set` a multi-word entity; always `create <entity> as <alias>` when a multi-word entity's fields must be written in the same workflow. No semantic loss for this case's domain, since OrderLine/StockReservation are write-once at order-creation time.
- round 4: after F-1's discovery, pivoted `Money` fields that need arithmetic or guard comparison to `Integer` (`*Cents` suffix, s1.md's own R3 wording — "전부 센트 정수 정밀도" — already implies integer-cents, so this is not a stretch of the requirement): `Product.priceCents`, `Order.{subtotal,discount,tax,total}Cents`, `OrderLine.{unitPrice,lineTotal}Cents`, `Payment.amountCents`, `Refund.amountCents`. Compiled clean, rc=0 (9 nodes, `.claude/tmp/round4.lir.json`).
- R1 visibility probe round: copied `src/` to `.claude/tmp/r1-probe-tree/`, added `payments/violation.lnpl` (`workflow PeekStock` / `find stock`) — `payments` namespace referencing `orders/internal`'s `Stock`. `lnpl compile .claude/tmp/r1-probe-tree/` → rc=2: `` `find stock` references 'Stock', declared `internal` to namespace 'orders' — not visible from namespace 'payments' (RFC-0033 `internal/` visibility)``. Confirms R1's visibility requirement is enforced. Re-ran `lnpl compile src/` (untouched) immediately after → rc=0, unaffected.

### F-2 correction (superseding the initial note above)

Further isolation (`.claude/tmp/find_probe/probe4.lnpl`) found the real rule:
`find`/`load`/`read` bind the row under the entity's **camelCase** binding
name (`repo_policy.binding_name`: first letter lowercased, rest untouched —
`OrderLine` → `orderLine`), while the **step object** you type to select
*which* entity to read uses the fully-lowercased concatenated form
(`orderline`, `naming.md`). `find orderline` + `set orderLine.qty to
orderLine.qty` compiles and runs cleanly with **no** `create ... as` needed.
F-2 is downgraded from "multi-word entities can't be `set` after `find`" (false
— my error) to: **the read-step object spelling and the later
value/assignment-reference spelling of the same entity are two different
casing conventions, and neither `references/naming.md` nor `references/
grammar.md` says so in one place** — doc axis, minor, cost ~7 rounds to find.

### F-3 (blocker) — every entity touched in one execution shares one payload `id`

`impl/lnpl/repo_policy.py::row_key(entity_id, payload)` returns
`f"{entity_id}#{payload.get('id','-')}"` — **the row key for every
`find`/`load`/`read`/`create` in a single workflow execution is keyed off the
same top-level payload `id` field**, regardless of which entity or which step
object name is used (verified by reading `repo_policy.py` to confirm the root
cause after the empirical test below — README §2 exception, root cause only,
no fix attempted). Empirically confirmed with a 2-entity probe
(`.claude/tmp/find_probe/probe5.lnpl`, `Product`+`Order`, `find product` then
`create order as newOrder`): placing a **second** order for the **same**
product (`payload.id` = the product's id, needed so `find product` resolves
it) fails: `repository create conflicts: entity.order already exists` — the
new Order's row key collided with the first order's, because both derived
from the same shared `id`. The golden example `examples/checkout.lnpl`
structurally has the identical shape (`find product` + `create order`, no
`as`, no explicit id story) and its own comment admits this is only "green"
because its Order table starts empty — it does not demonstrate two checkouts
of the same product in one suite run. **This makes CreateOrder as literally
"look up an existing Product/Customer by their real id, then create a new
Order with its own fresh id" impossible via plain `find`+`create` in one
execution — a foundational blocker for R2's "multiple orders against one
catalog" shape**, axis `expr`, would be a genuine stop-the-case blocker.

**Workaround found (`.claude/tmp/find_probe/probe6.lnpl`), no semantic loss for
the read side:** replace `find <entity>` (id-keyed single-row read) with
`list <entity> where id == input.<fieldNameMatchingSomeDeclaredField>`
(RFC-0038 equality predicate — unlike order comparisons, `==`/`!=` in `list
where` is not restricted to Integer/DateTime, RFC-0038 §Guide-level
Explanation) to look the row up by an **arbitrary** input field, independent
of the top-level payload `id`. That binds a RowSet, not a single row, so a
field is pulled back out via `max <entity>.<field>` (or `min`) — safe because
the predicate guarantees at most one matching row for a unique key. Verified:
`newOrder.id` keeps its own fresh value, `newOrder.priceCentsSeen` correctly
reads the found product's price, and a **second** order against the same
product succeeds (no conflict) once `id` is freed up for the Order's own
identity. Edge case also verified: if the predicate matches zero rows,
`max <entity>.<field>` fails the run cleanly —
`aggregate 'max product.priceCents': min-max-of-empty-rowset — 'max
priceCents' needs at least one row` (`status: failed`, a real `RunError`, not
a silent guard-skip) — this doubles as our "referenced row does not exist"
rejection path. **Residual semantic loss:** `input.<field>` must spell a name
that some declared entity field already uses (`spec.md` "입력 네임스페이스"
union rule) — payload keys are constrained to the domain's existing field
vocabulary, not free client-chosen names, and this whole workaround itself
(discovering + validating it) cost ~6 rounds not budgeted by the docs.

**Bonus finding used as a design lever:** the platform's "가드 거부는 200이다"
rule (`docs/serving.md` M9 — a guard skip still reports `completed`/200) does
**not** apply to a `RunError` (create conflict, empty-RowSet aggregate,
`money-encode-precision`, etc.) — those map to M8/M8a (500/409), a real
non-200 failure. Where a requirement needs an actual rejected status code
(R2/R4/R5/R6/R7), guarding with `list where` predicates that force an
empty-RowSet `RunError` on business-rule violation is used in place of a bare
`when` skip, specifically because a bare guard-skip would silently return 200
— see F-4 in FINDINGS.md.

Total authoring rounds this task: 4 (entity-only) + 7 sub-rounds isolating F-2
+ 6 sub-rounds isolating/solving F-3 + 1 R1 probe = 18 (all in
`.claude/tmp/find_probe/` and `.claude/tmp/r1-probe-tree/`, outside the graded
case dir per D9).

## `.lnpl` vocabulary decisions taken from the docs (traceability)

- Field name charset `^[a-z][a-zA-Z0-9]*$`: discovered by compiler diagnostic (round 1); not stated in `references/types.md` or `references/grammar.md` before hitting it.
- Namespace/`internal/` layout: `rfcs/0031-multi-file-compilation-unit.md`, `rfcs/0033-namespace-directories.md` (both public, README §2-allowed).
- Guard fields must be Integer/DateTime: `plugins/lnpl/skills/lnpl-authoring/references/grammar.md` "가드의 스코프" section, line ~99.
- Money cannot be a `set`/guard arithmetic operand: `rfcs/0044-money-arithmetic.md` §Guide-level Explanation ("이 RFC가 열지 않는 것"), confirmed empirically (F-1).
- `create ... as <name>` writable result binding, payload-seed-on-create: `rfcs/0030-create-result-binding-and-payload-seed.md`.

## Docs read (running list, started in evidence/00-env.md)

- AGENTS.md — 66 lines
- plugins/lnpl/skills/lnpl-authoring/SKILL.md — 77 lines
- plugins/lnpl/skills/lnpl-authoring/cli-surface.md — 491 lines
- examples/linkhub.lnpl — 112 lines
- plugins/lnpl/skills/lnpl-authoring/references/types.md — 66 lines
- plugins/lnpl/skills/lnpl-authoring/references/grammar.md — 143 lines
- plugins/lnpl/skills/lnpl-authoring/references/verbs.md — 35 lines
- plugins/lnpl/skills/lnpl-authoring/references/declarations.md — 59 lines
- plugins/lnpl/skills/lnpl-authoring/references/naming.md — 70 lines
- plugins/lnpl/skills/lnpl-authoring/references/spec.md — 93 lines
- plugins/lnpl/skills/lnpl-authoring/references/patterns.md — 14 lines
- rfcs/0031-multi-file-compilation-unit.md — 260 lines
- rfcs/0033-namespace-directories.md — 345 lines
- rfcs/0044-money-arithmetic.md — 333 lines
- rfcs/0030-create-result-binding-and-payload-seed.md — 272 lines
- rfcs/0038-list-where-predicate.md — 370 lines
- rfcs/0028-arithmetic-and-alternative-guards.md — read for §1 Integer division truncation contract (F-5)

## Rounds (D4 format — reconstructed round 2, per reviewer F3; round 1 used narrative prose instead, F-16)

- round 1: `lnpl compile src/` → rc=2, snake_case field names rejected (must be `^[a-z][a-zA-Z0-9]*$`)
- round 2: camelCase rename → rc=0, 9 entity nodes
- round 3: added scratch `workflow MoneyProbe` (Money*Integer `set`) to probe R3 → rc=2, wrong error (binding-name confusion, not yet the Money diagnostic)
- round 4: isolated `find orderline` alone → rc=0 (binding legal for reads)
- round 5: isolated `set orderline.qty to orderline.qty` (bare find) → same "not a declared entity" error
- round 6: control test, single-word entity `Order` → rc=0 (confirms multi-word-only symptom)
- round 7: tried PascalCase target `set OrderLine.qty` → different error ("must be camelCase or binding.field")
- round 8: tried `find orderline as line` (alias on a read verb) → same failure (grammar.md only documents `as` for create/insert)
- round 9: `create orderline as line` + `set line.qty` → rc=0 (create-as binding is writable)
- round 10: `create orderline as line` + `set line.lineTotal to line.unitPrice * line.qty` (Money target) → rc=2, the real F-1 diagnostic
- round 11: pivoted all money fields Order/OrderLine/Payment/Refund to Integer(`*Cents`) → rc=0, 9 nodes
- round 12: re-probed `find orderline`+`set orderLine.qty` (camelCase binding name, not alias) → rc=0 — corrects round 4-9's conclusion: multi-word entities don't need `create...as`, just the camelCase binding spelling (F-2)
- round 13: read RFC-0031/0033 (multi-file/namespace), designed `src/{catalog,orders,orders/internal,payments}` layout
- round 14: R1 visibility probe (`.claude/tmp/r1-probe-tree/payments/violation.lnpl`, `find stock` from `payments`) → rc=2, `not visible from namespace 'payments'` (R1 confirmed)
- round 15: first CreateOrder draft with `find customer`/`find catalogproduct`/`find stock` (each keyed by top-level payload `id`) → rc=0, but same-product two-order run → rc conflict on the 2nd order (F-3 discovered)
- round 16: isolated F-3 on a 2-entity fixture (`probe5.lnpl`) → confirmed `row_key` always uses payload `id` regardless of entity (`impl/lnpl/repo_policy.py` read, root cause)
- round 17: tried `list <entity> where id == input.<field>` + `max`/`sum` extraction (RFC-0038) → rc=0, resolved F-3 for reads
- round 18: verified empty-rowset-on-`max`/`min` forces a real `RunError` (not a silent 200) — adopted as the R2/R5/R7 rejection mechanism (F-4's workaround)
- round 19: rewired CreateOrder onto `list where` for customer/product/stock → rc=2, `validate order` entity-ambiguity error (9 declared entities)
- round 20: named `validate order` explicitly → rc=0
- round 21: `set line.unitPriceCents to catalogproduct.priceCents` (qualified cross-namespace value ref) → rc=2, "not a declared entity" — cross-namespace values need the short bare form (`product`), only the step object needs the qualified form
- round 22: fixed to `product.priceCents` → rc=0, 63 nodes
- round 23: first full `lnpl run` of CreateOrder (A1) → rc=2, `set newOrder.customer to input.customer` (UUID target) rejected — same class as F-1, but for any non-Integer/DateTime field, not just Money
- round 24: removed all UUID `set`s, relied on payload-seed-on-create (RFC-0030 §4) for `customer`/`product`/`order` FK fields instead
- round 25: added `discountCents` vip branch via `when customer.tier==1` → rc=2, "guard must not depend on a value this workflow changed" (customerTier had been `set` earlier)
- round 26: replaced the branch with arithmetic (`discountCents * customerTier`, 0/1 flag) — no guard needed, rc=0
- round 27: A1 mode-A run → correct subtotal/discount, tax/total off-by-one vs s1.md (F-5, expected per s1.md's own caveat)
- round 28: A3 (insufficient stock) run → real `failed` status confirmed, `policy rollback` verified via direct sqlite read (0 rows)
- round 29: Ship/Cancel first draft, `validate order` on a `{"id":...}`-only payload → rc=failed, "missing required field 'customer'" — removed `validate order` from Ship/Cancel (not needed, payload is minimal)
- round 30: CancelOrder single-guard design (`when status==1` pipeline + `when status==0` pipeline sharing the same field) → rc=2, same self-set-guard error again, now on `order.status`
- round 31: tried nested `pipeline` inside a guarded `pipeline` → rc=2, "pipeline block has no steps" (guard-as-first-line-of-a-pipeline doesn't parse as expected)
- round 32: flattened to one unconditional `list payment where...` before the guard, one guarded pipeline after → rc=2, `aggregation-orphaned-list` warning (list still read as "possibly guarded")
- round 33: moved the `list` fully outside/before the `when` → rc=0, clean
- round 34: A6/A7 mode-A runs → both correct at the time (A7's read-back gap discovered later, round 2 rework, evidence/03)
- round 35: Pay workflow, mismatched-amount guard (A5) → rc=0 directly (guard on `order.totalCents`/`order.status`, both read via `find`, never self-set — no repeat of round 25's error)
- round 36: Refund workflow, first draft with no cap check → rc=0 but 3 sequential refunds all "succeeded" (no cap at all)
- round 37: added cumulative-cap via `list payment where amountCents >= newRefund.cumulativeCents` (a `list where` referencing a field *this workflow just `set`*) → rc=0 — discovered this is legal where the identical pattern in a `when` guard (round 25/30) is not (F-10)
- round 38: `lnpl openapi src/` → `KeyError: 'newOrder'` (F-12); tried `find <entity>` before `respond` as a workaround → openapi succeeds
- round 39: re-ran mode A with the workaround in place → `create order` now fails with a false "already exists" conflict on a brand-new id (F-13); isolated on a 2-line fixture, reverted the workaround everywhere (3 workflows)
- round 40 (R10, evidence/07): gift_wrap `pipeline` with no closing control keyword absorbed the entire rest of the workflow into its guard (F-15); fixed with an empty `pipeline reserve` immediately after to force closure
- round 41 (rework, per reviewer F1): `given: stored Customer id X` (bare form) invisible to `list where`; switched to `stored Customer[0] id X` (RFC-0025 §8 indexed form) — resolved immediately (F-17)
- round 42 (rework, per reviewer F3): F-11 boundary test (four 1-cent refunds against a 108000-cent payment) — count cap confirmed absent by direct execution, not code review

Total: 42 rounds reconstructed (vs. round 1's "~40" narrative estimate —
close, not identical, because narrative prose in round 1 grouped some
sub-attempts together that this reconstruction lists separately, and vice
versa for a few compile-only syntax fixes that weren't narrated as
distinct rounds originally).
