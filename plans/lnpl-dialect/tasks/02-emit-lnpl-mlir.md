# Task 02: emit the `lnpl` dialect module from Semantic IR (S4)

## Objective

`backend._lnpl_ops(document, workflow_id)` returns the structured op stream, and
`backend.emit_lnpl_mlir(document, workflow_id)` renders it as `lnpl` dialect text
that passes `verify_lnpl_module`. Every op carries `lnpl.node_id` and
`loc("<node id>")`. `emit_mlir` is **not touched** in this task, so the 287 tests
stay green throughout.

## Wiki pages (read these first, only these)

- `wiki/testing/quality/minimum-case-set.md` — governs the case set for the two
  new functions: one normal, one error, one boundary each, asserting observable
  outcomes (the returned text), and asserting the error *contract*.
- `wiki/testing/quality/tests-that-cannot-fail.md` — governs D12: the reason
  `_lnpl_ops` must route through `_steps_in_order` is that five existing tests
  monkeypatch that name to prove the differential check can fail.

## Inputs

- From task 01: `backend.verify_lnpl_module(text)`, `backend.LNPL_IRDL_PATH`,
  `mlir/lnpl.irdl.mlir` (ops `lnpl.step`, `lnpl.effect`; `lnpl.node_id`
  required by the verifier).
- Existing code in `impl/lnpl/backend.py`, unchanged by task 01:
  - `_workflow_steps(document, workflow_id)` → `(nodes, steps)` where `steps` is
    a list of `(step_node, cond)` and `cond` is `None` or
    `(mode, condition_string)` with mode in `{"when", "until"}`.
  - `condition_field_names(document, workflow_id)` → ordered list of field names.
  - `_extract_condition_field(cond_str)` → `None`, `(field, kind)` for Presence,
    or `(field, op, value)` for Comparison.
  - `_UNTIL_ROUND_CAP = 16`.
- Decisions that bind you: **D6** (structured op stream is the shared
  intermediate), **D7** (two ops, flat, guards as attributes), **D9** (both
  traceability paths), **D11** (unrolled rounds share one node_id, differ by
  `lnpl.unroll_round`), **D12** (must go through `_workflow_steps`), **D13**
  (call `condition_field_names`, never re-derive), **D14** (do not invent a
  compile-context side table).

## Steps

1. Add `_lnpl_ops(document, workflow_id)` returning `(module_attrs, ops)`.

   Obtain steps with `nodes, steps = _workflow_steps(document, workflow_id)`.
   **This call is load-bearing for D12 — do not inline the flattening logic.**

   `module_attrs` is a dict:

   ```python
   {"lnpl.module": document["module"],
    "lnpl.lir_version": document["lir_version"],
    "lnpl.workflow": workflow_id,
    "lnpl.condition_fields": condition_field_names(document, workflow_id)}
   ```

   `ops` is a list of dicts, one per flattened step, in order, with
   `index` from `enumerate(steps, start=1)`:

   ```python
   {"node_id": step["id"], "name": step["name"], "index": idx,
    "guard_mode": mode_or_None, "guard_condition": cond_str_or_None,
    "unroll_round": n_or_None,
    "effects": [{"node_id": child_id, "kind": nodes[child_id]["kind"]}
                for child_id in step.get("children", [])]}
   ```

   Read `children` off the step dict you were handed (**not** off `document`) —
   `TestDivergenceIsDetected.test_dropped_effect_in_the_backend_is_reported_as_divergent`
   strips `children` from those dicts, and reading from `document` would restore
   the effects and disarm that test.

   `unroll_round`: number the repeats of the same `node_id` 1..N in emission
   order, by counting how many times that `node_id` has already been emitted.
   Set it whenever a `node_id` appears more than once — which covers **both**
   `until` (guarded rounds) and `repeat` (`guard_mode` is `None`, since
   `_steps_in_order` unrolls `repeat` without attaching a condition). Leave it
   `None` for a `node_id` that appears exactly once.

   This is RFC-0004's 1:다 확장 rule, and `repeat` is subject to it as much as
   `until` is — an earlier draft covered only `until` and would have left
   `repeat 3`'s three ops distinguishable solely by `lnpl.index`.

   Do **not** assume the count is `_UNTIL_ROUND_CAP` — the cap is monkeypatched
   by `TestDivergenceIsDetected.test_until_round_cap_violation_diverges`. Count
   what you actually emit.

   A `node_id` can repeat across *interleaved* bodies (an `until` over a
   `pipeline` of two steps yields `step.2` rounds 1..16 and `step.3` rounds
   1..16, interleaved). Counting per `node_id` rather than per round handles
   this; the audit verified that shape produces correct per-node numbering.

