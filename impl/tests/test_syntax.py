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
        self.assertEqual([i["line"].tokens for i in decls[0].items],
                         [["validate", "input"], ["authenticate"]])

    def test_guard_owns_the_item_that_follows_it(self):
        decls = parse("workflow W\n    when profile missing\n    load user\n")
        item = decls[0].items[0]
        self.assertEqual(item["item"], "guard")
        self.assertEqual(item["guard"]["mode"], "when")
        self.assertEqual(item["guard"]["arg"], "profile missing")
        self.assertEqual(item["guarded"]["line"].tokens, ["load", "user"])

    def test_parallel_needs_merge(self):
        with self.assertRaises(ParseError) as ctx:
            parse("workflow W\n    parallel\n        read user\n")
        self.assertIn("merge", str(ctx.exception))

    def test_pipeline_closes_at_the_next_keyword_without_merge(self):
        decls = parse("workflow W\n    pipeline Enrich\n        read user\n"
                      "    when x exists\n    load user\n")
        kinds = [i["item"] for i in decls[0].items]
        self.assertEqual(kinds, ["block", "guard"])
        self.assertEqual(decls[0].items[0]["block"]["name"], "Enrich")

    def test_repeat_needs_an_integer(self):
        with self.assertRaises(ParseError):
            parse("workflow W\n    repeat often\n    load user\n")

    def test_guard_with_nothing_to_guard_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse("workflow W\n    when x exists\n")
        self.assertIn("guards nothing", str(ctx.exception))

    def test_chained_guards_are_rejected(self):
        """Issue #45 / t2 F-2: a guard owns exactly one step or block.

        Before this contract, the second `when` overwrote the first's pending
        guard, so `payment.amount > 0` vanished from the IR with no diagnostic
        and a 0-amount payment was approved. Chaining is now a parse error.
        """
        with self.assertRaises(ParseError) as ctx:
            parse("workflow W\n"
                  "    when payment.amount > 0\n"
                  "    when payment.amount <= 10000\n"
                  "    approve payment\n")
        msg = str(ctx.exception)
        self.assertIn("line 3", msg)      # the chaining guard
        self.assertIn("line 2", msg)      # the guard it would have dropped
        self.assertIn("chaining", msg)

    def test_chained_guards_of_mixed_modes_are_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse("workflow W\n"
                  "    when order.total > 0\n"
                  "    until order.total <= 10\n"
                  "    ship order\n")
        msg = str(ctx.exception)
        self.assertIn("until", msg)
        self.assertIn("line 2", msg)
        self.assertIn("chaining", msg)

    def test_two_guards_each_owning_a_step_still_parse(self):
        """Non-destructive: guard -> step -> guard -> step is unchanged."""
        decls = parse("workflow W\n"
                      "    when payment.amount > 0\n"
                      "    charge payment\n"
                      "    when payment.amount <= 10000\n"
                      "    approve payment\n")
        items = decls[0].items
        self.assertEqual([i["item"] for i in items], ["guard", "guard"])
        self.assertEqual([i["guard"]["arg"] for i in items],
                         ["payment.amount > 0", "payment.amount <= 10000"])
        self.assertEqual([i["guarded"]["line"].tokens for i in items],
                         [["charge", "payment"], ["approve", "payment"]])

    def test_boundary_single_guard_and_step_still_parses(self):
        decls = parse("workflow W\n    when x exists\n    load user\n")
        items = decls[0].items
        self.assertEqual([i["item"] for i in items], ["guard"])
        self.assertEqual(items[0]["guard"]["lineno"], 2)
        self.assertEqual(items[0]["guarded"]["line"].tokens, ["load", "user"])

    def test_blocks_do_not_nest(self):
        with self.assertRaises(ParseError) as ctx:
            parse("workflow W\n    parallel\n        read user\n"
                  "        pipeline P\n            load user\n")
        self.assertIn("nesting depth", str(ctx.exception))


REFINE = """
refine Slug of Text
    pattern ^[a-z0-9-]{1,64}$
    maxLength 64
"""


