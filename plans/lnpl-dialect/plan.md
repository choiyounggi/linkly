# lnpl MLIR dialect (RFC-0004 S4) — issue #1

Goal: give the mode B pipeline a real, **registered and verified** custom `lnpl`
MLIR dialect stage between the Semantic IR and the standard dialects, carrying
RFC-0004's node-id traceability. Today `emit_mlir` jumps straight from IR to
`func`/`arith`/`scf`, which is the deviation recorded in `rfcs/0004-compiler.md`
§Open Questions and `impl/lnpl/backend.py`'s module docstring.

Acceptance criteria:

1. `mlir/lnpl.irdl.mlir` defines the `lnpl` dialect; stock `mlir-opt` registers it
   via `--irdl-file` and **rejects** ops that are undefined, missing
   `lnpl.node_id`, or carry a non-string `lnpl.node_id`.
2. `emit_lnpl_mlir(document, workflow_id)` produces an `lnpl` dialect module that
   passes that verifier, with every op carrying `lnpl.node_id` **and** a
   `loc("<node id>")` that survives a `mlir-opt` round trip.
3. `emit_mlir`'s standard-dialect output is **byte-identical to the pre-change
   output below the leading comment block**, proven against committed
   pre-change fixtures that are never regenerated.
4. `build()` writes `module.lnpl.mlir` and **verifies that file in place**; a
   module that fails the dialect verifier fails the build with no binary produced.
5. 287 existing tests still pass (regression 0). The two load-bearing
   deliberate-mismatch tests still observe divergence, and a new direct test
   pins the `_steps_in_order` routing they were being asked to guard.
6. The `lnpl` module and the standard-dialect module are proven to describe the
   **same** workflow, not merely to each verify.
7. New tests cover normal + error + boundary per behavior, each with assertions.

Stack: Python 3.14.6 (`.venv/bin/python`, deps `jsonschema` only — no new Python
deps), Homebrew LLVM/MLIR 22.1.8 at `/opt/homebrew/opt/llvm/bin` (keg-only).
Tests: `PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl`
(README:245). `mkdir -p .claude/tmp` first — `test_backend.py` mkdtemps there.

**No new build dependency.** This is the substantive change from how issue #1 and
the RFC framed the work.

> **This plan was adversarially audited** before implementation (independent
> Opus subagent, 2026-08-01). It found no fatal defect but five serious ones,
> all folded in below as D9/D10/D12/D17/D18/D19 and task 07. Three of its
> findings were independently re-measured before being accepted (see D12, D9,
> D10). Its one finding about **pre-existing** repo state — that three of the
> five `TestDivergenceIsDetected` cases pass vacuously — is recorded in
> §Pre-existing defect found and is deliberately **not** fixed here.

## Decisions

