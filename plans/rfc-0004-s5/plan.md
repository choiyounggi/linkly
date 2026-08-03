# rfc-0004-s5 — resolve OQ① + enrich the lnpl dialect (issue #7)

Goal: Close RFC-0004 issue #7 to the scope owner 영기 chose — **Pin → enrich the
`lnpl` IRDL dialect (flat marker ops) → defer the C++ pass**:

1. Resolve RFC-0004 **Open Question ①** — commit one canonical LLVM/MLIR
   version-pin file and give it a real reader (the repo has **no CI**, so the
   reader is the toolchain helper + a test, not a CI workflow).
2. Enrich `mlir/lnpl.irdl.mlir` with three flat marker ops — `lnpl.concurrency`,
   `lnpl.pipeline`, `lnpl.guard` — so the **structural node ids** (limitation ③)
   and the **parallel-vs-sequential distinction** (limitation ④) reach the
   artifact.
3. Emit those markers from `impl/lnpl/backend.py` **without perturbing** the
   existing step/effect stream (D12 seam, guard unroll, cache-budget truncation)
   or the standard-dialect output.
4. Prove ③ and ④ with tests; regression 0.
5. Record all of the above in `rfcs/0004-compiler.md`, and **explicitly defer**
   limitation ① (the real C++ `ConversionPattern`).

Acceptance criteria:
- A1 `mlir/llvm.pin` is the single machine-read source of the pinned version; a
  test parses it and (when the toolchain is present) asserts the installed
  `mlir-opt` matches it. No LLVM version literal is re-declared in code.
- A2 The enriched IRDL verifies the three new ops in stock `mlir-opt --irdl-file`
  and **rejects** any of them missing `lnpl.node_id` (verifier-enforced, not
  asserted).
- A3 A `parallel` workflow and its sequential equivalent now emit **different**
  `lnpl` modules (④); every `Guard`/`Concurrency`/`Pipeline` node id appears in
  the `lnpl` module as an `lnpl.node_id` (③).
- A4 `emit_mlir` (standard-dialect S5 text) is **byte-identical** below the
  leading comment block to pre-change output — markers are S4-only.
- A5 The full unittest suite is green (regression 0), including the two
  load-bearing deliberate-mismatch tests.
- A6 `rfcs/0004-compiler.md` marks OQ① resolved, ③/④ resolved, lists the three
  new ops under the (formerly Open-Q2) op list, and records limitation ① deferred
  with rationale.

Stack: Python 3.13 (`.venv/bin/python`; deps `jsonschema` only — no new Python
deps). Homebrew LLVM/MLIR **22.1.8**, keg-only at `/opt/homebrew/opt/llvm/bin`
(measured present; `which` misses it because keg-only formulae are off-PATH).
`cmake` is **not** installed and must stay uninstalled (C++ path is deferred).
Tests: `mkdir -p .claude/tmp && PYTHONPATH=impl .venv/bin/python -m unittest
discover -s impl/tests -t impl` (README:245).

## Measured facts this plan is built on (not assumptions)

- M1 `mlir-opt`/`mlir-tblgen` present, LLVM 22.1.8; `cmake` absent
  (`brew list cmake` empty). → C++ path is not merely undesired, it is
  unbuildable here without a new install.
- M2 The concurrency/guard structure is **not lost**: `_workflow_steps` returns
  the full `nodes` dict (Concurrency/Pipeline/Guard nodes with ids + children);
  `_steps_in_order` only *flattens* it into the linear step list. So the fix is
  contained to S4 (`backend.py` + the IRDL) — no `lower.py`/schema change.
