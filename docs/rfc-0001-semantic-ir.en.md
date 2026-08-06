# RFC-0001: Semantic IR — English summary

> This is a **summary**, not the specification. The normative document is
> [`rfcs/0001-semantic-ir.md`](../rfcs/0001-semantic-ir.md), written in Korean and
> `Accepted` since 2026-07-31 (updated by RFC-0011, §부록 A.6.3 and §부록 A.7).
> Where the two disagree, the Korean text wins. Identifiers, keywords, and schema
> field names are English in both.
>
> RFC-0001 is the document the rest of the suite is defined against: the surface
> language (RFC-0002) lowers *into* this IR, and the runtime (RFC-0003), the compiler
> (RFC-0004), and the agent protocol (RFC-0006) are all defined as *consumers* of it.

## The problem

A conventional compiler's AST — `Assignment`, `BinaryExpression`, `BlockStatement`,
`IfStatement` — preserves the *syntax* of the source and loses the developer's
*intent*: what is being validated, which side effects are caused, under what
constraints it runs. linkly discards the AST. Its intermediate representation makes
meaning first-class instead: `BusinessRule`, `Validation`, `NetworkCall`,
`RepositoryCall`, `CacheAccess`, `Transaction` are the units of a program.

What the IR deliberately does **not** carry is *how*: which library issues the JWT,
which driver reaches postgres. That is decided by the compiler from the declared
capabilities and constraints.

## Flat node table, not a nested tree

An IR document is a **flat set of nodes**. No node inlines another. That a workflow
has six steps is expressed only as an array of ids on the workflow node —
`children: ["wf.login.step.1", …]` — and each step is an independent row in the table.

Three reasons, in the RFC's own order:

1. **Constrained decoding.** For an LLM agent to emit IR fragments directly as
   structured output, the schema must stay inside structural limits (nesting ≤ 5).
   Referencing children only by id satisfies that bound *structurally* — no matter how
   deeply nodes compose, the schema's nesting depth is fixed.
2. **Cheap diffs and fragment exchange.** A node is a top-level row, so a per-node
   diff, or shipping a partial IR between agents, costs little.
3. **Stable serialization order**, which keeps KV-cache prefixes reusable across
   inference calls.

## Common fields

Every node has exactly these four. There are no other common fields.

| Field | Required | Form | Meaning |
|-------|----------|------|---------|
| `kind` | yes | one of the 21 PascalCase identifiers in the catalog | The sole discriminator of node type. The four categories below are an axis of the catalog table, not a node field |
| `id` | yes | dot-path matching `^[a-z][a-z0-9]*(\.[a-z0-9]+)*$` | Unique within the document. E.g. `svc.login`, `wf.login.step.3` |
| `meta` | no | object | Only `source` (origin location) and `origin` (`human` \| `agent:<name>`). Additional keys are rejected — `additionalProperties: false` |
| `children` | no | array of ids | Ownership (containment) references |

## Structure rules

1. **Flat table.** A node may not contain another as an inline nested object; children
   are referenced only as an id array.
2. **Single ownership.** A node appears in at most one node's `children`. A node in no
   `children` is a top-level entry node, and only `Declaration` nodes may be one.
3. **Order is meaningful.** `children` order is execution order for a Workflow, data
   flow order for a Pipeline; for Concurrency each child is a parallel branch and the
   end of the array is the join point.
4. **No cycles.** The ownership graph is acyclic.
5. **Two reference layers.** ① `children` = owning references. ② named reference
   fields (`requires`, `constraints`, `entity`, `event`, `target`, `source.ref`) =
   non-owning. Constraint nodes are never owned as children; they are referenced only
   through `constraints`.
6. **No dangling references.** Every reference, owning or not, must resolve to an `id`
   in the same document.

## Node catalog — 21 kinds in four categories

**Declaration** — what exists. The only category that may be an entry node.

`Entity`, `Service`, `Workflow`, `Event`, `Capability`, `Refinement`

**Behavior** — what is done.

