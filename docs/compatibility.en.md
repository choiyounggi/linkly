# Compatibility policy (0.x)

**English** | [한국어](compatibility.md)

> This is the English edition of [`docs/compatibility.md`](compatibility.md), translated in
> full. The Korean text is normative: where the two disagree, the Korean text
> wins. Identifiers, flags, environment variable names, paths and every code
> block are identical in both editions.

linkly is still 0.x — it follows [Semantic Versioning](https://semver.org/)'s 0.x
rule that "anything may change" exactly as written. Within that, this document states
**which surface is a contract, and what change gets announced as breaking in the
`Changed` section of [CHANGELOG.md](../CHANGELOG.md)** — narrowing "it's 0.x, so
anything can change" down to a list an operator can actually use.

Every breaking change is announced the same way: recorded as `Changed` in the
release tag's [CHANGELOG.md](../CHANGELOG.md) entry, naming which contract below it
changed. See [docs/RELEASING.md](RELEASING.md) for the release procedure.

## Contract list

### 1. Diagnostic `code` / `severity`

A compile diagnostic is a record made of five keys: `code` / `severity` / `where` /
`subject` / `message` (RFC-0021 §Diagnostic record shape). `severity` is derived from
`code` (`SEVERITY_OF[code]`) — reclassifying the same `code` to a different severity
between releases is breaking.

- **Guaranteed**: an existing `code` value's meaning and severity mapping are kept.
  Adding a new diagnostic `code` is not breaking.
- **Breaking**: removing or reassigning the meaning of an existing `code`, or
  changing the severity mapping.
- Verification: `lnpl compile <file> --strict=warning` — rc≠0 at `warning` grade
  or above (issue #62, promoted to the default gate in v0.5.0).
- **Extension codes**: RFC-0042 opens a namespace axis (`<prefix>/<code>`) on
  `code`. The guarantee/breaking rule above applies only to a bare (no-slash) `code`
  — bare is permanently reserved for the core only (RFC-0042 §Reference-level
  Specification/code → grade). **The persistence, reassignment of meaning, and
  severity of `<prefix>/<code>` are guaranteed by that extension itself, not by the
  core.** All the core guarantees is the five-key envelope shape
  (`code`/`severity`/`where`/`subject`/`message`).

**Machine channel — `lnpl compile --json` (issue #133)**: instead of the
human-oriented `format_lines` output, `--json` emits exactly one combined JSON
document to stdout — `{"lir_version", "module", "nodes", "diagnostics"}`.
Every record in `diagnostics` is fixed to seven keys: `code` / `severity` / `where` /
`subject` / `message` / `line` / `hint` (the five keys above plus RFC-0024's `line`
and issue #165's `hint`) — no key is ever omitted.

- With zero diagnostics, `"diagnostics": []` (`null` is forbidden). On a failure
  where compilation never produces a document (a parse/lower error), `lir_version` /
  `module` / `nodes` are `null` and `diagnostics` is still `[]` in the same shape —
  distinct from the `"nodes": []` an empty module successfully emits. A hard error
  message goes out only via stderr.
- Whether `--json` is given changes only the channel: exit code meaning is the
  same, and it is orthogonal to `--strict` (the rc of `--json --strict` is the same
  as giving only `--strict`).
- This seven-key, no-`null` rule is the contract — adding a key is not breaking,
  but removing a key or changing the `null` rule is breaking.

`hint` (issue #165) is a concrete repair instruction for `code` — `str` when the
code has an instruction, `null` when it does not, and always present in every record
following the same never-omitted rule as the other optional key (`line`). All 23 core
`CODES` have an instruction, and an `lnpl.diagnostics` extension (RFC-0042) can also
use the same mechanism by carrying an optional `"hint"` in its own code-registration
metadata (`null` if it does not declare one). The output of the RFC-0043
driver-enforcement bridge (`capabilities.enforcement_diagnostic_records()`) is not
covered by this — that bridge already emits a different shape from the core (six
keys, no `suggestion`), a pre-existing asymmetry this issue does not bring into
alignment.

### 2. Semantic IR schema (`schemas/lir.schema.json`)

The canonical schema for the IR JSON `lnpl compile` emits. The `lir_version`
field marks the schema generation.

- **Guaranteed**: within the same `lir_version`, an existing node `kind`'s required
  fields are kept. Adding a new `kind` or an optional field (for example v0.5.0's
  `line`, RFC-0024) is not breaking.
- **Breaking**: removing an existing required field or changing its type, or
  bumping `lir_version` (a change that could break a downstream consumer parsing with
  no re-validation).

**The `provenance` block (issue #136)**: the top-level `provenance` key on every
document `to_document()` emits — fixed to four keys: `compiler` /
`vocabulary_digest` / `enforcement_digest` / `extensions`. Exactly per the guarantee
above, "adding a new `kind` or optional field is not breaking", it is additive and
optional — `lir_version` was not bumped, and an older-generation document with no
such key is still valid (`lnpl.provenance.check()` fills its report with `None` in
that case). `vocabulary_digest` / `enforcement_digest` are the sha256 of a normalized
serialization (`sort_keys=True`, compact separators), and the `"sha256:"` prefix is
part of the contract — changing the prefix or hash algorithm is breaking. The value
itself (the digest's actual hex) is not part of the contract: it changes on every
normal commit that changes a vocabulary or enforcement constant. A signature or
attestation is out of this block's scope — its purpose is identifying the semantic
generation, not trusting the build platform.

### 3. sqlite storage schema (`lnpl_rows` / `lnpl_outbox`)

The two tables `--backend sqlite:<path>` opens. The canonical reference is
[docs/backends.en.md](backends.en.md).

- `lnpl_rows`: `entity_id, row_key, payload, _version`. `_version` is an internal
  column used only for an optimistic-concurrency conditional write (issue #92) —
  `UPDATE ... SET payload = ?, _version = _version + 1 WHERE ... AND
  _version = ?`.
- `lnpl_outbox`: the PK is `seq` (sqlite `AUTOINCREMENT`), not `emission_id` — issue
  #102 measured `emission_id` causing a PK collision on a re-run against the same DB,
  so row identity was moved to the storage-owned surrogate key `seq`. `lnpl outbox
  ack` is idempotent on re-`ack`ing the same `seq`.
- **Guaranteed**: an existing column's name and meaning are kept. Adding a column
  that an existing DB file can absorb via `ALTER TABLE ... ADD COLUMN ... DEFAULT
  ...` is not breaking (for example, `_version` itself was introduced this way).
- **Breaking**: removing an existing column or changing its meaning, changing the
  PK definition (for example, making `emission_id` the PK again), or changing a
  column's type with no migration.

### 4. `spec` block vocabulary — `given` / `expect`

The canonical reference for the forms `given` accepts (`valid`, `empty
repository`, `input.<field>`, `stored`, `stored <entity>[<i>]`, `call ... returns
...`, etc.) and the keys `expect` accepts
(`completed`/`failed`/`steps`/`rows`/`emitted`/`effects`/...) is the `lnpl-spec`
skill reference (`references/spec.md`, generated from the compiler's docstring
constants — a hand edit fails `test_plugin_references.py`).

- **Guaranteed**: an existing `given` form's or `expect` key's parsing and meaning
  are kept. Adding a new key/form (v0.5.0's `call ... returns ...`, RFC-0027) is not
  breaking. An undocumented key is rejected fail-closed by the generator (issue
  #61).
- **Breaking**: removing an existing key or form, or changing its meaning.

### 5. CLI surface

The set of subcommands `lnpl --help` lists, and each command's observable
behavior (input arguments, exit code, the stdout/stderr contract):

```
compile   parse and lower to Semantic IR
run       compile then execute (interpreter mode A)
spec      extract `spec` blocks as a test manifest
openapi   generate an OpenAPI 3.1 document from the IR
serve     serve workflows over HTTP at the OpenAPI paths (mode A, fake backend)
token     issue a bearer token for one served path (#25)
outbox    drain/ack the lnpl_outbox — at-least-once emit delivery (issue #102)
build     compile to a native binary (mode B)
diff      differential check: mode A vs mode B
kb        inspect the knowledge base (RFC-0005)
agents    run the RFC-0006 agent cycle over a source
```

The production deployment path (`lnpl.wsgi:build_app()` + the environment-variable
contract) is a separate contract from this subcommand list, and the canonical
reference is
[docs/serving.en.md](serving.en.md#production-deployment--wsgi-host-gunicorn-issue-80).

- **Guaranteed**: an existing subcommand's name, required arguments, exit code on
  success (0), and failure classification (the same principle as the diagnostic
  schema) are kept. Adding a new subcommand or optional flag is not breaking.
- **Breaking**: removing or renaming an existing subcommand, changing the meaning
  of a required argument, or an exit-code change that changes the success verdict.

## Supported Python versions

`pyproject.toml`'s `requires-python = ">=3.11"` is the floor, and for every
version in the table below, `ci.yml`'s `gate` matrix leg runs the full suite.
`impl/tests/test_python_support_matrix.py` checks that the table, `classifiers`, and
the matrix are the same set. Upstream status is as of
<https://devguide.python.org/versions/> (confirmed 2026-11-02).

| Python | Upstream status | Upstream EOL | CI leg |
|--------|---------------|--------------|---------|
| 3.11 | security | 2027-10 | `gate (py3.11)` |
| 3.12 | security | 2028-10 | `gate (py3.12)` |
| 3.13 | security | 2029-10 | `gate (py3.13)` |
| 3.14 | bugfix | 2030-10 | `gate (py3.14)` |

- Raising the floor (removing a version from the table) is breaking — announced in
  CHANGELOG `Changed`. Adding a new version is not breaking.
- `gate (py3.14)` is not a required check of `main` branch protection as of
  2026-11-02 — registering it is a repository-settings task (the
  "Required status check candidates" section of [CI-GATES.en.md](CI-GATES.en.md)).

## What this document does not cover

- Extending or shrinking the `.lnpl` language vocabulary (verbs/declarations)
  itself — that contract belongs to each RFC (the canonical source is `rfcs/`); this
  document covers only the **tooling surface** that consumes the vocabulary.
- Internal implementation details (module paths, private functions) — these were
  never a contract in the first place.
