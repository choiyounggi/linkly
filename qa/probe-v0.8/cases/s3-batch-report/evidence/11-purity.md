# 11-purity — scope purity proof (D17), round 2

```
$ git status --porcelain -uall | grep -v '^?? qa/probe-v0.8/cases/s3-batch-report/'
(empty)

$ git diff --stat -- impl scripts plugins docs rfcs examples README.md
(empty)
```
Both empty after round 2's additional work (oracle.py, bench.py, run_settlement.py,
run_rollup.py, serve/curl testing, migrate testing, spec block, openapi generation) — no
files outside `qa/probe-v0.8/cases/s3-batch-report/` were created or modified, protected
paths still have zero diff.

`impl/` read count: **0 deliberate `Read` calls.** One CLI crash (`lnpl openapi` on a
`create ... as` + `respond` combination, `06-serve.md` Bug 1) printed a Python traceback to
stderr that named `impl/lnpl/openapi.py:475` and the `by_binding` variable as a side effect
of the crash itself — this was not a deliberate file open, but the traceback text is enough
to state the root cause precisely, so no follow-up `Read` of that file was made. Every other
finding in this round (migrate's silent no-op, the write-conflict bug, the camelCase
binding-name rule, `expose`'s syntax and its Money/desc restrictions) was established purely
from compiler/runtime/CLI output and the allowed docs — zero additional impl/ exposure.

Sweep compile: `lnpl compile --strict=warning src/*.lnpl` → rc=0, 1 expected info diagnostic
(`declared-not-enforced` on the schedule event), 0 unknown-entity/unknown-verb.

`ls .claude/tmp/s3`: seed stores (`main10k.db`, `main10k_backup.db`,
`main10k_restored.db`, `bench_*.db`, `perf_*.db`, `small.db`), run/curl/compile output
captures referenced above, temp payload JSON files from `run_settlement.py`/`run_rollup.py`
(auto-deleted after each subprocess call). Not committed (sqlite binaries / scratch); all
regenerable deterministically (seed=42) except the backup/restore pair, which is
regenerable by re-running the R9 sequence in `10-backfill.md`.
