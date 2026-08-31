"""pass@k execution harness (issue #142) — no LLM API calls here.

Scope, per the task brief: build the harness + unbiased-estimator math and
prove it with stub generators. Actually calling an LLM API to produce real
pass@k numbers is out of scope (a follow-on, user-decided task) — see
../PROTOCOL.md.

Pieces, top to bottom:
  Prompt              — one requirement + a functional checker (no LLM code)
  Generator           — injected callable: (prompt, n) -> n candidate samples
  run_prompt          — functional-verification runner: samples -> (n, c)
  estimate_pass_at_k  — HumanEval's unbiased pass@k estimator (cited below)
  run_pass_at_k       — ties the three together across a prompt set

estimate_pass_at_k is the numerically-stable form from the HumanEval
reference implementation (openai/human-eval, human_eval/execution.py
`estimate_pass_at_k`; formula also given as Eq. 1 in Chen et al. 2021,
"Evaluating Large Language Models Trained on Code", arXiv:2107.03374):

    pass@k := E_Problems[ 1 - C(n-c, k) / C(n, k) ]

computed as 1 - prod_{i=n-c+1}^{n} (1 - k / i) to avoid the combinatorial
overflow of evaluating C(n, k) directly. The reference implementation notes
there is "no unbiased way of estimating pass@k when there are fewer samples
than k" — this harness raises instead of silently returning a biased number.
"""

import math
from dataclasses import dataclass
from typing import Callable, Iterable, List, Sequence


@dataclass(frozen=True)
class Prompt:
    """One pass@k evaluation prompt: a requirement plus its functional check.

    `check(sample)` must be a pure function over the generated text (e.g.
    "does this code define a function named `add` that returns a+b for a
    couple of cases") — it is the harness's only source of pass/fail, so it
    must not itself call an LLM.
    """

    name: str
    requirement: str
    check: Callable[[str], bool]


Generator = Callable[[Prompt, int], Sequence[str]]


def run_prompt(prompt: Prompt, generate: Generator, n: int) -> "PromptResult":
    """Functional-verification runner: draw n samples, count how many pass."""
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    samples = list(generate(prompt, n))
    if len(samples) != n:
        raise ValueError(
            f"generator for {prompt.name!r} returned {len(samples)} samples, "
            f"asked for n={n}"
        )
    c = sum(1 for sample in samples if prompt.check(sample))
    return PromptResult(prompt=prompt, n=n, c=c)


@dataclass(frozen=True)
class PromptResult:
    prompt: Prompt
    n: int
    c: int  # number of the n samples that passed prompt.check


def estimate_pass_at_k(n: int, c: int, k: int) -> float:
    """HumanEval's unbiased pass@k estimator — see module docstring for the
    formula and citation. Raises ValueError for n < k (no unbiased estimate
    exists there — human-eval's own script skips those cases rather than
    reporting a biased number; this harness makes that failure loud).
    """
    if n < 0 or c < 0 or k < 0:
        raise ValueError(f"n, c, k must be non-negative (got n={n}, c={c}, k={k})")
    if c > n:
        raise ValueError(f"c ({c}) cannot exceed n ({n})")
    if n < k:
        raise ValueError(f"cannot estimate pass@{k} from n={n} samples (need n >= k)")
    if n - c < k:
        return 1.0
    return 1.0 - math.prod(1.0 - k / i for i in range(n - c + 1, n + 1))


@dataclass(frozen=True)
class PassAtK:
    prompt_name: str
    n: int
    c: int
    k: int
    value: float


def run_pass_at_k(
    prompts: Iterable[Prompt], generate: Generator, n: int, k: int
) -> List[PassAtK]:
    """Run every prompt through `generate`, then estimate pass@k for each."""
    results = []
    for prompt in prompts:
        prompt_result = run_prompt(prompt, generate, n)
        value = estimate_pass_at_k(prompt_result.n, prompt_result.c, k)
        results.append(
            PassAtK(
                prompt_name=prompt.name,
                n=prompt_result.n,
                c=prompt_result.c,
                k=k,
                value=value,
            )
        )
    return results


def mean_pass_at_k(results: Sequence[PassAtK]) -> float:
    if not results:
        raise ValueError("mean_pass_at_k of an empty result set is undefined")
    return sum(r.value for r in results) / len(results)
