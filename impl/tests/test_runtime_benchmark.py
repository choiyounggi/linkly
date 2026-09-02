"""benchmarks/runtime/run.py — issue #164 runtime benchmark harness.

Loads run.py by path (importlib) and calls its pure `measure()` function
directly — never runs it as a subprocess (that would re-time an entire
Python startup, and re-write the committed results.json/REPORT.md as a
side effect of running tests). No absolute-time assertions: `seconds` is
a recorded artifact, not a test gate (brief constraint, D5).
"""
import importlib.util
import json
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN_PY = os.path.join(REPO, "benchmarks", "runtime", "run.py")
RESULTS_JSON = os.path.join(REPO, "benchmarks", "runtime", "results.json")


def load_run():
    spec = importlib.util.spec_from_file_location("runtime_bench_run", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MeasureFunctionTest(unittest.TestCase):
    def setUp(self):
        self.run = load_run()

    def test_measure_returns_the_three_key_shape(self):
        for operation in self.run.OPERATIONS:
            record = self.run.measure(operation, 5)
            self.assertEqual(set(record.keys()), {"operation", "n", "seconds"})
            self.assertIsInstance(record["seconds"], float)
            self.assertGreaterEqual(record["seconds"], 0)

    def test_n_zero_does_not_raise_and_returns_a_valid_record(self):
        for operation in self.run.OPERATIONS:
            record = self.run.measure(operation, 0)
            self.assertEqual(record["n"], 0)
            self.assertGreaterEqual(record["seconds"], 0)

    def test_unknown_operation_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.run.measure("nope", 5)


class CommittedResultsTest(unittest.TestCase):
    def test_results_json_covers_every_scale_and_operation(self):
        with open(RESULTS_JSON, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(set(doc.keys()), {"_generated", "measured_at", "results"})
        run = load_run()
        pairs = {(r["operation"], r["n"]) for r in doc["results"]}
        for n in run.N_SCALES:
            for operation in run.OPERATIONS:
                self.assertIn((operation, n), pairs,
                             "%s@n=%d missing from results.json" % (operation, n))
        # D4's explicit require: both pushdown and no-pushdown are present.
        self.assertIn(("list_where_pushdown", run.N_SCALES[0]), pairs)
        self.assertIn(("list_where_no_pushdown", run.N_SCALES[0]), pairs)


if __name__ == "__main__":
    unittest.main()
