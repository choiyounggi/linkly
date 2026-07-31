"""Lexing and parsing: keyword-delimited blocks, no indentation semantics."""

import unittest

from lnpl.lexer import LexError, parse_duration_ms, tokenize
from lnpl.parser import ParseError, parse

MINIMAL = """
entity User
    field
        id UUID
"""


class TestLexer(unittest.TestCase):
    def test_indentation_carries_no_meaning(self):
        flat = tokenize("entity User\nfield\nid UUID\n")
        deep = tokenize("entity User\n        field\n                id UUID\n")
        self.assertEqual([l.tokens for l in flat], [l.tokens for l in deep])

    def test_comments_and_blank_lines_are_dropped(self):
        lines = tokenize("# header\n\nentity User   # trailing\n\n")
        self.assertEqual([l.tokens for l in lines], [["entity", "User"]])

    def test_tabs_are_rejected(self):
        with self.assertRaises(LexError):
            tokenize("entity User\n\tfield\n")

    def test_reserved_word_is_rejected(self):
        with self.assertRaises(LexError) as ctx:
            tokenize("workflow W\n    if ready\n")
        self.assertIn("reserved", str(ctx.exception))

    def test_duration_parsing(self):
        self.assertEqual(parse_duration_ms("3s"), 3000)
        self.assertEqual(parse_duration_ms("5m"), 300000)
        self.assertEqual(parse_duration_ms("50ms"), 50)

    def test_duration_boundary_rejects_bare_unit(self):
        with self.assertRaises(LexError):
            parse_duration_ms("ms")


class TestParser(unittest.TestCase):
    def test_top_level_keyword_closes_the_previous_block(self):
        decls = parse(MINIMAL + "service S\n    policy\n        retry 1\n")
        self.assertEqual([(d.kind, d.name) for d in decls],
                         [("entity", "User"), ("service", "S")])
        self.assertEqual(len(decls[0].clauses["field"]), 1)

    def test_event_source_is_parsed(self):
        decls = parse("event UserCreated on User create\n")
        self.assertEqual(decls[0].extra["on"], ("User", "create"))

    def test_event_source_trigger_must_be_in_the_enum(self):
        with self.assertRaises(ParseError) as ctx:
            parse("event UserCreated on User destroy\n")
        self.assertIn("create|update|delete", str(ctx.exception))

    def test_content_before_any_declaration_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse("    retry 3\n")
        self.assertIn("before any declaration", str(ctx.exception))

    def test_clause_not_allowed_by_the_declaration_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse("entity User\n    policy\n        retry 1\n")
        self.assertIn("only the `field` clause", str(ctx.exception))

    def test_declaration_without_a_name_is_rejected(self):
        with self.assertRaises(ParseError):
            parse("entity\n")

    def test_workflow_body_lines_need_no_clause(self):
        decls = parse("workflow Login\n    validate input\n    authenticate\n")
        self.assertEqual([l.tokens for l in decls[0].items],
                         [["validate", "input"], ["authenticate"]])


if __name__ == "__main__":
    unittest.main()
