# Deliberate-mismatch repair (#8) + RFC-0002 OQ② close-out (#3)

Goal: make all five `TestDivergenceIsDetected` cases actually detect the fault
they name, and complete the `Updates` relation RFC-0008 left incomplete.

Acceptance criteria:

1. The `GUARDED` fixture's differential baseline is **EQUIVALENT** with no
   monkeypatch, so a mismatch case's patch is the only thing that can make it red.
2. Each of the five mismatch cases pins the **specific FAIL class** it causes,
   the way the two load-bearing ones already do.
3. Mode B's failure to enforce RFC-0003's cache-TTL contract stays **visible**
   after the fixture gains a TTL — it is pinned by a test and filed as an issue,
   not silently buried.
4. RFC-0002 §Open Questions ② is resolved through a proper `Updates` relation,
   and RFC-0002 carries its side of that relation.
5. 336 existing tests still pass. No grammar change, no new build dependency.

Stack: Python 3.14.6 (`.venv/bin/python`; deps `jsonschema` only — pytest is not
installed). Homebrew LLVM/MLIR 22.1.8 at `/opt/homebrew/opt/llvm/bin` (keg-only).

Tests: `cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp && PYTHONPATH=impl
.venv/bin/python -m unittest discover -s impl/tests -t impl`.
Targeted runs need the `tests.` prefix — `PYTHONPATH=impl` puts `impl` on the
path, not `impl/tests`, and a bare module name fails as `ModuleNotFoundError`
that unittest renders as `Ran 1 test … FAILED`.

## What the issues actually say vs. what is true

Both issue bodies are stale. Measured this session:

| Issue claims | Measured |
|---|---|
| #3: the parser still accepts `latency exceeds budget` | **False.** `parse_condition` rejects it, and `foo bar baz qux`. Only `token missing` and `counter >= 10` shapes pass |
| #3: "Decided: A — ship a superseding RFC, no exception to RFC-0000 §2" | **Stale.** RFC-0007 superseded RFC-0000 and added the `Updates` relation (§2.2) for exactly this case. RFC-0008 already used it correctly |
| #8: three cases pass vacuously | **True**, and the cause is measured below |

## The root cause behind #8

`GUARDED` is divergent before any monkeypatch:

```
FAIL 2/4 policy outcome — A=failed B=completed
```

`cache user` lowers to `CacheAccess set`. Mode A's `Cache.set` raises
`RunError("CacheAccess set without a TTL budget (RFC-0003 requires every cache
key to carry a TTL)")` because `GUARDED` declares no `performance / cache` budget.
**Mode B does not enforce that contract at all** — the C shim prints and returns 0.

So the differential was reporting a real mode A/B disagreement, and three tests
were written to assert `assertFalse(ok)` against it. Their own patches never
caused it: `GUARDED` contains no `until`, so `without_until` and `with_wrong_cap`
are provable no-ops on it, and `without_when`'s assertion is satisfied by the
baseline.

## Measured premises this plan rests on

Every row was run before planning, with `differential.verify`:

| # | Setup | Result |
|---|---|---|
| P1 | `GUARDED` + `capability redis` + `performance / cache 5m`, payload without `token`, `skip=False` | **EQUIVALENT** |
| P2 | same fixture, payload **with** `token`, `skip=True` (guard false → step skipped) | **EQUIVALENT** |
| P3 | P2 baseline + `without_when` patch | **DIVERGENT** — `FAIL 1/4`, `FAIL 3/4` |
| P4 | `until counter >= 10` fixture, `counter=100` (0 rounds) | EQUIVALENT; + `without_until` → **DIVERGENT** `FAIL 1/4`, `FAIL 3/4` |
| P5 | same fixture, `counter=0` (cap rounds) | EQUIVALENT; + `wrong_cap`(8) → **DIVERGENT** `FAIL 1/4` |

P2 is the load-bearing one and the least obvious: with the guard **true** the
step runs, so removing the guard changes nothing and the test stays vacuous. Only
a payload that makes the condition **false** gives the patch something to break.

## Decisions

