"""`lnpl vocab` / `lnpl vocab --json` — a vendor-neutral vocabulary manifest (#135).

The only channel the closed lexicon reached until now was Korean markdown in
the Claude Code plugin (`plugins/lnpl/skills/lnpl-authoring/references/`) —
no vendor-neutral machine channel existed. `vocabulary_document()`
(`impl/lnpl/vocab.py`) is the single source; this command is one of its three
consumers (CLI, MCP `lnpl_vocabulary`, `scripts/gen_plugin_references.py`).

Both the bare form and `--json` print the same stable JSON document — there is
no separate human-oriented view, since the only consumers are machines/LLMs.
"""

import contextlib
import io
import json
import unittest

from lnpl import cli
from lnpl.diagnostics import CODES
from lnpl.vocab import vocabulary_document

TOP_LEVEL_KEYS = {"lnpl_version", "verbs", "keywords", "types", "clauses",
                  "enforcement", "diagnostics", "reserved"}


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


def _no_nulls(value):
    """True if no `None` appears anywhere in this JSON-shaped value."""
    if value is None:
        return False
    if isinstance(value, dict):
        return all(_no_nulls(v) for v in value.values())
    if isinstance(value, list):
        return all(_no_nulls(v) for v in value)
    return True


class TestCliVocab(unittest.TestCase):

    # ---- normal ---------------------------------------------------------

    def test_json_flag_prints_a_valid_document_with_every_top_level_key(self):
        rc, out, err = _main(["vocab", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        doc = json.loads(out)
        self.assertEqual(set(doc.keys()), TOP_LEVEL_KEYS)

    def test_diagnostics_carries_all_18_codes_with_code_and_severity_only(self):
        rc, out, _err = _main(["vocab", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(len(doc["diagnostics"]), len(CODES))
        self.assertEqual(len(CODES), 18)
        for record in doc["diagnostics"]:
            self.assertEqual(set(record.keys()), {"code", "severity"})

    def test_bare_and_json_forms_print_the_identical_document(self):
        rc_bare, out_bare, _ = _main(["vocab"])
        rc_json, out_json, _ = _main(["vocab", "--json"])
        self.assertEqual(rc_bare, 0)
        self.assertEqual(rc_json, 0)
        self.assertEqual(json.loads(out_bare), json.loads(out_json))

    # ---- error / consistency --------------------------------------------

    def test_cli_output_matches_the_shared_source_function_exactly(self):
        # If cli.py ever hand-builds its own document instead of delegating to
        # vocabulary_document(), this is the one test that would catch it.
        _rc, out, _err = _main(["vocab", "--json"])
        self.assertEqual(json.loads(out), vocabulary_document())

    def test_an_unrelated_subcommand_does_not_have_a_vocab_flag(self):
        # `--json` is vocab's own flag; passing it to an unrelated subcommand
        # is an argparse usage error (rc 2), not silently ignored.
        rc, _out, err = _main_usage_error(["kb", "--json"])
        self.assertEqual(rc, 2)
        self.assertIn("unrecognized arguments", err)

    # ---- boundary ---------------------------------------------------------

    def test_empty_collections_are_arrays_or_objects_never_null(self):
        rc, out, _err = _main(["vocab", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertTrue(_no_nulls(doc), "the document must contain no null anywhere")

    def test_reserved_keywords_are_present_and_non_empty(self):
        rc, out, _err = _main(["vocab", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertIsInstance(doc["reserved"], list)
        self.assertGreater(len(doc["reserved"]), 0)


if __name__ == "__main__":
    unittest.main()
