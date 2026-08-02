# Task 07: ship — PR, merge, close #8 and #3, file the cache-TTL gap

## Objective

The work is squash-merged to `main` under the personal account, issues #8 and #3
are closed with what was actually found, and the mode B cache-TTL gap has its own
issue whose number is in the code.

## Wiki pages (read these first, only these)

None — repository process. (`[no-wiki]`.)

## Inputs

- Tasks 02, 03, 04, 06 complete; suite green.
- Git identity, already set in this working copy — verify, do not assume:
  `user.name = choiyounggi`,
  `user.email = 74581798+choiyounggi@users.noreply.github.com`.
  **No `Co-Authored-By: Claude` trailer.**
- Base branch `main`. **Never force-push it.**
- Auth: `gh` needs the personal token; the working copy's remote carries it.
  Extract without printing it:
  `GH_TOKEN=$(git remote get-url origin | sed -E 's|.*:([^@]+)@.*|\1|')`.
  If `gh` still fails on auth, ask 영기 rather than hunting for a token.
- From task 04: the docstring of
  `TestModeBDoesNotEnforceTheCacheTtlContract` contains the placeholder
  `see the cache-TTL follow-up issue`.
- Findings to surface in the PR body, all measured:
  - `GUARDED` was divergent before any monkeypatch (`FAIL 2/4 policy outcome —
    A=failed B=completed`) because `cache user` had no TTL budget; mode A refuses,
    mode B does not.
  - Three of five mismatch cases therefore asserted `assertFalse(ok)` against a
    divergence their own patch never caused.
  - The `when` case needed more than a fixture fix: with the guard **true** the
    step runs, so removing the guard changes nothing. It only detects anything
    with a payload that makes the condition false.
  - Issue #3's premises were stale twice — the parser already rejects
    `latency exceeds budget`, and "Decided: A (supersede)" predates RFC-0007's
    `Updates` relation.
  - The real #3 defect was RFC-0007 §2.2 rule 2: RFC-0008 contradicts RFC-0002
    §Open Questions ② without naming it in `Updates:`.

## Steps

1. Confirm the tree is green and the identity is right:

   ```bash
   cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
   git config user.email && git config user.name
   PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
   git status --short
   ```

2. File the cache-TTL issue **first**, so its number can go into the code.
   Three further findings get their own issues in step 11b; only this one is
   referenced from code, so only this one must exist before the branch.

   Title: `Mode B does not enforce RFC-0003's cache-TTL contract`

   Body must contain: the measured mode A error string, the fact that mode B's C
   shim prints and returns 0, the resulting `FAIL 2/4`, that
   `TestModeBDoesNotEnforceTheCacheTtlContract` pins it and goes red when the gap
   closes, and the likely fix shape (`build()` refusing a `CacheAccess set` with no
   budget, mirroring mode A) together with the reason it was not done here — it
   changes compile behaviour and needs its own equivalence argument.

   Write the body with the `Write` tool to
   `/Users/choeyeonggi/.claude/tmp/issue-ttl-gap.md`, then
   `gh issue create --repo choiyounggi/linkly --title … --body-file <literal
   absolute path>`.

3. Replace the placeholder in `impl/tests/test_backend.py` with the real number
   (`see issue #N`), and verify:

   ```bash
   git grep -n "cache-TTL follow-up issue" -- impl
   ```

   Success = empty.

4. Branch from a freshly fetched `main` — not the local ref:

   ```bash
   git fetch origin
   git checkout -b fix/mismatch-cases-and-oq2 origin/main
   ```

5. Commit by task boundary, so the fixture move, the test repair, the TTL pin and
   the RFC work stay separable. No Claude trailer.

6. Write the PR body with `Write` to
   `/Users/choeyeonggi/.claude/tmp/pr-body-mismatch-oq2.md` in a **separate call**
   before the `gh pr create` call — the Decision Log hook is evaluated before the
   command runs, so a body file made by a heredoc inside the same compound command
   is unreadable to it.

   The body needs a `## Decision Log` block: 의도 / 배제한 대안과 이유 / 리뷰 포인트.
   Mark anything not measured `[추정]` — everything above was measured, so it
   should be rare.

7. Create the PR, passing `--body-file` as a **literal absolute path** — no
   quotes, no `$HOME`, no variable. The gate's extractor reads
   `[^ '"]+`, so a quoted or interpolated value reads as absent and blocks the call.

   ```bash
   gh pr create --repo choiyounggi/linkly --base main --head fix/mismatch-cases-and-oq2 \
     --title "fix(tests): make the deliberate-mismatch cases detect their own fault; close RFC-0002 OQ2" \
     --body-file /Users/choeyeonggi/.claude/tmp/pr-body-mismatch-oq2.md
   ```

8. **Show 영기 the PR body and the diff stat, and get confirmation before
   merging.** Self-merge is pre-approved as a mechanism, but this PR adds a new
   Accepted RFC, so the content gets a look.

9. On confirmation:

   ```bash
   gh pr merge <N> --repo choiyounggi/linkly --squash --delete-branch
   ```

10. Verify by measurement, not by exit code:

    ```bash
    gh api repos/choiyounggi/linkly/commits/main --jq '{sha:.sha[:10], who:.author.login}'
    git log origin/main -3 | grep -i co-authored
    ```

    `who` must be `choiyounggi`; the grep must return nothing.

11. Close #8 and #3 with comments saying what was actually found — including that
    both issue bodies were stale, and how. For #3, state the change of course:
    the "supersede" decision recorded in its comment predates RFC-0007's `Updates`
    relation, and RFC-0009 uses `Updates` instead.

11b. File the three findings this change surfaced but did not fix. Each needs the
    measurement, not just the claim:

    - **`mutation_check.py`'s baseline is RED on `main`.** Measured:
      `baseline (unmutated copy) is not green (RED) — the harness cannot
      distinguish a caught mutation from a broken tree`, from a stale anchor in
      `interp.py`. Consequence worth stating: the proof that each repaired
      mismatch case can fail is now a **manual** procedure recorded in a task
      file, with no automated guard against them going vacuous again.
    - **RFC-0007 is `Status: Draft`** while RFC-0000 (Superseded) names it the
      effective process. RFC-0008 and now RFC-0009 both build on it. Promoting it
      is the owner's call.
    - **Mode A and mode B take the guard condition through different inputs.**
      Mode A evaluates it from `payload`; mode B takes a separate `skip` flag. A
      caller must keep the two consistent by hand — which is exactly what task 02
      had to do to make the `when` case non-vacuous, and a mismatch would look
      like a backend divergence.

12. Pull `main` and re-run the suite there:

    ```bash
    git checkout main && git pull origin main
    PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
    ```

    Success = `OK`, no regression.

## Deliverables

- A squash-merged PR on `choiyounggi/linkly` `main`
- A new issue for the cache-TTL gap, its number referenced in
  `impl/tests/test_backend.py`
- Issues #8 and #3 closed with findings

## Verify

- `gh pr view <N> --json state` → `MERGED`
- `gh issue view 8 --json state` and `… 3 …` → `CLOSED`
- `gh api repos/choiyounggi/linkly/commits/main --jq .author.login` → `choiyounggi`
- Suite on merged `main` → `OK`
- `git grep -n "cache-TTL follow-up issue" -- impl` → empty

## Out of scope

- Implementing the cache-TTL fix.
- Issues #2 and #7.
