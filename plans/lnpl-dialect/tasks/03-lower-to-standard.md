# Task 03: lower the op stream to standard dialects and recompose `emit_mlir` (S5)

## Objective

`backend._render_std(module_attrs, ops)` renders the task-02 op stream as
standard-dialect MLIR, and `emit_mlir(document, workflow_id)` becomes
`_render_std(*_lnpl_ops(document, workflow_id))`. Its output is **byte-identical**
to the pre-change output, proven against committed golden fixtures. The IR is no
longer read directly by the standard-dialect renderer — it goes through the lnpl
op stream, which is what makes S4 a real stage rather than a side artifact.

## Wiki pages (read these first, only these)

- `wiki/testing/quality/behavior-not-implementation.md` — governs the shape of
  this task: a behavior-preserving refactor must not require editing the six
  existing emission tests, and the golden fixtures are the equivalence proof.
- `wiki/testing/quality/tests-that-cannot-fail.md` — governs the mutation check
  in Verify: prove the byte-equality assertion can go red before trusting it.

## Inputs

- From task 02: `backend._lnpl_ops(document, workflow_id)` → `(module_attrs, ops)`
  where each op dict has `node_id`, `name`, `index`, `guard_mode`,
  `guard_condition`, `unroll_round`, `effects` (list of `{node_id, kind}`).
- Pre-change golden fixtures, already committed, captured from the current
  `emit_mlir` before any of this work:
  - `impl/tests/golden/wf_login.std.mlir` — 2428 bytes, `examples/login.lir.json`
    workflow `wf.login`.
  - `impl/tests/golden/w_until.std.mlir` — 7785 bytes, the `until counter >= 10`
    workflow below.
- The `until` workflow those fixtures came from:

  ```
  capability postgres
  entity User
      field
          id UUID
          email Email
  service S
  workflow W
      load user
      until counter >= 10
      cache user
  ```

