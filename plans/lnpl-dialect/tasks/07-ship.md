# Task 07: ship — PR with Decision Log, self-merge, close #1, open follow-ups

## Objective

The work is on `main` via a squash-merged PR whose body carries a
`## Decision Log`, issue #1 is closed, and the two deferred items this plan
identified have their own issues. Commit authorship is the personal account, not
the work one.

This task exists because the first draft of the plan had no owner for handoff §8's
last criterion ("PR에 `## Decision Log` 포함, 셀프 머지, issue #1 종료") — tasks 05
and 06 both listed it as out of scope. The audit caught it as silently missed.

## Wiki pages (read these first, only these)

None apply — repository process, not a design or testing decision. (`[no-wiki]`.)

## Inputs

- Tasks 01-06 complete; suite green.
- Git identity, **already configured in this working copy** (verify, do not
  assume): `user.name = choiyounggi`,
  `user.email = 74581798+choiyounggi@users.noreply.github.com`. The global default
  is the work address and must not leak into these commits. GitHub attributes by
  **author email**, not by name or by who pushed.
- **No `Co-Authored-By: Claude` trailer.** Explicit instruction from 영기.
- Base branch is `main` (measured: it is the default branch, and PRs #4/#5 both
  targeted it).
- Auth: the remote already carries a working credential. If a push or `gh` call
  fails on auth, **ask 영기** — do not go looking for a token in a file.
- Decisions to surface in the Decision Log: **D1** (IRDL over C++ ODS, with the
  rejected alternative and why), **D6** + **D8** + **D18** (op-stream lowering,
  and the two gates that keep the artifact load-bearing), **D7** + **D9**
  (resolves RFC-0004 Open Q2), **D10** (verifier-enforced traceability),
  **D14** (no S3 context side table — scoped out), **D17** (pre-change fixtures),
  and the pre-existing vacuous-test finding.

## Steps

1. Confirm the tree is green and the identity is right:

   ```bash
   cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
   git config user.email && git config user.name
   PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
   git status --short
   ```

   The email must be the `users.noreply.github.com` one. The suite must say `OK`.

2. Branch from a freshly fetched `main` — not from the local ref, which can be a
   generation behind:

   ```bash
   git fetch origin
   git checkout -b feat/lnpl-dialect-s4 origin/main
   ```

3. Commit. Group by task boundary rather than one giant commit, so the refactor
   (task 03) is separable from the new stage (tasks 01-02) in history. No Claude
   trailer.

4. Write the PR body to a file **in its own Bash call**, before the call that runs
   `gh pr create`. The Decision Log gate is a PreToolUse hook: it is evaluated
   *before* the command runs, so a body file created by a heredoc inside the same
   compound command is unreadable to it and the call is blocked. Use the `Write`
   tool for the body — that also keeps the prose out of Bash-guard scanning.

   Path: `/Users/choeyeonggi/.claude/tmp/pr-body-lnpl-dialect.md`.

   The body must contain a `## Decision Log` block with three parts:
   - **의도** — what S4 now does and why IRDL was chosen.
   - **배제한 대안과 이유** — C++ ODS/TableGen/cmake (build deps + LLVM 22 ABI
     coupling vs RFC-0004 Open Q1); re-parsing the lnpl module in Python (would
     mean writing an MLIR parser).
   - **리뷰 포인트** — the two honest limitations (op-stream lowering; no S3
     context side table), and the pre-existing three-vacuous-tests finding with
     its follow-up issue number.

   Mark anything not directly measured as `[추정]`. Everything in this plan's
   Decisions table was measured, so `[추정]` should be rare — do not sprinkle it
   to look cautious.

5. Create the PR. Pass `--body-file` as a **literal absolute path** — no quotes,
   no `$HOME`, no variable. The gate's extraction regex is of the
   `[^ '"]+` family, so a quoted or interpolated value reads as absent and the
   call is blocked even though the file is fine:

   ```bash
   gh pr create --repo choiyounggi/linkly --base main --head feat/lnpl-dialect-s4 \
     --title "feat(backend): RFC-0004 S4 — custom lnpl MLIR dialect via IRDL" \
     --body-file /Users/choeyeonggi/.claude/tmp/pr-body-lnpl-dialect.md
   ```

6. **Show 영기 the PR body and the branch diff stat, and get confirmation before
   merging.** Self-merge is pre-approved as a mechanism, but this PR changes an
   accepted RFC's normative text, so the content gets a look first.

7. On confirmation, squash-merge and delete the branch:

   ```bash
   gh pr merge <N> --repo choiyounggi/linkly --squash --delete-branch
   ```

8. Verify the merge landed and is attributed correctly — do not infer either from
   the merge command's exit code:

   ```bash
   gh api repos/choiyounggi/linkly/commits/main --jq '{sha:.sha[:10], who:.author.login}'
   ```

   `who` must be `choiyounggi`. Then close issue #1 with a comment naming the PR,
   and state plainly that the "needs a C++ TableGen build" premise in the issue
   body was disproven **and** made moot.

9. Open two follow-up issues:
   - **"S5 lowering should re-parse the lnpl module via an MLIR pass"** — the D6
     limitation. Reference `rfcs/0004-compiler.md`'s updated deviation note and
     note that a C++ ODS dialect plus a `ConversionPattern` is the known path, with
     `MLIRConfig.cmake`/`AddMLIR.cmake`/`mlir-tblgen` all confirmed present.
   - **"Three of the five deliberate-mismatch tests pass vacuously"** — quote the
     measured baseline (`GUARDED` is DIVERGENT with no monkeypatch:
     `FAIL 2/4 policy outcome — A=failed B=completed`), name the three tests, and
     note that `rfcs/0004-compiler.md:437` itself only ever claimed two cases.
     Say that the fix means changing the `GUARDED` fixture or mode A's policy
     outcome, which is why S4 did not touch it.

## Deliverables

- A squash-merged PR on `choiyounggi/linkly` `main`
- `/Users/choeyeonggi/.claude/tmp/pr-body-lnpl-dialect.md`
- Issue #1 closed with a closing comment
- Two new issues opened

## Verify

- `gh pr view <N> --repo choiyounggi/linkly --json state,mergeCommit` → `MERGED`.
- `gh api repos/choiyounggi/linkly/commits/main --jq .author.login` → `choiyounggi`.
- `gh issue view 1 --repo choiyounggi/linkly --json state` → `CLOSED`.
- `git log origin/main --format='%an <%ae>' -3` shows no work address and no
  Claude trailer (`git log origin/main -3 | grep -i co-authored` returns nothing).
- Re-run the suite on merged `main` after `git checkout main && git pull`:
  `OK`, with no regression.

## Out of scope

- Implementing either follow-up issue.
- Any change to `main` other than this merge. **Never force-push `main`** — no
  approval makes that acceptable.
