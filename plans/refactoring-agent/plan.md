# RefactoringAgent, and the RFC-0006 defects that block it (#2)

Goal: implement the ninth agent role, which requires first fixing the two
RFC-0006 defects that make its only groundable job impossible.

Acceptance criteria:

1. `RFC-0010` states, for the first time, how a role attaches a node it authored
   to a node it may not author, and what `ir.propose` does about a reference that
   moves. It `Updates` RFC-0006 and adds no new method.
2. Both rights gates — propose-time (`protocol._m_ir_propose`) and review-time
   (`agents.Reviewer._assess`) — implement that contract identically.
3. `RefactoringAgent` exists, performs the split `patterns-repository-call`
   prescribes, and refuses anything it cannot ground.
4. The permissive path cannot be abused. Precisely: on a node outside its rights a
   role can **only append references, in place** — it cannot reorder them, cannot
   move one between fields, cannot change any other field, cannot drop one, and
   cannot attach a child whose kind that parent may not own. It **can** re-parent
   a node it did not author via `move` (the split does exactly that); the
   guarantee is "no re-parenting across kinds it may not author".
5. 345 existing tests pass, `mutation_check.py` baseline stays GREEN with 0 STALE,
   and **every** new decision branch carries a mutation — not a sample of them.
6. The audit's four attacks are regression tests: `children` reordering, a
   reference migrated between fields, a `WorkflowStep` attached to an `Entity`,
   and a `move` that launders a Constraint removal.

Stack: Python 3.14.6 (`.venv/bin/python`; deps `jsonschema` only — pytest is not
installed). Tests: `cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp &&
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl`.
Targeted runs need the `tests.` prefix — a bare module name fails as
`ModuleNotFoundError` that unittest renders as `Ran 1 test … FAILED`.

## What the issue says vs. what is true

Issue #2 says RefactoringAgent cannot be built because no KB document prescribes
a refactoring, and offers three unblock paths. **Measured this session, all of
that is off-target.**

| Issue claims | Measured |
|---|---|
| No KB document prescribes a refactoring | **One does.** `patterns-repository-call`: *"한 step에 한 저장소 접근. 두 접근이 필요하면 두 step이다."* The issue found it and dismissed it |
| That refactoring "has no reachable input" — the lowering makes one `RepositoryCall` per step | True of the **`.lnpl` front end** (measured: 1, even with two `effect` blocks). **The schema accepts a two-access step** (measured VALID), and agents exchange IR, not source |
| The blocker is the absence of a prescription | The blocker is **two RFC-0006 defects**, both of which the issue lists as side findings |
| `ir.propose` cannot express removal (protocol limitation) | **RFC-0006 never says this.** Grepped: no removal rule anywhere. The refusal is implementation conservatism whose error message cites `(RFC-0006 §Methods)` — a rule that does not exist |
| The rights hole is about Constraints | It is **general** — three roles can author a node they cannot attach |

Running the split through the real protocol server, it is blocked **twice**:

```
권한 안의 절반만 제안  → removal: replacing wf.w.step.1 would drop reference(s)
                        wf.w.step.1.b — ir.propose cannot express a removal
부착까지 시도          → role RefactoringAgent may not propose Workflow nodes
```

| Role | may author | attachment needs | |
|---|---|---|---|
| RefactoringAgent | `WorkflowStep` | `Workflow` | **DENIED** |
| SecurityAuditor | `Security` | `Service` | **DENIED** |
| PerformanceAnalyzer | `Performance` | `Service` | **DENIED** |

So the issue's recorded order — successor RFC first, then the agent — is not
merely sensible, it is **forced**, and those two findings are the direct and sole
cause rather than adjacent observations.

## Decisions

