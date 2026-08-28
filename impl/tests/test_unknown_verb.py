"""A verb outside VERB_LEXICON is reported, not swallowed (issue #36).

`_derive_effect` is a closed-lexicon lookup, and R1 (lower.py's own module
docstring) is right that an unknown verb must derive no Effect — guessing that
`generate token` means a NetworkCall would put an invention into the program's
meaning. The bug #36 reports is not R1: it is that "no Effect" was also spelled
"no report", so `generate token` / `audit login` / `return token` compiled into
steps that do nothing and said nothing.

So these tests pin both halves at once: the IR must stay exactly as it was (the
step keeps deriving no Effect, and the golden `.lir.json` files do not move),
*and* the compiler must now hand back one diagnostic per occurrence.
"""

import json
import os
import unittest

from lnpl.lower import LowerError, lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN_LNPL = os.path.join(REPO, "examples", "login.lnpl")
GOLDEN_IR = os.path.join(REPO, "examples", "login.lir.json")

# Every verb here is inside VERB_LEXICON.
ALL_KNOWN = """
entity User
    field
        id UUID
        email Email
workflow Login
    validate input
    authenticate
    cache user
"""

ONE_UNKNOWN = """
entity User
    field
        id UUID
        email Email
workflow Login
    validate input
    generate token
"""

ONLY_UNKNOWN = """
entity User
    field
        id UUID
        email Email
workflow Login
    generate token
"""

REPEATED_UNKNOWN = """
entity User
    field
        id UUID
        email Email
workflow Login
    generate token
    authenticate
    generate refresh
"""

# `validate` is in the lexicon, but it needs an entity in scope and this module
# declares none — lowering must still raise rather than degrade to a diagnostic.
KNOWN_VERB_THAT_CANNOT_LOWER = """
workflow Login
    validate input
"""

# RFC-0026: `persist` is a `VERB_ALIASES` entry (tier 1 — a semantic
# near-synonym of `create`; character-similarity alone would never surface
# `create` as `persist`'s closest VERB_LEXICON match).
SEMANTIC_ALIAS = """
entity User
    field
        id UUID
        email Email
workflow Login
    validate input
    persist token
"""

# `craete` is a spelling typo one edit away from `create` — tier 2
# (`difflib`, cutoff 0.6) catches it without an alias table entry.
SPELLING_TYPO = """
entity User
    field
        id UUID
        email Email
workflow Login
    validate input
    craete token
"""

# `zzz` is not close to any VERB_LEXICON verb by alias or by spelling.
NO_SUGGESTION = """
entity User
    field
        id UUID
        email Email
workflow Login
    validate input
    zzz token
"""


def compile_module(source, name="t"):
    return lower(parse(source), name)


class TestUnknownVerbIsReported(unittest.TestCase):
    def test_one_unknown_verb_yields_one_diagnostic(self):
        mod = compile_module(ONE_UNKNOWN)
        diags = mod.diagnostics.all()
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].code, "unknown-verb")
        self.assertEqual(diags[0].subject, "generate")
        self.assertEqual(diags[0].severity, "warning")
        # `generate token` sits on line 8 of ONE_UNKNOWN: the leading newline
        # makes `entity User` line 2, and `validate input` is line 7.
        self.assertEqual(diags[0].where, "line 8")

    def test_the_message_names_the_whole_step_not_just_the_verb(self):
        # The author needs to find the line; the verb alone appears many times.
        mod = compile_module(ONE_UNKNOWN)
        self.assertIn("generate token", mod.diagnostics.all()[0].message)

    def test_the_step_still_derives_no_effect(self):
        # R1 is preserved: reporting the verb must not invent an Effect for it.
        doc = compile_module(ONE_UNKNOWN).to_document()
        steps = [n for n in doc["nodes"] if n["kind"] == "WorkflowStep"]
        self.assertEqual([s["name"] for s in steps],
                         ["validate input", "generate token"])
        self.assertNotIn("children", steps[1])
        # ...while the known verb next to it still derives one.
        self.assertEqual(len(steps[0]["children"]), 1)

    def test_no_effect_node_is_emitted_for_the_unknown_verb(self):
        doc = compile_module(ONE_UNKNOWN).to_document()
        ids = [n["id"] for n in doc["nodes"]]
        self.assertNotIn("wf.login.step.2.authz", ids)
        self.assertEqual([i for i in ids if i.startswith("wf.login.step.2")],
                         ["wf.login.step.2"])


