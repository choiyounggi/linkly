"""A step noun outside the declared entity list is reported, not swallowed
(issue #91).

`_resolve_entity` is a closed-lexicon lookup over the module's declared
entities, and with exactly one entity declared it falls back to that sole
entity so a program may omit the object (R1's documented exception). The bug
#91 reports is that the same fallback fires when the object *was* given and
names nothing the module declares — a typo'd or renamed entity noun compiles
clean and the runtime then "finds" a phantom row for it.

This is the noun-axis sibling of `unknown-verb` (#36/#82): same closed-lexicon
shape, same silent-no-report failure mode, same fix — a `warning`-grade
diagnostic, with the runtime's phantom-seed resolution left exactly as it was
(issue #91 §4 — the diagnostic gates it at compile time; it does not remove
it).
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest

from lnpl import cli
from lnpl.lower import LowerError, lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_ROOT = os.path.join(REPO, ".claude", "tmp")


def run_cli_split(argv):
    """Drive `cli.main(argv)`, keeping stdout and stderr apart."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()

# The issue's own reproduction: one declared entity (`Customer`), two steps
# naming an undeclared noun (`user`).
ISSUE_REPRO = """
entity Customer
    field
        id UUID
        credit Integer

workflow Check
    find user
    update user
"""

ALL_KNOWN = """
entity Customer
    field
        id UUID
        credit Integer

workflow Check
    find customer
    update customer
"""

# Two declared entities: an unmatched object is ambiguous, not unknown-entity
# — `_resolve_entity`'s pre-existing ambiguity error is out of this issue's
# scope (#91 §4 only addresses the silent single-entity fallback).
TWO_ENTITIES_AMBIGUOUS = """
entity Customer
    field
        id UUID
entity Order
    field
        id UUID

workflow Check
    find user
"""

# The object may be omitted with exactly one entity declared — no diagnostic.
OMITTED_OBJECT = """
entity Customer
    field
        id UUID
        credit Integer

workflow Check
    authenticate
"""

# `input` (RFC-0015 §D6) is the reserved payload keyword, not an entity noun
# — `validate input` is the pervasive single-entity convention (every golden
# example uses it) and must never fire unknown-entity.
VALIDATE_INPUT_KEYWORD = """
entity Customer
    field
        id UUID
        credit Integer

workflow Check
    validate input
"""

# The object matches a declared FIELD name, not the entity name — resolved,
# not unknown (pre-existing `_resolve_entity` behaviour, unchanged).
FIELD_NAME_OBJECT = """
entity Customer
    field
        id UUID
        credit Integer

workflow Check
    validate credit
"""

REPEATED_UNKNOWN = """
entity Customer
    field
        id UUID
        credit Integer

workflow Check
    find user
    authenticate
    update user
"""


def compile_module(source, name="t"):
    return lower(parse(source), name)


class TestUnknownEntityIsReported(unittest.TestCase):
    def test_the_issue_repro_yields_one_diagnostic_per_step(self):
        mod = compile_module(ISSUE_REPRO)
        diags = mod.diagnostics.by_code("unknown-entity")
        self.assertEqual(len(diags), 2)
        self.assertEqual([d.subject for d in diags], ["user", "user"])
        self.assertEqual([d.severity for d in diags], ["warning", "warning"])
        # `find user` sits on line 8 of ISSUE_REPRO, `update user` on line 9.
        self.assertEqual([d.where for d in diags], ["line 8", "line 9"])
        self.assertEqual([d.line for d in diags], [8, 9])

    def test_the_message_names_the_whole_step_not_just_the_noun(self):
        mod = compile_module(ISSUE_REPRO)
        diag = mod.diagnostics.by_code("unknown-entity")[0]
        self.assertIn("find user", diag.message)

    def test_the_message_names_no_declared_entity_and_the_declared_set(self):
        mod = compile_module(ISSUE_REPRO)
        diag = mod.diagnostics.by_code("unknown-entity")[0]
        self.assertIn("'user' names no declared entity", diag.message)
        self.assertIn("declared: customer", diag.message)

    def test_the_step_still_resolves_the_phantom_entity(self):
        # #91 §4: the diagnostic gates it at compile time; the runtime
        # resolution (the single declared entity, unchanged) is untouched.
        doc = compile_module(ISSUE_REPRO).to_document()
        calls = [n for n in doc["nodes"] if n["kind"] == "RepositoryCall"]
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c["entity"] == "entity.customer" for c in calls))


