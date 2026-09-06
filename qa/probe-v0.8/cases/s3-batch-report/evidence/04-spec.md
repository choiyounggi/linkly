# 04-spec — R10 round 2: C1/C2/C3-analog all pass; rerun surfaces a new spec-runtime bug (F-10)

Four `spec` blocks total now (`src/settlement.lnpl`): C1 on `MonthlySettlement` (round 1,
unchanged), C2 and a C3-scale-analog added to `MonthlySettlement` this round, and one rerun
block added to `ReplaceSettlement`.

```
$ lnpl spec src/domain.lnpl src/settlement.lnpl --run
spec: 24 passed, 7 failed
```

## C1 (unchanged from round 1) — 9/9 PASS
See round 1's record; re-verified clean after the domain.lnpl schema additions
(`SettlementSummary`, `Settlement.monthKey`, `Transaction.currency`) between rounds.

## C2 — zero transactions for the merchant — 4/4 PASS
```
given: merchant M2, status settled, monthKey 2026-07 (no transaction rows stored)
when: monthlySettlement
expect: failed | effects complete | error reason avg-of-empty-rowset | rows Settlement 0
```
All 4 assertions pass first try. Confirms round 1's C2 finding (`03-run.md`) is also
expressible and provable via `spec`, not just via a manual `lnpl run` + store inspection:
the workflow fails on the `avg` step over an empty RowSet, and — critically — leaves **zero**
`Settlement` rows (spec's own row-count check independently confirms the "no partial row on
failure" behavior `03-run.md` established by hand).

## C3 — scale analog (3 settled transactions, not literally 1001) — 6/6 PASS
```
given: 3 stored transaction[i] rows for M3, amount 1.00USD / fee 0.03USD each
when: monthlySettlement
expect: completed | rows Settlement 1 | gross==3.00USD | fees==0.09USD | txCount==3 | avg/max/min==1.00USD
```
**Not a literal reproduction of s3.md's C3** (1001 settled transactions) — `stored
transaction[i]` is a hand-authored, one-line-per-field-per-row fixture mechanism
(`references/spec.md`, RFC-0025 §8) with no batch/programmatic form; 1001 rows would be
~6,000 lines of `.lnpl` source, which defeats `spec`'s own purpose as a small, readable
fixture tool. This is recorded as a genuine, sourced limitation, not silently downgraded:
**`spec`'s `given` vocabulary cannot practically express a 1000+-row fixture.** Separately,
and independently of scale: R4's tier rule (`tx_count > 1000` ⇒ recompute fees at 1.5%) is
implemented entirely in `src/glue.py` (Money arithmetic is barred from `set`, F-1) — that
branch is **not part of the workflow `spec` exercises at all**, so no `spec` block, at any
row count, could assert the tier-adjusted fee; only the raw in-language aggregate (`sum
transaction.fee`) is reachable from `spec`. The 3-row analog above proves the *aggregation
mechanism* generalizes past the C1 fixture; it cannot and does not prove the tier boundary.

## Rerun (idempotent `ReplaceSettlement`) — 2/9 PASS, 7 FAIL — new finding F-10
```
given: id settlement-M1-2026-07, stored settlement <7 stale placeholder fields>, 4 stored
       transaction rows (same as C1)
when: replaceSettlement
expect: completed | rows Settlement 1 | 6 field-value assertions
```
Result: `status=failed`, `rows Settlement 1` (PASS — a row exists), all 6 field-value
assertions FAIL, with:
```
reason: step='create settlement as newSettlement' — repository create conflicts: entity.settlement already exists
```
`ReplaceSettlement` is `find settlement; delete settlement; list ...; create settlement as
newSettlement; ...`. In a **real** `lnpl run`, this exact sequence works — proven twice over
in `evidence/08-rerun-oracle.md` (round 1's single-M1 case and round 2's full 50-merchant
10k pass, both 0 mismatches). Isolated the discrepancy to `lnpl spec`'s fixture runner
specifically with a minimal reproduction (3 attempts, per the round-2 review's instruction):

**Attempt 1** (as above) — fails with the conflict.
**Attempt 2** — removed a redundant `stored settlement id ...` line (in case the explicit
`id` field on the stored fixture row conflicted with the top-level `given: id ...` line) —
identical failure.
**Attempt 3** — minimal isolated case, one entity, `find`+`delete` only (no `create`
afterward), asserting `rows Thing 0` post-execution:
```lnpl
workflow RemoveThing
    find thing
    delete thing
    spec
        given
            id t1
            stored thing n 1
        when
            removeThing
        expect
            completed
            effects complete
            rows Thing 0
```
Result: `completed` PASS, `effects complete` PASS, **`rows Thing 0` FAILS — `Thing rows=1
want=0`.** This isolates it precisely: **`delete` inside the `lnpl spec` fixture runner
registers as a successful effect but does not actually remove the row** from whatever the
runner's own row-count checker reads. `ReplaceSettlement`'s spec failure is a direct
consequence: the `stored settlement` fixture row survives its own `delete`, so the
subsequent `create` at the same key legitimately (from the runner's point of view) conflicts.

This is a genuine divergence between `lnpl spec`'s simulated execution and `lnpl run`'s real
one for the `delete` verb specifically — recorded as F-10 in FINDINGS.md. Left the failing
block in `src/settlement.lnpl` (commented as an intentional, documented reproduction) rather
than deleting it, so the divergence stays live and re-checkable rather than hidden.

## R10 verdict
**부분 → 충족(메커니즘), 우회(rerun 하위 항목)**: C1/C2 are fully proven by value; C3's
*aggregation* mechanism is proven at a practical scale (its 1001-row literal scale and its
tier-rule branch are both out of `spec`'s reach, for two independent, now-documented
reasons); the rerun scenario is asserted correctly in `.lnpl` but exposes a `spec`-runtime
bug (F-10) rather than a language-expressiveness gap — the *real* runtime behavior (proven
via `lnpl run` at both 1-merchant and 50-merchant/10k scale) is what R10's `요구` actually
cares about, and that is unambiguously correct.
