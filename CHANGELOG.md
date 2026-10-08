# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each `[x.y.z]`
entry below is retro-filled from its published GitHub Release notes
(`gh release view vX.Y.Z`) — see each entry's tag link for the full text.
This project does not yet follow Semantic Versioning strictly (0.x —
see [docs/compatibility.md](docs/compatibility.md) for what 0.x guarantees).

## [Unreleased]

### Fixed
- `capability http`'s `retry`/`breaker`/`path` clauses were parsed and
  compiled but silently dropped before reaching `HttpNetworkDriver` — both
  `lnpl run`/`lnpl serve` (`cli.py:_open_endpoints`) and
  `build_app()`/`make_wsgi_app` (`wsgi.py:_resolve_network`) projected a
  declared capability down to `{"method", "auth"}` before handing it to
  the driver. A declared `retry` never retried; a declared `path` made
  any `call ... with <ref>` fail with `"has path arguments but no path
  declared"` (issue #176).
- OpenAPI generation crashed (`KeyError`) on any workflow using `create
  <Entity> as <alias>` together with `respond <alias>...` —
  `_response_schema`'s `by_binding` map only ever held entities' own
  default binding names, never an `as`-declared alias, so the RFC-0030
  golden example itself could not compile to an OpenAPI document, and
  `lnpl serve` (which calls the same generator at startup) could not bind
  either. `_response_schema` now also resolves a `respond` reference
  against the workflow's own `create ... as` result bindings, and raises a
  clear `OpenApiError` instead of a bare `KeyError` for any reference
  resolving to neither (issue #173).
- `lnpl migrate`가 다개체(multi-entity) 모듈에서 `create`가 쓴 행을 조용히
  건너뛰고 rc 0으로 "완료"를 보고하던 문제를 고쳤다 — `id` 필드를 선언하지
  않은 entity의 행은 `create`가 자기 자신의 저장 키를 `id` 값으로 쓰는데,
  migrate가 그 값으로 저장 키를 다시 계산하면 이중으로 접두되어 재조회가
  실패했다. 이제 그 경우를 행 자신의 `id`로 재조회해 복구하고, 그래도
  확인할 수 없는 행이나 후보가 있었는데 하나도 못 쓴 실행은 rc 2로
  시끄럽게 실패한다 (issue #179).
- In-workflow write-state self-conflicts (issue #174): the default seed
  rule now excludes an entity whose first repository operation is
  `create` (previously seeded if it was ever read anywhere in the
  workflow, even after being created first); `persist()` now advances the
  bound row's optimistic-lock version after a successful write, so a
  second `set` on the same binding in one run no longer raises a phantom
  write conflict.
- `respond` naming a binding that a guard skipped, or a field the bound row
  does not carry, crashed with a raw `KeyError` (CLI rc 1; `lnpl serve`
  answered 500 with no `failed_step`). Such a reference is now omitted from
  the response; an absent field raises one `respond-field-missing` warning
  per reference, and when every reference is omitted the response is `{}`.
  A new compile warning `guard-scoped-binding-escape` flags a `respond` or
  `send` reference to a binding that only exists inside a guard. Existing
  programs that crashed now answer; none that succeeded change (issue #198).
- `If-Match` ignored a `by <ref>` lookup key: the precondition was checked
  against the payload `id`, so a stale ETag on a row read by another key got
  200 instead of 412. It now evaluates the row the workflow's first read
  addresses; a `by` ref that cannot be resolved from the request answers 400
  `precondition-unsupported` without running the workflow, and an absent
  addressed row answers 412. Workflows without `by` behave as before
  (issue #199).
- The default `Money` sample was `{"amount": "0", ...}`, which fails the
  type's own codec (USD has two decimals), so the default `spec`/`run`
  payload failed unconditionally. The sample is now
  `{"amount": "1.00", "currency": "USD"}`; any golden or fixture that
  pinned the old sample must be regenerated (issue #203).
- A `derived` field assigned with `set`/`format` earlier in the same guard
  scope was still rejected by `emit ... with <binding>.<field>`, with an
  error text that contradicted RFC-0049. It is now accepted when the
  assignment precedes the `emit` in the same scope, and otherwise rejected
  naming the missing assignment and the `emit` line; RFC-0049 was corrected
  in place (issue #204).
- Optimistic-lock write conflicts left the server as `500 workflow-failed`,
  indistinguishable from a server fault. They now fail with
  `failure_kind` `write-conflict` and answer `409 write-conflict`
  (problem+json, with `failed_step`); the event-consume path answers 503
  with `Retry-After` and releases the claim. Clients that retried on 500
  should retry on 409 (issue #201).
- A service whose `security` block declared `role <r>` without `jwt`
  compiled, and `lnpl serve` then answered 200 to a request with no
  Authorization header, because route authentication keys on `jwt` alone
  and the role check was never reached. Such a service is now rejected at
  compile time with a `LowerError` whose message leads with
  `role-requires-jwt`: `lnpl compile` exits 2, `build_app()` refuses to
  start, and the MCP compile response is `isError`. `jwt` together with
  `role` still answers 401/403 as before. Compatibility: a document that
  declared `role` without `jwt` compiled before and no longer compiles;
  add `jwt` to that service's `security` block (issue #213).

### Added
- `scripts/load_probe.py` (stdlib open-loop load generator) and
  `docs/postgres-load-ceiling.md` (measured sustained-load ceiling and
  root cause for the postgres backend) — issue #180.
- `emit`/`publish <Event> with <ref>...` maps the emitted event's payload
  from workflow bindings (created-row fields, `input.*`, network-call
  results) instead of always carrying the raw masked input; trailing
  words after `emit <Event>` that are not a `with`-clause now raise a
  compile error instead of being silently dropped (issue #178, RFC-0049).
- Guard predicates `<ref> is-numeric` / `<ref> is-not-numeric` ask whether
  a value reads as a number without failing, so a non-numeric external
  response can route to a fallback branch instead of the comparison
  `RunError`; unlike `exists`/`missing` they may be `and` terms, and
  `lnpl vocab` now lists both predicate tables (issue #177, RFC-0050).
- Money fields can be copied, added, subtracted, and multiplied by an
  Integer in `set`, and compared Money-to-Money in guards under all six
  comparators, evaluated exactly in minor units (previously a compile
  refusal); Decimal, Money division and Money × Money stay refused, a
  currency mismatch fails with `money-currency-mismatch`, `expect result`
  now evaluates Money order comparisons, and mode B refuses a Money guard
  as a recorded differential exemption instead of a false EQUIVALENT
  (issue #172, RFC-0051).
- `find`/`read`/`load`/`authenticate`/`update`/`delete <Entity> by <ref>`
  addresses the row under the ref's value instead of the payload `id`, so
  one workflow can create an order under its own id while finding and
  decrementing stock under the product id (probe-v0.8 s1 F-3/F-6); a `set`
  on a row read that way persists under the same key, a ref with no value
  fails the step, a first read `by input.<field>` is seeded under that
  field's value, and mode B refuses such a workflow as a recorded
  differential exemption. Other trailing words on those verbs are now a
  compile error instead of being silently dropped; `create` keeps
  `as <name>` only (issue #175, RFC-0052).
- `call`/`request <Target> [with <path refs>] send <ref>... [as <name>]`
  chooses the outbound body from workflow bindings (same mapping rules as
  `emit ... with`, RFC-0049) instead of always sending the whole input; a
  call without `send` is byte-identical to before. Mode B is unchanged
  (issue #200, RFC-0057).
- `lnpl token --role <r>` mints a token carrying the claim the runtime reads
  as the caller's role, so a `security jwt` service with a `role` rule can be
  tested with the built-in tool. It warns on stderr only when the route
  enforces the role (issue #202).
- `lnpl capabilities` and the MCP `lnpl_capabilities`/compile responses
  report `vocabulary_digest` and the loaded package path; the MCP launcher
  prints one discovery line on stderr, `lnpl-doctor` flags a CLI/MCP digest
  mismatch, and the generated reference header carries the digest, so two
  builds between tags can be told apart. `--version` is unchanged
  (issue #205).
- `fail <kebab-code>` ends a workflow as a business rejection: status
  `failed`, `failure_kind` `rejected`, the code in `failure_reason`, writes
  rolled back (RFC-0032), `422` problem+json with the author's code on
  `lnpl serve` and on the consume path, and the declared codes listed in
  OpenAPI. Codes the server already uses are reserved; `fail` is not retried
  by a retry policy; mode B refuses it (issue #206, RFC-0056).
- Guards compare Text-family fields and bare enum members with `==`/`!=`,
  checked at compile time against the enum's members (a did-you-mean hint
  only for close matches), so a state transition can be a guard. `spec`
  evaluates the comparison; mode B refuses it as a recorded differential
  exemption (issue #207, RFC-0054).
- The `optional` field modifier: a client may omit an optional field or send
  `null`, and both mean absent. Absent values are left out of stored rows,
  `emit ... with` and `respond`; OpenAPI request schemas drop them from
  `required`; `db check`/`db migrate` follow; absent rows sort last in both
  directions on `fake` and `sqlite`; aggregates skip them. A presence guard
  works on optional fields of any type including Money; an optional `id` is
  a compile error; arithmetic on an optional field protected only by a
  presence guard raises the `optional-field-unguarded-arithmetic` warning;
  mode B refuses guards that read an optional field (issue #208, RFC-0053).
- `respond` can answer an aggregate or a filtered list without storing rows:
  named terms `<name> as <agg> <ref>` and a bounded list term (`limit`
  required, `items`/`next` envelope), with zero repository writes, masked
  rowsets, an OpenAPI 200 schema derived from the terms, and `spec` results
  for named aggregates. Mode B refuses it (issue #210, RFC-0059).
- A new warning `spec-result-reads-input`: a spec's bare
  `expect result <name>` reads the run input, which `spec` fills with a
  sample value when no `given` sets it (RFC-0012), so a name shared with a
  `respond <binding>.<name>` field, with no same-name `respond` term and
  no `given` for that input, was silently compared against the sample. It
  fails under `--strict=warning`; write `result <binding>.<name>` to
  assert on the response, or set the input with `given <field> <value>`.
  The generated OpenAPI workflow `"400"` description now also names
  `id-required` (issue #209); the six `examples/*.openapi.json` goldens
  are regenerated (issue #216).

### Changed
- Persistent backends (sqlite, postgres) are no longer seeded from the
  request payload, so a read of a missing row no longer stores a phantom
  row. The step now fails with `failure_kind` `not-found` and `lnpl serve`
  answers `404 not-found` with `failed_step` (consume path: 422
  `event-rejected`; OpenAPI workflow operations gain a 404). The `fake`
  backend and the `spec`/`diff` runners keep seeding. Compatibility:
  a program that relied on a read miss succeeding on a persistent backend
  now gets 404 and must create the row first (issue #197, RFC-0052 §4
  corrected in place).
- `derived generated` (a per-run UUIDv4 id) and `derived clock` (the run's
  start instant) mark entity fields the server fills at `create`/`insert`;
  `spec` pins them with `given run.id` / `given run.clock`. A `create` or
  `insert` without a non-null `id` now fails with `id-required` (400; 422 on
  the consume path) unless the id is `derived generated`; UUID fields no
  longer store row-key strings; a bare-name `set` operand that no entity
  declares is rejected. Compatibility: an id-less create used to run and
  collide on one key from the second run; it now fails on the first, so add
  `derived generated` to the id or send an id. Mode B refuses the markers
  (issue #209, RFC-0055).
- Two structural changes to flow control, with one parse-time and one
  runtime consequence. (a) A control keyword (`when`, `until`, `repeat`,
  `pipeline`, `parallel`) indented inside an open `pipeline` body is now a
  parse error naming the block and both fixes, instead of silently closing
  the pipeline and compiling to a different structure (RFC-0058).
  Compatibility: a program that compiled this way must dedent the keyword
  or re-indent the body, and the old compile ran it as the dedented
  structure (steps after the keyword fell outside the enclosing guard).
  (b) In mode A a guard may read a field the workflow itself assigned
  earlier (its value at that point), and an `otherwise` sibling line owns
  one item after a `when` guard; `otherwise` after
  `until`/`repeat`, with no guard, twice, or inside `parallel` is a parse
  error, and `else` gets a did-you-mean. Mode B refuses both
  (issue #211, RFC-0060, resolves RFC-0015 OQ1). Compatibility: a guard
  reading an assigned field used to be a compile error and is now accepted
  in mode A, so a program that dodged the error by reordering still works;
  a mode-B build of a workflow that uses either form is now refused.
- Compatibility (issue #214, RFC-0063): a `call`/`request` with no `send`
  clause no longer sends Password-family input fields. A field is
  Password-family when any entity in the document declares that name with
  type `Password` or a `refine ... of Password`; its key is left out of
  the outbound body (not replaced by `***`). There is no opt-in to send
  such a value: `send` still rejects Password-family references at compile
  time (RFC-0057). A workflow whose input carries no Password-family field
  sends a byte-identical body. Mode B is unchanged (it builds no call
  body). This replaces the earlier note that a call without `send` is
  byte-identical to before (issue #200, RFC-0057).

## [0.8.0] — 2026-09-02
"The Money-contract release." The RFC-0044/0045 designs accepted in 0.7.0
now reach the last two places they had not: `spec` blocks can seed and
assert Money values, and an empty RowSet's Money `sum` finally returns the
shape RFC-0045 §5 always specified.

### Added
- `MoneyLiteral` in `spec` `given`/`expect` (RFC-0044 §3, issue #160):
  a single token like `100.50USD` seeds a Money field's wire dict from
  `stored`/`stored-indexed`/input-field lines and asserts one via
  `expect result <ref> == <literal>` (`==`/`!=` only — Money order stays
  aggregation-only). Decimal places must equal the currency's ISO 4217
  exponent exactly; a mismatch is a manifest-stage compile reject, never a
  rounding. Guard grammar is untouched: `MoneyLiteral` appears in no
  `Operand` position.
- RFC-0047 (Updates: RFC-0045): `nodeAssignment` gains the optional
  `agg_field_type` key (`Integer`/`DateTime`/`Money`) so the aggregated
  field's statically-known base type reaches the interpreter (issue #158).
  The IR-schema self-test gains a matching enum negative.

### Fixed
- An empty RowSet's Money `sum` returned plain integer `0` instead of
  RFC-0045 §5's `{"amount": "0", "currency": null}` — with zero rows the
  interpreter had no shape to dispatch on. `lower.py` now carries the
  field's declared base type on the `Assignment` node; IR compiled before
  RFC-0047 keeps the old result until recompiled, a deliberate
  backward-compatibility floor (issue #158).
- `agents.py`'s `_step_node_for` returned the first `WorkflowStep` whose
  text matched, silently confusing two workflows that share a step's
  wording. It now collects every candidate and refuses an ambiguous match
  with `RpcError("ambiguous_step")` naming the owning workflows —
  resolve.py's "does not guess, refuses" rule applied to the one consumer
  issue #151 could not cover (issue #159).

## [0.7.0] — 2026-08-31
"The production-readiness release." The 0.6.0 extensibility work is now
backed by a release pipeline, measured token claims, and a serving surface
hardened for real traffic.

### Added
- CI/CD: GitHub Actions PR gate across Python 3.11–3.13 and a tag-driven
  release workflow, plus `scripts/check_version_sync.py` so the package
  version and the plugin manifests cannot drift apart (issue #141).
  Publishing to PyPI is deliberately out of scope for this release.
- `benchmarks/token/`: measured token/edit-cost comparison against an
  equivalent FastAPI implementation (`equiv/`, `edits/`, `measure_tokens.py`)
  and a `pass@k` harness (`passk/harness.py`), with the protocol and results
  written up in `PROTOCOL.md`/`REPORT.md` (issue #142). The harness is
  committed; running it against a live model API is left to the operator.
- RFC-0044 (Money arithmetic on integer minor units) and RFC-0045
  (`avg`/`min`/`max` row-set aggregation) accepted (issue #145).
  Implementation follows separately — these entries record the accepted
  designs only.
- Directory namespaces and `internal/` visibility per RFC-0033: a source
  tree's directory layout now names entities (`billing/order.lnpl` ->
  `billing.Order`), and `internal/` marks a namespace as private to its own
  subtree (issue #146). Single-file compilation is byte-identical, pinned by
  fixtures under `impl/tests/lnpl_fixtures/rfc0033_byte_identical/`.
- `lnpl migrate` with an expand-contract migration model, a `_schema_gen`
  stamp carried on the payload so a running server can tell which schema
  generation it is serving, and a WAL backup guide (`docs/migration.md`,
  issue #147).
- Serving hardening for production traffic: request rate limiting, graceful
  drain on `SIGTERM`, network-driver keep-alive connection pooling, and a
  reference nginx TLS front-end (`examples/deploy/nginx.conf`) — issue #148.

### Fixed
- OpenAPI generation silently omitted `requestBody` for any entity whose id
  is not exactly two dotted segments. `_operation` rebuilt the id with a
  fixed `target.split(".")[:2]` slice, which names no real entity for a
  multi-word entity (`OrderItem` -> `entity.order.item`) or an RFC-0033
  namespaced one (`entity.billing.order`); the lookup missed and the request
  schema was dropped with no error. Resolution now follows the `rule` field
  the lowering pass already records rather than parsing the target string
  (issue #146).

## [0.6.0] — 2026-08-30
"The extensibility release." Every seam the platform owns is now an open,
TCK-guarded SPI surface, and the first external driver package exists to
prove the boundary works.

### Added
- Reference deployment story (issue #87): `examples/deploy/Dockerfile` +
  `.dockerignore` (measured `docker build`/`run`/`curl` boot of
  `lnpl.wsgi:build_app()` under gunicorn), `docs/compatibility.md`, and
  `docs/RELEASING.md`.
- SPI surfaces: repository drivers via `lnpl.drivers` entry-points + a
  published TCK (#75), caches/networks (#131, #132), token providers for
  external IdP trust (#119 B), generators with openapi re-entry (#139),
  extension diagnostics registration per RFC-0042 (#138, #140), and the
  RFC-0043 driver enforcement self-report SPI.
- The first external driver package proving that boundary:
  [lnpl-postgres](https://github.com/choiyounggi/lnpl-postgres) — TCK
  hardening in-repo (#115), the external repo with its own Testcontainers
  CI (#121).
- Language: multi-file compilation unit (RFC-0031, #77), `list ... where` /
  `order by` / `limit` with driver pushdown (#116), row-set model +
  list/sum/count aggregation (#65), `note` verb + canonical log line
  widening (#111).
- Serving: `serve` restructured into a WSGI callable (#80), workflow
  execution wrapped in a transaction boundary (#79), 409 conflict +
  `Idempotency-Key` replay + `ETag`/`If-Match` (#113), k8s ops surface
  `/-/healthz|readyz|metrics` (#110), CloudEvents `consume by` ingress +
  reference relay (#118), external triggers for `event schedule` (#81),
  NetworkDriver + `call`/`request` result binding (RFC-0027, #64, #76),
  HTTP resilience — retry/backoff/jitter, circuit breaker, path templates
  (#109).
- Observability: `--log-format json` + TraceExporter SPI (#78), W3C
  traceparent propagation (#107), actual evaluation values recorded on
  guard skip (#83).
- Runtime: `parallel` block execution — fail-fast, concurrency cap,
  write-conflict refusal (#108).
- Tooling and discovery: `lnpl.toml` profile config + `lnpl config check`
  (#114), `lnpl capabilities` catalog (#134), `lnpl vocab --json` +
  `lnpl_vocabulary`/`lnpl_spec` MCP tools (#135), `lnpl compile --json`
  (#133), deterministic `.lir.json` provenance block (#136), KB pack
  layering (#137), `lnpl db check` + stored-row shape warning (#85).

### Changed
- **Breaking**: `security encrypt` removed from the closed vocabulary
  (RFC-0035 §D3, #127) — touches the closed-vocabulary contract in
  [docs/compatibility.md](docs/compatibility.md).
- `security role` is now enforced, with caller namespaces (#119 A).
- README's suite-size claim is a ±5% band instead of an exact count (#124).

### Note — orchestration runs folded into this release
- First enterprise-hardening run (2026-08-24): 15 issues (#90–#104, PR #105)
  closed as one integrated branch. Source: `gh pr view 105`.
  **Fixed**: #90 http driver target validation, #91 `unknown-entity`
  diagnostic, #98 event-source-mismatch/orphaned diagnostics, #104 mode B
  sysroot resolution. **Added**: #93 `*`/`/` arithmetic + alternative guards
  (RFC-0028), #94 `format` verb, #96 `respond` verb, #97 `create ... as`
  result binding (RFC-0030), #99 GET single/list surfaces, #100 dual clock
  contract (RFC-0029), #101 `capability http` + endpoint mapping, #102
  outbox persistence + `lnpl outbox drain/ack`, #103 SSE subscriptions.
  **Changed**: #92 optimistic concurrency, #95 `derived` write-direction
  separation.
- Extensibility-axis run (2026-08-30): #131–#139 + RFC-0043 merged at
  `60cbbaf`. Merge-time suite/RFC snapshots belong to the PR and commit
  records, not to this file.

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

[Unreleased]: https://github.com/choiyounggi/linkly/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.8.0
[0.7.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.7.0
[0.6.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.6.0
[0.5.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.5.0
[0.4.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.4.0
[0.3.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.3.0
[0.2.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.2.0
[0.1.0]: https://github.com/choiyounggi/linkly/releases/tag/v0.1.0
