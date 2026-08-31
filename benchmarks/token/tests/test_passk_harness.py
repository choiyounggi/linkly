"""passk/harness.py unit tests (issue #142) — stub generators only, no LLM
API calls (see ../PROTOCOL.md). Pure stdlib (math, dataclasses), so unlike
test_equiv_spec.py / test_measure_tokens.py this file needs no venv skip.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "passk"))

from harness import (  # noqa: E402
    Prompt,
    estimate_pass_at_k,
    mean_pass_at_k,
    run_pass_at_k,
    run_prompt,
)


def always_pass_generator(prompt, n):
    return [f"sample-{i}" for i in range(n)]


def always_fail_generator(prompt, n):
    return [f"sample-{i}" for i in range(n)]


def half_pass_generator(prompt, n):
    return [f"sample-{i}" for i in range(n)]


class EstimatePassAtKTest(unittest.TestCase):
    def test_all_success_gives_pass_at_k_one(self):
        # c == n (boundary): every sample passed
        for n, k in [(5, 1), (5, 3), (5, 5), (10, 4)]:
            with self.subTest(n=n, k=k):
                self.assertEqual(estimate_pass_at_k(n=n, c=n, k=k), 1.0)

    def test_all_fail_gives_pass_at_k_zero(self):
        # c == 0 (boundary): no sample passed
        for n, k in [(5, 1), (5, 3), (5, 5), (10, 4)]:
            with self.subTest(n=n, k=k):
                self.assertEqual(estimate_pass_at_k(n=n, c=0, k=k), 0.0)

    def test_n_equals_k_boundary(self):
        # n == k (boundary): using every sample as the k attempts
        self.assertEqual(estimate_pass_at_k(n=5, c=1, k=5), 1.0)
        self.assertEqual(estimate_pass_at_k(n=5, c=0, k=5), 0.0)

    def test_matches_hand_computed_value(self):
        # n=10, c=5, k=3: 1 - C(5,3)/C(10,3) = 1 - 10/120 = 0.91666...
        expected = 1.0 - (math.comb(10 - 5, 3) / math.comb(10, 3))
        self.assertAlmostEqual(estimate_pass_at_k(n=10, c=5, k=3), expected, places=9)

    def test_raises_when_n_less_than_k(self):
        # error case: HumanEval's own estimator has no unbiased value here
        with self.assertRaises(ValueError):
            estimate_pass_at_k(n=2, c=1, k=5)

    def test_raises_when_c_greater_than_n(self):
        # error case: c cannot exceed n
        with self.assertRaises(ValueError):
            estimate_pass_at_k(n=3, c=5, k=1)

    def test_raises_on_negative_inputs(self):
        # error case: negative sample/pass/k counts are never valid
        with self.assertRaises(ValueError):
            estimate_pass_at_k(n=-1, c=0, k=1)


class RunPassAtKWithStubGeneratorsTest(unittest.TestCase):
    def setUp(self):
        self.prompt = Prompt(
            name="add-two-numbers",
            requirement="define add(a, b) that returns a + b",
            check=lambda sample: sample.startswith("sample-"),
        )

    def test_always_pass_generator_yields_pass_at_k_one(self):
        result = run_prompt(self.prompt, always_pass_generator, n=6)
        self.assertEqual((result.n, result.c), (6, 6))
        self.assertEqual(estimate_pass_at_k(result.n, result.c, k=3), 1.0)

    def test_always_fail_generator_yields_pass_at_k_zero(self):
        failing_prompt = Prompt(
            name="never-matches",
            requirement="define add(a, b) that returns a + b",
            check=lambda sample: False,
        )
        result = run_prompt(failing_prompt, always_fail_generator, n=6)
        self.assertEqual((result.n, result.c), (6, 0))
        self.assertEqual(estimate_pass_at_k(result.n, result.c, k=3), 0.0)

    def test_half_pass_generator_matches_hand_computed_value(self):
        half_prompt = Prompt(
            name="half-pass",
            requirement="define add(a, b) that returns a + b",
            check=lambda sample: int(sample.rsplit("-", 1)[1]) % 2 == 0,
        )
        result = run_prompt(half_prompt, half_pass_generator, n=10)
        self.assertEqual((result.n, result.c), (10, 5))
        expected = 1.0 - (math.comb(5, 3) / math.comb(10, 3))
        self.assertAlmostEqual(
            estimate_pass_at_k(result.n, result.c, k=3), expected, places=9
        )

    def test_run_prompt_rejects_zero_n(self):
        # error case: n must be positive
        with self.assertRaises(ValueError):
            run_prompt(self.prompt, always_pass_generator, n=0)

    def test_run_prompt_rejects_generator_with_wrong_sample_count(self):
        # error case: a misbehaving generator must fail loudly, not silently
        def short_generator(prompt, n):
            return ["only-one"]

        with self.assertRaises(ValueError):
            run_prompt(self.prompt, short_generator, n=5)

    def test_run_pass_at_k_and_mean_across_a_prompt_set(self):
        prompts = [
            self.prompt,
            Prompt(name="never-matches", requirement="x", check=lambda s: False),
        ]
        results = run_pass_at_k(prompts, always_pass_generator, n=4, k=2)
        self.assertEqual(len(results), 2)
        by_name = {r.prompt_name: r.value for r in results}
        self.assertEqual(by_name["add-two-numbers"], 1.0)
        self.assertEqual(by_name["never-matches"], 0.0)
        self.assertAlmostEqual(mean_pass_at_k(results), 0.5, places=9)

    def test_mean_pass_at_k_rejects_empty_results(self):
        # error case: mean of nothing is undefined, not silently 0
        with self.assertRaises(ValueError):
            mean_pass_at_k([])


if __name__ == "__main__":
    unittest.main()
