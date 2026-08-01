# Task 05: retire the S4 deviation in the normative record

## Objective

`rfcs/0004-compiler.md` no longer claims S4 is unimplemented, and its Open
Question ② (custom op list + Location notation) is recorded as resolved.
`impl/lnpl/backend.py`'s module docstring describes what the pipeline now does.
The golden fixtures are regenerated in this commit, because the header comment
they contain changes here.

## Wiki pages (read these first, only these)

None apply — this is editing project-specific normative prose, not a design or
testing decision. (`[no-wiki]` per the planning protocol.)

## Inputs

- Tasks 01-04 complete: the dialect is defined, registered, verified, emitted,
  lowered, and gated in `build()`.
- The exact locations to change, measured this session:
  - `rfcs/0004-compiler.md:429-439` — the `> **구현 이탈 1건 …**` blockquote under
    `## Open Questions`, which states S4 emits standard dialects directly and
    that registering a custom dialect "requires a C++ TableGen build".
  - `rfcs/0004-compiler.md:447-449` — Open Question ②, which leaves the custom op
    list and the Location notation undecided.
  - `impl/lnpl/backend.py:1-21` — the module docstring, whose second paragraph
    records the same deviation and whose `Pipeline:` block omits the lnpl stage.
  - `impl/lnpl/backend.py` `_render_std` header comment lines — currently
    `// RFC-0004 S4-S5: standard dialects (func, arith). See backend.py for the`
    / `// recorded deviation: the custom `lnpl` dialect is not yet registered.`
- Decisions to record: **D1** (IRDL, not C++ ODS — and why), **D6** + **D8** (the
  lowering reads the op stream; the artifact is load-bearing because `build()`
  gates on the verifier), **D7** (the op list, which resolves Open Q②), **D9**
  (`loc()` NameLoc, which resolves the other half of Open Q②), **D11**
  (unroll rounds share one node id), **D14** (no compile-context side table
  exists, so that part of the S4 invariant stays open).

## Steps

1. Rewrite the `rfcs/0004-compiler.md` deviation blockquote. It must now state:
   - S4 **is** implemented: `emit_lnpl_mlir` produces an `lnpl` dialect module,
     defined declaratively in `mlir/lnpl.irdl.mlir` and registered into stock
     `mlir-opt` with `--irdl-file`, so no C++ TableGen build is required. The
     old blocker was measured and is false — but it is also moot, because IRDL
     needs none of those libraries.
   - The measured pipeline is now
     `IR → lnpl dialect MLIR (verified) → 표준 dialect MLIR → (mlir-opt: scf→cf→llvm)
     → LLVM dialect → (mlir-translate) → LLVM IR → (clang) → 네이티브 바이너리`.
   - **Two honest limitations remain** — write these plainly, do not soften them:
     ① S5's lowering consumes the in-memory op stream that the `lnpl` module is
     serialised from, rather than re-parsing that module; the module is kept
     load-bearing by `build()` failing when the dialect verifier rejects it.
     Making the lowering a real MLIR `ConversionPattern` is tracked as a
     follow-up issue. ② The RFC's S3 compile-context side table does not exist in
     the reference implementation, so "materialise the whole context as
     attributes" is satisfied only for the compile decisions that exist at
     emission time (guard mode, guard condition, unroll round, condition-field
     list).

2. Update Open Question ②. The op list and the Location notation are now decided,
   so record the decision rather than deleting the entry: ops are `lnpl.step` and
   `lnpl.effect` (zero operands, zero results, flat in the module body, guards as
   attributes); the Location path is `loc("<node id>")` (NameLoc) carried
   alongside the `lnpl.node_id` attribute on every op. Note that
   `lnpl.node_id`'s presence is enforced by the dialect verifier via
   `irdl.attributes`. Leave Open Question ① (version pinning) untouched — D1
   deliberately avoided making it urgent.

3. Rewrite `impl/lnpl/backend.py`'s module docstring: drop the deviation
   paragraph, describe the `lnpl` stage and both traceability paths, and update
   the `Pipeline:` block to include
   `.lnpl.mlir --verify(mlir-opt --irdl-file)-->` ahead of the standard-dialect
   step. Keep the existing paragraph about the C runtime shim and what the
   differential check compares — it is still accurate.

4. Change the two `_render_std` header comment lines so the generated
   standard-dialect module no longer says the dialect is unregistered. Suggested
   replacement, same two-line shape:

   ```
   // RFC-0004 S5: standard dialects (func, arith), lowered from the `lnpl`
   // dialect module emitted at S4 (see mlir/lnpl.irdl.mlir).
   ```

5. **Do not touch the golden fixtures.** Task 03's comparison strips the leading
   `//` block from both sides precisely so that step 4 is possible without
   regenerating them. The fixtures hold pre-change bytes and are the only
   remaining evidence that the S4 refactor preserved behaviour; regenerating them
   would make that claim circular. If
   `TestStandardLoweringIsUnchanged` goes red after step 4, the change escaped
   the comment block — fix step 4, not the fixture.

## Deliverables

- `rfcs/0004-compiler.md` (modified)
- `impl/lnpl/backend.py` (modified — module docstring + two comment lines)

Nothing under `impl/tests/golden/` changes in this task.

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
git status --short impl/tests/golden/
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `git status` shows the golden directory **clean** (step 5), the suite
reports `OK`, and:

```bash
git grep -n "not yet registered\|C++ TableGen\|TableGen 빌드" -- rfcs impl
```

returns nothing.

## Out of scope

- `docs/ROADMAP.md`, `README.md`, `README.ko.md` — task 06 (parallel-ok with
  this one; they touch disjoint files).
- Regenerating the golden fixtures (step 5).
- The PR body and the follow-up issues — task 07.