| # | Decision | Choice | Wiki basis |
|---|----------|--------|------------|
| D1 | How to make `GUARDED`'s baseline equivalent | Add `capability redis` and a `performance / cache 5m` clause on the service. Measured P1/P2. Rejected changing `cache user` to a non-cache verb: it would stop the fixture exercising a guarded cache step, which is what three tests are about | `[no-wiki]` — measured |
| D2 | Where the fixture lives | One module, `impl/tests/fixtures.py`, imported by both test files. Today `GUARDED` is duplicated verbatim in `test_backend.py` and `test_lnpl_dialect.py`; changing one silently drifts from the other | testing-data-test-data-and-isolation ("Shared mutable fixture object … reserve shared fixtures for immutable data" — these are immutable source strings, so sharing is the right call) |
| D3 | Where the payload lives | **In the test body, never in the fixture module.** The fixture supplies source text only; each test passes the payload whose values explain why it passes | testing-data-test-data-and-isolation rule 1 ("a reader must be able to tell why the test passes from the values visible in the test body") |
| D4 | Fixture for the two `until` mismatch cases | The `until counter >= 10` source, moved into `fixtures.py` from `test_until_mode_equivalence.py`, which already proves it EQUIVALENT at `counter` 0/9/10/100. `GUARDED` has no `until` and never will — that mismatch is what made two cases no-ops | `[no-wiki]` — measured (P4, P5) |
| D5 | What each mismatch case asserts | `assertFalse(ok)` **plus** the specific `FAIL n/4` class from the premise table. A bare `any("FAIL" …)` is what let three cases ride a baseline divergence | testing-quality-tests-that-cannot-fail (the never-fails table: an assertion satisfied by unrelated state guards nothing) |
| D6 | Proving the repair worked | Each repaired case must be shown red **without** its patch removed — i.e. run the case against the un-patched baseline and require green, then with the patch and require red. Recorded per task | testing-quality-tests-that-cannot-fail step 1 |
| D7 | The mode B TTL gap | **Keep it visible three ways**: (a) a characterization test asserting the differential *detects* it, (b) a docstring naming the follow-up issue, (c) a filed issue. Rejected fixing mode B here — making `build()` refuse a TTL-less `CacheAccess` changes compile behaviour and belongs in its own change with its own equivalence argument | testing-quality-tests-that-cannot-fail (a gap nothing exercises is indistinguishable from a gap that closed) |
| D8 | Whether the TTL characterization test is "a test asserting a bug" | It asserts a **true and useful** fact — that `differential.verify` reports DIVERGENT for a TTL-less cache workflow. When mode B learns to enforce the contract it goes red, which is the signal to close the issue and invert it. The docstring says so | testing-quality-behavior-not-implementation |
| D9 | How to resolve RFC-0002 OQ② | A new **RFC-0009** with `Updates: RFC-0002 §Open Questions`, carrying the final text of that section with ② resolved. RFC-0008 is `Accepted`, and adding a section to its `Updates:` list changes the effective contract (RFC-0007 §2.2 rule 3), so it is a substantive change and cannot be edited in place | `[no-wiki]` — RFC-0007 §2.1 lifecycle + §2.2 rules 2, 3, 4, 6 |
| D10 | Why not supersede RFC-0002 | RFC-0007 §2.2 created `Updates` precisely so a one-section change would not force full replacement. Only §Open Questions changes; the rest of RFC-0002 is still the contract, so its status stays `Accepted` | `[no-wiki]` — RFC-0007 §2.2 relation table |
| D11 | Does RFC-0009 need to restate the whole OQ list? | Yes. RFC-0007 §2.2 rule 4: the updating RFC's section must contain **the text after substitution**, not "change X to Y". So RFC-0009 reproduces RFC-0002 §Open Questions with ② marked resolved and the others unchanged | `[no-wiki]` — RFC-0007 §2.2 rule 4 |
| D12 | Whether RFC-0008 gets touched | **No.** RFC-0009 supplies the missing relation; RFC-0008 stays as written. RFC-0009 states in prose that it completes what RFC-0008's `Updates:` list omitted | `[no-wiki]` |
| D13 | RFC-0009's section list | **All seven, verbatim and in order** — Status / Motivation / Guide-level Explanation / Reference-level Specification / Examples / Alternatives / Open Questions. RFC-0007 §7: *"7개 섹션의 이름과 순서는 고정이며 글자 단위로 일치해야 한다(섹션 추가·삭제·개명 금지)"*, and the §1 exemption covers **process** RFCs only — RFC-0009 is a design RFC. The first draft of this plan specified five and would have closed one 결함 by creating another | `[no-wiki]` — RFC-0007 §7, quoted |
| D14 | `docs/CONSISTENCY-CHECK.md`'s pending-supersede row | **Must be corrected in this change, not deferred.** Line 1382 records that RFC-0002 will be marked `Superseded by` for issue #3 — the course this plan reverses. It is not cosmetic: RFC-0007 §2.1 gates Review→Accepted on *"교차 정합성 체크리스트 전 항목 PASS"* and §8 names that checklist as this file, so leaving the row contradicting the repo blocks RFC-0009's own transition | `[no-wiki]` — RFC-0007 §2.1 + §8 |
| D15 | RFC-0009's Status on creation | Recorded as `Accepted` directly, following RFC-0008's precedent in this repo. RFC-0007 §2.2 rule 6 says an updating RFC *"Draft→Review→Accepted"* — this plan does **not** stage those transitions in separate commits, and says so rather than citing rule 6 as satisfied. A single-author repo with the review performed inline is the reason; if that is wrong, it is wrong for RFC-0008 too and should be fixed for both | `[no-wiki]` — noted deviation |
| D16 | The duplicated `until` source | `test_until_mode_equivalence.py` is **repointed** at `fixtures.UNTIL_COUNTER` in task 01. Copying it into `fixtures.py` while leaving the original would produce two verbatim copies of the `until` source — the exact drift D2 exists to prevent, committed in the name of preventing it | testing-data-test-data-and-isolation (same basis as D2) |
| D17 | Task 04's "mode A refuses" assertion | Assert a **pair**: mode A ends `status failed` on the TTL-less source and `status completed` on the same source with a budget. `observe_mode_a` does not surface the `RunError` text, so asserting `status failed` alone passes for any unrelated failure — measured: a workflow with a valid budget but no repo row also ends `status failed`. The pair is what makes the TTL the only variable | testing-quality-tests-that-cannot-fail (the "always-true assertion" row — the same defect being repaired in #8) |
| D18 | Issue #3's acceptance bullet *"RFC-0002 Open Questions ② is removed (not edited)"* | **Overridden, explicitly.** Under `Updates` semantics the target keeps its text and the updating RFC's section wins (RFC-0007 §2.2 rule 3), so ② stays in RFC-0002 and is superseded by RFC-0009's replacement section. The bullet was written under RFC-0000, where full replacement was the only mechanism. Task 07's close comment says this rather than letting #3 close against an unmet criterion | `[no-wiki]` — RFC-0007 §2.2 rule 3 |

