# CI gate roster and operating procedures

**English** | [한국어](CI-GATES.md)

> This is the English edition of [`docs/CI-GATES.md`](CI-GATES.md), translated in
> full. The Korean text is normative: where the two disagree, the Korean text
> wins. Identifiers, flags, environment variable names, paths and every code
> block are identical in both editions.

This layers 4 AI gates on top of `ci.yml`'s deterministic gates. This document
pins down the whole roster, the plumbing that lets an AI gate be judged by schema
validation rather than prose (`schemas/ai-gate-verdict.schema.json` +
`scripts/ai_gate_verdict.py` + `.github/workflows/_ai-gate.yml`), the advisory→blocking
promotion procedure, the secret-registration procedure, and the required-status-check
candidates.

The per-gate workflow files (`ai-gates.yml`, `ai-gates-quality.yml`) and the prompts
(`.github/ai-gates/*.md`) are owned by those workflows themselves, not this document —
here they exist only as the roster.

## Gate roster

| Gate | Deterministic/AI | Trigger | Current state | What it catches |
|--------|-----------|--------|-----------|----------------|
| Test suite (matrix) | Deterministic | `ci.yml` — `pull_request`, `push: main` | blocking | Regressions in `impl/tests/` (py3.11/3.12/3.13/3.14 — `gate (py3.14)` is not yet required, issue #246) |
| RFC lint (`rfc_lint.py`) | Deterministic | `ci.yml` | blocking | RFC-0007 §3 numbering/title, §3 duplicate/gap numbering, §2.1 Status vocabulary, §7 template sections (name/order), §2.1 CHANGELOG citation (the cited RFC is in rfcs/ and is Accepted or Superseded — issue #249), §2.2 `Updated-by:` back-link (for every `Updates:` target of an Accepted RFC — issue #263), §2.2 rule-7 document count (at most 2 documents to open to read one section of an Accepted RFC, a bundle of section names per `Updated-by:` — issue #268) |
| Reference drift (`gen_plugin_references.py --check`) | Deterministic | `ci.yml` | blocking | A plugin skill reference document differs from what regenerating it from the compiler's tables produces |
| Version sync (`check_version_sync.py`) | Deterministic | `ci.yml` | blocking | Version drift between the root `pyproject.toml` and the plugin manifests |
| ruff | Deterministic | `ci.yml` (t1) | blocking + required | Python lint violations (`impl/lnpl`, `scripts`, `impl/tests`) |
| Doc-snippet compilation (`check_doc_snippets.py`) | Deterministic | `ci.yml` (t2) | advisory → scheduled to become blocking | Whether the `.lnpl` snippets embedded in the docs actually compile |
| `rfc-conformance` | AI | `_ai-gate.yml` (t4) | advisory | A mismatch between what an RFC says and what the code does |
| `golden-approval` | AI | `_ai-gate.yml` (t4) | advisory | Whether a golden-scenario change is justified |
| `test-quality` | AI | `_ai-gate.yml` (t5) | blocking + required (promoted 2026-10-22 — a promotion-criteria exception, see "The advisory → blocking promotion procedure" below) | A test that grades its own code (implementation/evaluation not separated), a fake pass |
| `prose-factcheck` | AI | `_ai-gate.yml` (t5) | advisory | A claim in PR prose (description, comments) that conflicts with the actual diff |
| Release workflow wiring (the `image`/`publish-pypi` job and tag/version guard assertions in `test_release_workflow.py`) | Deterministic | `release.yml` (tag push) | blocking (release-only) | A missing `image` job, the smoke-before-push order, multi-arch (`platforms: linux/amd64,linux/arm64`, the QEMU action's SHA pin coming before the arm64 build/boot-check/buildx/login, the arm64 boot-check script's 200/`arm64`/`ERROR` verdict exercised with a stub), the tag list (`vX.Y.Z`+`X.Y`, no `latest`), the `run:` block forbidding `github.` expressions, `permissions` scope, `publish-pypi` wiring regressions (`environment: pypi`, `id-token: write` as the sole permission, `needs: [build, release]`, a revived `if: false`, an added `skip-existing`, action SHA pins), and `gates` failing to catch a tag/`pyproject.toml` version mismatch |
| Deterministic per-request counters (`test_perf_counters.py`) | Deterministic | `ci.yml` — a module inside the test suite (matrix) job | blocking (via the `gate` job) | A regression in the number of DB connections created/closed, storage statements, or driver creations per request (e.g. a change that opens one extra connection per request) |
| Weekly load report (`load-weekly.yml`) | Deterministic | `load-weekly.yml` — `schedule` (Monday 07:00 UTC) + `workflow_dispatch` | report-only (non-required) | Absolute throughput/latency trends (2 gunicorn sync workers, fake/sqlite backends, 50/100/200/400 rps). Never used as a verdict |
| Lockfile and install invariants (`test_dependency_lockfile.py`) | Deterministic | `ci.yml` — a module inside the test suite (matrix) job | blocking (via the `gate` job) | A missing hash, a range pin, a changed header command, a lost 3.11 floor, or tooling drifting to a different lockfile in any of the four lockfiles (`requirements*.txt`), a mismatch between a `pyproject.toml` group pin and a lockfile pin, and a hash-less `pip install`/`pip wheel`/`python -m build` line in a workflow, `docker/Dockerfile`, or `examples/deploy/Dockerfile` (including `pip3`/`python3 -m` spellings, outside the allowlist) and a digest-less `FROM` in either Dockerfile |
| pip-audit (the `pip-audit (lockfiles)` job in `ci.yml`) | Deterministic | `ci.yml` — `pull_request`, `push: main` | blocking (non-required — making it required is a repo-settings decision) | Published vulnerabilities in the pinned versions of the four lockfiles. Run on py3.11 so it also audits the environment-marked `typing-extensions` |
| Action SHA pin invariants (`test_workflow_action_pins.py`) | Deterministic | `ci.yml` — a module inside the test suite (matrix) job | blocking (via the `gate` job) | Reports, by file:line, any external action `uses:` in `.github/workflows/*.yml` that is not a 40-char commit SHA + `# vX.Y.Z` comment (a mutable tag `@v7`, a branch, a short or long SHA, a missing comment). Excludes local reusable workflows (`./`) and comment lines |
| Coverage (the `coverage (advisory)` job in `ci.yml`) | Deterministic | `ci.yml` — `pull_request`, `push: main` | advisory (non-required, no `--fail-under` — see "The coverage promotion path" below) | Reports `impl/lnpl`'s total line/branch coverage and the diff coverage of the executable lines a PR changed, in the job summary and the `coverage-report` artifact (`coverage.xml`/`coverage.json`/`coverage-summary.md`). Runs the same module set as `gate` under `coverage run --branch` via `scripts/ci_test_suite.py`, and counts only code executed inside the test process (issue #247). Never blocks a merge |

Lockfiles: dependency pins live in `pyproject.toml`'s `[dependency-groups]`
(build, coverage, serve, audit) and the `lint` extra, and the four hashed lockfiles are
built with `uvx uv@0.11.5 pip compile ... --universal --python-version 3.11
--generate-hashes` (the full command is on each file's second line). To regenerate, rerun
the four commands in that order (requirements.txt → -serve → -coverage → -audit) and
verify with `git diff --exit-code requirements.txt requirements-serve.txt
requirements-coverage.txt requirements-audit.txt`. `requirements-coverage.txt` is
installed by the `coverage (advisory)` job's second install-step line, `pip install
--require-hashes -r requirements-coverage.txt` (a line on the allowlist).

actionlint/Scorecard: workflow syntax and shell checks are a local check, not a CI
gate — `docker run --rm -v "$PWD:/repo:ro" --workdir /repo
rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667`
must return rc 0. OpenSSF Scorecard's `Pinned-Dependencies` is checked with the v5.6.0
binary. Running it directly from the worktree root dies on `.venv`'s symlinks, so build a
copy directory from `git ls-files -co --exclude-standard` excluding `.venv/`/`.claude/`,
and run `scorecard --local=<사본> --checks=Pinned-Dependencies --show-details`
(`<copy>`). The only
warnings left at that point are these 4, all non-shipping (out of scope per the
2026-10-29 ruling): `qa/probe-v0.8/cases/s4-ops-deploy/src/Dockerfile:9`/`:22` (no base
image digest), `benchmarks/load/i195/run_linux.sh:43`/`:44` (a hash-less `pip install`).
One residual Scorecard does not see: `docker/setup-qemu-action` in the `image` job of
`release.yml` pulls `tonistiigi/binfmt:latest`, unpinned by digest, run as a privileged
container (it runs before the login step, so no registry credential is on disk yet).

The check names of the 4 AI gates are `rfc-conformance / gate`, `golden-approval /
gate`, `test-quality / gate`, `prose-factcheck / gate` (a generic-http call site is
`<잡>-generic-http / gate` (`<job>-generic-http / gate`) — because the reusable job has no `name:`, and a job
skipped by a job-level `if:` is reported without ever evaluating the `name:` expression
(measured 2026-10-22 on 4 public repos: facebook/rocksdb, qualcomm-linux/meta-qcom,
shakfu/inferna, zeta-chain/node. Behavior not documented by GitHub).

All 4 AI gates sit on top of this document's own reusable workflow,
`_ai-gate.yml` (`on: workflow_call`). The per-gate workflow only needs to pass
`gate_name`/`prompt_file`, and the verdict itself (schema validation, exit code) is
entirely shared here — the core value of this plumbing is never letting prose decide the
exit code.

## How an AI gate is judged

1. `_ai-gate.yml` calls `anthropics/claude-code-action`, pinned by commit SHA
   (`--json-schema schemas/ai-gate-verdict.schema.json` in `claude_args`). The agent
   emits only JSON conforming to that schema as `structured_output`.
2. `scripts/ai_gate_verdict.py` validates that JSON and decides the exit code —
   whatever the agent wrote, only this script decides pass/fail.

| exit code | Meaning |
|-----------|------|
| 0 | Pass |
| 1 | A violation (`verdict=fail`, or 1 or more `severity=blocker` findings) |
| 2 | A format error (no input/an empty file/not JSON, a schema violation, a `gate` field mismatch) |
| 3 | A vacuous pass (`--expect-nonempty` given, yet `verdict=pass` with `examined.files` empty — a pass with nothing actually looked at) |

Why 2 and 3 are kept separate from 1: mixing "the gate is broken" with "the code is
bad" breaks reproducibility.

The table above is the exit code when `scripts/ai_gate_verdict.py` actually runs.
`_ai-gate.yml` distinguishes one more state before that: **gate execution failure** (the
claude step ended non-zero, or `structured_output` is empty — a typical cause is a
transient failure like an Anthropic API 5xx/rate-limit). In that case the verdict script
is never called at all — passing it empty input would give exit 2 (a format error),
mixing "a gate-definition defect" with "the gate couldn't even run." If the cause is
transient, **just re-run the workflow — there is no need to reopen the PR** — this is
not something to fix in the diff or the gate definition.

`_ai-gate.yml` picks the runner via the `runner` input: `claude-code` (default, the
existing path above) and `generic-http` (an OpenAI-compatible `/chat/completions`
endpoint, `scripts/ai_gate_http_runner.py`). Both runners write the same verdict file,
and `scripts/ai_gate_verdict.py` checks that file with the same schema and the same exit
codes. A generic-http failure (a non-2xx response, truncated output, empty or non-JSON
content) falls into the same **gate execution failure** (`unavailable`) bucket as a
Claude Code action failure. On generic-http, JSON that violates the schema or carries a
different `gate` value (verdict-script exit 2) also falls into the same unavailable
bucket — because `response_format json_object` only guarantees it is JSON, not that it
conforms to the schema. In that case the on-screen warning reads as a generic
execution-failure message ("generic-http runner failed or returned empty output"), and
the real cause (the schema-violation line) is in the verdict step's log. A model's
formatting mistake can be deterministic and so does not disappear on a re-run. On the
claude-code runner, exit 2 still fails the job, independent of blocking.

## The advisory → blocking promotion procedure

All 4 AI gates start **advisory** (the `blocking` input of `_ai-gate.yml` defaults
to `false`). advisory applies **only to exit 1 (verdict=fail, or a blocker finding) and
a gate execution failure** — the result is left as a PR comment (or just an
execution-failure log), but it never blocks a merge. exit 3 (a vacuous pass) on both
runners, and exit 2 (a format error) on the claude-code runner, **always** fail the job
regardless of `blocking`. The known exception is exit 2 on the generic-http runner — as
noted above, it falls into the `unavailable` bucket and, while `blocking` is false, only
leaves a warning; the real cause (the schema-violation line) must be read from the
verdict step's log. If advisory lets "the code is bad" (1) and "the gate itself is
broken" (2, 3) through the same way, a broken gate looks like the cleanest gate with 0
false positives, which defeats the promotion procedure below.

Promotion criterion: run advisory for roughly **50 PRs' worth** to measure the
reviewer acceptance rate, and if **the acceptance rate is ≥80% (a false-positive rate
under 10%)**, flip that one gate to `blocking: true`. Judge each gate independently —
never promote all 4 at once.

- Measuring acceptance: the share of a gate's `blocker` findings a reviewer actually
  acted on (a code fix, or acknowledgment in a PR comment). The comment history
  `use_sticky_comment` leaves is the evidence.
- Promotion is flipping one line, `blocking: true`, in the workflow file that calls
  that gate (`ai-gates.yml`/`ai-gates-quality.yml`, owned by t4/t5) — the reusable
  workflow itself is never touched.
- Source of the criterion: this threshold (80%/10%, 50 PRs) is not something observed
  in this project but a researched, settled practice for staged advisory→blocking
  promotion applied here. Once 50 real PRs have accumulated, update this document's
  table with this repo's measured acceptance rate.

### The `test-quality` promotion — a criteria exception (issue #244)

`test-quality` (one claude-code call-site job) was promoted to `blocking: true` on
2026-10-22 **before** meeting the criterion above. The criterion (roughly 50 PRs, 80%
acceptance) was not met. The supporting measurement (2026-10-22, main `315d410`):

| Fact | Measurement command |
|------|-----------|
| 33 `ai-gates-quality.yml` runs across 16 branches, all `success` since 2026-08-31 | `gh run list --repo choiyounggi/linkly --workflow ai-gates-quality.yml --limit 200 --json conclusion,headBranch,createdAt` |
| All 20 `test-quality` jobs among the 20 runs since 2026-10-01 ran with the secret present and `success` | `gh run view <id> --repo choiyounggi/linkly --json jobs` on each run — the "시크릿 부재 처리" (handle missing secret) step is `skipped`, the job is `success` |
| The same 20 logs show "게이트 통과(exit 0)" (gate passed (exit 0)) 20 times, 0 `##[warning]`/`##[error]` annotations — 0 runner failures, 0 `unavailable`, 0 blocker findings, 0 verdicts that would have blocked a merge | `gh run view <id> --repo choiyounggi/linkly --log` on each run, counting only the `test-quality` job's lines (by its old-name prefix) |
| 0 comments, 0 reviews on the recent PRs #221/#259 | `gh pr view <n> --repo choiyounggi/linkly --json comments,reviews` |

The acceptance rate **cannot be measured** — there is no denominator with 0 blocker
findings, and no sticky comment was ever left. That is, this promotion is not "80%
acceptance confirmed" but an exception resting on "it ran with no runner failures and no
false-positive signal." Why it is promoted now: the user decided it in #244 — with a
single collaborator, human review cannot be required (see "Why no required approvals"
below), so one AI gate stands in for the second reviewer. Why only this one was chosen:
among the four gates, `test-quality` runs on every PR (no `paths` filter) and has no
history of runner failure. The other three remain advisory.

Every case where the gate cannot render a verdict is a job failure (while blocking):

1. A missing secret — "시크릿 부재 처리" (handle missing secret) raises `::error::` and fails.
2. A gate execution failure — the `unavailable` branch of "판정 반영" (apply verdict) (a Claude
   step failure or empty output).
3. 0 changed files — a deletion-only PR or an empty diff. "변경 파일 없음 처리" (handle no changed files)
   fails it (or just warns, if advisory). A deletion-only PR works around this with the
   `skip-ai-gate` label below.
4. Verdict-script exit 3 (a vacuous pass) always fails, regardless of `blocking`. exit
   2 (a format error) always fails on the claude-code runner, and falls into case 2's
   `unavailable` bucket on the generic-http runner.

The escape hatch is the `skip-ai-gate` label (the section below). This exception is
closed once the criterion is met and this section is updated with a measured acceptance
rate.

### The coverage promotion path (issue #247)

The `coverage (advisory)` job is a deterministic job, not an AI gate, so it does not
use the acceptance-rate criterion above. It is promoted in three stages:

1. **advisory (current)** — reports only the line/branch totals and the PR's diff
   coverage, in the job summary and the artifact. No `--fail-under`, not a required
   check. The report step is `if: always()`, so the report survives even when tests are
   red.
2. **Ratchet** — condition: the coverage job is green 10 runs in a row on `main`, and
   re-running the same commit gives the same total (confirming the figure is
   deterministic). At that point, add a
   `python3 -m coverage report --fail-under=<하한>` (`--fail-under=<floor>`)
   step to the coverage job. The floor is the minimum of those 10
   totals (the integer `coverage report --format=total` prints, line+branch combined).
   Raising the floor is always fine; lowering it only happens with a CHANGELOG
   `Changed` entry.
3. **Required** — once the ratchet runs with no false positive, drop `(advisory)` from
   the job name and add that name to `CHECKS` in `scripts/setup_branch_protection.sh`
   and to "Required status check candidates" below (a repo-settings task, the user's
   job).

Diff coverage is not a promotion target — its denominator is small per PR, so one
line flips the result. The numbers above (10 runs, an integer floor) are not observed in
this project but chosen values. They are updated with measured figures once the ratchet
stage begins.

## `ANTHROPIC_API_KEY` registration procedure and the OIDC alternative

### One of three credentials — an API key / an OAuth token / OIDC federation

`_ai-gate.yml` declares **both** `anthropic_api_key` and `claude_code_oauth_token`,
and the gate runs if **either one** is present. The "check secret presence" step judges
a skip only when both are empty, and logs which one was used to authenticate.

| Method | Secret name to register | Nature |
|---|---|---|
| API key | `ANTHROPIC_API_KEY` | Issued at console.anthropic.com. Billed by usage |
| OAuth token | `CLAUDE_CODE_OAUTH_TOKEN` | Issued via `claude setup-token`. Tied to a subscription |
| OIDC federation | (no static secret) | See the section below. Safest, since no credential is ever stored |

If both are registered, the API key takes priority.

**Never register it under the wrong name.** Registering an OAuth token under the
name `ANTHROPIC_API_KEY` makes the action pass that value as the `ANTHROPIC_API_KEY`
environment variable, but an OAuth token must go as `CLAUDE_CODE_OAUTH_TOKEN`, so
authentication fails.

### Registering the API key as a repository secret

This repo has `CLAUDE_CODE_OAUTH_TOKEN` registered (`gh secret list`, 2026-10-22).
When no secret is present, an AI gate prints
`SKIPPED: neither ANTHROPIC_API_KEY nor CLAUDE_CODE_OAUTH_TOKEN is configured` at the
"check secret presence" step of `_ai-gate.yml` and never runs.

**What matters is how the job ends at that point.** If ending the job quietly with
`success` just because the secret is missing, a green checkmark can no longer
distinguish "the AI looked and found no problem" from "the AI never ran at all" — the
very vacuous pass this whole plumbing exists to prevent happens inside the plumbing
itself. So the "시크릿 부재 처리" (handle missing secret) step handles this case with **the same
semantics** as the `unavailable` branch of `판정 반영` (apply verdict):

| `blocking` | Missing secret → |
|---|---|
| `false` (advisory — the 3 gates other than test-quality) | Leaves a `::warning::` annotation, job is green. The annotation states on screen "this green means it was never reviewed." Never blocks a merge |
| `true` (blocking — currently test-quality) | `::error::` + job failure |

The other two cases where the gate cannot render a verdict land on the same
outcome: a runner failure or empty output (the `unavailable` branch of "판정 반영" (apply
verdict)) and 0 changed files ("변경 파일 없음 처리" (handle no changed files) — a deletion-only PR or an empty diff; a
deletion-only PR goes through the `skip-ai-gate` label). advisory means warning + green,
blocking means error + failure.

The second row closes a hole in the promotion procedure. After a gate is promoted to
`blocking: true` and registered as a required status check, if the secret ever expires,
rotates, or is renamed, that required check would **pass silently forever** without this
branch — a state where a gate nobody is watching keeps approving merges.

The registration procedure (only the repo owner can do this — out of scope):

1. GitHub repository Settings → Secrets and variables → Actions.
2. `New repository secret` → name `ANTHROPIC_API_KEY` → enter the Anthropic API key
   value.
3. Confirm each gate workflow (owned by t4/t5) calls `_ai-gate.yml` with
   `secrets: anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}`.

### A recommended alternative: GitHub OIDC workload identity federation

Instead of a static key, if the Anthropic organization registers GitHub Actions as a
trusted issuer, the job exchanges GitHub's OIDC token for a short-lived Anthropic token
on every run — with no long-lived key stored, there is nothing left to leak or rotate.
`claude-code-action` supports this path via the `anthropic_federation_rule_id` +
`anthropic_organization_id` inputs (`anthropic_service_account_id`/
`anthropic_workspace_id` are optional).

The prerequisite is that organization setup on the Anthropic console side (issuing a
federation rule) must come first — this repo's workflow alone cannot turn it on (out of
scope). Once that is set up, as the comment left in the "Run Claude Code gate" step of
`_ai-gate.yml` says, delete the `anthropic_api_key` line, replace it with the two lines
`anthropic_federation_rule_id`/`anthropic_organization_id`, and add `id-token: write` to
the job's `permissions`.

### Registering the generic-http runner (an OpenAI-compatible endpoint)

The four jobs `rfc-conformance-generic-http`, `golden-approval-generic-http`,
`test-quality-generic-http`, `prose-factcheck-generic-http` run advisory alongside the
claude-code jobs on the same PR, but only when the repository variable
`AI_GATE_HTTP_BASE_URL` is registered. Before that, they show as `Skipped` checks, and
the existing four jobs behave exactly as before.

```
gh secret set AI_GATE_HTTP_API_KEY
gh variable set AI_GATE_HTTP_BASE_URL --body "https://api.example.com/v1"
gh variable set AI_GATE_HTTP_MODEL --body "<model-id>"
gh variable set AI_GATE_HTTP_API_STYLE --body "classic"   # 선택
```

- `AI_GATE_HTTP_BASE_URL` is the prefix up to, but not including, `/chat/completions`,
  and includes `/v1`. The runner appends `/chat/completions` itself.
- `AI_GATE_HTTP_API_STYLE`:
  - Empty or `classic` sends `max_tokens` (16384) and `temperature: 0`. Fits OpenAI
    gpt-4o/gpt-4.1 models and self-hosted vLLM/llama.cpp/Ollama servers.
  - `reasoning` sends `max_completion_tokens` (32768) and never sends temperature. For
    OpenAI o-series/gpt-5 models — these reject `max_tokens` and a non-default
    temperature with HTTP 400.
- If the variable exists but the secret is missing, it skips under the same `시크릿 부재 처리`
  (handle missing secret) rule as the Anthropic case (advisory: leaves `::warning::` and stays
  green; blocking: red).
- PR text: the runner sends the PR title/body and the merge-base..head commit messages
  to all four generic-http gates (rfc-conformance/golden-approval/test-quality/
  prose-factcheck) together, in a "--- PR text" block at the end of the user message. The
  workflow reads the title/body from the `GITHUB_EVENT_PATH` event file with jq. An empty
  body becomes `(empty)`, and no commits becomes `(none)`.
- Size budget: the diff is truncated at 200000 bytes, with a visible
  `[diff truncated at 200000 bytes]` line appended. PR text is truncated at 65536 bytes,
  with a `[pr text truncated at 65536 bytes]` line appended. Both ceilings were set
  against a 128k-token window, but tokens per byte vary by model and language, so a
  request that fills both ceilings can still exceed the 128k window. Exceeding the
  window fails with `error: http 400` and shows as `unavailable`.
- Key exposure:
  - A plaintext `http://` base URL sends the key unencrypted. Use `https://` unless the
    endpoint sits on a trusted private network. Redirects are never followed (a 3xx is a
    named failure), so the key never crosses to a different host.
  - The job runs the PR side's copy of `scripts/ai_gate_http_runner.py` together with
    the key. This creates no new exposure: a fork PR never reaches this job (forks are
    blocked), and anyone who can write to this same repo can already edit the workflow
    itself.

## Required status check candidates

As of 2026-10-23, branch protection on `main` is as follows (`gh api
repos/choiyounggi/linkly/branches/main/protection`): 6 required status checks
(`gate (py3.11)`, `gate (py3.12)`, `gate (py3.13)`, `lint (ruff)`,
`modeb-linux (test_repo_state under real mode B)`, `test-quality / gate`), `strict` on,
`enforce_admins: true`, force-push and deletion blocked, no
`required_pull_request_reviews`, `required_conversation_resolution: true`, and linear
history/block creations/lock/fork syncing off. That is, a merge is blocked if a
deterministic gate or the AI gate `test-quality` fails, and also blocked while an
unresolved review conversation remains. The other 3 AI gates never block a merge. The
candidates to register as required status checks are as follows — exactly the check-run
names GitHub actually produces (confirmed directly from the job `name:` fields in
`ci.yml`, not guessed. An AI gate's name is `<호출 잡> / gate` (`<calling job> / gate`)
because the job in `_ai-gate.yml` has no `name:`):

- `gate (py3.11)` / `gate (py3.12)` / `gate (py3.13)` / `gate (py3.14)` — the test
  matrix (`ci.yml`). `gate (py3.14)` is not in branch protection as of 2026-11-02 — add
  it to `CHECKS` in `scripts/setup_branch_protection.sh` and register it after its first
  green run (a repo-settings task, the user's job, issue #246)
- `lint (ruff)` — the ruff gate (`ci.yml`)
- `modeb-linux (test_repo_state under real mode B)` — the real mode B gate (`ci.yml`)
- `test-quality / gate` — the one promoted AI gate (the `test-quality` calling job in
  `ai-gates-quality.yml` + the job id `gate` in `_ai-gate.yml`)

RFC lint, the plugin reference drift check, the version sync check, and the doc
snippet compile gate are **not** separate check runs — they all run as steps of the one
`gate` job above, so GitHub never exposes them as independently addressable check runs.
An earlier version of this list mistook these step names for check-run names and listed
them that way — this table is the correction.

`modeb-linux (test_repo_state under real mode B)` was added to `ci.yml` by issue
#161. It is in the default list because a green run was observed on a GitHub-hosted
runner (`gh api repos/choiyounggi/linkly/commits/315d410/check-runs`, 2026-10-22:
`success`) and it is already set as required in live protection. `--include-modeb` is
kept only so old runbooks do not break; it changes nothing.

`scripts/setup_branch_protection.sh` exists as a script holding the desired payload
(idempotent). The payload is the live settings above plus `test-quality / gate` and
`required_conversation_resolution: true`, with `required_linear_history`,
`block_creations`, `lock_branch`, and `allow_fork_syncing` explicitly written at their
default (false). `--check` is read-only: it prints the payload, reads the live main
protection settings with one GET, and emits an `ok:`/`drift:` line per item plus a
`summary:` line. The expected result after the 2026-10-23 apply is `summary: 0 drift, 17
ok`. This script is never auto-run by CI or any orchestration task — applying it is
always a manual step through an explicit human/coordinator decision, done only after
`--check`, and only after the `test-quality / gate` check run has actually been observed
on the head of the PR carrying this change. A PR on a branch created before the change
reports the old check names, so it must merge `main` to satisfy the new required check.

Of the 4 AI gates, only `test-quality` is `blocking: true` and is listed above as
`test-quality / gate`. The other three (`rfc-conformance`, `golden-approval`,
`prose-factcheck`) are not registered as required while advisory — a required status
check by definition blocks a merge on failure, so registering one with an unverified
false-positive rate defeats the point of the advisory stage (not blocking merges while
measuring acceptance). Only a gate that has been flipped to `blocking: true` through the
promotion procedure above is added to this list.

Mutation testing (issue #166) is also absent from this list for the same reason —
the PR-facing `mutation-pr` job is advisory (non-required, genuinely red/green with no
`continue-on-error`), and the weekly `mutation-weekly` job only files SURVIVED mutations
as an issue and never blocks a PR. See "Mutation testing, two stages" below for
details.

The weekly load report (`load-weekly`, issue #195) is also absent from this list —
absolute figures vary by runner and cannot be used as a PR verdict, and this job never
even wakes on `pull_request`. Blocking a PR for a performance regression is the job of
the deterministic counter tests inside the `gate` job (see "Performance regression —
deterministic counters and the weekly load report" below).

### Why no required approvals

There is 1 collaborator (`gh api repos/choiyounggi/linkly/collaborators --jq
length` → 1, 2026-10-22), `enforce_admins: true` is set, and a PR's author cannot
approve their own PR ([GitHub
docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-pull-request-reviews-before-merging)).
So setting `required_approving_review_count: 1` would block every merge — not even the
admin is an exception. Instead, two things are kept: required conversation resolution
(`required_conversation_resolution`) and the `test-quality / gate` required check. This
does not substitute for human review — OpenSSF Scorecard's `Code-Review` check is
**not satisfied** under this substitute ([Scorecard
checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md): "Review by bots,
including bots powered by artificial intelligence / machine learning (AI/ML), do not
count as code review"). Scorecard itself also notes that requiring review is impossible
with only 1 active contributor. Revisit once a second collaborator exists.

## Mutation testing, two stages

`impl/tests/mutation_check.py` (77 mutations + a no-op control, a full run takes
25+ minutes) is left untouched (no semantic change, out of scope for issue #166), and
`.github/workflows/mutation.yml` wraps it in two branches:

- **`mutation-pr`** (PR-triggered, advisory, non-required): `scripts/mutation_scope_select.py`
  filters `mutation_check.MUTATIONS` down to only the entries whose anchor file
  intersects the PR's changed files, then calls the harness's own `main()` unchanged.
  `mutation_check.py` itself is not touched by even one line. This job never uses
  `continue-on-error` — a failure shows genuinely red, but since it is not on the
  required list, it never blocks a PR merge (see the section above).
- **`mutation-weekly`** (a weekly cron, all 77 kinds + the no-op control): captures the
  harness's rc, then parses stdout with `scripts/mutation_report.py`. Only a SURVIVED
  mutation (a rule with no test) is filed as a GitHub issue — this is not a failure but
  an "unverified rule" notice. Conversely, an unexplained nonzero rc from STALE (an
  anchor string drifted from the source), HANG (a timeout), or the no-op control
  tripping means the harness itself cannot render a verdict, so it **fails closed**,
  failing the job and skipping the issue update.

Both jobs reuse, unchanged, the pinned apt.llvm.org LLVM/MLIR toolchain install
sequence the `modeb-linux` job from issue #161 uses (the version derives from
`mlir/llvm.pin`, exporting `LNPL_LLVM_BIN`). `ci.yml` is not modified — this is a
separate workflow file.

A mutation-score threshold gate (e.g. "must catch ≥80% to pass") is an explicit
non-goal of this issue — SURVIVED is always a report, never a failure condition.

## Performance regression — deterministic counters and the weekly load report (issue #195)

Absolute throughput/latency figures vary with the runner's CPU and neighboring
jobs even for the same code. Blocking a PR on such figures would create failures
unrelated to the code, so the PR-blocking gate asserts only **deterministic counters**
that come out identically on every run:

- `impl/tests/test_perf_counters.py` counts what one request does — the number of
  DB connections created (`sqlite3.connect`), connections closed, storage statements
  (`execute`), and driver creations (`repository_factory` calls). It asserts exact
  values (`== 1`, etc.) on the sqlite path, the fake path, and the `build_app()` path,
  and also catches a request that never touched storage (0) as a failure. Since it is
  one module in the ordinary unittest suite, the `gate` job in `ci.yml` runs it as-is (no
  network, no docker).
- `DegradedDoubleControlTest` in the same file proves on every run that the counters
  actually see a regression, using a driver that opens one extra connection per
  statement (`_ConnectPerCallDriver`). Plugging that driver into the gate tests fails
  three tests with `1 != 3`/`1 != 2`.

For absolute figures, `.github/workflows/load-weekly.yml` leaves only a report,
once a week (Monday 07:00 UTC, also triggerable manually via `workflow_dispatch`):
the output of `scripts/load_probe.py` (including the `verdict=` line), measured with 2
gunicorn sync workers against the fake/sqlite backends at 50/100/200/400 rps, is posted
to the job summary and an artifact (`load-weekly-report`, retained 90 days). The job
never fails regardless of what was measured. Only a server that fails to start fails the
job as a harness defect — because that is "unable to measure," not "a measurement
result." A ceiling table measured on a single local machine is in
`docs/gunicorn-load-measurement.md`.

## The `skip-ai-gate` label

If a PR carries the `skip-ai-gate` label, the job itself in `_ai-gate.yml` is
skipped by `if:` (the whole job never runs — it is not just the verdict being bypassed).
A job skipped by `if:` runs not a single step, so it leaves no reason in the log — the
reason goes in the PR body.

This label is the **intended escape hatch** for the required check `test-quality /
gate`. When the job is skipped, the check run `test-quality / gate` ends as `skipped`,
and GitHub counts `skipped` as satisfying a required status check ("Required status
checks must have a successful, skipped, or neutral status" — [About protected
branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches),
confirmed 2026-10-22). That a skipped reusable job with no `name:` is still reported
under the same name is not in GitHub's documentation — it is measured on 4 public repos
(explained below the roster above) — confirm the real name with one labeled PR after
applying protection.

- **The label does not trigger a run.** `pull_request`'s default activity types are
  `opened`/`synchronize`/`reopened`
  ([docs](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)).
  After adding the label, a new commit must be pushed, or the PR closed and reopened,
  before the workflow runs again and reports `skipped`.
- **A deletion-only PR** (0 changed files) fails because a blocking gate cannot render a
  verdict ("변경 파일 없음 처리" / handle no changed files). It uses this label.
- **The label does not exist in the repo yet.** The coordinator creates it with `gh
  label create skip-ai-gate --repo choiyounggi/linkly` before applying protection.
- **A fork PR** is skipped by the job's `if:` (`head.repo.full_name ==
  github.repository`). It passes the required check through the same path (no AI
  review) — a fork PR is read and merged by a human.

Usage criterion: use it only when a merge is urgent and an AI gate is blocking it
(for a model issue, a timeout, an obvious false positive, etc.), or for a deletion-only
PR. It is not for bypassing a deterministic gate — this label is wired only into the job
condition of `_ai-gate.yml` and has no effect at all on the deterministic gates in
`ci.yml`. A PR carrying this label states its reason in the PR body (not mechanically
enforced).