- M3 A **region-bearing** IRDL op requires a terminator ("block with no
  terminator"), and IRDL exposes **no** way to declare a terminator op or a
  `NoTerminator`/RegionKind trait. Only a *borrowed* foreign terminator
  (`omp.terminator`, `llvm.unreachable`) verifies in a region. → true regions
  cost a foreign-dialect wart in the artifact.
- M4 **Design F verifies**: flat `lnpl.concurrency`/`lnpl.pipeline`/`lnpl.guard`
  ops carrying required-string `lnpl.node_id` + discardable `lnpl.mode` +
  `lnpl.children` (string array) verify in stock `mlir-opt --irdl-file`; `loc(id)`
  survives `--mlir-print-debuginfo` round-trip; a marker missing `lnpl.node_id`
  is **rejected**. (Spikes in `.claude/tmp/`.)
- M5 The repo has **no CI** (`.github` absent). OQ①'s "CI reads the pin file" is
  satisfied by the toolchain helper + test suite as the reader.

## Decisions

| # | Decision | Choice | Wiki basis |
|---|----------|--------|------------|
| D1 | Overall scope | Pin + IRDL dialect enrichment; **defer** the C++ `ConversionPattern` (limitation ①). Do **not** install cmake or create `.td`/`CMakeLists`/`lnpl-opt` | `[no-wiki]` — 영기's decision (scope question, this session) |
| D2 | Concurrency/guard encoding | **Design F — flat marker ops**, not regions. Grounded in M3 (regions need a borrowed terminator; IRDL can't declare one) | `[no-wiki]` — 영기's decision (encoding question), measured M3 |
| D3 | New `lnpl` op set | `lnpl.concurrency`, `lnpl.pipeline`, `lnpl.guard`. Each declares **only** `lnpl.node_id = irdl.base "#builtin.string"` (required + string, so the verifier rejects missing/non-string). All other attrs (`lnpl.mode`, `lnpl.children`, `lnpl.name`, `lnpl.guard_condition`, `lnpl.count`) ride **undeclared/discardable**, matching how `lnpl.step`/`lnpl.effect` already work | testing-quality-tests-that-cannot-fail (verifier that can actually reject) + RFC-0004 §Reference-level (materialize decisions as op attributes) |
| D4 | Pin file | `mlir/llvm.pin`, one line, format `llvm 22.1.8` (matches `brew list --versions llvm`; single token to compare; no YAML dep). It is the **only** machine-read declaration of the version | platforms-toolchains-version-management (one committed pin as the source of truth; not README prose, not a duplicated literal) |
| D5 | Pin reader (no CI) | `pinned_llvm_version()` in `backend.py` reads `mlir/llvm.pin`; a test in `test_backend.py`: (a) parses the pin, (b) if `toolchain_available()`, asserts the pin version string appears in `mlir-opt --version`. **No hard build gate** — drift fails a test, never the build | platforms-toolchains-version-management + testing-quality-tests-that-cannot-fail |
| D6 | Pin file location | Absolute path from `backend.__file__` (`<repo>/mlir/llvm.pin`), exposed as `LLVM_PIN_PATH`, exactly like `LNPL_IRDL_PATH`. Never cwd-relative (`build()` runs in an arbitrary workdir) | platforms-environment-path-resolution (locate correctness-critical files by anchored path, not cwd/PATH) |
| D7 | Where markers come from | **Do NOT change `_lnpl_ops`'s arity** — 5 existing tests + the `emit_mlir` splat unpack it as `(module_attrs, ops)`. Add a **separate** `_structural_markers(document, workflow_id)`. `emit_lnpl_mlir` calls both and renders markers; `emit_mlir`→`_render_std(*_lnpl_ops(...))` is **untouched** → standard-dialect output byte-identical (A4). The flat `ops` path (D12 seam, unroll, truncation) is not read or modified | testing-quality-behavior-not-implementation (a behavior-preserving change must not alter the frozen std-dialect output or the seam tests) |
| D8 | Marker walk & placement | `_structural_markers` does a **pre-order DFS** from `wf["children"]` over `nodes` (`nodes = {n["id"]: n for n in document["nodes"]}`): `Concurrency`→`lnpl.concurrency` (`lnpl.mode` from `node["mode"]`, e.g. `"parallel"`), `Pipeline`→`lnpl.pipeline` (`lnpl.name` from `node["name"]`), `Guard`→`lnpl.guard` (`lnpl.mode` from `node["mode"]` ∈ when/until/repeat; `lnpl.guard_condition` from `node.get("condition")`; `lnpl.count` from `node.get("count")`). Each marker carries `lnpl.node_id` + `loc(id)` + `lnpl.children` = ordered **immediate child node ids** (`node.get("children")`, authored/pre-flatten). Render with the existing `_mlir_attr_dict`/`_mlir_str`/`_mlir_str` helpers (which already drop `None` keys and render a list as `["a","b"]`). Markers render as a **prefix block** inside the module, before the step/effect ops | `[no-wiki]` — engineering call; pre-order + child-id lists make ③ ids present and the structure reconstructable by a future pass |
| D9 | ④ proof | A test emits a `parallel` workflow and its sequential equivalent and asserts the two `lnpl` module texts **differ** (concurrency marker present in one, absent in the other) — the exact byte-identity the issue measured as the bug | testing-quality-tests-that-cannot-fail |
| D10 | ③ proof | A test asserts every `Guard`/`Concurrency`/`Pipeline` node id in the IR appears as an `lnpl.node_id` in the emitted `lnpl` module | testing-quality-spec-artifact-checks (ids resolve across the IR↔artifact boundary) |
| D11 | RFC edits | In `rfcs/0004-compiler.md`: mark **OQ① resolved** (pin file canonical + reader); add the three ops to the (Open-Q2) op list; mark limitations **③ and ④ resolved**; record limitation **① deferred** (C++ `ConversionPattern`) with the M1/M3 rationale | testing-quality-spec-artifact-checks (doc-as-spec: the RFC must match what shipped) |
| D12 | C++ path artifacts | None created. No `LnplOps.td`, no `CMakeLists.txt`, no `tools/lnpl-opt`, no cmake install. Limitation ① stays a documented follow-up | `[no-wiki]` — 영기's decision (D1) |

Ingest candidates (for `knowledge-flush`, not this loop): "declarative MLIR
dialects via IRDL cannot declare a terminator or NoTerminator trait, so a
region-bearing IRDL op must borrow a foreign terminator (omp.terminator /
llvm.unreachable) — prefer flat marker ops with a child-id-list attribute when
regions aren't worth that coupling"; "Homebrew LLVM is keg-only — verify tools at
/opt/homebrew/opt/llvm/bin, not via `which`, before concluding the toolchain is
absent".

## Task order

| Task | Concern | Depends on | Parallel-ok |
|------|---------|------------|-------------|
| 01-oq1-pin | OQ① canonical pin file + reader + test | — | with 02 |
| 02-enrich-irdl | Add the 3 flat marker ops to the IRDL dialect | — | with 01 |
| 03-emit-markers | Emit markers from `_lnpl_ops` (std output unchanged) | 02 | — |
| 04-tests | ③/④ + regression tests | 03 | — |
| 05-rfc-doc | Record OQ①/③/④ resolved, ① deferred, in the RFC | 01,02,03,04 | — |

## Out of scope (deferred limitation ①, per D1/D12)
- Any C++ ODS: `LnplOps.td`, `mlir_tablegen`, `CMakeLists.txt`, an `lnpl-opt`
  binary or pass plugin, `--lower-lnpl-to-std`, cmake.
- Rewriting `_render_std` into a real `ConversionPattern` that re-parses the
  artifact. S5's input stays the in-memory op stream (RFC OQ① follow-up ①).
- Any change to `impl/lnpl/lower.py`, the IR schema, or Mode A (`interp.py`).
