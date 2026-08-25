# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each `[x.y.z]`
entry below is retro-filled from its published GitHub Release notes
(`gh release view vX.Y.Z`) — see each entry's tag link for the full text.
This project does not yet follow Semantic Versioning strictly (0.x —
see [docs/compatibility.md](docs/compatibility.md) for what 0.x guarantees).

## [Unreleased]

### Added
- Reference deployment story (issue #87): `examples/deploy/Dockerfile` +
  `.dockerignore` (measured `docker build`/`run`/`curl` boot of
  `lnpl.wsgi:build_app()` under gunicorn), `docs/compatibility.md`, and
  `docs/RELEASING.md`.

### Note — first enterprise-hardening orchestration run (2026-08-24)
15 issues (#90–#104, PR #105) closed as one integrated branch, merged before
this entry. Source: `gh pr view 105`.
- **Fixed**: #90 http driver target validation, #91 `unknown-entity`
  diagnostic, #98 event-source-mismatch/orphaned diagnostics, #104 mode B
  sysroot resolution (env-caused failures only — see PR #105 body for the
  exact count and its derivation).
- **Added**: #93 `*`/`/` arithmetic + alternative guards (RFC-0028), #94
  `format` verb, #96 `respond` verb, #97 `create ... as` result binding
  (RFC-0030), #99 GET single/list surfaces, #100 dual clock contract
  (RFC-0029), #101 `capability http` + endpoint mapping, #102 outbox
  persistence + `lnpl outbox drain/ack`, #103 SSE subscriptions.
- **Changed**: #92 optimistic concurrency (`_version` conditional writes),
  #95 `derived` field write-direction separation.
- Full suite count and RFC count at this point: see PR #105 body directly
  (this file does not restate merge-time snapshots that go stale — those
  numbers belong to the PR record, not to a changelog entry with no tag).

## [0.5.0] — 2026-08-17
"The safe-defaults release." Closed issues #60–#63, #66, #67.
Source: `gh release view v0.5.0`.

### Added
- `examples/linkhub.lnpl` as the reference example the authoring skill
  points to: real pipeline usage, 3 spec blocks (normal/error/boundary),
  every spec asserting `effects complete`, zero warnings (#66, PR #73).
- Source `line` field on IR nodes and on 3 enforcement diagnostics
  (`declared-not-enforced` etc.), surfaced in both CLI and MCP (#67, PR #69,
  RFC-0024).
- `spec` reference doc's expect-format table (`rows <Entity> <N>`,
  `effects complete`, `emitted`), generated from the docstring source of
  truth; undocumented new keys are rejected fail-closed (#61, PR #72).

### Changed
- No-op verb defense promoted to the default path: lnpl-verify step 1 is now
  `lnpl compile --strict=warning`, so an unknown verb leaking into a
  workflow halts with rc≠0 instead of compiling silently (#62, PR #68).
- Build backend switched to hatchling; `mlir/` and `kb/` are bundled into
  the wheel under `lnpl/assets` so a `pip install`-only environment resolves
  them (packaged assets → repo anchor → recovery-hint error chain), with
  zero source-tree moves (#60, PR #70).
- Clause-keyword typo diagnostic now lists the valid clauses it could mean
  (#63, PR #71).

### Numbers (source: `gh release view v0.5.0`)
- Test suite: 1969 → 2016 (all passing).
- RFC count: 24 → 25 (24 Accepted).

## [0.4.0] — 2026-08-12
"The usability release." Source: `gh release view v0.4.0`.

### Added
- `guard-orphaned-steps` compile-time diagnostic (RFC-0023, warning
  severity): flags an unguarded later step that reads/writes an entity a
  preceding `when` guard protects.
- `lnpl-mcp` plugin — the compiler exposed as MCP tools (`lnpl_compile`,
  `lnpl_kb_route`) instead of only a shell command; execution surfaces
  (run/spec/diff/serve/build) deliberately not exposed.
- `lnpl-reviewer` subagent, capability-restricted (no Write/Edit) so review
  independence is enforced by tool access, not convention.
- `SessionStart` hook that resolves the compiler at session start and stays
  silent when everything is ready.

### Fixed
- Diagnostics hook's compiler lookup: `command -v lnpl` alone missed the
  repo-local `.venv/bin/lnpl`, silently disabling the hook after one notice.
  Replaced with a fallback chain (`$LNPL_BIN` → nearest `.venv/bin/lnpl`
  walking up from the edited file → `$CLAUDE_PROJECT_DIR/.venv/bin/lnpl` →
  `PATH` → `python3 -m lnpl`).
- README's flagship example used 3 out-of-lexicon verbs (silent no-ops);
  rewritten inside the vocabulary. `examples/login.lnpl` intentionally keeps
  them as the issue #36 regression fixture.
- README test/RFC counts were two releases stale; now pinned by
  `test_readme_currency.py`.

### Numbers (source: `gh release view v0.4.0`)
- Test suite: 1893 (v0.3.0) → 1969, plus a 77-case mutation harness.
- `gen_plugin_references.py --check`, `rfc_lint.py`, `dev_doctor.sh`: all
  rc 0 at release time.

## [0.3.0] — 2026-08-07
"The production-readiness release." Source: `gh release view v0.3.0`.

### Added
- Guard comparisons against entity fields, binary arithmetic, `==`/`!=`,
  `and`-composition, `input.<field>` payload guards (RFC-0015, RFC-0016).
- `set <ref> to <value>` assignment with observable effects.
- DateTime comparison/arithmetic via an epoch-ms codec; `Duration` units
  `ms`/`s`/`m`/`h`/`d`; time-window policies.
- `event <Name> on schedule daily at HH:MM UTC` — declared but explicitly
  UNENFORCED at this tag (executor tracked as issue #26).

### Changed
- Masking enforced on every output channel; the differential check scans
  the leak channel.
- Guard skips are now observable (`skipped[]` records,
  `guard-skipped-steps` diagnostic, `--strict` rc=2).
- Refinement facets enforced at runtime in both modes.

### Numbers (source: `gh release view v0.3.0`)
- Test suite: 1204 → 1513.
- Production-readiness frictions: 46 → 33 resolved / 7 partial / 6
  remaining; verdict No-Go → conditional Go (batch/aggregation still
  blocking). Reports: `qa/REPORT.md`, `qa/rerun/REPORT.md`.
- Known issues carried forward: #51 (until entry-true mode B divergence),
  #25, #26.

## [0.2.0] — 2026-08-03
"The lnpl MLIR dialect, and all nine agent roles." Source:
`gh release view v0.2.0`.

### Added
- RFC-0004 stage S4 — the custom `lnpl` MLIR dialect (#6), defined
  declaratively in `mlir/lnpl.irdl.mlir` and loaded into stock `mlir-opt`
  via `--irdl-file` — no C++ TableGen build needed (v0.1.0 had assumed it
  would).
- The ninth and final agent role, `RefactoringAgent` (#14), plus RFC-0010
  (attachment/move semantics for `ir.propose`) that made it possible.

### Fixed
- `until` now obeys its condition in mode B instead of always unrolling to
  the round cap (#5) — modes A and B agree at 0, 9, 10, 100 iterations.
- RFC-0008 G8's condition-field list had 3 independent derivations; reduced
  to one source (#4).
- The deliberate-mismatch differential suite: 3 of 5 cases were passing
  against a standing divergence unrelated to their own patch; all 5 now
  assert an equivalent baseline first (#10).

### Numbers (source: `gh release view v0.2.0`)
- Test suite: 264 → 386. 5 merged PRs, 50 files, +7573/−250.

### Known limitations at this tag
Mode B did not enforce the RFC-0003 cache-TTL contract (#9); S5's lowering
consumed an in-memory op stream rather than the re-parsed `lnpl` module
(#7); RFC-0004 invariants V1/V5 were only partially enforced (#15); modes A
and B read a Presence guard's condition from different inputs (#12).

## [0.1.0] — 2026-07-31
"Parser, semantic IR, and native compilation." First tagged release.
Source: `gh release view v0.1.0`.

### Added
- `.lnpl` parses and lowers to the semantic IR described in RFC-0001.
- Mode A (IR interpreter) executes the golden scenario end to end.
- Mode B (native compilation): the same IR compiles through MLIR to a
  native binary.
- Differential verification across execution order, policy outcome,
  observability signals, and masking — reports EQUIVALENT on the golden
  scenario.
- `when` guard conditions evaluated at runtime in both modes (RFC-0008 G8).
- OpenAPI generated from the IR rather than hand-maintained.
- Eight RFCs, all `Accepted` (0000–0008 excluding gaps).

### Numbers (source: `gh release view v0.1.0`)
- 264 tests passing.

### Known limitations at this tag
`until` was statically unrolled to a 16-round cap in mode B regardless of
when its condition became true (fixed in #5, after this tag). RFC-0008 G8's
condition-field plumbing was only correct for exactly two condition fields
(fixed in #4, after this tag).

[Unreleased]: https://github.com/choiyounggi/linkly/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.5.0
[0.4.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.4.0
[0.3.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.3.0
[0.2.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.2.0
[0.1.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.1.0
