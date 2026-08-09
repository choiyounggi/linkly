"""`Line.indent` — the source column a line starts at (issue #53).

The lexer strips indentation because RFC-0002 makes it non-structural, and that
stays true: `tokens` is unchanged, so the same token sequence still parses to the
same structure. What was missing is the *record* of how the author laid the line
out, which is the only evidence distinguishing "a step the author put inside a
guard" from "the next step" — the two are token-identical (N-1).

Recording is all this module does. `parser` is what reads the column, and only
to reject a layout that contradicts the structure it parsed.
"""

import unittest

from lnpl.lexer import LexError, tokenize


class TestLineIndent(unittest.TestCase):
    def test_indent_records_the_leading_space_count(self):
        lines = tokenize("workflow W\n    load user\n        deep step\n")
        self.assertEqual([l.indent for l in lines], [0, 4, 8])

    def test_tokens_are_unchanged_by_indentation(self):
        """RFC-0002 §Block structure: the token stream stays layout-independent."""
        flat = tokenize("entity User\nfield\nid UUID\n")
        deep = tokenize("entity User\n        field\n                id UUID\n")
        self.assertEqual([l.tokens for l in flat], [l.tokens for l in deep])
        self.assertEqual([l.indent for l in flat], [0, 0, 0])
        self.assertEqual([l.indent for l in deep], [0, 8, 16])

    def test_a_trailing_comment_does_not_change_the_indent(self):
        lines = tokenize("    load user   # why\n")
        self.assertEqual(lines[0].indent, 4)
        self.assertEqual(lines[0].tokens, ["load", "user"])

    def test_tabs_are_still_rejected(self):
        with self.assertRaises(LexError) as ctx:
            tokenize("workflow W\n\tload user\n")
        self.assertIn("tabs are forbidden", str(ctx.exception))

    # ---- boundaries ----

    def test_zero_indent_is_recorded_as_zero(self):
        lines = tokenize("entity User\n")
        self.assertEqual(lines[0].indent, 0)

    def test_blank_and_comment_only_lines_produce_no_line_at_all(self):
        lines = tokenize("\n   \n    # just a comment\nentity User\n")
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].indent, 0)

    def test_a_deeply_indented_comment_only_line_is_still_dropped(self):
        self.assertEqual(tokenize("        # note\n"), [])
