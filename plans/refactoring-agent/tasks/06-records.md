# Task 06: RFC-0006's backlink, and the records that predicted a supersede

## Objective

RFC-0006 carries its side of the RFC-0010 relation, and the two project records
that predict a *supersede* for it say what actually happened instead.

## Wiki pages (read these first, only these)

None — project RFC process. (`[no-wiki]`.)

## Inputs

- From task 01: `rfcs/0010-proposal-intent.md`, `Accepted`, with
  `Updates: RFC-0006 §Agent Roles & IR Access, RFC-0006 §Methods`.
- **The obligation.** RFC-0007 §2.2, `Updates` row: the target keeps `Accepted`
  and carries `Updated-by: RFC-NNNN (§<절 이름>)` **plus a pointer line at the head
  of each named section**. Both halves, per section.
- **The precedent in this repo — follow it exactly.** From the RFC-0009 work:
  - `rfcs/0002-syntax.md` `## Status` block carries one `Updated-by:` line per
    updating RFC (they accumulate — RFC-0007 §2.2 rule 5).
  - each updated section's head carries a blockquote `> 갱신됨: RFC-NNNN`, with a
    blank line either side. `rfcs/0002-syntax.md:291` and `rfcs/0003-runtime.md`
    §Guard show the shape.
  - `rfcs/0002-syntax.md`'s guard-line item shows the in-line variant when only
    part of a section changes: `(… 부분은 갱신됨: RFC-0009)`.
- `docs/CONSISTENCY-CHECK.md` — the table I corrected in the previous PR now has a
  row reading, for RFC-0006: **대기 중.** *권한표와 제거 연산이라 한 절에 그치지
  않으므로, `Updates`로 충분한지 전면 대체가 필요한지는 착수 시 판단한다.* That
  judgment is now made (D10).
- `docs/ROADMAP.md` — check for a risk row naming the RFC-0006 rights hole or
  RefactoringAgent; if one exists, it is now resolved. `git grep -n
  "RefactoringAgent" -- docs` finds it.
- Decisions that bind you: **D10** (`Updates`, and why the recorded supersede was
  stale), **D12** (RFC-0006 never prohibited removal).

## Steps

1. In `rfcs/0006-agent-protocol.md`'s `## Status` block, add below the existing
   `- Status: Accepted (2026-07-31)`:

   ```
   - Updated-by: RFC-0010 (§Agent Roles & IR Access, §Methods)
   ```

   Do **not** change the `Status:` line — RFC-0006 stays `Accepted` (D10).

2. Add the pointer at the head of each named section — after the heading, blank
   line either side, matching `rfcs/0002-syntax.md:291`:

   - `### Agent Roles & IR Access` → `> 갱신됨: RFC-0010`
   - `### Methods` → `> 갱신됨: RFC-0010 (`ir.propose`)`

   The second is scoped in-line because only the `ir.propose` subsection changes,
   following RFC-0002's guard-line precedent.

3. **Leave RFC-0006's body otherwise unchanged.** Under `Updates` the target keeps
   its text and the updating RFC's section wins (RFC-0007 §2.2 rule 3). Rewriting
   the rights table or the `ir.propose` params here would put the contract in two
   places — the drift the relation exists to prevent.

4. `docs/CONSISTENCY-CHECK.md` — replace the RFC-0006 row's **대기 중** verdict with
   what happened: the revision went out as **RFC-0010 via `Updates`**, naming two
   sections; RFC-0006 stays `Accepted` and is **not** superseded. State the reason
   the judgment came out that way — RFC-0007 §2.2 rule 7 measures by how many
   documents a reader must open per section, and with no prior update that is 2,
   inside the limit.

   Add one sentence recording the sharper finding, because the file is where this
   repo keeps discovered inconsistencies: **RFC-0006 never prohibited removal.**
   The implementation refused it and cited `RFC-0006 §Methods` for a rule that is
   not there; RFC-0010 states the semantics for the first time and the citation was
   corrected.

   Also add the **V5 divergence**: RFC-0004 §S2 names five document invariants and
   the implementation enforces V2/V3/V4 only — V1 and V5 (`kind별 children 허용 종별`)
   are absent, and the schema types `children` as an unrestricted id array. RFC-0010
   gates `attach` on V5 but leaves the document-wide invariant unimplemented.
   RFC-0007 §5 requires a known divergence to be recorded here **before** it is
   worked around, so this is obligatory, not tidying.

5. `docs/ROADMAP.md` — two places, found by `git grep -n "RefactoringAgent" -- docs`:
   - a **blockquote note** around `:223`-`:227` reading *"9종 중 8종 … 남은 것:
     **RefactoringAgent 1종**(`ir.propose`가 노드 제거를 표현하지 못해 …)"*. It is
     not a risk row, so it would fall outside a "risk rows only" sweep — update it
     anyway: 9종 전부 구현됐고, 그 괄호 안의 사유는 **틀렸다**(RFC-0006은 제거를
     금지한 적이 없다).
   - any risk row naming the gap → mark resolved pointing at RFC-0010, in the same
     struck-through style used for R13 and R30. Do not restate the new contract
     here.

6. **`README.md` and `README.ko.md`** — both carry issue #2 in the open-issues
   table with the refuted premise: *"it needs `ir.propose` to express node
   *removal*, an RFC-0006 revision"* (`README.md:326`, `README.ko.md:302`). Task 07
   closes #2, so leaving the row would advertise a closed issue on a premise this
   change disproves. Remove the row from both, and keep the two files **identical in
   content** — they are translations of each other.

## Deliverables

- `rfcs/0006-agent-protocol.md` (modified — one Status line, two pointers)
- `docs/CONSISTENCY-CHECK.md` (modified — one row, one sentence, the V5 divergence)
- `docs/ROADMAP.md` (modified — the blockquote note, plus any risk row)
- `README.md`, `README.ko.md` (modified — issue #2's row removed)

Six files. That is over the plan's own ≤3 bound, and deliberately so: they are all
one-line record corrections that belong to the same fact, and splitting them would
put the RFC's relation in one commit and the statements it falsifies in another.

## Verify

```bash
cd ~/Desktop/workspace/ai
grep -nE "^- (Status|Updated-by):" rfcs/0006-agent-protocol.md
grep -n "갱신됨: RFC-0010" rfcs/0006-agent-protocol.md
git diff --numstat rfcs/0006-agent-protocol.md
```

Success = `Status:` still `Accepted`; one `Updated-by:` naming both sections; **two**
pointer lines; and the numstat shows **insertions only, 0 deletions** — a deletion
means step 3 was violated.

```bash
git grep -n "대기 중" -- docs/CONSISTENCY-CHECK.md
```

Success = the RFC-0006 row no longer says 대기 중.

Docs-only, so:

```bash
mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`.

## Out of scope

- RFC-0010's own content — task 01.
- Editing RFC-0006's rights table or `ir.propose` params (step 3).
- The `rationale`/`kb_pins` non-enforcement finding — task 07 files it.
