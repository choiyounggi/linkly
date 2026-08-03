# Task 07: ship — PR, merge, close #2, file what was found

## Objective

The work is squash-merged to `main` under the personal account, issue #2 is closed
with what was actually found, and the adjacent defect this work uncovered has its
own issue.

## Wiki pages (read these first, only these)

None — repository process. (`[no-wiki]`.)

## Inputs

- Tasks 01-06 complete; suite green; `mutation_check.py` baseline GREEN with 0
  STALE and the four new entries RED.
- Git identity, already set in this working copy — verify, do not assume:
  `user.name = choiyounggi`,
  `user.email = 74581798+choiyounggi@users.noreply.github.com`.
  **No `Co-Authored-By: Claude` trailer.**
- Base branch `main`. **Never force-push it.**
- Auth: extract the token from the remote without printing it —
  `GH_TOKEN=$(git remote get-url origin | sed -E 's|.*:([^@]+)@.*|\1|')`. If `gh`
  still fails on auth, ask 영기.
- Findings to surface, all measured:
  - Issue #2's premise was wrong three ways: a prescription **does** exist
    (`patterns-repository-call`); the input **is** reachable (the schema accepts a
    two-access step — measured VALID — while the `.lnpl` front end cannot produce
    one); and `ir.propose`'s inability to remove is **implementation
    conservatism, not protocol** — RFC-0006 contains no removal rule, and the
    error message cited a section that does not have one.
  - The rights hole is **general**, not Constraint-specific: three roles can
    author a node they cannot attach.
  - The two "side findings" the issue recorded are the **direct and sole** cause
    of the block, measured by running the split through the real server and
    getting both refusals.
  - The recorded "ships as a supersede" decision predates RFC-0007's `Updates`
    relation — the same stale premise corrected in #3.
- Decisions to surface in the Decision Log: **D3** (intent, and both rejected
  mechanisms with their measured reasons — the 8-method ceiling and RFC-0006's
  output-derivation of rights), **D7** (what stops abuse), **D9** (the invariant
  gate already existed; this change removes an over-constraint), **D12**, **D14**.

## Steps

1. Confirm green and correctly attributed:

   ```bash
   cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
   git config user.email && git config user.name
   PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
   git status --short
   ```

2. File the adjacent defect **first**, so the PR body can reference its number:

   Title: `ir.propose's rationale and kb_pins are required by RFC-0006 and never read`

   Body must contain: RFC-0006 §Methods lists
   `params: { module, ir_fragment, rationale, kb_pins, _meta }` and calls `kb_pins`
   **필수** (사용하지 않았다면 `[]`), with validation delegated to `### Errors` ④;
   measured, `impl/lnpl/protocol.py` never reads either name (`git grep -n
   "kb_pins\|rationale" -- impl/lnpl/protocol.py` returns nothing). So a proposal
   with no KB grounding at all is accepted by the transport, and the Reviewer's
   provenance check on `meta.source` is the only thing standing in for it. Note
   that this was found while changing the same method's params for RFC-0010 and
   deliberately left alone to keep that change reviewable.

   Write the body with `Write` to
   `/Users/choeyeonggi/.claude/tmp/issue-kb-pins.md`, then `gh issue create
   --repo choiyounggi/linkly --title … --body-file <literal absolute path>`.

3. Branch from a freshly fetched `main`:

   ```bash
   git fetch origin
   git checkout -b feat/refactoring-agent origin/main
   ```

4. Commit by task boundary — RFC, propose gate, review gate, agent, mutations,
   records — so the contract is separable from its implementation in history. No
   Claude trailer.

5. Write the PR body with `Write` to
   `/Users/choeyeonggi/.claude/tmp/pr-body-refactoring-agent.md` in a **separate
   call** before the `gh pr create` call — the Decision Log hook is evaluated
   before the command runs, so a body file created by a heredoc inside the same
   compound command is unreadable to it.

   Needs a `## Decision Log` block: 의도 / 배제한 대안과 이유 / 리뷰 포인트. Mark
   anything not measured `[추정]`; everything above was measured, so it should be
   rare.

6. Create the PR, passing `--body-file` as a **literal absolute path** — no quotes,
   no `$HOME`, no variable, or the gate's extractor reads it as absent and blocks:

   ```bash
   gh pr create --repo choiyounggi/linkly --base main --head feat/refactoring-agent \
     --title "feat(agents): RefactoringAgent, and the RFC-0006 defects that blocked it" \
     --body-file /Users/choeyeonggi/.claude/tmp/pr-body-refactoring-agent.md
   ```

7. **Show 영기 the PR body and the diff stat, and get confirmation before
   merging.** Self-merge is pre-approved as a mechanism, but this PR adds a new
   Accepted RFC that changes the agent protocol's contract, so the content gets a
   look.

8. On confirmation: `gh pr merge <N> --repo choiyounggi/linkly --squash
   --delete-branch`.

9. Verify by measurement, not exit code:

   ```bash
   gh api repos/choiyounggi/linkly/commits/main --jq '{sha:.sha[:10], who:.author.login}'
   git log origin/main -3 | grep -i co-authored
   ```

   `who` must be `choiyounggi`; the grep must return nothing.

10. Close #2 with a comment stating what was found — including that the issue's
    three unblock paths were all off-target, that its own two side findings were
    the actual cause, and that the recorded supersede decision was superseded by
    RFC-0007's `Updates` relation. Note that the mechanism also unblocks
    SecurityAuditor and PerformanceAnalyzer, whose wiring is left for a follow-up,
    and file that follow-up.

11. Pull `main` and re-run the suite plus the mutation baseline there:

    ```bash
    git checkout main && git pull origin main
    PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
    ```

## Deliverables

- A squash-merged PR on `choiyounggi/linkly` `main`
- Issue #2 closed with findings
- Two new issues: the `rationale`/`kb_pins` defect, and the
  SecurityAuditor/PerformanceAnalyzer attachment wiring

## Verify

- `gh pr view <N> --json state` → `MERGED`
- `gh issue view 2 --json state` → `CLOSED`
- `gh api repos/choiyounggi/linkly/commits/main --jq .author.login` → `choiyounggi`
- Suite on merged `main` → `OK`; `mutation_check` baseline → `GREEN`

## Out of scope

- Implementing either follow-up.
- Any change to `main` other than this merge. **Never force-push `main`.**
