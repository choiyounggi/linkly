# Contributing to linkly

Thank you for helping. This guide takes you from a fresh clone to a pull request, in the order the repository's checks expect.

## Before you start

- Read [AGENTS.md](AGENTS.md). It routes each kind of change (writing `.lnpl`, editing an RFC, running the mutation harness) to the skill that owns the rules for it. The skills live under `plugins/lnpl/skills/` and `plugins/lnpl-dev/skills/`.
- Report security problems privately as described in [SECURITY.md](SECURITY.md), never in a public issue.
- Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## 1. Set up and check your environment

You need Python 3.13 and an LLVM/MLIR toolchain. `scripts/dev_doctor.sh` checks both and prints a fix for anything missing.

Create a virtual environment inside your checkout and install linkly with the lint extra:

```bash
python3.13 -m venv .venv
.venv/bin/pip install '.[lint]'
```

macOS (Homebrew): install the toolchain with `brew install llvm`, then export these paths in every shell that runs the suite:

```bash
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
SDK="$(xcrun --show-sdk-path)"
export CPATH="$SDK/usr/include"
export LIBRARY_PATH="$SDK/usr/lib"
```

Linux: skip the block above. Install the `clang-<N>`, `mlir-<N>-tools` and `libmlir-<N>-dev` packages from [apt.llvm.org](https://apt.llvm.org/), where `<N>` is the major version in `mlir/llvm.pin`, and put them on your `PATH` with `export PATH="/usr/lib/llvm-<N>/bin:$PATH"`. The environment check looks for `mlir-opt`, `mlir-translate` and `clang` on `PATH`. Its install hints (`brew install python@3.13`, `brew install llvm`, `/opt/homebrew`) are written for macOS; on Linux, install the same tools with your package manager.

Then run the environment check:

```bash
bash scripts/dev_doctor.sh
```

Exit 0 means you are ready. Otherwise apply the fixes it prints and run it again. A missing prerequisite does not stop the suite; it shows up later as test failures that look like code regressions. The background is in [plugins/lnpl-dev/skills/lnpl-dev-env/SKILL.md](plugins/lnpl-dev/skills/lnpl-dev-env/SKILL.md).

If you work in several git worktrees, give each worktree its own `.venv` and call it by the relative path `.venv/bin/python`.

## 2. Run the test suite

From the repository root:

```bash
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl \
  2>&1 | grep -E "^(OK|FAILED|Ran )"
```

Read the summary through `grep`: tests print runtime traces to stdout, so the summary is buried if you only look at the last lines. After editing anything under `impl/lnpl/`, reinstall before running the suite again:

```bash
.venv/bin/pip install --force-reinstall --no-deps .
```

Run the suite once on your branch's starting point before you change anything. A change is ready when it adds no new failures to that result.

## 3. Change the language through an RFC

Language and toolchain behaviour is specified in [rfcs/](rfcs/). The process is defined in [rfcs/0007-rfc-process-v2.md](rfcs/0007-rfc-process-v2.md):

- A new behaviour starts as a new RFC with the next free number, written from the template in section 7 of RFC-0007.
- An Accepted RFC is never edited in place. Replace it with a new RFC that **Supersedes** it, or amend named sections with a new RFC that **Updates** it.
- Check every RFC change with the linter before you open a pull request:

```bash
.venv/bin/python scripts/rfc_lint.py
```

Breaking changes follow the compatibility policy in [docs/compatibility.md](docs/compatibility.md) and are announced under `Changed` in [CHANGELOG.md](CHANGELOG.md).

## 4. Pull request checklist

Before you open a pull request:

- [ ] `bash scripts/dev_doctor.sh` exits with status zero.
- [ ] The test suite adds no new failures compared with your starting point.
- [ ] New behaviour and bug fixes come with tests.
- [ ] A language change cites the RFC that specifies it.
- [ ] User-visible changes have an entry under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md).
- [ ] The deterministic checks CI runs pass locally:

```bash
.venv/bin/python scripts/rfc_lint.py
.venv/bin/python scripts/gen_plugin_references.py --check
.venv/bin/python scripts/check_version_sync.py
.venv/bin/python scripts/check_doc_snippets.py
.venv/bin/ruff check impl/lnpl scripts impl/tests
```

### What CI runs on your pull request

Deterministic gates: the test suite, `rfc_lint.py`, `gen_plugin_references.py --check`, `check_version_sync.py`, `check_doc_snippets.py`, and ruff.

AI gates review the pull request with a language model and report a schema-validated verdict:

- `rfc-conformance`: places where an RFC and the code disagree.
- `golden-approval`: whether a change to a golden scenario is justified.
- `test-quality`: tests that grade their own implementation, and passes that test nothing.
- `prose-factcheck`: claims in the pull request description or comments that the diff contradicts.

Which gates block a merge and which are advisory changes over time. [docs/CI-GATES.md](docs/CI-GATES.md) is the current roster and explains how to re-run a gate that failed to run.