class TestRefineDecl(unittest.TestCase):
    """RefineDecl ::= 'refine' PascalName 'of' BaseTypeName EOL FacetLine+

    Facet lines sit directly under the declaration — `refine` has no clause
    keyword, so the parser treats the body the way it treats a workflow body.
    Facet *values* are not judged here; that is lowering's job.
    """

    def test_refine_declaration_parses(self):
        decls = parse(REFINE)
        self.assertEqual(len(decls), 1)
        d = decls[0]
        self.assertEqual(d.kind, "refine")
        self.assertEqual(d.name, "Slug")
        self.assertEqual(d.extra["base"], "Text")
        self.assertEqual([l.tokens for l in d.items],
                         [["pattern", "^[a-z0-9-]{1,64}$"], ["maxLength", "64"]])

    def test_refine_takes_no_clauses_dict(self):
        self.assertEqual(parse(REFINE)[0].clauses, {})

    def test_refine_and_entity_coexist(self):
        decls = parse(REFINE + "entity Link\n    field\n        slug Slug\n")
        self.assertEqual([d.kind for d in decls], ["refine", "entity"])
        # The entity's field line must not leak into the refine block's body.
        self.assertEqual(len(decls[0].items), 2)
        self.assertEqual([l.tokens for l in decls[1].clauses["field"]],
                         [["slug", "Slug"]])

    def test_field_line_is_still_two_tokens(self):
        decls = parse(REFINE + "entity Link\n    field\n        slug Slug\n")
        for line in decls[1].clauses["field"]:
            self.assertEqual(len(line.tokens), 2)

    def test_refine_is_a_top_level_keyword(self):
        # A `refine` line closes whatever block precedes it.
        decls = parse("entity Link\n    field\n        slug Text\n" + REFINE)
        self.assertEqual([d.kind for d in decls], ["entity", "refine"])

    def test_missing_of_is_a_parse_error(self):
        with self.assertRaises(ParseError) as ctx:
            parse("refine Slug Text\n    maxLength 64\n")
        self.assertIn("of <BaseType>", str(ctx.exception))

    def test_trailing_tokens_are_a_parse_error(self):
        with self.assertRaises(ParseError) as ctx:
            parse("refine Slug of Text Extra\n    maxLength 64\n")
        self.assertIn("of <BaseType>", str(ctx.exception))

    def test_refine_without_a_base_is_a_parse_error(self):
        with self.assertRaises(ParseError) as ctx:
            parse("refine Slug\n    maxLength 64\n")
        self.assertIn("of <BaseType>", str(ctx.exception))

    def test_refine_takes_no_clauses(self):
        with self.assertRaises(ParseError) as ctx:
            parse("refine Slug of Text\n    field\n")
        self.assertIn("takes no clauses", str(ctx.exception))

    def test_refine_without_a_name_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse("refine\n")
        self.assertIn("needs a name", str(ctx.exception))

    def test_refine_with_no_facet_lines_parses(self):
        # The parser cannot know the block is empty until it closes, so the
        # "at least one facet" rule (RFC-0001 A.7 ⓑ) belongs to lowering. This
        # test pins that contract: parsing succeeds, the body is empty.
        d = parse("refine Slug of Text\n")[0]
        self.assertEqual(d.items, [])
        self.assertEqual(d.extra["base"], "Text")

    def test_facet_values_are_not_judged_by_the_parser(self):
        d = parse("refine Slug of Bogus\n    maxLenght notanumber\n")[0]
        self.assertEqual(d.extra["base"], "Bogus")
        self.assertEqual([l.tokens for l in d.items], [["maxLenght", "notanumber"]])


class TestRegexTokenization(unittest.TestCase):
    """RFC-0002 §Full grammar: `Regex` excludes space/tab/`#` as a CONSEQUENCE of
    the lexer — tokens split on whitespace and `#` starts a comment. These tests
    pin what the lexer actually does with each, because the downstream error (or
    the lack of one) depends on the token count it produces.
    """

    def test_a_space_splits_the_pattern_into_three_tokens(self):
        self.assertEqual([l.tokens for l in tokenize("pattern ^a b$")],
                         [["pattern", "^a", "b$"]])

    def test_a_leading_hash_leaves_the_facet_with_no_value(self):
        self.assertEqual([l.tokens for l in tokenize("pattern #abc")],
                         [["pattern"]])

    def test_a_well_formed_pattern_is_one_token(self):
        self.assertEqual([l.tokens for l in tokenize("pattern ^[a-z0-9-]{1,64}$")],
                         [["pattern", "^[a-z0-9-]{1,64}$"]])

    def test_KNOWN_LIMITATION_mid_regex_hash_truncates_silently(self):
        """A `#` inside a regex yields a well-formed 2-token line, truncated.

        `^a#b$` becomes `^a` — the author's intent is silently widened. This is
        not a lexer bug: `#` is genuinely outside `Regex`'s alphabet per
        RFC-0002, so the comment rule is behaving as specified. It cannot be
        turned into a lex error without amending frozen Wave 1 lexer behavior.
        Lowering compiles the value, which catches truncations that break a
        construct (`^a[b#c]$` -> `^a[b`), but `^a` compiles and survives.
        Named so a reader sees a known limitation, not an accident.
        """
        self.assertEqual([l.tokens for l in tokenize("pattern ^a#b$")],
                         [["pattern", "^a"]])
        self.assertEqual([l.tokens for l in tokenize("pattern ^a[b#c]$")],
                         [["pattern", "^a[b"]])


if __name__ == "__main__":
    unittest.main()
