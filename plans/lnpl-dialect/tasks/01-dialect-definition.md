# Task 01: define the `lnpl` dialect and verify it from Python

## Objective

`mlir/lnpl.irdl.mlir` exists and defines the `lnpl` dialect with two ops.
`backend.verify_lnpl_module(text)` runs stock `mlir-opt --irdl-file` over a
module and raises `BackendError` with the verifier's message when it does not
verify. Tests prove the verifier rejects three distinct bad inputs.

## Wiki pages (read these first, only these)

- `wiki/platforms/environment/path-resolution.md` — governs how `mlir-opt` and
  the `.irdl.mlir` data file are located (D3, D4): pin absolute paths, never
  depend on the caller's cwd or PATH for correctness-critical inputs.
- `wiki/testing/quality/tests-that-cannot-fail.md` — governs the negative
  controls: a "the dialect is registered" test that cannot go red proves nothing.

## Inputs

- Decisions that bind you: **D1** (IRDL, not C++ ODS), **D3** (reuse
  `backend.tool()`), **D4** (`LNPL_IRDL_PATH` derived from `backend.__file__`),
  **D7** (two ops, zero operands/results, flat — no regions), **D10**
  (`lnpl.node_id` required by the verifier), **D16** (negative controls).
- Existing code: `impl/lnpl/backend.py` — `tool()`, `toolchain_available()`,
  `BackendError`, `_run()`.
- Measured IRDL facts (do not re-derive; confirmed on LLVM 22.1.8, twice):
  - `irdl.operands()` / `irdl.results()` with **named** entries when non-empty
    (`irdl.operands(idx: %c)`); empty parens are valid.
  - `irdl.attributes {"lnpl.node_id" = %c}` makes that attribute **required**.
  - `%c = irdl.base "#builtin.string"` constrains it to a string. Only that
    quoted `#`-form parses — `"!builtin.string"` and bare `#builtin.string` both
    fail. Do **not** use `irdl.any` here: it lets `lnpl.node_id = 42 : i64`
    verify, which makes the check presence-only (plan D10).
  - Attributes **not** declared in `irdl.attributes` are still accepted (they
    ride along as discardable), including names without an `lnpl.` prefix — so
    declare only `lnpl.node_id`.
  - `mlir-opt` prints **no** `loc(...)` unless `--mlir-print-debuginfo` is
    passed (measured: 0 vs 4 occurrences). The verifier argv must include it,
    or the Location traceability path silently vanishes (plan D9).

## Steps

1. Create `mlir/lnpl.irdl.mlir`:

   ```mlir
   // The `lnpl` dialect — RFC-0004 S4. Loaded into stock `mlir-opt` with
   // --irdl-file, so no C++ TableGen build is required (plan D1).
   //
   // Only `lnpl.node_id` is declared, which makes it *required* and *string*: an
   // op with no node id, or with a non-string one, fails verification. That is
   // RFC-0004's traceability invariant, machine-checked rather than merely
   // tested. Every other attribute (name, index, kind, step, guard_mode,
   // guard_condition, unroll_round) rides as a discardable attribute and is
   // deliberately unconstrained here.
   irdl.dialect @lnpl {
     irdl.operation @step {
       %id = irdl.base "#builtin.string"
       irdl.operands()
       irdl.results()
       irdl.attributes {"lnpl.node_id" = %id}
     }
     irdl.operation @effect {
       %id = irdl.base "#builtin.string"
       irdl.operands()
       irdl.results()
       irdl.attributes {"lnpl.node_id" = %id}
     }
   }
   ```

2. In `impl/lnpl/backend.py`, next to the existing `BREW_LLVM_BIN` constant, add:

   ```python
   REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
       os.path.abspath(__file__))))
   LNPL_IRDL_PATH = os.path.join(REPO_ROOT, "mlir", "lnpl.irdl.mlir")
   ```

   `backend.py` is at `<repo>/impl/lnpl/backend.py`, so three `dirname` calls
   reach `<repo>`. Verify that in step 5 rather than trusting the count.