| # | Decision | Choice | Wiki basis |
|---|----------|--------|------------|
| D1 | Which unblock path | **None of the three.** No new KB document (one exists), no `pool` in the grammar (unrelated), no Constraint-rights widening (wrong target — the need is *attachment*) | `[no-wiki]` — measured |
| D2 | Is the input reachable | Yes, through IR. The schema accepts a step owning two `RepositoryCall`s; the `.lnpl` front end cannot produce one. Same shape as the #3 finding about `Guard.condition` — the front end's restrictions are not the IR's | `[no-wiki]` — measured |
| D3 | Attachment mechanism | **Intent on the proposal** (영기's choice). A proposal declares `attach`/`move`; the Reviewer validates invariants instead of surface diffs. Rejected: **field-level rights**, because RFC-0006 derives rights from a role's *outputs* (*"각 역할의 제안 범위는 그 역할이 Charter에서 만들어내는 산출물의 성격에서 유도했다"*) and a field grant is not an output; **a separate `ir.attach`**, because the method set is fixed at 8 (cited in 4 places, and `-32601` is defined as "8종 밖의 메서드") and a ninth method is itself RFC-0006 §Open Questions 4 | `[no-wiki]` — 영기 decision + measured constraints |
| D4 | Method count | Unchanged at 8. `intent` is a new **param** on `ir.propose` | `[no-wiki]` — RFC-0006 §Methods, §Open Questions 4 |
| D5 | `intent` shape | `{"attach": [{"parent": id, "child": id}], "move": [{"node": id, "from": id, "to": id}]}`. Both keys optional. **Absent `intent` behaves exactly as today** — every one of the 345 existing tests must pass with no edit, which is the compatibility proof | `[no-wiki]` |
| D6 | What "reference-only edit" means | **Per-field and order-preserving**, not set-based. A node whose kind is outside the role's rights is permitted **iff**: (a) it already exists in the document, (b) `kind` matches, (c) every **non-reference** field is equal to the existing node's, and (d) for **every** reference field independently — `children` and each of `NAMED_REF_FIELDS` — deleting the references this field newly contains, in order, yields a sequence **identical** to the existing node's value for that field. Anything else → `rights:` as today.<br><br>**The first draft of this decision was set-based and had two holes**, both demonstrated by an independent audit against a faithful implementation: reversing a `Workflow`'s `children` while adding one child was approved (and `children` order **is** execution order, RFC-0001 rule 3), and moving a `Policy` id from a `Service`'s `constraints` into its `children` was approved — set-identical, but `interp.py` reads `constraints` for retry/timeout/rollback, so it silently disabled retry (measured: attempts 4 → 1). Per-field order-preserving equality closes both with one rule | `[no-wiki]` — audit-corrected |
| D7 | What stops arbitrary re-parenting | An `attach` entry's `child` **must be authored in this same proposal** — present in `nodes`, absent from the document. Combined with D6(d), which makes an out-of-rights edit strictly additive, a role can attach only kinds it may author. **Note what this does *not* buy**: `move` has no such containment, and the split itself re-parents a `RepositoryCall` the agent did not author. The guarantee is "cannot re-parent across kinds it may not author", not "cannot re-parent" | testing-quality-tests-that-cannot-fail |
| D8 | When a dropped reference is allowed | Iff a declared `move` names it with a matching `from`, **and after the merge the declared `to` references it in the same field it left**, and — because RFC-0001 rule 5 forbids owning a Constraint through `children` — a `Policy`/`Security`/`Performance` node may only land in `constraints`. The first draft required only that the destination reference it *somewhere*, which the audit used to launder a Constraint removal into a `children` entry (measured: a step's `constraints` emptied, approved) | `[no-wiki]` — audit-corrected |
| D9 | Who checks the invariants | `_structure_fault(merged)` for dangling (rule 6), one-owner (rule 2), orphans (rules 2·5), acyclicity (rule 4) — **plus a new kind-compatibility gate on `attach`**. RFC-0004 §S2 lists five document invariants and `_structure_fault` implements only V2/V3/V4; **V5 (kind별 children 허용 종별) is absent from the implementation entirely** (measured: no such table anywhere), and the schema types `children` as an unrestricted id array. The first draft claimed the existing machinery sufficed; the audit attached a `WorkflowStep` to an `Entity` and it was approved. Since this relaxation's entire content is "write a reference into a node whose kind you do not own", the missing invariant is exactly the load-bearing one. Scope: gate `attach` on RFC-0001's children-allowed column. Enforcing V5 document-wide is a larger change — filed, and recorded in `docs/CONSISTENCY-CHECK.md` per RFC-0007 §5 | `[no-wiki]` — audit-corrected |
| D9b | Auditability of the permissive path | The reference-only edit **must carry `meta.origin = "agent:<role>"`**. RFC-0006 §IR Fragment Embedding already requires it on fragment nodes, but `_assess` skips provenance for existing nodes, so without this nothing in the merged document records that a role reached outside its rights — which is what would make a D6 regression undetectable after the fact | `[no-wiki]` — audit finding |
| D10 | RFC-0010's relation to RFC-0006 | `Updates: RFC-0006 §Agent Roles & IR Access, RFC-0006 §Methods`. RFC-0007 §2.2 rule 7 measures by *"한 절을 읽으려고 몇 개 문서를 열어야 하는가 — 2개를 넘으면 통합 시점"*; RFC-0006 has no prior update, so a reader opens 2 documents per section. Within the rule. The issue's recorded "supersede" decision predates RFC-0007's `Updates` relation — the same stale premise corrected in #3 | `[no-wiki]` — RFC-0007 §2.2 rule 7 |
| D11 | Sections deliberately **not** named | `§Proposal & Approval` — the two-stage flow is unchanged (read it: it describes propose→judge→merge, no removal rule). `§IR Fragment Embedding` — its check-timing table stays correct; reference integrity is still judged on the merged result, which is exactly what this design leans on. Naming a section that does not change would misstate the contract | `[no-wiki]` — read both |
| D12 | The removal prohibition's provenance | It was **never in RFC-0006**. The code's `removal:` message cites `(RFC-0006 §Methods)` for a rule that does not exist there. RFC-0010 states the semantics for the first time, and the citation is corrected to RFC-0010 | `[no-wiki]` — measured (grep found no removal rule) |
| D13 | RFC-0010 section list | All seven, character-exact and in order, per RFC-0007 §7 (*"섹션 추가·삭제·개명 금지"*; the §1 exemption is for process RFCs). `RFC-0009` is the precedent | `[no-wiki]` — RFC-0007 §7 |
| D14 | RefactoringAgent's job | Exactly one: a `WorkflowStep` owning more than one `RepositoryCall` is split so each step owns one, grounded on `kb:patterns-repository-call@0.1.0`. Anything else → propose nothing, mirroring `Coder._fragment_for` returning `None` rather than inventing an Effect.<br><br>**Only when the step's owner is a `Workflow` or a `Pipeline`.** The audit showed the first draft would happily split a step owned by a `Concurrency` node — making the new step a **parallel branch** — or by a `Guard`, leaving it with two guarded items where RFC-0001 allows exactly one, and under `repeat 3` repeating both. Mode A is single-threaded so no test would have seen the first. Other owners → refuse | `[no-wiki]` — audit-corrected |
| D14b | Is the split behaviour-preserving? | **No, and the plan says so.** RFC-0006's role table says RefactoringAgent *"의미를 보존하며 구조를 바꾼다"*, and the KB's own reason for one-access-per-step is that **a step is the unit of retry and span** — so splitting necessarily changes retry granularity. Measured by the audit with `retry 2` and a failing repository: the moved effect went from executing 3× to 1×. Effect *order* is preserved (only the 2nd+ accesses move, and they move to a step inserted immediately after). RFC-0010 must state this rather than eliding it: the transform preserves the **sequence of effects**, not the **retry grouping**, and that is the point of the prescription | `[no-wiki]` — audit finding |
| D15 | New node ids and names | id = `<workflow id>.split.<n>`, `n` 1-based, skipping ids already in the document. Follows RFC-0004 §변형의 형태's precedent of `<workflow id>.par.<n>` for a synthesised sibling step, and satisfies RFC-0001's id pattern. `name` = `"<operation> <entity name lowercased>"` (e.g. `update user`) — a verb phrase as `WorkflowStep.name` requires, and the verb matches `patterns-repository-call`'s dictionary. **Original step ids are never renamed or reused** (RFC-0004 §노드 id 안정성) | `[no-wiki]` — RFC-0004 precedent |
| D16 | Provenance on proposed nodes | `meta.origin = "agent:RefactoringAgent"` (schema pattern `^(human\|agent:.+)$`; `test_agents.py` uses PascalCase e.g. `agent:Coder`) and `meta.source = "kb:patterns-repository-call@0.1.0"`, which satisfies `_SOURCE_FORM` and resolves through `kb.verify` | `[no-wiki]` — measured |
| D17 | Where the two-access fixture lives | Local to `impl/tests/test_agents.py`. `impl/tests/fixtures.py` holds `.lnpl` **source strings**; this is an IR document dict, and mixing the two would blur what that module is for | testing-data-test-data-and-isolation (fixtures shared only when genuinely shared and of one kind) |
| D18 | Mutation coverage for the new gates | Each new permissive branch gets a `mutation_check.py` entry, because a gate that only ever says yes is indistinguishable from an absent gate | testing-quality-tests-that-cannot-fail |

### Deliberately out of scope

- **`rationale` and `kb_pins`.** RFC-0006 §Methods lists both in `ir.propose`'s
  params and calls `kb_pins` **필수**; measured, `protocol.py` never reads either.
  Adjacent to the method being changed, but a separate defect — filed, not fixed.
- Making the `.lnpl` front end able to express a two-access step. The IR is the
  hub; the agent's input arrives as IR.
- **Wiring** SecurityAuditor's and PerformanceAnalyzer's proposals to use the new
  attachment path. But note what is *not* deferred: the propose-time relaxation is
  **role-agnostic the moment it lands**, so both roles gain the capability
  immediately even though neither uses it. The audit confirmed both could run the
  same attacks. So D6/D8/D9's gates must be correct for every role, not just for
  the one this round exercises — "prove the mechanism through RefactoringAgent"
  describes the test coverage, not the blast radius.
- **Enforcing V5 (kind별 children 허용) document-wide.** This round gates `attach`
  on it; the general invariant stays unimplemented. Filed, and recorded in
  `docs/CONSISTENCY-CHECK.md` per RFC-0007 §5, which requires a known
  spec/implementation divergence to be written down before it is worked around.
- Issue #7 (S5 MLIR pass) and #9/#11/#12 from the previous round.

### Known bypass this design does not close

`_structure_fault` runs **only** in `Reviewer._assess`. `decide(approve=True)` and a
hand-built `agent.report` reach `_apply`, which checks dangling only — pinned today
by `test_an_override_still_reaches_the_apply_time_guard`. D9 rests on the review
gate, so an explicit override carries the new permissive path with almost nothing in
front of it. Pre-existing and out of scope, but it must be **stated in RFC-0010**
rather than left for a reader to discover: the intent mechanism is enforced at
review time, and an override is trusted by construction.

### Stale artifacts a split creates

`Tester.derive` emits a `"steps %d"` case from the step count, so any spec manifest
derived before a split goes stale. No task regenerates them; RFC-0010 notes it as a
consequence of the transform.

## Task order

| Task | Depends on | Parallel-ok |
|------|-----------|-------------|
| 01 RFC-0010 — the contract | — | |
| 02 `intent` param and the propose-time rights gate | 01 | |
| 03 the review-time gate | 02 | |
| 04 RefactoringAgent | 03 | |
| 05 mutations for the new gates | 04 | |
| 06 RFC-0006 backlink and the project records | 01 | parallel-ok with 02-05 |
| 07 ship | 05, 06 | |
