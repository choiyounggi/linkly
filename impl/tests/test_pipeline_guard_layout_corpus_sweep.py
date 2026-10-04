"""RFC-0060 must reject nothing already shipped (issue #211 (3)).

The new rule rejects a control keyword indented deeper than the open
`pipeline` it implicitly closes. Every `.lnpl` the repo ships — examples, QA
cases, test fixtures, benchmarks — is parsed and checked for that rule's own
message; any hit means the rule would break shipped material.

Files that already fail to parse for an unrelated reason (QA probes that
document other placement errors) are recorded, not asserted on. A zero-hit
sweep proves nothing on its own — a wrong glob or a check that is never
reached also reports zero — so the same message is asserted on a known
violation (the issue's own repro).

The second corpus, fenced `lnpl` blocks in docs, is covered by running
`scripts/check_doc_snippets.py`, which compiles every one of them.
"""

import glob
import os
import subprocess
import sys
import unittest

from lnpl.lower import LowerError, lower
from lnpl.parser import ParseError, parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CORPUS = sorted(
    glob.glob(os.path.join(REPO, "examples", "*.lnpl"))
    + glob.glob(os.path.join(REPO, "qa", "**", "*.lnpl"), recursive=True)
    + glob.glob(os.path.join(REPO, "impl", "examples", "*.lnpl"))
    + glob.glob(os.path.join(REPO, "impl", "tests", "lnpl_fixtures", "**", "*.lnpl"),
                recursive=True)
    + glob.glob(os.path.join(REPO, "benchmarks", "**", "*.lnpl"), recursive=True)
)

RULE_MARK = "runs outside the pipeline"

# Issue #211 (3), verbatim apart from the declarations it needs to stand alone.
ISSUE_REPRO = """
capability postgres

entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer
        paid Integer

workflow PlaceOrder
    find product
    when product.stock >= input.quantity
    pipeline place
        create order as o
        call PaymentGateway as pay
        when pay.status == 200
            set o.paid to 1
        update order
"""


def _check(source):
    """Return the RFC-0060 message if `source` trips the rule, else None.

    Any other ParseError/LowerError is reported as the string "uncompiled".
    """
    try:
        lower(parse(source), "sweep")
    except ParseError as e:
        return str(e) if RULE_MARK in str(e) else "uncompiled"
    except LowerError:
        return "uncompiled"
    return None


def _sweep():
    """Check the whole corpus once; returns (clean, caught, uncompiled) paths."""
    clean, caught, uncompiled = [], [], []
    for path in CORPUS:
        with open(path, encoding="utf-8") as fh:
            outcome = _check(fh.read())
        if outcome is None:
            clean.append(path)
        elif outcome == "uncompiled":
            uncompiled.append(path)
        else:
            caught.append(path)
    return clean, caught, uncompiled


class TestCorpusSweep(unittest.TestCase):

    def test_the_corpus_is_not_trivially_empty(self):
        self.assertGreaterEqual(len(CORPUS), 30, CORPUS)

    def test_no_shipped_file_is_caught_by_this_rule(self):
        clean, caught, _uncompiled = _sweep()
        self.assertEqual(caught, [], "unexpected RFC-0060 rejection(s): %r" % caught)
        self.assertGreater(len(clean), 0)

    def test_the_sweep_catches_the_issue_repro(self):
        message = _check(ISSUE_REPRO)
        self.assertIsNotNone(message)
        self.assertIn(RULE_MARK, message)
        self.assertIn("pipeline place", message)
        # both repairs, on the guard path
        self.assertIn("Dedent it to the pipeline's own column", message)
        self.assertIn("wrap the following steps in a new `pipeline`", message)

    def test_the_repro_dedented_to_the_pipelines_column_compiles(self):
        fixed = ISSUE_REPRO.replace("        when pay.status == 200\n"
                                    "            set o.paid to 1\n"
                                    "        update order\n",
                                    "    when pay.status == 200\n"
                                    "    set o.paid to 1\n")
        self.assertNotEqual(fixed, ISSUE_REPRO)
        self.assertIsNone(_check(fixed))

    def test_doc_snippets_still_pass(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO, "scripts", "check_doc_snippets.py")],
            capture_output=True, text=True, cwd=REPO)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