class TestGoldenScenario(unittest.TestCase):
    """`examples/login.lnpl` uses three verbs outside the lexicon."""

    def setUp(self):
        with open(GOLDEN_LNPL, encoding="utf-8") as fh:
            self.mod = lower(parse(fh.read()), "login")

    def test_reports_exactly_the_three_out_of_lexicon_verbs(self):
        subjects = sorted(d.subject
                          for d in self.mod.diagnostics.by_code("unknown-verb"))
        self.assertEqual(subjects, ["audit", "generate", "return"])

    def test_the_golden_ir_is_unchanged(self):
        # The diagnostic lives beside the document, never inside it: if this
        # fails, `examples/login.lir.json` would have to be regenerated and the
        # change has escaped its blast radius.
        with open(GOLDEN_IR, encoding="utf-8") as fh:
            committed = json.load(fh)
        # `provenance` (issue #136) is excluded from golden comparisons — its
        # digests are environment-dependent (docs/compatibility.md §2).
        compiled = self.mod.to_document()
        compiled.pop("provenance")
        self.assertEqual(compiled, committed)

    def test_the_golden_still_compiles_rather_than_failing(self):
        # #36 must not become a hard error: the charter's own golden scenario
        # would stop compiling.
        doc = self.mod.to_document()
        self.assertEqual(len([n for n in doc["nodes"]
                              if n["kind"] == "WorkflowStep"]), 6)


class TestErrorPathsAreStillErrors(unittest.TestCase):
    def test_a_known_verb_that_cannot_lower_still_raises(self):
        # A diagnostic must not become a way to swallow a real failure.
        with self.assertRaises(LowerError) as cm:
            compile_module(KNOWN_VERB_THAT_CANNOT_LOWER)
        self.assertIn("validate", str(cm.exception))

    def test_an_unknown_verb_does_not_rescue_an_otherwise_broken_module(self):
        source = """
entity User
    field
        id UUID
workflow Login
    generate token
    emit
"""
        # `emit` is in the lexicon and requires an object; the unknown verb
        # above it must not turn that into a warning.
        with self.assertRaises(LowerError) as cm:
            compile_module(source)
        self.assertIn("emit", str(cm.exception))


class TestBoundaries(unittest.TestCase):
    def test_a_module_with_no_unknown_verbs_reports_nothing(self):
        mod = compile_module(ALL_KNOWN)
        self.assertEqual(mod.diagnostics.by_code("unknown-verb"), [])

    def test_a_workflow_whose_only_step_is_unknown(self):
        mod = compile_module(ONLY_UNKNOWN)
        diags = mod.diagnostics.by_code("unknown-verb")
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].subject, "generate")
        # The workflow still exists and still owns that one step.
        doc = mod.to_document()
        wf = [n for n in doc["nodes"] if n["kind"] == "Workflow"][0]
        self.assertEqual(len(wf["children"]), 1)

    def test_the_same_unknown_verb_twice_is_reported_twice(self):
        # Two sites to fix; collapsing them would send the author back for a
        # second round after fixing the first.
        mod = compile_module(REPEATED_UNKNOWN)
        diags = mod.diagnostics.by_code("unknown-verb")
        self.assertEqual(len(diags), 2)
        self.assertEqual([d.subject for d in diags], ["generate", "generate"])
        self.assertEqual([d.where for d in diags], ["line 7", "line 9"])
        self.assertEqual(len(set(d.where for d in diags)), 2)


class TestLineIsStructured(unittest.TestCase):
    """RFC-0026 widens RFC-0024's `line` to `unknown-verb`."""

    def test_the_diagnostic_carries_its_source_line_as_an_int(self):
        diag = compile_module(ONE_UNKNOWN).diagnostics.by_code("unknown-verb")[0]
        self.assertEqual(diag.line, 8)
        # `where`'s pre-existing surface is unchanged (RFC-0026 §1).
        self.assertEqual(diag.where, "line 8")


class TestDidYouMean(unittest.TestCase):
    """RFC-0026: a two-tier suggestion — VERB_ALIASES first, difflib second."""

    def test_a_semantic_alias_suggests_its_lexicon_verb(self):
        diag = compile_module(SEMANTIC_ALIAS).diagnostics.by_code("unknown-verb")[0]
        self.assertEqual(diag.suggestion, "create")
        self.assertIn("did you mean 'create'?", diag.message)

    def test_a_spelling_typo_suggests_its_closest_lexicon_verb(self):
        diag = compile_module(SPELLING_TYPO).diagnostics.by_code("unknown-verb")[0]
        self.assertEqual(diag.suggestion, "create")
        self.assertIn("did you mean 'create'?", diag.message)

    def test_an_unrelated_word_gets_no_suggestion(self):
        diag = compile_module(NO_SUGGESTION).diagnostics.by_code("unknown-verb")[0]
        self.assertIsNone(diag.suggestion)
        self.assertNotIn("did you mean", diag.message)


if __name__ == "__main__":
    unittest.main()