`BusinessRule`, `Validation`, `WorkflowStep`, `Guard`, `Pipeline`, `Concurrency`

**Effect** — what side effect is caused. Making side effects first-class nodes is the
core of this IR.

`NetworkCall`, `RepositoryCall`, `CacheAccess`, `Transaction`, `Authorization`,
`EventEmit`

**Constraint** — under what constraint it runs. Never owned as children; referenced
through the `constraints` field of Service / Workflow / WorkflowStep / Effect nodes.

`Policy`, `Security`, `Performance`

Two distinctions worth noting. `Event` (a Declaration) states that an event exists and
what its payload is; `EventEmit` (an Effect) is the act of publishing it at a specific
point. And `Guard` is **one** kind carrying a closed `mode` enum
(`when` / `until` / `repeat`), not three separate kinds.

Adding or removing a row in the catalog is an amendment to the RFC, not an
implementation detail. Field *notation* is owned by RFC-0002; *execution meaning*
(ordering, failure, retry) by RFC-0003.

## Semantic types — 18, and user types are refinements only

Primitives are minimized and domain meaning is carried by the type itself. Each type
embeds a validation rule, and that rule is the source from which validation code,
OpenAPI, and frontend validation are generated.

13 domain types: `UUID`, `Money`, `Email`, `Phone`, `Password`, `Address`, `Image`,
`File`, `Currency`, `GeoLocation`, `Json`, `Html`, `Markdown`.

5 primitive auxiliaries: `Text`, `Integer`, `Decimal`, `Boolean`, `DateTime`.

The rules are external standards wherever one exists — RFC 4122 for `UUID`, RFC 5322
addr-spec for `Email`, E.164 for `Phone`, ISO 4217 for `Currency`, ISO 3166-1 alpha-2
for the country in `Address`, RFC 3339 for `DateTime`, RFC 8259 for `Json`, CommonMark
for `Markdown`. Two carry prohibitions rather than formats: `Money` forbids binary
floating-point representation (summation error), and `Password` must never appear in
logs, serialization, or error messages — the runtime masking contract is RFC-0003's.

**A user-defined type can only be a refinement.** You pick one of the 18 as a `base`
and *tighten* it (range, pattern, enum, length). Minting a new primitive is forbidden,
because an arbitrary primitive breaks the chain that auto-generates validation.

## Serialization (Appendix A)

- **Schema.** `schemas/lir.schema.json` (JSON Schema draft 2020-12) is canonical. The
  golden example is `examples/login.lir.json`; the runnable checker is
  `scripts/validate_ir.py` (single-document validation plus `--self-test`). The root
  is `{"lir_version": "0.1", "module": "<name>", "nodes": [...]}`.
- **On-disk form** is 2-space pretty JSON — LLMs and humans read the same file. Key
  order and whitespace are not normative in the stored form.
- **Equality, hashing, signing** use **RFC 8785 (JSON Canonicalization Scheme)**. No
  home-grown canonicalization: store pretty, canonicalize with JCS before comparing.
- **Constrained-decoding-compatible subset.** Kind discrimination is a 21-branch
  `anyOf` — `oneOf` is not used, and neither is `default` (both unsupported by
  structured-output runtimes). Because `default` is unavailable, the "omitted means
  true" semantics of `fields[].required` is fixed by the appendix rather than the
  schema: **a field with no `required` key is required.** Maximum object/array nesting
  is 5 levels, and the flat node table is what makes that bound independent of how
  deeply nodes compose.
- `pattern` is declared on `id` and on node-reference fields. The `jsonschema` checker
  enforces it, but a constrained-decoding runtime may not — so always re-validate with
  `scripts/validate_ir.py` before accepting a fragment.

## Scope

RFC-0001 owns the conceptual model, the node catalog, and the type system. Surface
notation for `.lnpl` belongs to RFC-0002 and execution semantics to RFC-0003. The
canonical definitions of terms live in [`docs/GLOSSARY.md`](GLOSSARY.md) and are not
restated here.
