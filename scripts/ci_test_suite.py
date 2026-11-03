#!/usr/bin/env python3
"""Run impl/tests with the module set ci.yml's `gate` job runs (issue #247).

The coverage job wraps this with `coverage run`, which needs a script path, so
the gate step's stdin heredoc cannot be reused as-is. EXCLUDED and the file
rule must stay equal to the gate heredoc's; impl/tests/test_ci_test_suite.py
pins that parity.

    PYTHONPATH=impl python3 scripts/ci_test_suite.py

An empty selection exits 1: running zero tests is a broken runner, not a pass.
"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(REPO, "impl", "tests")
EXCLUDED = {"test_repo_state"}


def selected_modules(filenames, excluded=EXCLUDED):
    modules = []
    for fname in sorted(filenames):
        if not (fname.startswith("test_") and fname.endswith(".py")):
            continue
        module = fname[:-3]
        if module in excluded:
            continue
        modules.append(module)
    return modules


def main(tests_dir=TESTS_DIR):
    print("excluded from CI discovery: "
          + ", ".join("tests." + name for name in sorted(EXCLUDED)))
    modules = selected_modules(os.listdir(tests_dir))
    if not modules:
        print("ci_test_suite: 0 test modules under %s — nothing ran" % tests_dir)
        return 1
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for module in modules:
        suite.addTests(loader.loadTestsFromName("tests." + module))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
