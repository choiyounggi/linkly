# Task 03: emit flat structural marker ops from the node tree

## Objective
`emit_lnpl_mlir` now emits, as a prefix block before the step/effect ops, one
flat marker op per `Concurrency`/`Pipeline`/`Guard` node — carrying its node id,
`loc`, mode/name/condition/count, and an ordered `lnpl.children` id-list. The
standard-dialect output (`emit_mlir`) is **byte-identical** to before, because a
new `_structural_markers()` function supplies the markers and `_lnpl_ops` is not
touched.

## Wiki pages (read these first, only these)
- wiki/testing/quality/behavior-not-implementation.md — use for: the invariant
  that the frozen standard-dialect bytes and the `_lnpl_ops` seam tests must not
  change; only the `lnpl`-dialect text gains markers.

## Inputs
- `impl/lnpl/backend.py`:
  - `_lnpl_ops(document, workflow_id)` returns `(module_attrs, ops)` — **leave it
    exactly as is** (5 tests + `emit_mlir` unpack it as a 2-tuple).
  - `emit_lnpl_mlir` (~line 425): `module_attrs, ops = _lnpl_ops(...)`, then a
    `module attributes {...} {` line, then the `for op in ops:` loop, then `}`.
  - `emit_mlir` (~line 640): `return _render_std(*_lnpl_ops(...))` — **do not
    touch**.
  - Helpers: `_mlir_attr_dict(pairs)` drops any pair whose value is `None`;
    `_mlir_attr` renders a `list` as `["a", "b"]` and an `int` as `N : i64`;
    `_mlir_str(s)` returns `"..."`. Reuse them — no new rendering code.
- Doc construction (reuse, do not invent): `from lnpl.lower import lower` /
  `from lnpl.parser import parse`; `doc = lower(parse(src), "t").to_document()`;
  workflow id = `next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")`.
  A parallel source is `"workflow W\n    parallel\n    load user\n    authenticate\n    merge\n"`
  (prepend the `GUARDED` header from `impl/tests/fixtures.py` if a bare workflow
  will not lower).
- IR node fields (from `lower.py`): `Concurrency` has `mode` (`"parallel"`) +
  `children`; `Pipeline` has `name` + `children`; `Guard` has `mode`
  (`when`/`until`/`repeat`), `condition` (when/until) **or** `count` (repeat) +
  `children`. `WorkflowStep`'s children are effects, not structural.
- Decisions that bind you: D7 (separate function, `_lnpl_ops` untouched), D8
  (pre-order DFS, attrs, prefix placement).

## Steps
1. Add, near `_lnpl_ops`, a pure walk (no I/O):
   ```python
   def _structural_markers(document, workflow_id):
       """RFC-0004 ③/④: flat marker ops for Guard/Concurrency/Pipeline nodes.

       `_steps_in_order` flattens these structural nodes out of the step stream,
       so their ids never reached the artifact (③) and a parallel workflow was
       byte-identical to its sequential form (④). This walks the *un-flattened*
       node tree and materialises one marker op per structural node, carrying its
       id, mode, and ordered immediate children. It reads only the node tree — the
       step/effect stream (`_lnpl_ops`) is untouched.
       """
       nodes = {n["id"]: n for n in document["nodes"]}
       wf = nodes.get(workflow_id)
       if wf is None or wf["kind"] != "Workflow":
           raise BackendError("no such workflow: %r" % workflow_id)
       markers = []
       _walk_markers(nodes, wf.get("children", []), markers)
       return markers

   def _walk_markers(nodes, ids, out):
       for nid in ids:
           node = nodes[nid]
           kind = node["kind"]
           if kind == "Concurrency":
               out.append(("lnpl.concurrency", nid, [
                   ("lnpl.mode", node.get("mode")),
                   ("lnpl.children", list(node.get("children", []))),
               ]))
               _walk_markers(nodes, node.get("children", []), out)
           elif kind == "Pipeline":
               out.append(("lnpl.pipeline", nid, [
                   ("lnpl.name", node.get("name")),
                   ("lnpl.children", list(node.get("children", []))),
               ]))
               _walk_markers(nodes, node.get("children", []), out)
           elif kind == "Guard":
               out.append(("lnpl.guard", nid, [
                   ("lnpl.mode", node.get("mode")),
                   ("lnpl.guard_condition", node.get("condition")),
                   ("lnpl.count", node.get("count")),
                   ("lnpl.children", list(node.get("children", []))),
               ]))
               _walk_markers(nodes, node.get("children", []), out)
           # WorkflowStep: its children are effects, handled by _lnpl_ops. Skip.
   ```
2. In `emit_lnpl_mlir`, after the `module attributes {...} {` line and **before**
   the `for op in ops:` loop, insert the marker prefix:
   ```python
   for opname, node_id, attrs in _structural_markers(document, workflow_id):
       lines.append('  "%s"() {%s} : () -> () loc(%s)' % (
           opname,
           _mlir_attr_dict([("lnpl.node_id", node_id)] + attrs),
           _mlir_str(node_id)))
   ```
   (`lnpl.node_id` first keeps it stable; `_mlir_attr_dict` drops the `None`
   entries — e.g. `lnpl.count` on a `when` guard.)
3. Do not change `_lnpl_ops`, `_render_std`, or `emit_mlir`.

## Deliverables
- `impl/lnpl/backend.py` (add `_structural_markers` + `_walk_markers`; insert the
  marker prefix loop into `emit_lnpl_mlir`)

## Verify
- Standard-dialect output unchanged (A4):
  `PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl`
  → the golden/std-dialect emission tests still pass **without** touching
  `impl/tests/golden/`. (Some `emit_lnpl_mlir` exact-text tests will now fail on
  the added markers — that is expected and is fixed in task 04, not by editing
  golden std fixtures.)
- Markers present for a parallel workflow:
  ```
  PYTHONPATH=impl .venv/bin/python - <<'PY'
  from lnpl import lexer, parser, lower, backend
  src = "workflow W:\n  parallel:\n    - do A\n    - do B\n"
  # build a document via the repo's normal path; then:
  # print(backend.emit_lnpl_mlir(doc, wid))
  PY
  ```
  Expect `"lnpl.concurrency"() {... lnpl.children = ["...","..."] ...}` in output.
  (If the exact front-end call path is unclear, derive it from an existing
  `test_lnpl_dialect.py` helper — do NOT invent an API.)

## Out of scope
- Writing the ③/④ assertion tests and updating the now-stale `emit_lnpl_mlir`
  text expectations — task 04.
- Touching `_lnpl_ops`, `_render_std`, `emit_mlir`, or `impl/tests/golden/`.