- Decisions that bind you: **D5** (`emit_mlir`'s contract is unchanged),
  **D6** (the lowering consumes the op stream, not reparsed text), **D17**
  (golden fixtures are the refactor-equivalence guard).

## Steps

1. Move the body of the current `emit_mlir` into
   `_render_std(module_attrs, ops)`, changing **only** where it gets its data.
   This is a mechanical transposition — resist rewriting it. The four places it
   reads the IR map to the op stream as follows:

   | Current code reads | Read instead |
   |---|---|
   | `document["lir_version"]`, `document["module"]` in the header comment | `module_attrs["lnpl.lir_version"]`, `module_attrs["lnpl.module"]` |
   | `step["name"]` and `nodes[child_id]["kind"]` in the interning loop | `op["name"]`, then `e["kind"] for e in op["effects"]` |
   | `condition_field_names(document, workflow_id)` for the params | `module_attrs["lnpl.condition_fields"]` |
   | `cond` tuples `(mode, cond_str)` in both the constant-collection loop and the main loop | `op["guard_mode"]`, `op["guard_condition"]` |
   | `step.get("children", [])` → `nodes[child_id]["kind"]` in the three emission branches | `op["effects"]` → `e["kind"]` |

   **Interning order must not change** — it decides the `@s0`, `@s1`, … symbol
   numbering and therefore the bytes. The current order is: for each step in
   order, the step name first, then that step's effect kinds in order. Preserve
   exactly that.

   `idx` in the main loop currently comes from `enumerate(steps, start=1)`; use
   `op["index"]`, which task 02 populated from the same enumeration.

2. Replace `emit_mlir` with the composition, keeping its signature, docstring
   intent, and public name:

   ```python
   def emit_mlir(document, workflow_id):
       """Semantic IR -> standard-dialect MLIR, by way of the `lnpl` dialect (S4-S5).

       The op stream this renders is the same one `emit_lnpl_mlir` serialises, so
       the standard-dialect module and the `lnpl` module cannot describe different
       workflows.
       """
       return _render_std(*_lnpl_ops(document, workflow_id))
   ```

3. Do **not** edit any existing test in `test_backend.py`. If one fails, the
   refactor changed behaviour — fix `_render_std`, not the test.

4. Add to `impl/tests/test_lnpl_dialect.py` a class `TestStandardLoweringIsUnchanged`
   (not toolchain-gated). Fixture directory is
   `os.path.join(REPO, "impl", "tests", "golden")`, deriving `REPO` the way
   `test_backend.py` does.

   Write one module-level helper and use it in both comparisons:

   ```python
   def _body(text):
       """Drop the leading `//` comment block — the part task 05 legitimately edits.

       The fixtures hold **pre-change** bytes and are never regenerated, so the
       comparison has to survive a deliberate comment change without becoming
       circular (plan D17).
       """
       lines = text.split("\n")
       i = 0
       while i < len(lines) and lines[i].startswith("//"):
           i += 1
       return "\n".join(lines[i:])
   ```

   - **normal** `test_golden_login_lowering_is_unchanged` — `assertEqual` on
     `_body(...)` of `impl/tests/golden/wf_login.std.mlir` and of
     `backend.emit_mlir(golden(), "wf.login")`. Compare the full strings so the
     failure output shows the diff.
   - **boundary** `test_until_workflow_lowering_is_unchanged` — same against
     `w_until.std.mlir`, built from the source in Inputs. The 16-round case: the
     largest output, and the only one with guard branches.
   - **normal** `test_the_header_still_names_the_module_and_version` — `_body`
     discards the header, so assert separately that the first line of
     `emit_mlir(golden(), "wf.login")` contains `lir_version 0.1` and
     `module login`. Without this, stripping the comments would drop real
     coverage of the values `module_attrs` carries.
   - **error** `test_the_fixtures_exist` — assert both fixture files exist with
     `os.path.isfile`. A silently absent fixture must fail loudly rather than
     turn the comparisons above into vacuous passes.
   - **boundary** `test_the_stripper_leaves_non_comment_text_alone` — `_body`
     is test-only logic that the two main assertions depend on, so pin it:
     `_body("// a\n// b\nmodule {\n}\n")` equals `"module {\n}\n"`, and
     `_body("module {\n// inner\n}\n")` is unchanged (only *leading* comments go).

5. Add a class `TestLnplAndStandardDescribeTheSameWorkflow` (not toolchain-gated).
   This is plan **D18**, and it is the test that stops the `lnpl` module from
   being decorative: the dialect verifier is a structural gate that accepts a
   1-step module where 6 belong, and the differential check observes only the
   binary, so a drop/reorder/duplicate bug in `emit_lnpl_mlir` alone is otherwise
   invisible.

   For **both** the golden `wf.login` and the `until` workflow, assert:

   - `emit_lnpl_mlir(...).count('"lnpl.step"')` equals
     `emit_mlir(...).count("func.call @lnpl_step")`.
   - `emit_lnpl_mlir(...).count('"lnpl.effect"')` equals
     `emit_mlir(...).count("func.call @lnpl_effect")` — note `emit_mlir` also
     contains one `@lnpl_effect` *declaration*, so count `func.call @lnpl_effect`
     specifically, not the bare symbol.
   - the ordered list of `lnpl.node_id` values parsed out of the lnpl text equals
     the ordered `[op["node_id"] for op in ops]` plus each op's effect node ids,
     taken from `_lnpl_ops(...)` directly.

   Split these into three named tests rather than one — a single test with nine
   assertions reports only the first failure.

6. Add a class `TestOpStreamRoutesThroughStepsInOrder` (not toolchain-gated) —
   plan **D12**, given its own direct test because the suite it was going to lean
   on is a weak detector (see plan §Pre-existing defect found: three of the five
   `TestDivergenceIsDetected` cases pass vacuously).

   Monkeypatch `backend._steps_in_order` to drop the last step, restore it in
   `tearDown` (follow `test_backend.py::TestDivergenceIsDetected`'s
   `setUp`/`tearDown` shape), and assert `_lnpl_ops(golden(), "wf.login")`
   returns exactly one fewer op than unpatched. If `_lnpl_ops` grew its own
   flattening logic instead of calling `_workflow_steps`, this goes red — which
   is the whole point.

## Deliverables

- `impl/lnpl/backend.py` (modified — `_render_std` added, `emit_mlir` recomposed)
- `impl/tests/test_lnpl_dialect.py` (modified — `TestStandardLoweringIsUnchanged`,
  `TestLnplAndStandardDescribeTheSameWorkflow`,
  `TestOpStreamRoutesThroughStepsInOrder`)

Note: `impl/tests/golden/wf_login.std.mlir` and `w_until.std.mlir` already exist
and hold **pre-change** bytes. This task reads them and **never** regenerates
them — not now and not in a later task. Regenerating would make the equivalence
claim circular and leave the plan's AC3 false at merge.

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`, all 287 pre-existing tests still passing, plus task 01/02/03's
new tests.

Then **prove the two new guards can fail** — `tests-that-cannot-fail` step 1.
Run each mutation, require red, revert, require green:

| Mutation | Must turn red |
|---|---|
| In `_render_std`, change an emitted **non-comment** line (e.g. make `%c0 = arith.constant 0 : i32` use `1`). Mutating a `//` header line will **not** work — `_body` strips those by design | `TestStandardLoweringIsUnchanged` |
| In `emit_lnpl_mlir`, skip the last step (`for op in ops[:-1]`) | `TestLnplAndStandardDescribeTheSameWorkflow` |
| In `_lnpl_ops`, replace the `_workflow_steps(...)` call with an inlined copy of the flattening loop | `TestOpStreamRoutesThroughStepsInOrder` |

```bash
PYTHONPATH=impl .venv/bin/python -m unittest -v \
  tests.test_lnpl_dialect.TestStandardLoweringIsUnchanged \
  tests.test_lnpl_dialect.TestLnplAndStandardDescribeTheSameWorkflow \
  tests.test_lnpl_dialect.TestOpStreamRoutesThroughStepsInOrder
```

Note the `tests.` prefix. `PYTHONPATH=impl` puts `impl` on the path, not
`impl/tests`, so a bare `test_lnpl_dialect.X` fails with
`ModuleNotFoundError` — which unittest reports as `Ran 1 test … FAILED`,
indistinguishable at a glance from a real failure. If a targeted run reports
one test where you expected several, suspect the module path before the code.

If a mutation stays green, that guard is decoration — fix it before moving on.
If **every** mutation turns red including ones that should not, suspect the
harness rather than the code.

## Out of scope

- Changing the header comment text (it still says the dialect "is not yet
  registered", which becomes false with this work) — task 05. Because `_body`
  strips leading comments, task 05 can make that change without touching a
  fixture.
- `build()` — task 04.
