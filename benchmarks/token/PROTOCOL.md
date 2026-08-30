# PROTOCOL — issue #142 token benchmark

Scope of this document: what was measured, how, and the two things this
benchmark deliberately does **not** do — call an LLM API, and report a real
pass@k number. Both are explicit follow-on work (user decision), not
oversights.

## Environment (bench-only venv — never the project's)

```bash
python3.13 -m venv benchmarks/token/.venv
benchmarks/token/.venv/bin/pip install tiktoken fastapi httpx pytest
```

`pyproject.toml` and `impl/` are untouched — `tiktoken`/`fastapi`/`httpx` are
fixtures for this benchmark only, never project dependencies (constraint in
`.orchestration/briefs/t142.md`).

## Tokenizer choice (D2)

Two public tiktoken encodings are reported side by side, plus a
tokenizer-independent fallback (character counts, with/without whitespace):

| Encoding | Current OpenAI model family | Source |
|---|---|---|
| `o200k_base` | `gpt-4o`, `gpt-4o-mini` | <https://github.com/openai/tiktoken>; encoding table in <https://developers.openai.com/cookbook/examples/how_to_count_tokens_with_tiktoken> |
| `cl100k_base` | `gpt-4`, `gpt-3.5-turbo`, text-embedding-ada-002 | same sources |

Both are widely-used, publicly documented encodings rather than a single
cherry-picked one, per the brief's "공개 토크나이저 기준, 사용 토크나이저
명기" requirement. `measure_tokens.py` records the exact `tiktoken` version
used (`tiktoken.__version__`) in its output — see REPORT.md.

Char counts (raw, and with whitespace stripped) are reported as a
tokenizer-independent cross-check, since tokenizer behavior can itself shift
between library versions.

## Source token measurement (D1, D3)

`measure_tokens.py` counts tokens for two files:

- `examples/linkhub.lnpl` (the golden LNPL scenario)
- `benchmarks/token/equiv/linkhub_fastapi.py` (the FastAPI port)

"Equivalent" is defined by `equiv/MAPPING.md` (entity fields, endpoints,
validation, cache TTL, retry policy — one row per correspondence) plus 3
ported `spec` blocks re-run as pytest cases (`tests/test_equiv_spec.py`):
SaveBookmark's normal + error case, and GetBookmark's boundary case. This is
**not** a claim of exhaustively verified behavioral equivalence — only these
3 scenarios are checked; see REPORT.md's limitations footnotes.

## Edit token measurement (D4)

Two fixed edit tasks, each applied independently to the same LNPL and
FastAPI baselines (`edits/<task>/{lnpl,fastapi}_{before,after}.{lnpl,py}`):

- **M1** — add a `note` field to `Bookmark` and thread it through the save
  path.
- **M2** — add a guard to `SaveBookmark` that rejects a duplicate save.
  (Result, verified via the real `lnpl` parser/interpreter: LNPL 0.6.0's
  grammar cannot express "reject only duplicates, allow new saves" — see
  `edits/m2_duplicate_guard/lnpl_after.lnpl`'s header comment and REPORT.md's
  limitations. The measurement is still reported, unfavorable as it is.)

`measure_tokens.py`'s `diff_lines()` takes each pair through
`difflib.unified_diff`, strips the `+++`/`---` file headers, and tokenizes
only the `+`/`-` content lines (not the diff markers themselves) — this is
the "added+삭제 라인의 토큰 수" the brief specifies (D4).

## pass@k harness (D5)

`passk/harness.py` implements the **unbiased pass@k estimator** from the
HumanEval reference implementation:

    pass@k := E_Problems[ 1 - C(n-c, k) / C(n, k) ]

evaluated in the numerically-stable product form (avoids overflow from
evaluating `C(n, k)` directly for large `n`):

    pass@k = 1 - prod_{i=n-c+1}^{n} (1 - k / i)

Source: `openai/human-eval` (<https://github.com/openai/human-eval>,
`human_eval/execution.py`'s `estimate_pass_at_k`); the estimator and its
motivation are also given as Eq. 1 in Chen et al. 2021, "Evaluating Large
Language Models Trained on Code" (<https://arxiv.org/pdf/2107.03374>). The reference
implementation notes there is "no unbiased way of estimating pass@k when
there are fewer samples than k" and skips those cases; `estimate_pass_at_k`
in this harness raises `ValueError` instead of silently returning a biased
number, so the failure is loud rather than a quietly wrong number.

The harness itself needs no LLM: `Generator` is an injected callable
`(Prompt, n) -> Sequence[str]`, and `Prompt.check` is a pure function over
generated text. `tests/test_passk_harness.py` proves the estimator and the
runner with stub generators (always-pass, always-fail, half-pass) across the
boundaries the brief specifies: `n == k`, `c == 0`, `c == n`, plus error
cases (`n < k`, `c > n`, a misbehaving generator).

### What real pass@k measurement would still need (out of scope here)

1. A concrete prompt set — one requirement + `check()` per LNPL vocabulary
   feature or FastAPI equivalent being exercised (this benchmark ships the
   plumbing, not the prompt set).
2. A `Generator` that actually calls an LLM API (`(Prompt, n) -> samples`) —
   deliberately not implemented; the brief's Out of scope explicitly
   excludes "실제 LLM API 호출·pass@k 수치 산출" as a user decision.
3. A sampling budget/temperature policy — the HumanEval paper samples with
   temperature > 0 specifically to get n independent draws per problem;
   choosing n, k, and temperature is a follow-on task, not this one.

## Reproducing REPORT.md's numbers

```bash
benchmarks/token/.venv/bin/python benchmarks/token/measure_tokens.py
```

Deterministic: two runs on an unchanged tree produce byte-identical stdout
(`tests/test_measure_tokens.py::test_two_runs_identical_stdout` pins this).
REPORT.md's tables are this output, pasted verbatim between the marked
BEGIN/END blocks — never hand-edited.
