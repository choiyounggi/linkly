# Task 04: put the lnpl module in the build path and make it load-bearing

## Objective

`build()` writes `module.lnpl.mlir` into the workdir and runs the dialect
verifier on it **before** producing anything else. A module that fails
verification raises `BackendError` and no binary is produced. `module.lnpl.mlir`
joins the kept intermediates.

## Wiki pages (read these first, only these)

- `wiki/testing/quality/tests-that-cannot-fail.md` — governs the negative
  control: "the build verifies the lnpl module" is only true if a bad module
  actually fails the build, so that must be tested by making one fail.
- `wiki/platforms/environment/path-resolution.md` — governs D3/D4 again: the
  verifier subprocess must resolve `mlir-opt` and the `.irdl.mlir` by pinned
  absolute paths, because `build()` runs against an arbitrary `workdir`.

## Inputs

- From task 01: `verify_lnpl_module(text, stage=...)`, `LNPL_IRDL_PATH`.
- From task 02: `emit_lnpl_mlir(document, workflow_id)`.
- From task 03: `emit_mlir` recomposed; standard-dialect output unchanged.
- Existing `build(document, workflow_id, workdir, keep_intermediate=True)` in
  `impl/lnpl/backend.py`. Current file set it manages:
  `module.mlir`, `module.llvm.mlir`, `module.ll`, `runtime.c`, `module`,
  `module.fields.json`.
- Existing test that enumerates intermediates:
  `test_backend.py::TestNativeBuild::test_intermediates_are_kept_for_inspection`
  currently checks `("module.mlir", "module.llvm.mlir", "module.ll")`.
- `differential.observe_mode_b` calls `backend.build(...)`, so every differential
  test exercises this path automatically — including the five in
  `TestDivergenceIsDetected`.
- Decisions that bind you: **D8** (load-bearing: verification failure fails the
  build), **D4** (pinned `.irdl.mlir` path).

## Steps

1. In `build()`, add `lnpl_path = os.path.join(workdir, "module.lnpl.mlir")`
   alongside the existing path variables.

2. Immediately after `os.makedirs(workdir, exist_ok=True)` and the
   `fields = condition_field_names(...)` line, and **before** writing
   `module.mlir`:

   ```python
   lnpl_text = emit_lnpl_mlir(document, workflow_id)
   with open(lnpl_path, "w", encoding="utf-8") as fh:
       fh.write(lnpl_text)
   # S4 gate: a module that does not satisfy the `lnpl` dialect's verifier is a
   # failed conversion, not a warning (RFC-0004 S4). Nothing downstream runs.
   verify_lnpl_module(lnpl_text, path=lnpl_path)
   ```

   Order matters: write the file first so a failing module is on disk for
   inspection, then verify.

   Pass `path=lnpl_path` (plan **D19**). Without it `verify_lnpl_module` stages a
   *second copy* in `.claude/tmp` and checks that, so the artifact on disk would
   never be the verified object and `BackendError` would name a temp path instead
   of the file this task tells the user to inspect.

3. Add `lnpl_path` to the `keep_intermediate=False` cleanup tuple, keeping the
   existing members.

4. Extend `test_intermediates_are_kept_for_inspection`'s tuple to include
   `"module.lnpl.mlir"`. This is the one pre-existing test this plan permits
   editing, because the set it enumerates genuinely grew.

5. Add to `impl/tests/test_lnpl_dialect.py` a `@NEEDS_TOOLS` class
   `TestBuildGatesOnTheDialect`, with `setUp`/`tearDown` mkdtemp'ing into
   `os.path.join(REPO, ".claude", "tmp")` exactly as `test_backend.py`'s classes
   do (the repo forbids `/tmp`; `tempfile.mkdtemp(dir=...)` is the established
   pattern here).

   - **normal** `test_build_writes_the_lnpl_module` — `build(golden(), "wf.login",
     workdir)`, then assert `module.lnpl.mlir` exists and its text contains
     `"lnpl.step"` and `lnpl.node_id`.
   - **normal** `test_the_binary_still_runs_after_the_dialect_stage` — build, run
     via `backend.run_binary`, assert `rc == 0` and the last line is
     `status completed`. This is the end-to-end guard that inserting S4 did not
     break S5-S7.
   - **error / negative control** `test_a_module_failing_the_dialect_verifier_fails_the_build`
     — monkeypatch `backend.emit_lnpl_mlir` to return a module with an op that
     the verifier rejects (reuse task 01's rejected shape: an `lnpl.step` with no
     `lnpl.node_id`), assert `build(...)` raises `backend.BackendError`, assert
     the message mentions `lnpl.node_id`, and assert **no binary was produced**
     (`not os.path.exists(os.path.join(workdir, "module"))`). Restore the
     original in `tearDown` or a `finally`. Without this test, D8's claim that
     the artifact is load-bearing is unverified.
   - **boundary** `test_intermediates_are_removed_when_not_kept` — call with
     `keep_intermediate=False` and assert `module.lnpl.mlir` is gone while the
     binary remains. This covers the cleanup-tuple edit in step 3, which is
     otherwise untested.

## Deliverables

- `impl/lnpl/backend.py` (modified — `build()`)
- `impl/tests/test_backend.py` (modified — one tuple in
  `test_intermediates_are_kept_for_inspection`)
- `impl/tests/test_lnpl_dialect.py` (modified — `TestBuildGatesOnTheDialect`)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`, no failures, no errors, and the count is 287 + all new tests.

Then confirm the differential check still both passes and can fail — RFC-0004's
equivalence requirement and its deliberate-mismatch requirement:

```bash
PYTHONPATH=impl .venv/bin/python -m unittest -v \
  tests.test_backend.TestDifferential tests.test_backend.TestDivergenceIsDetected
```

The `tests.` prefix is required — `PYTHONPATH=impl` does not put `impl/tests` on
the path, and a bare name fails as `ModuleNotFoundError` that unittest renders as
a one-test failure.

All must pass: `TestDifferential` reports EQUIVALENT, and the two **load-bearing**
mismatch cases still observe the divergence class they pin —
`test_reordered_backend_is_reported_as_divergent` (`FAIL 1/4`) and
`test_dropped_effect_in_the_backend_is_reported_as_divergent` (`FAIL 3/4`).

Do **not** infer from "all five pass" that the routing is intact. Measured, the
other three cases pass vacuously against a baseline divergence in the `GUARDED`
fixture that their monkeypatch never causes (plan §Pre-existing defect found), so
they would keep passing even if S4 bypassed `_steps_in_order` entirely. The
routing is pinned by task 03's `TestOpStreamRoutesThroughStepsInOrder`; that is
the test to trust here.

## Out of scope

- Documentation. Tasks 05 and 06.
- Making the lowering an actual MLIR pass — the follow-up issue.
