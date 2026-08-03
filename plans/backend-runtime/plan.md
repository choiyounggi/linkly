# Backend/Runtime Issues #12 and #9 Implementation Plan

## Status
- Mode: TDD (test-first, RED-GREEN-REFACTOR)
- Baseline: 386 tests, 1 failure (jsonschema — ignore), 53 skipped (LLVM — expected)
- Order: #12 first (changes differential.verify signature), then #9
- Worktree: `/Users/choeyeong-gi/Desktop/workspace/linkly-worktrees/wt-c`

## ISSUE #12: Presence Guard Skip Parameter Derivation

### Problem
- **Mode A** evaluates Presence conditions against the `payload` dict (via `_condition_holds`)
- **Mode B** takes a separate boolean `skip` parameter threaded from caller
- **Caller risk**: Must supply both sources and keep them consistent by hand
- **Contract violation**: When they disagree, indistinguishable from real mode A/B divergence
- **Root cause**: Presence conditions can't go through i64 `condition_field_names` channel (RFC-0008 G8) because they check key absence (a boolean property, not a numeric value)

### Solution (RFC-0008 recommended option 1)
- **Derive `skip` from payload INSIDE `differential.verify`** instead of accepting it as parameter
- Use same Presence evaluation mode A uses: `parse_condition` + dict lookup
- **Reuse** existing helper; no logic duplication
- Remove `skip` from public `verify(...)` signature
- Thread derived value down to `run_binary` internally
- Update all call sites (tests/fixtures)

### Success Criteria
1. `differential.verify(...)` no longer takes `skip` parameter
2. Presence-guarded workflows agree in both modes (EQUIVALENT) when key present/absent
3. Impossible to create spurious divergence via mis-wired skip (param is gone)
4. All tests pass; no new failures

### Verification Command
```bash
cd /Users/choeyeong-gi/Desktop/workspace/linkly-worktrees/wt-c
PYTHONPATH=impl python3 -m pytest impl/tests/test_backend.py::TestDifferential -xvs
PYTHONPATH=impl python3 -m pytest impl/tests/ -k "Presence or guard" -xvs
```

### Test Plan
- **RED**: Add 3 new tests (Presence guarded workflow with key present, key absent, Comparison guard works unchanged)
- **GREEN**: Implement fix
- Verify existing tests still pass

---

## ISSUE #9: Mode B Cache-TTL Enforcement

### Problem
- **RFC-0003 contract**: Every cache key must carry a TTL
- **Mode A enforces**: `Cache.set` raises `RunError: CacheAccess set without a TTL budget`
- **Mode B ignores**: Generated C shim just prints effect, returns 0
- **Result**: `differential.verify` reports DIVERGENT when budget is absent
- **Pinned test class**: `TestModeBDoesNotEnforceTheCacheTtlContract` (3 tests) expecting this divergence

### Solution
- **Make mode B refuse `CacheAccess set` without owning service's `cache` budget**
- **Mirror mode A's behavior** to achieve observable equivalence
- **Compile-time vs run-time decision**:
  - **Recommended**: Run-time enforcement in generated binary (preserves equivalence — both modes refuse same way)
  - **Fallback**: Compile-time refusal in `build()` (stricter than mode A, must document and update differential handling)

### Implementation Path
1. Analyze `_render_std` to understand where to emit the check
2. Add i64 parameter for cache budget (or flag) to `lnpl_run` signature
3. Before `CacheAccess set` in MLIR, check budget > 0
4. If budget absent/zero, emit error state and exit
5. Update `runtime_c` to accept cache budget and pass it through

### Success Criteria
1. Mode B binary rejects `CacheAccess set` without budget (observable failure)
2. Mode A and B produce same observable failure on budget-less workflow
3. `TestModeBDoesNotEnforceTheCacheTtlContract` assertions INVERTED (not weakened)
4. All existing tests still pass

### Verification Command
```bash
cd /Users/choeyeong-gi/Desktop/workspace/linkly-worktrees/wt-c
PYTHONPATH=impl python3 -m pytest impl/tests/test_backend.py::TestModeBDoesNotEnforceTheCacheTtlContract -xvs
```

### Handling Pending-LLVM Tests
- Tests that require MLIR/LLVM toolchain will remain pending until toolchain is installed
- Track which tests are pending in final report
- Do NOT weaken or delete tests to make them pass

---

## Implementation Sequence

### Phase 1: Issue #12 (Remove `skip` parameter)
1. **RED**: Write failing tests for Presence guards (present/absent cases)
2. **Implement**:
   - Modify `differential.verify` to accept only `(document, workflow_id, payload, repo_rows, workdir)`
   - Remove `skip` parameter from signature
   - Derive `skip` from payload inside verify: extract Presence condition, evaluate against payload
   - Update `observe_mode_b` call
   - Update `run_binary` call
3. **GREEN**: Update all call sites in test files
4. **Refactor**: Ensure no duplication of condition evaluation logic

### Phase 2: Issue #9 (Cache-TTL enforcement)
1. **Analysis**: Identify where cache budget is available in IR
2. **RED**: Invert test assertions in `TestModeBDoesNotEnforceTheCacheTtlContract`
3. **Implement** (run-time preferred):
   - Extract cache budget from workflow's Performance constraint
   - Thread budget to `lnpl_run` as i64 parameter
   - Generate MLIR check before each `CacheAccess set`
   - Emit error/exit if budget absent or zero
4. **GREEN**: Verify mode B now enforces
5. **Refactor**: Minimize complexity

---

## Files to Modify

### Core Changes
- `impl/lnpl/differential.py` — remove `skip` parameter from `verify()`
- `impl/lnpl/backend.py` — derive `skip` internally, update `run_binary` call
- `impl/lnpl/interp.py` — may need minor updates if condition derivation changes

### Test Files
- `impl/tests/test_backend.py` — update all `verify()` call sites, invert TTL test assertions
- `impl/tests/test_differential.py` — update call sites
- Any fixture files using `differential.verify(..., skip=...)`

### Expected NOT to touch
- `impl/lnpl/protocol.py`, `impl/lnpl/agents.py` (another worktree owns these)
- `docs/CONSISTENCY-CHECK.md` — keep separate labeled section if needed

---

## Acceptance Checklist

### Issue #12
- [ ] `differential.verify` signature no longer includes `skip` parameter
- [ ] All call sites updated
- [ ] Presence guard tests verify both key present and absent
- [ ] Comparison guard tests still pass (unchanged path)
- [ ] No new test failures vs baseline

### Issue #9
- [ ] `TestModeBDoesNotEnforceTheCacheTtlContract` assertions inverted
- [ ] Mode B enforces cache TTL (raises observable error)
- [ ] Mode A/B produce observable equivalence on budget-less workflow
- [ ] No new test failures vs baseline

### Overall
- [ ] Two atomic commits (one per issue)
- [ ] Commit messages reference issue numbers
- [ ] Baseline test count maintained or improved
- [ ] LLVM-pending tests explicitly listed
