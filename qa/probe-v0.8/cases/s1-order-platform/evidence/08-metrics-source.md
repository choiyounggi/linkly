# evidence/08 — METRICS.md source commands

```
$ find src -name '*.lnpl' | xargs wc -l
  46 src/payments/payments.lnpl
  18 src/catalog/catalog.lnpl
  91 src/orders/orders.lnpl
   8 src/orders/internal/stock.lnpl
 163 total
$ find src -name '*.lnpl' | wc -l
4
```

**Round count:** evidence/01's rounds are narrated prose (not the
`- round N:` grep-able line format D4 specified) — a self-inflicted
process deviation, noted rather than silently reformatted after the fact.
Manual tally by re-reading evidence/01/03/04/07: 4 (entity-only) + 7
(F-2 isolation) + 6 (F-3 isolation/list-where discovery) + 1 (R1 visibility
probe) + ~10 (CreateOrder workflow: money-arithmetic pivot, camelCase
binding fixes ×3, `validate` object-naming, derived-field fixes ×2,
guard-restriction rediscovery, list-where cap technique) + ~6 (Pay/Cancel/
Refund authoring, field-name/`order`-keyword collision, nested-guard
retry, cap enforcement) + 2 (openapi crash isolation + reverted workaround)
+ 4 (R10) = **~40 authoring/debug rounds total** across the whole case,
well past the point of a "quick" build — reported as `~40` (estimate
qualifier per FINDINGS-SCHEMA "값이 없으면 N/A, 추정치는 ~").

**CLI commands executed:** every `lnpl compile`/`run`/`openapi`/`serve`/
`token` invocation quoted across evidence/00–07, plus their seed calls —
not separately counted line-by-line; order of magnitude **~90** (30
compiles, ~45 mode-A runs across seeding+A1–A8+R10, 2 openapi attempts, 1
serve session with ~12 curl calls, 4 token issuances).

**Docs read:** tallied live in evidence/00 §Docs read and evidence/01 — 15
files, sizes there. Total ~2,285 lines read (SKILL.md/cli-surface.md/
references ×8/examples/linkhub.lnpl/RFC-0031/0033/0044/0030/0038, the last
one for the refund-cap breakthrough).

**Wall-clock:** session-timestamp-based, not separately logged per
D1/D4 rules — this case ran as one continuous session; the coordinator's
own token-report/session log is the authoritative timer (METRICS' 벽시계
row is left for the coordinator per the shared template's 토큰 row
convention, since both derive from the same transcript).
