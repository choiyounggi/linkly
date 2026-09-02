"""`lnpl grammar --format gbnf|json` — the closed-vocabulary grammar CLI (#162).

Mirrors `test_cli_vocab.py`'s structure: the only consumers are machines/
pipelines, so both formats print the identical content `impl/lnpl/grammar.py`
would return if called directly — there is no separate human-oriented view.
"""

import contextlib
import io
import json
import os
import unittest

from lnpl import cli
from lnpl.grammar import grammar_json_document

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA_JSON = os.path.join(REPO, "schemas", "lnpl-grammar.json")


def _main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _main_usage_error(argv):
    """Same, for argv argparse rejects before dispatch — it raises SystemExit."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(argv)
        except SystemExit as exc:
            return exc.code, out.getvalue(), err.getvalue()
    raise AssertionError("expected a usage error for %r" % (argv,))


class TestCliGrammar(unittest.TestCase):

    # ---- normal ---------------------------------------------------------

    def test_bare_form_defaults_to_json_and_prints_a_valid_document(self):
        rc, out, err = _main(["grammar"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        doc = json.loads(out)
        self.assertEqual(set(doc.keys()), {"_generated", "vocabulary"})

    def test_format_gbnf_prints_the_do_not_edit_banner(self):
        rc, out, err = _main(["grammar", "--format", "gbnf"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertTrue(out.startswith("# generated"))

    # ---- error / boundary -------------------------------------------------

    def test_an_unknown_format_is_a_usage_error(self):
        rc, _out, err = _main_usage_error(["grammar", "--format", "bogus"])
        self.assertEqual(rc, 2)
        self.assertIn("invalid choice", err)

    # ---- contract -----------------------------------------------------------

    def test_cli_output_matches_the_shared_source_function_exactly(self):
        # If cli.py ever hand-builds its own document instead of delegating
        # to grammar_json_document(), this is the one test that would catch it.
        _rc, out, _err = _main(["grammar", "--format", "json"])
        self.assertEqual(json.loads(out), grammar_json_document())

    def test_cli_output_matches_the_committed_schema_file(self):
        # Cross-checks task 03's committed `schemas/lnpl-grammar.json` without
        # re-deriving it — both must come from the same function.
        _rc, out, _err = _main(["grammar", "--format", "json"])
        with open(SCHEMA_JSON, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(json.loads(out), committed)


if __name__ == "__main__":
    unittest.main()
