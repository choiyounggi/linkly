# Task 02: add three flat marker ops to the lnpl IRDL dialect

## Objective
`mlir/lnpl.irdl.mlir` defines `lnpl.concurrency`, `lnpl.pipeline`, and
`lnpl.guard` as flat (region-less) ops, each requiring a string `lnpl.node_id`.
Stock `mlir-opt --irdl-file` verifies a module that uses them and **rejects** any
of them missing `lnpl.node_id`.

## Wiki pages (read these first, only these)
- wiki/testing/quality/tests-that-cannot-fail.md — use for: the value is that the
  verifier *rejects* a missing node id, not merely accepts a good one; the
  Verify below includes that negative control.

## Inputs
- `mlir/lnpl.irdl.mlir` — current dialect with `@step` and `@effect`, each:
  `%id = irdl.base "#builtin.string"` then `irdl.attributes {"lnpl.node_id" = %id}`.
  Mirror that exact shape.
- Measured (M3/M4): region ops need a borrowed terminator, so these are **flat**
  (no `irdl.region`/`irdl.regions`). Only the quoted `#`-form
  `irdl.base "#builtin.string"` parses (bare `#builtin.string` and
  `"!builtin.string"` do not).
- Decisions that bind you: D2 (flat markers), D3 (only `lnpl.node_id` declared;
  `lnpl.mode`/`lnpl.children`/etc. undeclared/discardable).

## Steps
1. Inside `irdl.dialect @lnpl { ... }`, after `@effect`, add three ops, each
   identical in shape to `@step`:
   ```mlir
   irdl.operation @concurrency {
     %id = irdl.base "#builtin.string"
     irdl.attributes {"lnpl.node_id" = %id}
   }
   irdl.operation @pipeline {
     %id = irdl.base "#builtin.string"
     irdl.attributes {"lnpl.node_id" = %id}
   }
   irdl.operation @guard {
     %id = irdl.base "#builtin.string"
     irdl.attributes {"lnpl.node_id" = %id}
   }
   ```
2. Update the file's header comment: the dialect is no longer only `step`/
   `effect`; note that `concurrency`/`pipeline`/`guard` are **flat structural
   marker ops** carrying `lnpl.node_id` + a discardable `lnpl.children` id-list
   and `lnpl.mode`, and that regions were rejected because IRDL cannot declare a
   terminator (M3). Keep the existing note that undeclared attributes ride along.

## Deliverables
- `mlir/lnpl.irdl.mlir` (modified)

## Verify
Run both — the first must PASS (exit 0), the second must FAIL (non-zero, with the
"expected but not provided" message). Use `.claude/tmp/`, never `/tmp`.
```
OPT=/opt/homebrew/opt/llvm/bin/mlir-opt
# positive: markers verify + loc round-trips
printf 'module {\n  "lnpl.concurrency"() {lnpl.node_id="c1", lnpl.mode="parallel", lnpl.children=["s1","s2"]} : () -> () loc("c1")\n  "lnpl.step"() {lnpl.node_id="s1"} : () -> () loc("s1")\n  "lnpl.pipeline"() {lnpl.node_id="p1", lnpl.children=["s1"]} : () -> () loc("p1")\n  "lnpl.guard"() {lnpl.node_id="g1", lnpl.mode="when"} : () -> () loc("g1")\n}\n' > .claude/tmp/t02_pos.mlir
$OPT --irdl-file=mlir/lnpl.irdl.mlir --mlir-print-debuginfo .claude/tmp/t02_pos.mlir; echo "pos exit=$?"
# negative: a marker with no node_id is rejected
printf 'module {\n  "lnpl.guard"() {lnpl.mode="when"} : () -> ()\n}\n' > .claude/tmp/t02_neg.mlir
$OPT --irdl-file=mlir/lnpl.irdl.mlir .claude/tmp/t02_neg.mlir; echo "neg exit=$?"
```
Success = pos exit 0 with `loc("c1")`/`loc("g1")` printed; neg exit non-zero with
`'lnpl.guard' op attribute "lnpl.node_id" is expected but not provided`.

## Out of scope
- Emitting these ops from Python — that is task 03.
- Regions, `omp.terminator`, or any terminator op (D2 rejected regions).
