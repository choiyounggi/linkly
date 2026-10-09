# 01-authoring — round tally

Rounds = edit→recompile/rerun cycles. Discovery probes (throwaway files under
`.claude/tmp/probe/`, deleted after each answer) are counted separately from
the case's own `src/*.lnpl` rounds — they answered "is X expressible" questions
the skill docs left silent, and every one produced a real compiler/runtime
message, so they are evidence, not guesses.

## Discovery probes (not part of src/, each deleted immediately after)
1. `set report.net to report.gross - report.fees` (Money subtraction in plain `set`) → compile error, `money`/RFC-0016 dimension rejection. Confirms RFC-0044's stated restriction.
2. `set report.net to input.net` (plain Money-to-Money copy, no operator) → same rejection — the restriction is on the **target field's type**, not on the presence of an arithmetic operator.
3. `list payment where merchant == input.merchantId` → compile error: "input field 'merchantId', which no entity declares". Undocumented (not in lnpl-authoring skill docs or the RFCs read) global rule: every `input.<field>` token in source must name a field some entity declares.
4. Same file with `input.merchant` (a declared field name) → compiles. Confirms probe 3's rule.
5. `when input.bumpAmount > 0` (guard context, not list-where) → same "no entity declares" rejection — confirms the rule is global, not list-where-specific.
6. `list payment where merchant == input.merchant` + `set report.total to sum payment.amount` (Money aggregate) → compiles clean. Confirms RFC-0044/0045's aggregate-only Money evaluator channel is real and reachable.

## src/*.lnpl rounds
- Round 1 (domain.lnpl only): compiled clean, rc=0, no diagnostics. (Entities decided before probes 1-2 above ran, but no rework needed once Money fields were scoped to aggregate-only usage per the probe findings.)
- Round 2 (domain.lnpl + settlement.lnpl, MonthlySettlement + ComputeDailyRollup + event, no explicit `service`): not run standalone — went straight to the service-qualified version below once naming.md's "nearest preceding service" rule was read, to avoid a wasted round on the schedule/service-ownership ambiguity.
- Round 3 (domain.lnpl + settlement.lnpl with `service SettlementService` / `service RollupService`): compiled clean, rc=0, 1 info diagnostic (`declared-not-enforced` on the schedule event — expected, matches ENFORCEMENT-MATRIX.md).
- Round 4 (added `workflow ReplaceSettlement` for the idempotent-rerun path, R5): compiled clean, rc=0, same 1 info diagnostic.

## Runtime rounds (data format, not source edits)
- `lnpl run` on the small fixture failed once with `money-encode-precision — 1000 has 0 decimal place(s), currency USD requires exactly 2`: `seed.py`'s `money()` helper encoded minor units as a bare integer string (`"1000"`); Money.amount must be a decimal string with exactly the currency's exponent digits (`"10.00"`). Fixed in `seed.py`, re-seeded, reran — passed. This is a `seed.py` (Python glue) fix, not an `.lnpl` round.

Total round 1: 4 `.lnpl` compile rounds (2 with 0 diagnostics beyond the expected info; the file never needed a second attempt at the same friction), 1 seed-data-format runtime round, 6 discovery probes.

## Round 2 (coordinator review r1: Task 04/05/06 execution)
- Round 5: added `entity SettlementSummary` + `Settlement.monthKey` (domain.lnpl) + `SettlementTotals` workflow (settlement.lnpl) — compiled clean first try.
- Round 6: added `service ... expose / list Settlement by net` — compile error (Money not a legal `expose list` sort field). Round 7: switched sort field to `txCount` (Integer) — compiled clean. (2 rounds, `05-openapi.md`/`06-serve.md`.)
- Round 8: `SettlementTotals` using `create settlementsummary as newSummary` + `respond newSummary.*` — compiled and ran fine, but **`lnpl openapi` crashed** (`06-serve.md` Bug 1). Round 9: rewrote to `find settlementsummary` + `set settlementSummary.*` (lowercase-concat for the object, then discovered — 2 more probe rounds — that the *binding* reference afterward needs camelCase, not the same lowercase-concat token) + `respond settlementSummary.*` — `lnpl openapi` succeeded. Runtime still fails (Bug 2, write-conflict on the 2nd sequential `set`) — recorded as a platform bug, not re-authored further (fixing platform bugs is out of scope).
- Round 10: `entity Transaction` `+currency Currency` field (R9 expand step) — compiled clean.
- Round 11: added the C1 `spec` block to `MonthlySettlement` — compile error (`empty repository` + `stored ...` contradiction). Round 12: dropped `empty repository` — `lnpl spec --run` passed 9/9 assertions first try after that fix.
- 1 `bench.py` bug (own harness, not lnpl): reused a stale `bench_100000.db` across two runs, second run hit a `create`-conflict on a repeated bench id. Fixed by deleting the store before each seed; not counted as an `.lnpl` round.
- 6 additional discovery probes this round: `expose` block-form syntax (1, succeeded first try), `expose ... desc` (1, rejected), `expose` Money sort field (1, rejected — see above), two-list-in-one-workflow feasibility (1, succeeded), `respond` on a bare RowSet (1, rejected — confirms no per-row projection exists), minimal `find`+2×`set` write-conflict reproduction (1, confirmed the bug independent of Money/Settlement specifics).

Round 2 total: 8 more `.lnpl` compile rounds (5 clean-first-try, 3 with a real friction each resolved in the very next round), 6 more discovery probes, 1 own-harness bug (bench.py), 1 genuine tool bug hit and worked around at the authoring level (openapi crash) plus 1 genuine tool bug hit and **not** worked around because no in-language workaround exists (write-conflict, `06-serve.md`).