2. Add `emit_lnpl_mlir(document, workflow_id)` rendering that stream. Target
   shape (attribute order within the braces does not matter — `mlir-opt`
   normalises it):

   ```mlir
   // Generated from Semantic IR (lir_version 0.1, module login) — do not edit.
   // RFC-0004 S4: the custom `lnpl` dialect. Registered into stock mlir-opt via
   // --irdl-file=mlir/lnpl.irdl.mlir (no C++ TableGen build).
   module attributes {lnpl.condition_fields = ["counter"], lnpl.lir_version = "0.1", lnpl.module = "login", lnpl.workflow = "wf.login"} {
     "lnpl.step"() {lnpl.node_id = "wf.login.step.1", lnpl.name = "validate input", lnpl.index = 1 : i64} : () -> () loc("wf.login.step.1")
     "lnpl.effect"() {lnpl.node_id = "wf.login.step.1.check", lnpl.kind = "Validation", lnpl.step = "wf.login.step.1"} : () -> () loc("wf.login.step.1.check")
   }
   ```

   Rules:
   - Emit each step's `lnpl.step` followed immediately by its `lnpl.effect` ops.
   - Integers as `N : i64`. Strings escaped with `.replace('"', '\\"')`, the
     same way `emit_mlir` already escapes interned names.
   - `lnpl.condition_fields` renders as an MLIR array of strings:
     `["a", "b"]`; an empty list renders as `[]`.
   - Include `lnpl.guard_mode`, `lnpl.guard_condition`, `lnpl.unroll_round` only
     when not `None`.
   - Every op gets `loc("<node_id>")` — that is D9's second path.

3. Add tests to `impl/tests/test_lnpl_dialect.py` in a new class
   `TestLnplEmission` (**not** toolchain-gated — this is text generation, like
   `TestMlirEmission` in `test_backend.py`). Use the golden IR the way
   `test_backend.py` does (`REPO`, `examples/login.lir.json`) and the same
   `GUARDED` source shape for guard cases.

   - **normal** `test_every_step_becomes_an_lnpl_step_op_in_order` — 6
     `"lnpl.step"` ops for `wf.login`, and the `lnpl.node_id` values appear in
     declared order `wf.login.step.1` … `.6`.
   - **normal** `test_every_op_carries_a_node_id_and_a_location` — for each
     emitted `"lnpl.` line, assert it contains both `lnpl.node_id = "` and
     `loc("`. Assert the count of such lines is > 0 first, so the loop cannot
     pass vacuously.
   - **normal** `test_effects_become_lnpl_effect_ops` — 3 `"lnpl.effect"` ops
     for `wf.login`, with the `Validation` / `RepositoryCall` / `CacheAccess`
     kinds present.
   - **boundary** `test_unrolled_until_rounds_share_one_node_id` — with an
     `until counter >= 10` workflow, the number of distinct `lnpl.node_id`
     values on the guarded step is 1 while `lnpl.unroll_round` runs 1..16
     (RFC-0004 1:다 확장, D11). Assert both the distinct-id count **and** the
     round count.
   - **boundary** `test_unrolled_repeat_rounds_share_one_node_id` — same for
     `repeat 3` (substitute it for the `when` line in `GUARDED`, as
     `test_backend.py::test_repeat_guard_unrolls_to_a_constant_number_of_steps`
     already does): 1 distinct node id, `unroll_round` 1..3. `repeat` carries no
     `guard_mode`, so this is the case that catches an implementation which keys
     the round marker off `guard_mode == "until"`.
   - **error** `test_unknown_workflow_is_an_error` — `emit_lnpl_mlir(golden(),
     "wf.nope")` raises `backend.BackendError`; assert the message names the
     workflow.
   - **boundary** `test_condition_fields_come_from_the_single_source` — assert
     the `lnpl.condition_fields` attribute equals
     `condition_field_names(doc, wf)` rendered, including the empty-list case
     for the golden workflow (D13).

   And one toolchain-gated class `TestEmittedModuleVerifies`:
   - `test_the_emitted_golden_module_passes_the_dialect_verifier` —
     `verify_lnpl_module(emit_lnpl_mlir(golden(), "wf.login"))` does not raise.
   - `test_the_emitted_until_module_passes_the_dialect_verifier` — same for the
     `until` workflow (this is the 16-op case, so it exercises repetition).

## Deliverables

- `impl/lnpl/backend.py` (modified — `_lnpl_ops`, `emit_lnpl_mlir`)
- `impl/tests/test_lnpl_dialect.py` (modified — two new classes)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`, and the **287 pre-existing tests are all still among the
passes** — `emit_mlir` was not touched, so any failure in `test_backend.py`
means this task broke something it should not have.

Then eyeball the artifact once:

```bash
PYTHONPATH=impl .venv/bin/python -c "
import json; from lnpl import backend
print(backend.emit_lnpl_mlir(json.load(open('examples/login.lir.json')), 'wf.login'))"
```

## Out of scope

- Changing `emit_mlir` or the standard-dialect output — task 03.
- Writing the module to disk during `build()` — task 04.
- Any MLIR-text *parser*. The lowering in task 03 consumes `_lnpl_ops`'s
  structured output (D6), not this text.