class TestErrorPathsAreStillErrors(unittest.TestCase):
    def test_two_declared_entities_and_an_unmatched_object_still_raises(self):
        # Ambiguity across >1 declared entity is out of #91's scope — the
        # pre-existing hard error must not be downgraded to a warning.
        with self.assertRaises(LowerError) as cm:
            compile_module(TWO_ENTITIES_AMBIGUOUS)
        self.assertIn("does not say which entity it means", str(cm.exception))

    def test_no_entities_declared_at_all_still_raises(self):
        with self.assertRaises(LowerError):
            compile_module("workflow Check\n    validate input\n")


class TestBoundaries(unittest.TestCase):
    def test_a_module_with_no_unknown_entities_reports_nothing(self):
        mod = compile_module(ALL_KNOWN)
        self.assertEqual(mod.diagnostics.by_code("unknown-entity"), [])

    def test_an_omitted_object_with_one_entity_reports_nothing(self):
        mod = compile_module(OMITTED_OBJECT)
        self.assertEqual(mod.diagnostics.by_code("unknown-entity"), [])

    def test_the_input_keyword_reports_nothing(self):
        mod = compile_module(VALIDATE_INPUT_KEYWORD)
        self.assertEqual(mod.diagnostics.by_code("unknown-entity"), [])

    def test_an_object_matching_a_field_name_reports_nothing(self):
        mod = compile_module(FIELD_NAME_OBJECT)
        self.assertEqual(mod.diagnostics.by_code("unknown-entity"), [])

    def test_the_same_unknown_noun_twice_is_reported_twice(self):
        mod = compile_module(REPEATED_UNKNOWN)
        diags = mod.diagnostics.by_code("unknown-entity")
        self.assertEqual(len(diags), 2)
        self.assertEqual([d.where for d in diags], ["line 8", "line 10"])
        self.assertEqual(len(set(d.where for d in diags)), 2)


class TestDidYouMean(unittest.TestCase):
    """#91 §D3: a single declared entity is unconditionally the suggestion."""

    def test_a_single_declared_entity_is_unconditionally_suggested(self):
        diag = compile_module(ISSUE_REPRO).diagnostics.by_code("unknown-entity")[0]
        self.assertEqual(diag.suggestion, "customer")
        self.assertIn("did you mean 'customer'?", diag.message)


class TestLineIsStructured(unittest.TestCase):
    def test_the_diagnostic_carries_its_source_line_as_an_int(self):
        diag = compile_module(ISSUE_REPRO).diagnostics.by_code("unknown-entity")[0]
        self.assertEqual(diag.line, 8)
        self.assertEqual(diag.where, "line 8")


class TestStrictWarningGate(unittest.TestCase):
    """#91's own completion criterion: `--strict=warning` must gate it (rc != 0),
    exactly as it already does for `unknown-verb` (issue #62)."""

    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.tmpdir = tempfile.mkdtemp(dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.repro = os.path.join(self.tmpdir, "p7_rename.lnpl")
        with open(self.repro, "w", encoding="utf-8") as fh:
            fh.write(ISSUE_REPRO)

    def test_the_issue_repro_fails_the_strict_warning_gate(self):
        rc, _, err = run_cli_split(["compile", self.repro, "--strict=warning"])
        self.assertNotEqual(rc, 0)
        self.assertIn("unknown-entity", err)
        self.assertIn("user", err)

    def test_the_same_repro_still_compiles_rc_0_without_strict(self):
        # The diagnostic reports; it must not become a way to reject the
        # program outright (#91 §4 — the runtime phantom seed is unchanged).
        rc, _, err = run_cli_split(["compile", self.repro])
        self.assertEqual(rc, 0, err)
        self.assertIn("unknown-entity", err)


if __name__ == "__main__":
    unittest.main()