| # | Decision | Choice | Wiki basis |
|---|----------|--------|------------|
| D1 | How to register a custom dialect with `mlir-opt` | **IRDL** — declarative dialect in `mlir/lnpl.irdl.mlir`, loaded by stock `mlir-opt --irdl-file`. Not a C++ ODS/TableGen/cmake build | `[no-wiki]` — 영기's decision after this session measured both paths viable (`MLIRConfig.cmake` present **and** `--irdl-file` present). Rejected C++ ODS: adds cmake + a C++ toolchain as hard build deps and couples to the LLVM 22 C++ ABI, which collides with RFC-0004 Open Q1 (version pinning still unresolved). Ingest candidate: "declarative MLIR dialects via IRDL avoid an out-of-tree C++ build" |
| D2 | The old blocker ("brew provides tools only, no dev libraries") | **Disproven** — headers, 391 `libMLIR*`, `mlir-tblgen`, `MLIRConfig.cmake`, `AddMLIR.cmake`, cmake all present. Also **moot**: with D1 none of them are needed | `[no-wiki]` — measured, previous session + this one |
| D3 | Locating `mlir-opt` | Reuse the existing `backend.tool()` — keg-only absolute path first, `shutil.which` fallback, raise `BackendError` otherwise. Never a bare-name call | platforms-environment-path-resolution ("automation pins binaries; scripts must not depend on the caller's PATH for correctness-critical tools") |
| D4 | Locating `mlir/lnpl.irdl.mlir` | Absolute path derived from `backend.__file__` (`<repo>/mlir/lnpl.irdl.mlir`), exposed as `LNPL_IRDL_PATH`. Never relative to cwd — tests run from the repo root but `build()` runs with an arbitrary `workdir` | platforms-environment-path-resolution (same rule, applied to data files) |
| D5 | `emit_mlir`'s public contract | **Unchanged.** It keeps returning standard-dialect text. It becomes a composition: `_lnpl_ops` → `_render_std`. All six existing emission tests keep passing untouched | testing-quality-behavior-not-implementation (a behavior-preserving refactor must not require editing the tests) |
| D6 | What the two renderings share | A structured **op stream** (`_lnpl_ops`), rendered two ways: `emit_lnpl_mlir` → lnpl dialect text, `_render_std` → standard dialect text. The lowering consumes the op stream, **not** re-parsed MLIR text — no Python MLIR parser is written | `[no-wiki]` — engineering call. Honest limitation, stated in the PR Decision Log: S5's input is the in-memory serialization source rather than the reparsed artifact. D8 + D18 keep the artifact load-bearing |
| D7 | `lnpl` op set (resolves RFC-0004 Open Q2) | Two ops, zero operands, zero results, flat in the module body (no regions — `builtin.module` carries `NoTerminator`, verified): `lnpl.step` and `lnpl.effect`. Guards ride as **attributes** on `lnpl.step`, because `_steps_in_order` has already flattened and unrolled them before S4 sees them | RFC-0004 §Reference-level (S4 must materialize compile decisions as op attributes) |
| D8 | Is the lnpl module load-bearing or decorative? | **Load-bearing.** `build()` writes `module.lnpl.mlir` and verifies it; failure raises `BackendError` and no binary is produced. The verifier is a *structural* gate only — D18 adds the content gate | RFC-0004 S4 ("실체화되지 않은 결정은 유실이며 변환 실패로 취급한다") |
| D9 | Traceability representation | **Both** RFC paths on every op: discardable attribute `lnpl.node_id = "<id>"` and `loc("<id>")` (NameLoc). **The verifier argv must include `--mlir-print-debuginfo`** — measured, without it `mlir-opt` prints 0 `loc(` and the Location path silently vanishes (audit S5, re-measured: 0 vs 4). That would invert the RFC's own rationale, which treats Location as the durable path and the attribute as discardable | RFC-0004 §dialect 변환 이후의 역추적 (attribute name is RFC-owned; this resolves the Location notation left open in Open Q2) |
| D10 | Enforcing traceability | `irdl.attributes {"lnpl.node_id" = %id}` where `%id = irdl.base "#builtin.string"`. The verifier then rejects both a **missing** node id (`op attribute "lnpl.node_id" is expected but not provided`) and a **non-string** one (`expected base attribute 'builtin.string' but got 'builtin.integer'`) — both re-measured. Plain `irdl.any` was the first draft and is rejected: it let `lnpl.node_id = 42` verify, making D10 presence-only. Note only the quoted `#`-form parses; `"!builtin.string"` and bare `#builtin.string` do not | testing-quality-tests-that-cannot-fail (prefer a check that can actually fail) |
| D11 | Unrolled guards and node ids | Every unrolled round of **both** `until` and `repeat` carries the **same** `lnpl.node_id` (the step's), distinguished by `lnpl.unroll_round = N`, 1-based per node id. This is RFC-0004's 1:다 확장 rule. `repeat` was missing from the first draft (audit MINOR) — it unrolls identically and needs the same marker | RFC-0004 §역추적 보존 규칙 3 |
| D12 | Keeping the divergence detector alive | `_lnpl_ops` **must** obtain its steps from `_workflow_steps()`, which calls the module-global `_steps_in_order`. **Correction to the first draft:** that draft claimed bypassing the seam "would disarm all five" `TestDivergenceIsDetected` cases. Measured, that is false — only two of the five are load-bearing (§Pre-existing defect found). So the routing gets its **own direct test** (task 03) rather than being delegated to a suite that would not reliably catch it | testing-quality-tests-that-cannot-fail |
| D13 | Condition-field list | `emit_lnpl_mlir` calls `condition_field_names()` — it does **not** re-derive the list. PR #4 existed precisely because three sites derived it independently | `[no-wiki]` — repo history (`0223a60`), enforced by `test_g8_condition_params.py` |
| D14 | Compile context (RFC's `노드 id → 결정` side table) | The reference implementation **has none** (measured: no such structure in `impl/lnpl/`; independently confirmed by the audit). So "materialize the whole context" is vacuous today. Materialize the compile decisions that *do* exist at emission — guard mode, guard condition, unroll round, condition-field list — and do not invent a side table. Recorded as scoped-out, not as done | `[no-wiki]` — measured |
| D15 | Test level for the new stage | Unit tests on text generation (no toolchain needed) + toolchain-gated tests for verification and build, using the existing `NEEDS_TOOLS` skip decorator. No new e2e layer | testing-strategy-test-level-choice; existing `test_backend.py` convention |
| D16 | New-test case set | Per behavior: one normal, one error, one boundary — plus negative controls that prove the dialect verifier can reject (undefined op, missing node_id, non-string node_id, no `--irdl-file`) | testing-quality-minimum-case-set; testing-quality-tests-that-cannot-fail |
| D17 | Golden fixtures for the refactor | `impl/tests/golden/wf_login.std.mlir` (2428 B) and `w_until.std.mlir` (7785 B), captured from the **pre-change** `emit_mlir` and **never regenerated**. Comparison strips the leading `//` comment block from both sides, so task 05 can fix the now-false header comment without destroying the proof. The first draft had task 05 regenerate them, which would have made the equivalence claim circular and left AC3 false at merge (audit S3) | testing-quality-behavior-not-implementation |
| D18 | Proving the two renderings agree | A **cross-renderer correspondence test** (task 03): step-op count, effect-op count, and the ordered `lnpl.node_id` list from `emit_lnpl_mlir` must match the `@lnpl_step`/`@lnpl_effect` call sites and op stream of `_render_std`. Without it, a drop/reorder/duplicate bug in `emit_lnpl_mlir` alone would leave the lnpl module describing a different workflow while `build()` and the differential both pass — the differential observes only the binary (audit S2, verified: the verifier accepts a 1-step module where 6 belong, and an empty one) | testing-quality-tests-that-cannot-fail |
| D19 | What gets verified | `verify_lnpl_module(text, stage=..., path=None)`. With `path`, it verifies **that file in place**; `build()` passes `lnpl_path`. The first draft verified a second copy in `.claude/tmp`, so the on-disk artifact was never the verified object and `BackendError` named a temp path instead of the file the user is told to inspect (audit S4) | platforms-environment-path-resolution |

### Deliberately out of scope

- A C++ ODS dialect and a real MLIR `ConversionPattern` for S5 — 영기 chose to
  split this into a follow-up issue. This PR closes issue #1; the follow-up
  covers "make the lowering an MLIR pass that re-parses the artifact".
- An S3 compile-context side table (D14).
- MLIR version pinning (RFC-0004 Open Q1) — untouched, and D1 keeps it non-urgent.
- Regions / `async` / `memref` / `vector` ops. The pipeline runs only
  `scf`→`cf`→`llvm` plus `func`/`arith` (measured).
- **Handoff §8 criterion 1** ("hello-dialect ODS + cmake build succeeds first") —
  **dropped**, not missed. D1 needs neither TableGen nor cmake, and D2 makes the
  premise moot. The equivalent risk gate was the IRDL spike run before planning.
- **Handoff §8's "build dependencies grew, reflect them in README/ROADMAP"** —
  **void** under D1: no dependency grew. Task 06 records it as void rather than
  quietly adding nothing.
- Fixing the three vacuous divergence tests (next section).

### Pre-existing defect found (not fixed here)

The audit measured, and this session independently re-measured, that the
`GUARDED` fixture in `test_backend.py` is **already** divergent with no
monkeypatch at all:

```
NO-PATCH ok = False
   FAIL 2/4 policy outcome — A=failed B=completed
   differential: DIVERGENT
```

`GUARDED` contains a `when` guard and no `until`, so two of the five
`TestDivergenceIsDetected` patches (`without_until`, `with_wrong_cap`) provably
do not change `emit_mlir`'s output at all, and a third (`without_when`) changes
it but has its assertion satisfied by the baseline. **Three of the five cases
therefore pass vacuously** — they assert `assertFalse(ok)` against a divergence
their patch never caused. Only `test_reordered_backend...` (pins `FAIL 1/4`) and
`test_dropped_effect...` (pins `FAIL 3/4`) are load-bearing, which matches
`rfcs/0004-compiler.md:437`'s own claim of "고의 불일치 케이스 **2건**".

This predates this work (introduced with PR #5) and fixing it means changing
either the `GUARDED` fixture or mode A's policy outcome — both out of scope for
S4. It gets a follow-up issue, and D12 stops depending on the weak cases.

## Task order

| Task | Depends on | Parallel-ok |
|------|-----------|-------------|
| 01 dialect definition + Python-side verifier | — | |
| 02 `emit_lnpl_mlir` (S4 artifact) | 01 | |
| 03 `_render_std`, recompose `emit_mlir`, correspondence + routing tests | 02 | |
| 04 `build()` writes and verifies the lnpl module in place | 03 | |
| 05 normative docs — RFC-0004 + backend docstring | 04 | parallel-ok with 06 |
| 06 status docs — ROADMAP + READMEs | 04 | parallel-ok with 05 |
| 07 PR with Decision Log, self-merge, close #1, open follow-ups | 05, 06 | |
