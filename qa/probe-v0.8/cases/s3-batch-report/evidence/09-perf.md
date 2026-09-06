# 09-perf — R7 (full: 3 reps × {1k,10k}, 100k attempt, pushdown check)

`src/bench.py`, freshly-seeded store per size (fixed a bug where an earlier version reused
a stale `bench_100000.db` across runs and hit a `create`-conflict — deleted the store before
each seed).

```
1k  raw=['0.0961', '0.0741', '0.0723'] median=0.0741
10k raw=['0.0825', '0.0768', '0.0773'] median=0.0773
10k/1k median ratio: 1.04 (linear would be ~10 if dominated by table scan; <<10 implies pushdown/index, not a full scan)
100k seed_time=0.60s run=0.1396s rc=0
```
100k completed in 0.14s — nowhere near the 600s cap, no timeout needed. Wall time is flat
(within noise) from 1k to 100k total rows for a single-merchant `MonthlySettlement`,
consistent with the sqlite driver pushing the `merchant == input.merchant` equality
predicate down to SQL rather than scanning and filtering the whole table in Python
(RFC-0038 §4's opt-in `supports_predicate` driver contract).

## Pushdown on/off/misspelled-control — switch absent
Checked `lnpl run --help` (no `--pushdown`/`--no-pushdown` or similar flag) and
`docs/backends.md` §3/§8: `supports_predicate` is a **driver-class constant** compiled into
`SqliteRepositoryDriver`, not a runtime option any CLI flag exposes. There is no way to run
the "pushdown off" arm of the control-pair against the same sqlite backend — recorded as
"switch absent" per the round-1 review's instruction, not silently skipped. The flat 1k→100k
timing above is therefore stated as "consistent with pushdown", not "proven by an on/off
comparison".
