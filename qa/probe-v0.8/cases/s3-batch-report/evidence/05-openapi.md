# 05-openapi — R8 support artifact

```
$ lnpl openapi src/domain.lnpl src/settlement.lnpl -o openapi.json
wrote openapi.json (10 path(s))
```
rc=0 (after fixing the two `06-serve.md` bugs' authoring-side triggers — the final
`settlement.lnpl` uses `find`-bound `respond` targets only, never `create ... as` +
`respond`, to avoid Bug 1). Paths generated:

| Path | Method | Source |
|------|--------|--------|
| `/settlement-service/monthly-settlement` | POST | `workflow MonthlySettlement` |
| `/settlement-service/replace-settlement` | POST | `workflow ReplaceSettlement` |
| `/settlement-service/settlement-totals` | POST | `workflow SettlementTotals` (runtime still fails — Bug 2, `06-serve.md`) |
| `/settlement-service/settlement` | GET | `expose / list Settlement by txCount` |
| `/settlement-service/settlement/{id}` | GET | auto (Settlement is read/written by this service) |
| `/settlement-service/settlement-summary/{id}` | GET | auto (SettlementSummary is read by `SettlementTotals`) |
| `/settlement-service/transaction/{id}` | GET | auto (Transaction is read by `MonthlySettlement`) |
| `/rollup-service/compute-daily-rollup` | POST | `workflow ComputeDailyRollup` |
| `/rollup-service/daily-total/{id}` | GET | auto |
| `/rollup-service/transaction/{id}` | GET | auto |

Confirms the URL-slug convention empirically: kebab-case of the **full** declaration name
(service/workflow/entity), NOT the dotted-and-trailing-word-dropped node-id form
`naming.md` documents for internal ids (`SettlementService` → `settlement-service`, keeping
"-service"; `MonthlySettlement` → `monthly-settlement`). `lnpl serve`'s own startup check
(route set must match `lnpl openapi`'s output, `docs/serving.md` line 18) passed — the
server bound successfully on this final module.

## Authoring-time discovery costing 2 rounds: assignment-target binding name is camelCase, not the lowercase-concatenated step-object form
`naming.md` documents the lowercase-concatenated form (`settlementsummary`) for referring to
an entity as a step **object** (`find settlementsummary`). It does **not** document that a
*later* `set`/`respond` reference to that **same binding** must use **camelCase**
(`settlementSummary`) instead — for a single-word entity the two forms are identical
(`bookmark` == `bookmark`), which is why every example this case's authoring read
(`examples/linkhub.lnpl`, the RFC-0030 `newOrder` examples) never exposed the discrepancy.
Reproduced minimally:
```lnpl
entity ReportSummary
    field
        id UUID
        total Integer
workflow MakeSummary
    find reportsummary                    # lowercase-concat object -- resolves fine
    set reportsummary.total to ...        # compile error: 'reportsummary' is not a declared entity
    set reportSummary.total to ...        # camelCase -- compiles
```
`doc` axis, minor severity (2 rounds, no semantic loss once found) — but the naming rule for
the binding a `find` *creates* is a different rule than the naming rule for the step
*object* used to find it, and only `naming.md`'s object-resolution table is documented.
