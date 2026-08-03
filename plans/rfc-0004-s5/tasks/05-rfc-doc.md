# Task 05: record OQ①/③/④ resolved and ① deferred in RFC-0004

## Objective
`rfcs/0004-compiler.md` reflects what shipped: OQ① (version pinning) is resolved
by `mlir/llvm.pin` + its reader; limitations ③ and ④ are resolved by the flat
marker ops; the op list gains the three new ops; and limitation ① (the real C++
`ConversionPattern`) is explicitly recorded as **deferred** with rationale.

## Wiki pages (read these first, only these)
- wiki/testing/quality/spec-artifact-checks.md — use for: a doc-as-spec change
  must match the shipped artifact exactly (the op names, the pin file path, the
  reader name), and cross-doc ids/claims must resolve — not aspirational text.

## Inputs
- `rfcs/0004-compiler.md`, `## Open Questions` section:
  - The boxed follow-up list items **①/③/④** (the block that states: ① lowering
    does not re-parse the module; ③ structural node ids do not reach the module;
    ④ the dialect cannot express Concurrency — parallel and sequential are
    byte-identical).
  - Numbered open question **1. MLIR/LLVM 버전 고정 정책** (OQ①) — currently
    "어떤 형식의 핀 파일로 무엇을 고정할지는 미결" with the form fixed (one
    committed pin file, CI reads it).
  - Numbered open question **2** — already "해소 (2026-08-01)", lists the op set
    (`lnpl.step`, `lnpl.effect`) and attributes.
- Shipped facts to cite (from tasks 01–04): pin file `mlir/llvm.pin` (format
  `llvm 22.1.8`), reader `backend.pinned_llvm_version()`, new ops
  `lnpl.concurrency`/`lnpl.pipeline`/`lnpl.guard` carrying `lnpl.node_id` +
  `lnpl.children` + mode/name/condition/count, encoded **flat** (measured: IRDL
  region ops need a borrowed terminator — M3).
- Decisions that bind you: D11 (what to mark), D12 (① stays deferred), D2/D4/D5.

## Steps
1. **OQ① → resolved.** Under numbered open question 1, add a resolution note
   (mirror the "해소 (…)" style used by question 2): the canonical pin is
   `mlir/llvm.pin` (one `llvm <version>` line), read by
   `backend.pinned_llvm_version()` and checked by a test; the version literal is
   declared **only** there. Note there is no CI, so the test suite + toolchain
   helper are the reader (the "선언이 둘이면 갈라진다" principle is honored: one
   machine-read declaration).
2. **Op list (question 2) → extend.** Add `lnpl.concurrency`, `lnpl.pipeline`,
   `lnpl.guard` to the op list: flat marker ops (no regions), each with required
   string `lnpl.node_id`, plus discardable `lnpl.children` (ordered child node
   ids) and `lnpl.mode`/`lnpl.name`/`lnpl.guard_condition`/`lnpl.count`. One line
   on *why flat*: IRDL cannot declare a terminator or `NoTerminator`, so a
   region-bearing op would have to embed a foreign terminator (`omp.terminator`);
   flat markers avoid that coupling.
3. **③ and ④ → resolved.** In the boxed follow-up list, mark ③ and ④ resolved:
   the structural node ids now reach the module as `lnpl.node_id` on the marker
   ops (③), and a `parallel` workflow now emits an `lnpl.concurrency` marker its
   sequential form does not, so the two modules differ (④). Reference the tests
   in `test_lnpl_dialect.py::TestStructuralMarkers`.
4. **① → explicitly deferred.** Leave ① open but state the decision: the real C++
   `ConversionPattern` (`LnplOps.td` + `mlir_tablegen` + `lnpl-opt
   --lower-lnpl-to-std` + cmake) is **deferred** — `cmake` is not installed and
   the C++ path couples the build to the LLVM-22 ABI, which the project avoids
   while it is unpinned at the ABI level; S5's input remains the in-memory op
   stream. This is issue #7's own recommended order.
5. Do not alter unrelated RFC sections.

## Deliverables
- `rfcs/0004-compiler.md` (modified: OQ① resolved, op list extended, ③/④
  resolved, ① deferred)

## Verify
Checklist (record each with a file citation in the task report — this is a doc
task, no runnable command):
- [ ] OQ① now carries a resolution note naming `mlir/llvm.pin` and
      `pinned_llvm_version()`.
- [ ] The op list names all five ops (`step`, `effect`, `concurrency`,
      `pipeline`, `guard`) and states markers are flat with `lnpl.children`.
- [ ] ③ and ④ are marked resolved with a pointer to `TestStructuralMarkers`.
- [ ] ① remains open but is explicitly labeled deferred with the cmake/ABI
      rationale.
- [ ] `grep -n "llvm.pin\|pinned_llvm_version\|lnpl.concurrency\|lnpl.guard"
      rfcs/0004-compiler.md` returns the added references.

## Out of scope
- Any code or test change (done in 01–04).
- Actually building the C++ path (deferred — D12).
