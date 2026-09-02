"""`lnpl cost` — the operation cost-model contract CLI (#164).

Mirrors `test_cli_grammar.py`'s structure: a single JSON document, no
--format flag (cost_model_document() has only one shape), same shared
source function as SCHEMA_RENDERERS's "cost-model.json" entry.
"""

import contextlib
import io
import json
import os
import unittest

from lnpl import cli
from lnpl.cost_model import cost_model_document

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA_JSON = os.path.join(REPO, "schemas", "cost-model.json")


def _main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _main_usage_error(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(argv)
        except SystemExit as exc:
            return exc.code, out.getvalue(), err.getvalue()
    raise AssertionError("expected a usage error for %r" % (argv,))


class TestCliCost(unittest.TestCase):

    # ---- normal ---------------------------------------------------------

    def test_bare_form_prints_a_valid_document(self):
        rc, out, err = _main(["cost"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        doc = json.loads(out)
        self.assertEqual(set(doc.keys()), {"_generated", "cost_model"})

    # ---- contract ---------------------------------------------------------

    def test_cli_output_matches_the_shared_source_function_exactly(self):
        _rc, out, _err = _main(["cost"])
        self.assertEqual(json.loads(out), cost_model_document())

    def test_cli_output_matches_the_committed_schema_file(self):
        _rc, out, _err = _main(["cost"])
        with open(SCHEMA_JSON, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(json.loads(out), committed)

    # ---- error / boundary -------------------------------------------------

    def test_an_unknown_flag_is_a_usage_error(self):
        rc, _out, err = _main_usage_error(["cost", "--bogus"])
        self.assertEqual(rc, 2)
        self.assertIn("unrecognized arguments", err)


if __name__ == "__main__":
    unittest.main()