### Deliberately out of scope

- Fixing mode B to enforce the cache TTL (D7). Filed instead.
- ~~`impl/tests/mutation_check.py`~~ — **brought back in scope during
  implementation.** The first draft recorded its red baseline as pre-existing,
  "from a stale anchor in `interp.py`". That was wrong twice over. A stale anchor
  reports as `STALE`, never as a red baseline; the baseline was red because
  `TREE_CONTENTS` omits `mlir/` and `CHARTER.md`, **both of which the S4 PR
  introduced** — so it was a regression from the previous change, not a
  pre-existing condition. Fixed here, baseline verified GREEN. The stale anchor
  was real and separate: it is issue #3's own acceptance bullet ("평가 불가 조건
  수용"), re-anchored on the current refusal path, and it survived until a test
  was added because nothing reached that branch.
- Issues #2 and #7 — 영기 scoped this round to #8 and #3.
- The `payload` / `skip` split noticed while measuring P2: mode A reads the
  condition from `payload` while mode B takes a separate `skip` flag, so a caller
  must keep two inputs consistent by hand. Worth an issue; not this one.
- **RFC-0007 is itself `Status: Draft`** while RFC-0000 (Superseded) names it the
  effective process, and RFC-0008 already builds on it. RFC-0009 makes that two.
  Promoting it is a process decision for the repo owner, not a side effect of
  this change — reported in the PR, filed as an issue.

## Task order

Tasks 02 and 04 both modify `impl/tests/test_backend.py`; the first draft marked
them parallel-ok, which would have had two tasks writing one file.

| Task | Depends on | Parallel-ok |
|------|-----------|-------------|
| 01 one home for the test sources (+ the TTL) | — | |
| 02 repair the three mismatch cases | 01 | |
| 03 repoint `test_lnpl_dialect.py` at the shared fixture | 01 | parallel-ok with 02 |
| 04 pin the mode B cache-TTL gap | 02 | |
| 05 write RFC-0009 | — | parallel-ok with 01-04 |
| 06 complete RFC-0002's relation and the records that contradict it | 05 | |
| 07 ship — PR, merge, close #8 and #3, file the follow-ups | 03, 04, 06 | |
