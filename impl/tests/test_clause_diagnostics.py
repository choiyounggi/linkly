"""issue #63: `outside any clause` names the valid clause set (no did-you-mean).

Exhaustive listing joins the compiler's existing pattern (type errors, workflow
id errors, spec `given` errors) rather than guessing at the typo. `workflow` is
excluded from the listing set: parser.py:300 unconditionally swallows every
workflow-body content line as a step before this error site is ever reached, so
there is no input that raises it in workflow context (verified live, see the
regression guard below) — issue #63's DoD item covering workflow listing was
premised on an unreachable path.
"""

import unittest

from lnpl.parser import SERVICE_CLAUSES, ENTITY_CLAUSES, ParseError, parse


class TestServiceContextListsItsClauses(unittest.TestCase):
    """issue #63 repro: a mistyped clause keyword under `service`."""

    def test_typo_lists_all_five_service_clauses(self):
        with self.assertRaises(ParseError) as ctx:
            parse("service S\n    polices\n        timeout 2s\n")
        message = str(ctx.exception)
        self.assertIn("line 2", message)
        self.assertIn("polices", message)
        for clause in SERVICE_CLAUSES:
            with self.subTest(clause=clause):
                self.assertIn(clause, message)


class TestEntityContextListsItsClauses(unittest.TestCase):
    def test_stray_line_lists_the_field_clause(self):
        with self.assertRaises(ParseError) as ctx:
            parse("entity E\n    stray line\n")
        message = str(ctx.exception)
        self.assertIn("line 2", message)
        for clause in ENTITY_CLAUSES:
            self.assertIn(clause, message)


class TestWorkflowBodyNeverReachesThisError(unittest.TestCase):
    """Regression guard: locks in the unreachability D1 relies on.

    If a future change to parser.py's workflow-item handling ever lets a
    content line fall through to the `outside any clause` site, this test
    starts failing — which is exactly the signal that the listing set must be
    revisited to include `workflow`.
    """

    def test_stray_looking_line_parses_as_a_workflow_step_without_error(self):
        decls = parse("workflow W\n    stray looking line\n")
        workflow = decls[0]
        self.assertEqual(workflow.kind, "workflow")
        self.assertEqual(len(workflow.items), 1)


class TestClauselessDeclarationsSayTheyTakeNone(unittest.TestCase):
    def test_event_stray_line_says_it_takes_no_clause_lines(self):
        with self.assertRaises(ParseError) as ctx:
            parse("event E on Foo create\n    stray line\n")
        message = str(ctx.exception)
        self.assertIn("takes no clause lines", message)
        self.assertNotIn("opens:", message)

    def test_capability_stray_line_says_it_takes_no_clause_lines(self):
        with self.assertRaises(ParseError) as ctx:
            parse("capability C\n    stray line\n")
        message = str(ctx.exception)
        self.assertIn("takes no clause lines", message)
        self.assertNotIn("opens:", message)


class TestRefineFacetLinesStillParse(unittest.TestCase):
    """refine's FacetLine+ sits directly under the declaration, clause-free
    (parser.py:304-309) — this error site must stay unreachable for it."""

    def test_facet_line_parses_without_error(self):
        decls = parse("refine PositiveInt of Int\n    min 1\n")
        refine = decls[0]
        self.assertEqual(refine.kind, "refine")
        self.assertEqual(len(refine.items), 1)


class TestTopLevelKeywordTypoIsUnchanged(unittest.TestCase):
    """A mistyped top-level keyword takes a different, pre-existing error path
    (line 241-243, before any declaration exists) — this task must not touch it."""

    def test_message_is_unchanged(self):
        with self.assertRaises(ParseError) as ctx:
            parse("servics S\n")
        self.assertEqual(
            str(ctx.exception),
            "line 1: 'servics' appears before any declaration")


if __name__ == "__main__":
    unittest.main()
