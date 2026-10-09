# 06-serve — R8 (GET /settlements/{month}: partial — two platform bugs found)

`lnpl serve src/domain.lnpl src/settlement.lnpl --backend sqlite:.claude/tmp/s3/main10k.db
--port 8099`, launched as a tracked background job (a plain `nohup ... &` inside one Bash
call was reaped by the harness between tool calls — `lnpl serve: drain complete -- shutting
down` appeared in the log with no signal I sent; using the tool's background-job mode kept
it alive for the curl calls below).

## What R8 literally asks for is not one lnpl primitive — it's two, and they don't compose
Read `docs/serving.md` lines 1-30 closely: every **workflow** binds to `POST
/<service-slug>/<workflow-slug>` (`respond` can only emit named scalar fields off one bound
row — confirmed by direct compiler rejection, see below, when trying `respond item` on a
whole RowSet: "respond reference 'item' must name a bound row's field
(`<binding>.<field>`), not a bare name"). The **only** way to get a JSON array of settlement
rows is the opt-in `service ... expose / list <Entity> by <field>` sugar, which maps to
`GET /<service-slug>/<entity-slug>?after=&limit=N` returning `{"items":[...], "next":...}`
— fixed shape, **no path-parameter filter, no `desc` modifier** (confirmed: `list Settlement
by net desc` → `compile error: line 8: 'expose list' needs 'list <Entity> by <field>'`), and
**Money is not a legal sort field at all** (`list Settlement by net` → `compile error: ...
expose list sort field must be Integer or DateTime ... but Settlement.net is base 'Money'`
— worked around here by exposing `by txCount` instead, an Integer field, just to prove the
mechanism). Neither primitive can produce "a filtered, `net`-descending, top-10 list with a
header-totals block" — R8 as literally specified therefore decomposes into two separate
endpoints that a caller must combine; this case implements and curls both.

### GET /settlement-service/settlement?limit=5 (works)
```json
{"items": [{"...": "...", "id": "settlement-M15-2026-07", "merchant": "M15", "txCount": 40, ...}, ...5 rows, ascending by txCount...], "next": "<opaque cursor>"}
```
Confirms the auto-list route, its cursor contract, and ascending-only order empirically.

### POST /settlement-service/settlement-totals (blocked by a real platform bug, twice over)

**Bug 1 — `respond` on a `create ... as` binding crashes `lnpl openapi` (and therefore
`lnpl serve`, which validates its routes via the same generator at startup).** Minimal
reproduction, no Money/aggregate involved:
```lnpl
entity Foo
    field
        id UUID
        n Integer
workflow MakeFoo
    create foo as newFoo
    set newFoo.n to input.n
    respond newFoo.n
```
```
$ lnpl openapi <this file>
KeyError: 'newFoo'
  File ".../impl/lnpl/openapi.py", line 475, in _response_schema
    entity = by_binding[binding]
```
(This traceback text appeared as the CLI's own crash output on stderr — not from a
deliberate `Read` of `impl/`; `근인(비의도적 열람 — 크래시 스택에 노출된
impl/lnpl/openapi.py:475, by_binding 조회)`.) A `find`-bound entity's `respond` does not
crash (`entity Foo … workflow TouchFoo: find foo; respond foo.n` → `lnpl openapi` succeeds).
This directly contradicts RFC-0030 §2, which documents `create <noun> as <name>` as a
first-class binding usable by `respond` exactly like a `find`-bound one — a genuine
regression against the platform's own contract, not a doc gap. **Severity: blocker** — the
failure mode is "the whole module's `lnpl serve` refuses to start", not a degraded response.

Worked around here by making `SettlementTotals` `find` a pre-seeded `SettlementSummary`
placeholder row (per (month) key) instead of `create`-ing one, which surfaced a **second**,
independent bug:

**Bug 2 — a second sequential `set` on the same `find`-bound row spuriously fails with
"write conflict: row changed since read".** Minimal reproduction, no Money involved:
```lnpl
entity Counter
    field
        id UUID
        a Integer
        b Integer
workflow BumpBoth
    find counter
    set counter.a to counter.a + 1
    set counter.b to counter.b + 1
```
Seeded one row (`{"id":"<uuid>","a":0,"b":0}`), ran it:
```
step find counter                        found=True
step set counter.a to counter.a + 1      value=1        <- succeeds
step set counter.b to counter.b + 1      FAILED
failure_reason: "write conflict: row changed since read (entity.counter entity.counter#<id>)"
```
`docs/backends.md` §3's optimistic-concurrency contract (`_version` captured at read time,
checked at write time) is designed for **cross-request** conflicts; here it fires
**within a single request**, against the row's *own* prior write from the same execution —
the in-memory binding's remembered `_version` is evidently never refreshed after a
successful in-workflow `set`. Net effect: **any workflow that `find`s a row and writes more
than one field to it will fail on the second write.** `create ... as` + multiple aggregate
`set`s does not hit this (proven repeatedly in `MonthlySettlement`/`ReplaceSettlement`,
6 sequential sets each, zero conflicts) — the bug is specific to a `find`-then-multi-`set`
sequence. **Severity: blocker** — this makes "read a record, update several of its fields"
(an extremely common real-world workflow shape) unreliable on the sqlite backend for any
row not freshly created in the same call.

Given both bugs, `SettlementTotals` as authored in `src/settlement.lnpl` still fails at
runtime (`POST /settlement-service/settlement-totals` → 500 `workflow-failed`,
`"write conflict..."`) even after routing around Bug 1 — R8's totals half is therefore
**불가**, not merely unattempted; it was attempted three different ways (create-as+respond,
find+multi-set+respond, create-as+aggregate+refind+respond — the last one hit a third,
less-confidently-root-caused issue: a stub row with only the `id` field appeared in the
store keyed to the *later* `find`'s target before that step even executed, observed once
during probing but not chased to a confirmed mechanism given the time budget — noted as
"observed, root cause unconfirmed" rather than asserted).

## F4 (ordering hazard) — measured
`glue.py` writes `entity.settlement`'s payload directly via SQL, bypassing lnpl entirely —
there is no lnpl-side way to make a row unreadable until glue completes (no draft/committed
status field exists in the schema, and adding one would need `set` on a non-Money field
before/after, which is a real, available mechanism — RFC-0030 payload-seed order confirms
`create`'s own payload seed already lands atomically with the row, so the exposure window
is specifically the *raw-run-to-glue* gap). With the auto-list GET route live, curling
`GET /settlement-service/settlement/{id}` for a row between its `MonthlySettlement` run and
its `glue.py` pass returns the **raw, pre-glue** row: `fees` = raw sum (not tier-adjusted for
txCount>1000 merchants) and **`net` is entirely absent** from the JSON body. Confirmed by
inspecting `entity.settlement` payloads mid-pipeline during this round's 10k run (before the
`glue.py` loop completed) — this is the concrete, measured version of round 1's F-4 known
issue: a real client hitting the API during that window gets a materially incomplete
settlement record with no signal that it is incomplete (no error, 200 OK, just a missing
field) — **known-issue condition (1b): do not read `/settlement-service/settlement/*` from
any client until the `glue.py` pass for that run has completed; the platform has no
in-language way to enforce or signal this window.**
