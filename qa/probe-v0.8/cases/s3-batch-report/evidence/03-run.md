# 03-run — C1, C2, C3 executed output (mode A, sqlite backend)

Store: `.claude/tmp/s3/small.db`, seeded by `src/seed.py --small` (fixed after the
`money-encode-precision` round in `01-authoring.md`). Workflow: `wf.monthly.settlement`
(`src/settlement.lnpl`), `--backend sqlite:<path>`.

## C1 — M1: settled 1000/2000/3000 (fee 30/60/90), refunded 9999
```
$ lnpl run src/domain.lnpl src/settlement.lnpl --workflow wf.monthly.settlement \
    --backend sqlite:.claude/tmp/s3/small.db \
    --payload '{"id":"settlement-M1-2026-07","merchant":"M1","month":"2026-07-01T00:00:00Z","status":"settled","monthKey":"2026-07"}' --json
```
result.status = `completed`. `newSettlement` binding:
```json
{"gross": {"amount": "60.00", "currency": "USD"},
 "fees":  {"amount": "1.80",  "currency": "USD"},
 "txCount": 3,
 "avgTicket": {"amount": "20.00", "currency": "USD"},
 "maxTicket": {"amount": "30.00", "currency": "USD"},
 "minTicket": {"amount": "10.00", "currency": "USD"}}
```
Expected (s3.md C1): gross 6000, fees 180, count 3, avg 2000, max 3000, min 1000 (cents) →
**exact match** ($60.00/$1.80/3/$20.00/$30.00/$10.00). The refunded 9999 row is correctly
excluded by `status == input.status` ("settled"). `net` is absent here — R3's net = gross −
fees is a Money subtraction, which `set` rejects outright (see `02-compile.md`); computed
by `src/glue.py` instead, see below.

## C2 — M2: zero transactions
Same call with `merchant: "M2"`. Result: `status: failed`.
```
ERROR step failed: "set newSettlement.avgTicket to avg transaction.amount",
reason: "aggregate 'avg transaction.amount': avg-of-empty-rowset — averaging 'amount' needs at least one row"
```
`sum`/`count` had already run and produced 0/0 (per RFC-0025's "empty RowSet → sum/count
=0" contract) before `avg` raised `RunError avg-of-empty-rowset` (RFC-0045 §3-4, "빈
집합의 평균은 정의되지 않는다"). **Checked the store directly afterward — no
`entity.settlement` row for M2 exists.** The workflow's writes (including the `create`
that had already logged `assignment applied` for gross/fees/txCount) were not persisted
when a later step in the same run failed — this is a positive finding: a failed run leaves
no partial/corrupt row, so **C2's answer, sourced from executed behavior, is "Settlement
행 없음"** (no row), not "0-row present". This resolves s3.md's own open question ("어느
쪽인지 문서 근거로 결정·기록") from actual runtime behavior since no doc states it
explicitly.

## C3 — M3: 1001 settled × amount 100 / fee 3
Same call with `merchant: "M3"`. `status: completed`.
```json
{"gross": {"amount": "1001.00", "currency": "USD"},
 "fees":  {"amount": "30.03",  "currency": "USD"},
 "txCount": 1001,
 "avgTicket": {"amount": "1.00", "currency": "USD"},
 "maxTicket": {"amount": "1.00", "currency": "USD"},
 "minTicket": {"amount": "1.00", "currency": "USD"}}
```
`fees` here is the **raw** sum (3¢ × 1001 = 3003¢ = $30.03) — the tier rule (R4:
txCount>1000 ⇒ fees = 1.5% of gross) is a Money multiply, also rejected by `set`
(`02-compile.md`). `src/glue.py` reads the row back, applies the tier rule with
half-to-even rounding to the cent, and writes fees/net directly into the sqlite payload
(the only remaining write path — `update`+`set` on a Money field is rejected the same as
`create`, so this cannot go back through `lnpl run` at all):
```
$ .venv/bin/python3 src/glue.py --store .claude/tmp/s3/small.db --settlement-id settlement-M3-2026-07
"fees": {"amount": "15.02", "currency": "USD"}   # 1001.00 * 0.015 = 15.015 -> half-to-even -> 15.02
"net":  {"amount": "985.98", "currency": "USD"}  # 1001.00 - 15.02
```
Matches s3.md's own worked value (1.5% of 100100¢ = 1501.5¢) and names the rounding rule
(half-to-even, ties to the even cent — 15.015 is exactly halfway, 15.02 is the even
neighbor) exactly as required. Cross-checked M1 through the same script (txCount=3, tier
rule does not fire): `fees` unchanged at $1.80, `net` = $58.20 = 60.00 − 1.80, correct.

## Coverage this file feeds
R3 (aggregate values, minus net — see glue.py), R4 (raw fee sum; tier rule via glue.py),
R6 (exact match against the hand-computed s3.md expected values for C1/C3; a full 10k
independent-oracle diff was not run — see FINDINGS "Frictions"/coverage table).