3. Add `verify_lnpl_module(text, stage="S4 (lnpl dialect verification)", path=None)`.

   ```python
   def verify_lnpl_module(text, stage="S4 (lnpl dialect verification)", path=None):
       """Run the `lnpl` dialect's verifier over a module; return the round trip.

       With `path`, the file at that path is verified **in place** — the artifact
       `build()` wrote is the object that gets checked, and the BackendError names
       the file the user is told to inspect. Without it, `text` is staged in the
       repo's own tmp directory (never /tmp — repo policy) and removed after.
       """
   ```

   - When `path` is `None`: stage `text` with
     `tempfile.mkstemp(dir=os.path.join(REPO_ROOT, ".claude", "tmp"), suffix=".mlir")`
     after `os.makedirs(..., exist_ok=True)`. Use `mkstemp`, not a fixed name —
     `build()` can run concurrently, and the repo already uses
     `mkdtemp(dir=...)` for exactly this reason. Remove it in a `finally`.
   - When `path` is given: use it as-is and do **not** delete it.
   - Invoke, via the existing `_run(argv, stage)` so a non-zero exit becomes
     `BackendError` carrying mlir-opt's stderr:

     ```python
     [tool(MLIR_OPT), "--irdl-file", LNPL_IRDL_PATH,
      "--mlir-print-debuginfo", target_path]
     ```

     `--mlir-print-debuginfo` is required, not cosmetic: without it `mlir-opt`
     prints zero `loc(...)` and the round trip cannot show that the Location
     traceability path survived (plan D9).
   - Return `_run`'s stdout (the round-tripped module). Do not add a new
     subprocess wrapper.

4. Create `impl/tests/test_lnpl_dialect.py`. Follow `test_backend.py`'s
   conventions: `from lnpl import backend`, and gate toolchain-dependent tests
   with the same skip decorator shape:

   ```python
   NEEDS_TOOLS = unittest.skipUnless(
       backend.toolchain_available(),
       "MLIR/LLVM toolchain not installed (brew install llvm)")
   ```

   Write these tests, all in one `@NEEDS_TOOLS` class
   `TestDialectRegistration`:

   - `test_the_dialect_file_is_where_the_code_looks_for_it` — not toolchain
     gated; put it in a separate plain `unittest.TestCase`. Assert
     `os.path.isfile(backend.LNPL_IRDL_PATH)`.
   - **normal** `test_a_valid_module_verifies` — a hand-written module with one
     `lnpl.step` and one `lnpl.effect`, both carrying `lnpl.node_id`; assert the
     returned text contains `lnpl.step` and `lnpl.node_id`.
   - **normal** `test_a_location_survives_the_round_trip` — a `lnpl.step` written
     with `loc("wf.login.step.1")`; assert the returned text contains both
     `loc(` and `wf.login.step.1`. This is what makes `--mlir-print-debuginfo`
     load-bearing; measured, the flag's absence drops locations entirely.
   - **error** `test_an_op_without_a_node_id_is_rejected` — a `lnpl.step` with no
     attributes; `assertRaises(backend.BackendError)` and assert the message
     contains `lnpl.node_id` (per minimum-case-set: assert the error contract,
     not just that something raised). Measured message:
     `op attribute "lnpl.node_id" is expected but not provided`.
   - **error** `test_a_non_string_node_id_is_rejected` — `lnpl.node_id = 42 : i64`;
     assert `BackendError` and that the message mentions `builtin.string`.
     Measured: `expected base attribute 'builtin.string' but got
     'builtin.integer'`. This is the test that would go red if someone relaxed
     the constraint back to `irdl.any`.
   - **error** `test_an_undefined_lnpl_op_is_rejected` — `"lnpl.bogus"()`;
     assert `BackendError` and that the message mentions `lnpl.bogus`.
   - **boundary** `test_an_empty_module_verifies` — `module {\n}\n` verifies
     without raising. Zero ops is the boundary of the collection input.
   - **negative control** `test_the_registration_is_what_makes_it_parse` — run
     `mlir-opt` on the same valid module **without** `--irdl-file` (call
     `backend._run` yourself, or `subprocess`, and expect failure). Assert it
     fails. Without this, every test above would also pass if `--irdl-file` were
     silently ignored.

## Deliverables

- `mlir/lnpl.irdl.mlir` (new)
- `impl/lnpl/backend.py` (modified — `REPO_ROOT`, `LNPL_IRDL_PATH`,
  `verify_lnpl_module`)
- `impl/tests/test_lnpl_dialect.py` (new)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK` with a total of **287 + (your new test count)**; no failures and
no errors. Then confirm the negative control is real:

```bash
PYTHONPATH=impl .venv/bin/python -c "
from lnpl import backend
print(backend.verify_lnpl_module('module {\n}\n')[:40])"
```

Success = it prints a module rather than raising.

## Out of scope

- Generating an lnpl module from Semantic IR — that is task 02. This task only
  defines the dialect and the verification helper, and tests them against
  **hand-written** MLIR text.
- Touching `emit_mlir` or `build()`.
