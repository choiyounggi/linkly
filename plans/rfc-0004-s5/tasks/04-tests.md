# Task 04: prove ③ and ④, refresh stale expectations, keep regression 0

## Objective
`test_lnpl_dialect.py` gains a `TestStructuralMarkers` class proving limitation ④
(parallel ≠ sequential module) and limitation ③ (Guard/Concurrency/Pipeline ids
reach the artifact), including a negative control. Any existing `emit_lnpl_mlir`
exact-text expectations that the marker prefix made stale are updated to expect
the markers (never by loosening an assertion). The full suite is green.

## Wiki pages (read these first, only these)
- wiki/testing/quality/minimum-case-set.md — use for: cover normal + boundary +
  error for the new behavior (parallel-with-markers, no-structure workflow,
  verifier-rejects-missing-id).
- wiki/testing/quality/tests-that-cannot-fail.md — use for: the ④ test must
  actually distinguish parallel from sequential (assert the concurrency marker is
  present in one and absent in the other), and the ③ negative control drives the
  real `mlir-opt` verifier.
- wiki/testing/quality/spec-artifact-checks.md — use for: the ③ assertion is that
  every structural IR node id *resolves* to an `lnpl.node_id` in the artifact.

## Inputs
- `impl/tests/test_lnpl_dialect.py` helpers you MUST reuse (do not invent):
  `golden()`, `guarded_doc(guard)`, `node_ids(lnpl_text, op='"lnpl.step"')`,
  `module(body)`, `NEEDS_TOOLS` (skip-unless-toolchain), and
  `from lnpl.lower import lower` / `from lnpl.parser import parse`.
- Doc construction: `doc = lower(parse(src), "t").to_document()`. Get the
  workflow id from the doc, do **not** hardcode it:
  `wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")`.
- DSL surface syntax (measured from `parser.py`, no indentation semantics):
  - parallel block: a `parallel` line, then the step lines, then a `merge` line.
  - guard: a `when <cond>` / `until <cond>` / `repeat <n>` line owns the next item.
  - `guarded_doc("when token missing")` yields a doc with a `Guard` node.
- Marker op names (from task 03): `"lnpl.concurrency"`, `"lnpl.pipeline"`,
  `"lnpl.guard"`; each carries `lnpl.node_id`, `lnpl.children`, and mode/name.
- Decisions that bind you: D9 (④ proof), D10 (③ proof), A5 (regression 0).

## Steps
1. Add `class TestStructuralMarkers(unittest.TestCase)` with at least:
   - `test_parallel_differs_from_sequential` (④): build
     ```
     par = "workflow W\n    parallel\n    load user\n    authenticate\n    merge\n"
     seq = "workflow W\n    load user\n    authenticate\n"
     ```
     (prepend whatever entity/capability declarations `parse`/`lower` require —
     reuse the `GUARDED` header pattern if a bare workflow won't lower). Emit both
     with `backend.emit_lnpl_mlir(doc, wid)`. Assert the two texts are **not
     equal**, AND `'"lnpl.concurrency"'` is `in` the parallel text and `not in`
     the sequential text.
   - `test_structural_node_ids_reach_the_module` (③): build a doc containing a
     `Guard` (via `guarded_doc("when token missing")`) — and, if a Concurrency/
     Pipeline is easy to include, a parallel/pipeline block too. For each
     structural node in `doc["nodes"]` whose kind is in
     `{"Guard","Concurrency","Pipeline"}`, assert its `id` appears in the emitted
     text as an `lnpl.node_id` (reuse `node_ids(text, op='"lnpl.guard"')` etc.,
     or a direct `assertIn('lnpl.node_id = "%s"' % nid, text)`).
   - `test_no_structural_nodes_emits_no_markers` (boundary): a flat workflow
     (`seq` above) emits text containing none of `"lnpl.concurrency"`,
     `"lnpl.pipeline"`, `"lnpl.guard"`.
   - `@NEEDS_TOOLS test_markers_verify_and_missing_id_is_rejected` (error/negative
     control): (a) the emitted parallel module passes
     `backend.verify_lnpl_module(text)`; (b) a hand-built module with a marker op
     lacking `lnpl.node_id` (wrap via `module('"lnpl.guard"() {lnpl.mode="when"} :
     () -> ()')`) makes `verify_lnpl_module` raise `BackendError`.
2. Find every existing test that asserts the **exact** `emit_lnpl_mlir` text (not
   the std-dialect `emit_mlir`) and update its expected string to include the new
   marker prefix lines. Do **not** touch `impl/tests/golden/` (those are the
   std-dialect bytes and must stay frozen — A4). Do not weaken any assertion.
3. Confirm the two load-bearing deliberate-mismatch tests and the
   `_lnpl_ops`-routes-through-`_steps_in_order` test (`test_lnpl_dialect.py`
   ~line 495) still pass unchanged.

## Deliverables
- `impl/tests/test_lnpl_dialect.py` (add `TestStructuralMarkers`; refresh any
  stale `emit_lnpl_mlir` text expectations)

## Verify
- `mkdir -p .claude/tmp && PYTHONPATH=impl .venv/bin/python -m unittest discover
  -s impl/tests -t impl` → OK, 0 failures, 0 errors. Skips are acceptable only for
  `@NEEDS_TOOLS` cases when the toolchain is absent (here it is present, so they
  must run and pass).
- `PYTHONPATH=impl .venv/bin/python -m unittest
  impl.tests.test_lnpl_dialect.TestStructuralMarkers -v` → all cases pass.

## Out of scope
- Editing `rfcs/0004-compiler.md` — task 05.
- Any change to `impl/tests/golden/` or to `backend.py`.
