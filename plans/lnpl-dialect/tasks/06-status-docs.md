# Task 06: update the status surfaces (ROADMAP, READMEs)

## Objective

The roadmap and both READMEs stop listing the `lnpl` dialect as missing and stop
claiming it needs a C++ TableGen build. The R13 risk entry is closed. Neither
README grows a new build prerequisite, because there is none.

## Wiki pages (read these first, only these)

None apply — status prose, not a design or testing decision. (`[no-wiki]`.)

## Inputs

- Tasks 01-04 complete; task 05 owns the normative record (`rfcs/`, backend
  docstring) and is disjoint from these files.
- The exact locations to change, measured this session:
  - `docs/ROADMAP.md:126` — `> … dialect(S4)** — C++ TableGen 빌드가 필요해 이번
    조각에서 제외했고, 이탈을 RFC-0004 …` (the deviation note).
  - `docs/ROADMAP.md:161-162` — the Phase 2 remaining-work bullets listing
    "`lnpl` MLIR dialect + S4 변환" and the S5→S6→S7 line.
  - `docs/ROADMAP.md:184` — risk **R13**, "`lnpl` dialect 커스텀 op 목록 미확정 +
    MLIR Location 구성 방식 미결".
  - `docs/ROADMAP.md:300` — the open-questions table row
    "② `lnpl` dialect op 목록·Location 표기 | Phase 2 (R13)".
  - `README.md:323` — issue table row:
    `| [#1](…/issues/1) | RFC-0004 S4 — the custom \`lnpl\` MLIR dialect (needs a C++ TableGen build) |`
  - `README.ko.md:300` — the same row in Korean:
    `RFC-0004 S4 — 커스텀 \`lnpl\` MLIR dialect(C++ TableGen 빌드 필요)`
- Facts you may state (all measured this session, do not hedge them):
  - The dialect is defined in `mlir/lnpl.irdl.mlir` and registered into stock
    `mlir-opt` via `--irdl-file`.
  - **No new build dependency.** The existing `brew install llvm` prerequisite is
    unchanged; cmake and a C++ compiler are not required.
  - The verifier enforces `lnpl.node_id` on every op.
- Decisions that bind you: **D1**, **D7**, **D9**, and the two limitations from
  task 05 step 1 (op-stream lowering; no S3 context side table).

## Steps

1. `docs/ROADMAP.md:126` — rewrite the deviation note as done. State that S4 is
   implemented via IRDL and that the C++ TableGen premise was both false and
   unnecessary. Carry forward the two remaining limitations in one sentence each
   (op-stream lowering rather than a re-parsing MLIR pass; no S3 compile-context
   side table), so the roadmap does not overclaim.

2. `docs/ROADMAP.md:161-162` — move the "`lnpl` MLIR dialect + S4 변환" bullet
   out of remaining work. **Keep** the S5→S6→S7 bullet but narrow it: measured
   this session, `build()` runs only `--convert-scf-to-cf`,
   `--convert-cf-to-llvm`, `--convert-func-to-llvm`, `--convert-arith-to-llvm`,
   so `async`, `memref` and `vector` are genuinely still unimplemented and the
   bullet should name those three rather than the full list.

3. `docs/ROADMAP.md:184` — close **R13**. The op list and the Location notation
   are decided (task 05 step 2 records them normatively); reference that rather
   than restating the design.

4. `docs/ROADMAP.md:300` — update the open-questions row for ② from "Phase 2
   (R13)" to resolved, pointing at `rfcs/0004-compiler.md`. Leave row ① (version
   pinning) alone.

5. `README.md:323` and `README.ko.md:300` — remove issue #1's row from the open
   issues table, since this PR closes it. Check the surrounding table: if #2 and
   #3 rows are still accurate, leave them untouched. If removing the row empties
   the table, keep the table with the remaining rows rather than deleting the
   section.

6. Both READMEs: confirm the prerequisites section still says only
   `brew install llvm` and **add no new prerequisite**. If either README lists
   mode B prerequisites, add a one-line note that the `lnpl` dialect is loaded
   from `mlir/lnpl.irdl.mlir` at build time and needs no extra tooling. Do not
   invent a section that does not exist.

   The handoff's completion criterion "빌드 의존성(cmake·C++ 툴체인)이 늘어났으므로
   README/ROADMAP에 요구사항 반영" is **void**, not satisfied: under D1 no
   dependency grew. Say so explicitly wherever the roadmap tracks that criterion,
   so a later reader does not conclude the step was forgotten.

## Deliverables

- `docs/ROADMAP.md` (modified)
- `README.md` (modified)
- `README.ko.md` (modified)

## Verify

```bash
cd ~/Desktop/workspace/ai
git grep -n "C++ TableGen\|TableGen 빌드" -- docs README.md README.ko.md
git grep -n "R13" -- docs
```

Success = the first command returns nothing, and every remaining `R13` mention
reads as closed. Then re-run the suite to confirm no doc edit touched a fixture
or a docstring a test asserts on:

```bash
mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`.

Keep the two READMEs' claims **identical in content** — they are translations of
each other, and a fact fixed in only one of them is the drift this repo already
guards against elsewhere.

## Out of scope

- `rfcs/0004-compiler.md`, `impl/lnpl/backend.py`, the golden fixtures — task 05.
- The PR body and the follow-up issue.
