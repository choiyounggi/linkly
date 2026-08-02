# Task 06: complete RFC-0002's relation, and fix the records that contradict it

## Objective

A reader who opens `rfcs/0002-syntax.md` alone is told that §Open Questions has
been updated, and by whom. The two project records that still predict a
*supersede* for this work no longer contradict it.

## Wiki pages (read these first, only these)

None — project RFC process. (`[no-wiki]`.)

## Inputs

- From task 05: `rfcs/0009-guard-condition-open-question.md`, `Accepted`, with
  `Updates: RFC-0002 §Open Questions`.
- **The obligation.** RFC-0007 §2.2 relation table, `Updates` row: the target
  keeps `Accepted` and carries
  `Updated-by: RFC-NNNN (§<절 이름>)` **+ 해당 절 머리에 포인터 1줄**. Both halves
  are required; the Status-block line alone is not enough.
- **The precedent already in this repo — follow it exactly.** RFC-0008's relation
  to RFC-0002 is recorded as:
  - `rfcs/0002-syntax.md:6` → `- Updated-by: RFC-0008 (§Full grammar)`
  - `rfcs/0002-syntax.md`, at the head of `### Full grammar (W3C-style EBNF)` →
    a blockquote line `> 갱신됨: RFC-0008`
  - the same shape appears in `rfcs/0003-runtime.md` at `### Guard`.
- Decisions that bind you: **D10** (RFC-0002 stays `Accepted` — do not change its
  Status line).

## Steps

1. In `rfcs/0002-syntax.md`'s `## Status` block, **add a second line** below the
   existing `- Updated-by: RFC-0008 (§Full grammar)`:

   ```
   - Updated-by: RFC-0009 (§Open Questions)
   ```

   Two `Updated-by:` lines is the correct end state — RFC-0007 §2.2 rule 5 says a
   target's pointer lines accumulate. Do not merge them into one line, and do not
   replace the RFC-0008 one.

2. At the head of `## Open Questions` in the same file, add the pointer line, in
   the same blockquote form the other two updated sections use:

   ```
   > 갱신됨: RFC-0009
   ```

   Place it immediately after the heading, with a blank line on each side, exactly
   as `### Full grammar (W3C-style EBNF)` does it.

3. **Leave the five open-question items themselves unchanged.** Under `Updates`
   semantics the target keeps its text and the updating RFC's section wins
   (RFC-0007 §2.2 rule 3). Rewriting item ② here would create a second place the
   answer lives, which is the drift the relation exists to prevent.

4. Do not touch RFC-0002's `Status:` line. It stays `Accepted` (D10).

5. **`docs/CONSISTENCY-CHECK.md` — correct the pending-supersede row (D14).**
   Around line 1378 a table is introduced with *"아래가 현재 대기 중인 대체 대상이며,
   각각 새 RFC 번호로 나간다(원본은 `Superseded by`로 표시)"*, and line 1382 is:

   ```
   | RFC-0002 (Syntax) | Open Questions ② 가드 조건식 문법 확정 + 평가기 없는 `Word Word? Word? Word?` 생산 규칙 제거 | 이슈 #3 |
   ```

   That predicts the course this change reverses. Rewrite the row to record what
   actually happened: the production was removed by **RFC-0008 via `Updates`**, and
   §Open Questions ② by **RFC-0009 via `Updates`**; RFC-0002 stays `Accepted` and is
   **not** superseded. Add one sentence under the table saying the original
   prediction predates RFC-0007's `Updates` relation, so a later reader does not
   read it as a missed obligation.

   This is not tidying. RFC-0007 §2.1 gates Review→Accepted on *"교차 정합성
   체크리스트 전 항목 PASS"* and §8 names this file as that checklist, so a row
   asserting RFC-0002 will be superseded blocks RFC-0009's own transition.

6. **`docs/ROADMAP.md` — retire the restated OQ②.** Risk **R30** (near line 280)
   repeats the sentence RFC-0009 retires — *"`Condition`이 비교식 + 1~4토큰 구가
   전부이며…"* — and carries a line reference into RFC-0002 that is already stale.
   Mark R30 resolved, pointing at RFC-0009, the way R13 was marked resolved when
   S4 landed. Do not repeat the new grammar here; point at the RFC.

## Deliverables

- `rfcs/0002-syntax.md` (modified — two added lines)
- `docs/CONSISTENCY-CHECK.md` (modified — one row + one sentence)
- `docs/ROADMAP.md` (modified — R30 marked resolved)

## Verify

```bash
cd ~/Desktop/workspace/ai
grep -n "Updated-by:\|^- Status:" rfcs/0002-syntax.md
```

Success = the `Status:` line still says `Accepted`, and **two** `Updated-by:`
lines are present — RFC-0008 (§Full grammar) and RFC-0009 (§Open Questions).

```bash
git diff --numstat rfcs/0002-syntax.md
```

Success = **3 insertions, 0 deletions**. Three, not two: the pointer follows the
repo's convention of heading / blank line / `> 갱신됨:` / blank line, so step 2
adds two lines and step 1 adds one. Any **deletion** means step 3 was violated —
that is the number to care about.

Then confirm both pointer directions resolve, for every relation in the repo:

```bash
grep -n "갱신됨" rfcs/0002-syntax.md rfcs/0003-runtime.md
```

Success = three pointer lines — RFC-0002 §Full grammar, RFC-0002 §Open Questions,
RFC-0003 §Guard.

Suite, unaffected by a docs change:

```bash
mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`.

Then confirm nothing still predicts a supersede for this work:

```bash
git grep -n "Superseded by" -- docs/CONSISTENCY-CHECK.md
git grep -n "1~4토큰 구가 전부" -- docs rfcs
```

The second must return only `rfcs/0002-syntax.md` — the target keeps its text
under `Updates` semantics (step 3); `docs/` must be clear of it.

## Out of scope

- Rewriting RFC-0002 item ② (step 3 — the updating RFC owns the new text).
- Promoting RFC-0007 from `Draft`. It is the effective process while formally a
  draft, which RFC-0008 already relied on. A process decision for the owner;
  task 07 files it.
