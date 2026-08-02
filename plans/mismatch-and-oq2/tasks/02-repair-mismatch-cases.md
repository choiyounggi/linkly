# Task 02: make the three vacuous mismatch cases detect the fault they name

## Objective

All five `TestDivergenceIsDetected` cases run against an **equivalent** baseline
and pin the specific `FAIL n/4` class their patch causes. None can pass on a
divergence it did not cause.

## Wiki pages (read these first, only these)

- `wiki/testing/quality/tests-that-cannot-fail.md` — the whole task. Note the
  never-fails row "Always-true assertion … on a value that is always defined":
  `assertFalse(ok)` against a baseline that is already `False` is that row.
- `wiki/testing/data/test-data-and-isolation.md` — rule 1: the payload that makes
  each case work belongs in the test body, visible, not hidden in the fixture.

## Inputs

- From task 01: `impl/tests/fixtures.py` exporting `GUARDED`,
  `guarded_source(guard)`, and `UNTIL_COUNTER`.
- `impl/tests/test_backend.py` — its module-level `GUARDED` constant, and the
  five tests in `TestDivergenceIsDetected`. Its `PAYLOAD` constant stays.
- Decisions that bind you: **D3** (payload in the test body), **D4** (the two
  `until` cases use `UNTIL_COUNTER`, not `GUARDED`), **D5** (pin the FAIL class),
  **D6** (prove each repaired case red).
- **Measured premises — build the tests to match these, do not re-derive them:**

  | Case | Fixture | Payload / flags | Baseline | With patch |
  |---|---|---|---|---|
  | `when` removed | `GUARDED` | payload **contains** `token`, `skip=True` | EQUIVALENT | `FAIL 1/4` + `FAIL 3/4` |
  | `until` removed | `UNTIL_COUNTER` | `{"counter": 100}` | EQUIVALENT | `FAIL 1/4` + `FAIL 3/4` |
  | wrong round cap | `UNTIL_COUNTER` | `{"counter": 0}` | EQUIVALENT | `FAIL 1/4` |

  The `when` row is the subtle one: with the guard **true** the step runs, so
  removing the guard changes nothing and the case stays vacuous. It only works
  with a payload that makes `token missing` **false** — hence a payload carrying
  `token`, paired with `skip=True` so mode B skips too.

## Steps

1. Delete `test_backend.py`'s module-level `GUARDED` and import it instead:
   `from tests.fixtures import GUARDED, UNTIL_COUNTER, guarded_source`.
   `test_backend.py` is imported as `tests.test_backend` under the suite's
   `PYTHONPATH=impl`, so `from tests.fixtures import …` resolves.

2. Replace every existing `GUARDED.replace(...)` call site with
   `guarded_source("<guard>")` — there are call sites for `repeat 3` and for
   `until token exists`. Behaviour must not change; these tests are already green
   and must stay green.

3. Rewrite `test_when_guard_removed_diverges`:
   - payload: `dict(PAYLOAD, token="present")` — spelled in the test body so a
     reader sees why the guard is false.
   - repo rows: `{"entity.user": dict(PAYLOAD)}` as the other cases do.
   - call `differential.verify(..., skip=True)`.
   - **assert the baseline first**: run `verify` with no patch and
     `assertTrue(ok)`. This is the assertion that makes the case non-vacuous —
     without it the test cannot tell "my patch broke it" from "it was already
     broken".
   - then apply `without_when` and assert `assertFalse(ok)` **and**
     `any("FAIL 1/4" in line for line in report)`.

4. Rewrite `test_until_guard_removed_diverges` and
   `test_until_round_cap_violation_diverges` to use `UNTIL_COUNTER` with the
   payloads in the table, each following the same shape as step 3: baseline
   asserted equivalent, then patched, then `FAIL 1/4` pinned. Repo rows for this
   fixture are `{"entity.workflow": dict(payload)}` — the entity is `Workflow`,
   not `User`.

5. Leave `test_reordered_backend_is_reported_as_divergent` and
   `test_dropped_effect_in_the_backend_is_reported_as_divergent` alone except for
   adding the same baseline assertion. They already pin `FAIL 1/4` and `FAIL 3/4`
   and are the two cases that were load-bearing all along.

6. Update the class docstring: five cases, each asserting its baseline equivalent
   before patching, and why (three of them used to ride a baseline divergence
   caused by a missing cache TTL).

## Deliverables

- `impl/tests/test_backend.py` (modified)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK` with **336 or more** tests and no failures.

Then prove each repaired case can fail — D6. For each of the three, comment out
**its own patch assignment** (the `backend._steps_in_order = …` line) so the case
runs against the unpatched baseline, and require **red**:

```bash
PYTHONPATH=impl .venv/bin/python -m unittest -v \
  tests.test_backend.TestDivergenceIsDetected
```

With the patch disabled the case must fail on `assertFalse(ok)` — that is the
proof the baseline is equivalent and the patch is what causes the divergence.
Restore the line and require green again.

If a case still **passes** with its patch disabled, it is still vacuous; the
fixture or the payload is wrong. Fix it here.

## Out of scope

- `test_lnpl_dialect.py`'s duplicate `GUARDED` — task 03.
- The mode B cache-TTL gap — task 04.
- `test_until_mode_equivalence.py`. It keeps its own `SRC`; consolidating it is
  not part of this plan.
