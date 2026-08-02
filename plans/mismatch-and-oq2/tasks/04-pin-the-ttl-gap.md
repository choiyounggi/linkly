# Task 04: keep mode B's missing cache-TTL enforcement visible

## Objective

A test pins the fact that `differential.verify` reports DIVERGENT for a workflow
whose `CacheAccess set` has no TTL budget — because mode A refuses it and mode B
does not. The gap that made three tests vacuous cannot now disappear unnoticed
behind the TTL task 01 added.

## Wiki pages (read these first, only these)

- `wiki/testing/quality/tests-that-cannot-fail.md` — why a gap nothing exercises
  is indistinguishable from a gap that closed.
- `wiki/testing/quality/behavior-not-implementation.md` — D8: assert the
  observable fact (the checker reports a divergence), not the internals of either
  mode.

## Inputs

- From task 01: `impl/tests/fixtures.py` exporting `GUARDED` — the **TTL-bearing**
  version. This task needs a TTL-**less** one, defined locally in the test file.
- Measured behaviour, which this test encodes:
  - mode A: `Cache.set` raises
    `RunError("CacheAccess set without a TTL budget (RFC-0003 requires every
    cache key to carry a TTL)")` when `con["cache_ttl_ms"]` is `None`.
  - mode B: the generated C shim prints `effect CacheAccess` and returns 0.
  - `differential.verify` therefore reports
    `FAIL 2/4 policy outcome — A=failed B=completed`.
- Decisions that bind you: **D7** (pin it, file it, do not fix mode B here),
  **D8** (assert the checker's verdict, and say in the docstring what a red run
  means).

## Steps

1. In `impl/tests/test_backend.py`, add a class
   `TestModeBDoesNotEnforceTheCacheTtlContract` next to `TestDivergenceIsDetected`,
   gated with the existing `@NEEDS_TOOLS` decorator and using the same
   `mkdtemp(dir=os.path.join(REPO, ".claude", "tmp"))` setUp/tearDown shape as the
   neighbouring classes.

2. Define the TTL-less source **locally in this file**, not in `fixtures.py` — it
   exists only to characterise the gap, and putting it in the shared module would
   invite someone to use it as a general fixture:

   ```python
   NO_TTL_CACHE = """
   capability postgres
   capability redis
   entity User
       field
           id UUID
           email Email
   service S
   workflow W
       load user
       cache user
   """
   ```

   No guard: the point is the cache effect, not the guard.

   And its control, the same source with a budget — name it exactly this, so the
   two read as a pair:

   ```python
   TTL_CACHE = NO_TTL_CACHE.replace(
       "service S\n", "service S\n    performance\n        cache 5m\n")
   ```

3. Write the class docstring to say all of this plainly:
   - RFC-0003 requires every cache key to carry a TTL.
   - Mode A enforces it by refusing; mode B does not enforce it at all.
   - So the differential reports a real disagreement, and this test pins it.
   - **When this test goes red, mode B has learned to enforce the contract** —
     that is the signal to close the follow-up issue and invert the assertion,
     not to weaken it.
   - Name the follow-up issue. Task 07 files it; until it has a number, write
     `see the cache-TTL follow-up issue` and task 07 replaces that with the number.

4. Write three tests:
   - **normal** `test_the_differential_reports_the_disagreement` — `verify` on
     `NO_TTL_CACHE` returns `ok is False`, and the report contains `FAIL 2/4`.
     Assert the FAIL class, not just falsity (the same rule task 02 applies).
   - **error** `test_mode_a_refuses_only_when_the_budget_is_missing` — observe
     mode A on **both** sources and assert `NO_TTL_CACHE` ends `status failed`
     **while** `TTL_CACHE` ends `status completed`.

     Assert the pair, not just the failure (**D17**). `observe_mode_a` returns
     only order/effects/status/text — the `RunError` message never reaches the
     caller — so `status failed` alone is satisfied by any unrelated failure.
     Measured: a workflow with a valid budget but no repo row also ends
     `status failed`. Pairing makes the budget the only variable, which is the
     same standard task 02 applies to the cases it repairs.
   - **boundary** `test_adding_a_ttl_budget_makes_the_two_modes_agree` —
     `differential.verify` on `TTL_CACHE` returns `ok is True`. This is the
     control that proves the divergence comes from the missing TTL and not from
     something else about the fixture.

## Deliverables

- `impl/tests/test_backend.py` (modified — one new class)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest -v \
  tests.test_backend.TestModeBDoesNotEnforceTheCacheTtlContract
```

Success = 3 tests, `OK`. The third test passing is what proves the first two are
about the TTL rather than about the fixture being malformed.

Then the full suite:

```bash
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`, no failures.

## Out of scope

- **Making mode B enforce the TTL.** That changes compile behaviour — `build()`
  would have to refuse a `CacheAccess set` with no budget — and needs its own
  equivalence argument. Task 07 files it as an issue.
- Touching `interp.py` or the C shim.
