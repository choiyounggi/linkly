# 08-rerun-oracle — R5 (idempotent rerun) and R6 (full 10k oracle)

Round 2 supersedes round 1's small-fixture-only version: everything below ran against
`.claude/tmp/s3/main10k.db` (fresh 10k/50-merchant seed), driven by `src/run_settlement.py`
(one `lnpl run`/`lnpl trigger` subprocess call per merchant — no in-language per-group loop
exists, see F-1-style finding in FINDINGS.md) and checked by `src/oracle.py`.

## R6 — full 10k, all 50 merchants, 7 fields, 3 rounding rules
```
$ python3 src/oracle.py --store .claude/tmp/s3/main10k.db --size 10000
merchants expected: 50, settlement rows found: 50
matched rounding rule: half_even
mismatches: 0
```
`oracle.py` regenerates the dataset from `seed.py`'s own generator (imported, never reads
the lnpl store) and independently computes gross/txCount/maxTicket/minTicket/avgTicket/
fees(tier-adjusted)/net for all 50 merchants under three candidate rounding rules (floor,
half-up, half-even) before comparing to the actual `Settlement` rows (post-`glue.py`). Zero
mismatches under half-even for all 50 merchants × 7 fields — confirms half-to-even both for
lnpl's own `avg` aggregate (RFC-0044 §4's stated policy) and for `glue.py`'s hand-rolled
tier-fee rounding.

## R5 — same month, all 50 merchants, run twice
Pass 1: `run_settlement.py --pass first` → `wf.monthly.settlement` × 50, `50/50 completed`.
Pass 2 (idempotent rerun): `run_settlement.py --pass replace` → `wf.replace.settlement`
(find→delete→recreate, per round 1's F-2) × 50, `50/50 completed`. Both passes' raw
CLI `--json` outputs saved (`run1.json`, `run2.json`, pre-`glue.py`, so directly comparable
field-for-field):
```
$ python3 src/oracle.py --store .claude/tmp/s3/main10k.db --compare-runs run1.json run2.json
run A: 50 rows, run B: 50 rows
field diffs: 0
```
50/50 rows both runs, 0 field diffs across gross/fees/txCount/avgTicket/maxTicket/minTicket.
R5 holds at full 10k scale via the same delete-then-recreate mechanism round 1 established
at small scale (Money fields cannot be `update`d — F-1's root cause repeats here).

## R2/C5 — daily rollup, full 10k, 2026-07-15
`src/run_rollup.py` triggers `event.daily.rollup` once per merchant for `dayKey=2026-07-15`
(same external-loop shape as `run_settlement.py`): `50/50 completed`.
```
$ python3 src/oracle.py --store .claude/tmp/s3/main10k.db --daily 2026-07-15 --size 10000
merchants with settled tx on 2026-07-15: 43, DailyTotal rows matched: 50
mismatches: 0
```
43 of 50 merchants had at least one settled transaction that day; all 50 still got a
`DailyTotal` row (7 merchants got a legitimate zero-row: `sum`/`count` are defined as 0 on
an empty RowSet, RFC-0025 — unlike `MonthlySettlement`'s `avg`/`min`/`max`, which fail
outright on an empty RowSet, round 1's C2 finding). 0 mismatches on gross+count for the 43
merchants with real activity — this is a positive design-consequence finding: a rollup
built only from `sum`/`count` degrades gracefully on empty input; one built from
`avg`/`min`/`max` (like `MonthlySettlement`) does not.
