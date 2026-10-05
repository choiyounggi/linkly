"""Placement rules: where a clause may sit, and what a guard may own (issue #53).

Three silent failures shared one shape — the parser accepted the line, produced
no diagnostic, and dropped what the author wrote:

  N-1  `repeat` with two indented steps kept only the first inside the guard
  N-3  a `policy` clause in a workflow body swallowed every later line
  N-5  a workflow item written after `spec` disappeared the same way

Each is a placement error, so each is rejected here rather than lowered into
silence. The tests assert the error *type and its text* (a bare "it raises"
passes when the wrong rule fires), and every non-breaking case asserts the
surviving item count — "compiles" is not evidence that anything survived.
"""

import unittest

from lnpl.lexer import KEYWORDS_CLAUSE
from lnpl.parser import (CLAUSE_OWNER, WORKFLOW_CLAUSES, ParseError, parse)

HEAD = """
capability postgres

entity Order
    field
        id UUID
        qty Integer

service OrderService
    policy
        retry 3
"""


def workflow(body):
    """`HEAD` plus a workflow whose body is `body` (already indented)."""
    return HEAD + "\nworkflow Restock\n" + body


def only_workflow(decls):
    return [d for d in decls if d.kind == "workflow"][0]


class TestClauseOwnerTableIsComplete(unittest.TestCase):
    """The rejection reads `CLAUSE_OWNER[head]`, so a gap there is a crash.

    Adding a keyword to `KEYWORDS_CLAUSE` without giving it an owner would turn
    a clean "move it to the service" message into a KeyError on user input.
    """

    def test_every_non_workflow_clause_keyword_has_an_owner(self):
        needs_owner = [k for k in KEYWORDS_CLAUSE if k not in WORKFLOW_CLAUSES]
        self.assertTrue(needs_owner)
        self.assertEqual(sorted(needs_owner), sorted(CLAUSE_OWNER))

    def test_every_owner_is_a_declaration_that_takes_that_clause(self):
        self.assertEqual(set(CLAUSE_OWNER.values()), {"service", "entity"})


class TestWorkflowClauseAllowlist(unittest.TestCase):
    """N-3: a clause that belongs to another declaration must not parse here."""

    def test_service_clause_in_a_workflow_body_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    validate order\n"
                           "    policy\n"
                           "        retry 3\n"
                           "    notify order\n"))
        message = str(ctx.exception)
        self.assertIn("line 15", message)          # the `policy` line itself
        self.assertIn("policy", message)
        self.assertIn("service", message)          # where it belongs

    def test_every_service_clause_is_rejected_in_a_workflow(self):
        for clause in ("policy", "security", "performance", "database", "goal"):
            with self.subTest(clause=clause):
                with self.assertRaises(ParseError) as ctx:
                    parse(workflow("    validate order\n    %s\n" % clause))
                self.assertIn("service", str(ctx.exception))

    def test_entity_clause_in_a_workflow_body_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    validate order\n    field\n        id UUID\n"))
        self.assertIn("entity", str(ctx.exception))

    def test_spec_section_outside_a_spec_block_is_rejected(self):
        for clause in ("given", "when", "expect"):
            with self.subTest(clause=clause):
                with self.assertRaises(ParseError) as ctx:
                    parse(workflow("    validate order\n    %s\n        x\n" % clause))
                self.assertIn("spec", str(ctx.exception))

    # ---- non-breaking: the shapes that must keep working ----

    def test_a_service_level_policy_still_parses(self):
        decls = parse(workflow("    validate order\n    notify order\n"))
        service = [d for d in decls if d.kind == "service"][0]
        self.assertEqual(len(service.clauses["policy"]), 1)
        self.assertEqual(len(only_workflow(decls).items), 2)

    def test_a_workflow_spec_block_still_parses(self):
        decls = parse(workflow("    validate order\n"
                               "    spec\n"
                               "        given\n"
                               "            valid order\n"
                               "        expect\n"
                               "            completed\n"))
        wf = only_workflow(decls)
        self.assertEqual(len(wf.items), 1)
        self.assertEqual(len(wf.extra["specs"]), 1)
        self.assertEqual(len(wf.extra["specs"][0]["given"]), 1)

    # ---- boundaries ----

    def test_an_empty_workflow_body_is_accepted(self):
        decls = parse(workflow(""))
        self.assertEqual(only_workflow(decls).items, [])

    def test_a_workflow_whose_only_content_is_a_spec_block_is_accepted(self):
        decls = parse(workflow("    spec\n        given\n            valid order\n"))
        wf = only_workflow(decls)
        self.assertEqual(wf.items, [])
        self.assertEqual(len(wf.extra["specs"]), 1)

    def test_a_misplaced_clause_with_no_lines_under_it_is_still_rejected(self):
        """The empty case must not slip through: nothing follows to give it away."""
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    validate order\n    policy\n"))
        self.assertIn("service", str(ctx.exception))


class TestGuardLayout(unittest.TestCase):
    """N-1: a guard owns one item, so a second "indented" item is a lie.

    The two shapes are token-identical — `repeat 3 / read order / set …` either
    way — so the author's column is the only thing that separates "I meant both
    of these to repeat" from "I meant one to repeat and then this to run once".
    A deeper column that the structure does not honour is rejected.
    """

    def test_two_indented_steps_under_repeat_are_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    repeat 3\n"
                           "        validate order\n"
                           "        notify order\n"))
        message = str(ctx.exception)
        self.assertIn("line 16", message)      # the second step
        self.assertIn("repeat", message)
        self.assertIn("pipeline", message)     # the spelling that does work

    def test_the_same_trap_is_rejected_for_when_and_until(self):
        for mode in ("when order.qty > 0", "until order.qty > 0"):
            with self.subTest(mode=mode):
                with self.assertRaises(ParseError) as ctx:
                    parse(workflow("    %s\n"
                                   "        validate order\n"
                                   "        notify order\n" % mode))
                self.assertIn("pipeline", str(ctx.exception))

    def test_a_guard_indented_into_the_previous_guards_block_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    repeat 3\n"
                           "        validate order\n"
                           "        when order.qty > 0\n"
                           "        notify order\n"))
        self.assertIn("repeat", str(ctx.exception))

    def test_a_block_indented_into_the_guards_block_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    repeat 3\n"
                           "        validate order\n"
                           "        pipeline Later\n"
                           "            notify order\n"))
        self.assertIn("repeat", str(ctx.exception))

    # ---- non-breaking: the shapes that must keep working ----

    def test_a_single_step_repeat_at_the_guards_own_column_is_accepted(self):
        """`examples/guarded.lnpl` style: guard and its step share a column."""
        decls = parse(workflow("    repeat 3\n"
                               "    validate order\n"
                               "    notify order\n"))
        items = only_workflow(decls).items
        self.assertEqual([i["item"] for i in items], ["guard", "step"])
        self.assertEqual(items[0]["guard"]["mode"], "repeat")

    def test_one_indented_step_followed_by_a_dedented_step_is_accepted(self):
        decls = parse(workflow("    repeat 3\n"
                               "        validate order\n"
                               "    notify order\n"))
        items = only_workflow(decls).items
        self.assertEqual([i["item"] for i in items], ["guard", "step"])

    def test_a_guard_owning_a_pipeline_block_keeps_every_step(self):
        """The alternative the rejection points at — a guard over many steps."""
        decls = parse(workflow("    repeat 3\n"
                               "        pipeline Attempt\n"
                               "            validate order\n"
                               "            notify order\n"))
        items = only_workflow(decls).items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item"], "guard")
        block = items[0]["guarded"]["block"]
        self.assertEqual(block["type"], "pipeline")
        self.assertEqual(len(block["steps"]), 2)

    def test_a_guard_owning_a_parallel_block_is_accepted(self):
        decls = parse(workflow("    repeat 2\n"
                               "        parallel\n"
                               "            validate order\n"
                               "            notify order\n"
                               "        merge\n"))
        items = only_workflow(decls).items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["guarded"]["block"]["type"], "parallel")

    def test_a_later_guard_starts_a_fresh_layout_scope(self):
        decls = parse(workflow("    repeat 3\n"
                               "        validate order\n"
                               "    when order.qty > 0\n"
                               "        notify order\n"))
        items = only_workflow(decls).items
        self.assertEqual([i["item"] for i in items], ["guard", "guard"])

    # ---- boundaries ----

    def test_a_guard_that_owns_nothing_still_reports_that(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    validate order\n    repeat 3\n"))
        self.assertIn("guards nothing", str(ctx.exception))

    def test_zero_and_one_round_counts_are_accepted(self):
        for count in ("0", "1"):
            with self.subTest(count=count):
                decls = parse(workflow("    repeat %s\n        validate order\n" % count))
                items = only_workflow(decls).items
                self.assertEqual(items[0]["guard"]["arg"], count)

    def test_a_guarded_step_at_column_zero_is_accepted(self):
        decls = parse(HEAD + "\nworkflow Restock\nrepeat 3\nvalidate order\n"
                      "notify order\n")
        items = only_workflow(decls).items
        self.assertEqual([i["item"] for i in items], ["guard", "step"])


class TestPipelineGuardLayout(unittest.TestCase):
    """RFC-0060 (issue #211 (3)): a `pipeline` closes at the next control
    keyword, never by indentation — so a keyword written deeper than the open
    pipeline's own line looks nested but runs outside it.

    The two repairs differ by path, so each path's message is asserted on that
    path only: a guard can be re-homed in a new `pipeline`; a block opener is
    already a block and is only offered the dedent.
    """

    PIPELINE = "    pipeline place\n        validate order\n"

    def test_a_guard_indented_into_an_open_pipeline_is_rejected(self):
        for guard in ("when order.qty > 0", "until order.qty > 0", "repeat 3"):
            with self.subTest(guard=guard):
                with self.assertRaises(ParseError) as ctx:
                    parse(workflow(self.PIPELINE
                                   + "        notify order\n"
                                   + "        %s\n" % guard
                                   + "            notify order\n"))
                message = str(ctx.exception)
                self.assertIn("line 17", message)          # the guard line
                self.assertIn("`%s`" % guard.split()[0], message)
                self.assertIn("pipeline place", message)
                self.assertIn("Dedent it to the pipeline's own column", message)
                self.assertIn("wrap the following steps in a new `pipeline`",
                              message)

    def test_a_nested_block_opener_indented_into_an_open_pipeline_is_rejected(self):
        for opener in ("pipeline inner\n            notify order\n",
                       "parallel\n            notify order\n        merge\n"):
            with self.subTest(opener=opener.split("\n")[0]):
                with self.assertRaises(ParseError) as ctx:
                    parse(workflow(self.PIPELINE + "        " + opener))
                message = str(ctx.exception)
                self.assertIn("line 16", message)          # the opener line
                self.assertIn("pipeline place", message)
                self.assertIn("meant a new sibling block", message)
                self.assertNotIn("wrap the following steps", message)

    # ---- non-breaking ----

    def test_each_implicitly_closing_keyword_still_compiles_at_the_pipelines_own_column(self):
        for keyword, tail in (("when order.qty > 0", "        notify order\n"),
                              ("until order.qty > 0", "        notify order\n"),
                              ("repeat 3", "        notify order\n"),
                              ("pipeline second", "        notify order\n"),
                              ("parallel", "        notify order\n    merge\n")):
            with self.subTest(keyword=keyword):
                decls = parse(workflow(self.PIPELINE + "    %s\n" % keyword + tail))
                items = only_workflow(decls).items
                # a sibling of `pipeline place`, not swallowed into its steps
                self.assertEqual(len(items), 2)
                self.assertEqual(items[0]["item"], "block")
                self.assertEqual(len(items[0]["block"]["steps"]), 1)

    def test_a_flat_layout_pipeline_is_untouched(self):
        """Layout carries no signal when nothing is indented — stay out of it."""
        decls = parse(HEAD + "\nworkflow Restock\npipeline place\nvalidate order\n"
                      "when order.qty > 0\nnotify order\n")
        items = only_workflow(decls).items
        self.assertEqual([i["item"] for i in items], ["block", "guard"])

    # ---- boundaries ----

    def test_a_keyword_deeper_than_an_unnamed_pipeline_names_its_line(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    pipeline\n"
                           "        validate order\n"
                           "        when order.qty > 0\n"
                           "            notify order\n"))
        message = str(ctx.exception)
        self.assertIn("the `pipeline` opened on line 14", message)
        self.assertNotIn("pipeline None", message)

    def test_one_column_deeper_is_already_deeper(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow(self.PIPELINE + "     when order.qty > 0\n"
                                           "        notify order\n"))
        self.assertIn("pipeline place", str(ctx.exception))


class TestOtherwiseBranch(unittest.TestCase):
    """RFC-0062: `otherwise` on the line after a `when` guard's item owns
    exactly one item, as the guard's sibling — never a nested block.

    The parse tree carries it on the guard item itself (`item["otherwise"]`),
    so a guard with no `otherwise` keeps exactly the shape it had.
    """

    def test_otherwise_after_a_guarded_step_is_attached_to_that_guard(self):
        decls = parse(workflow("    when order.qty > 0\n"
                               "    validate order\n"
                               "    otherwise\n"
                               "    notify order\n"))
        items = only_workflow(decls).items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item"], "guard")
        self.assertEqual(items[0]["guarded"]["line"].tokens, ["validate", "order"])
        self.assertEqual(items[0]["otherwise"]["item"], "step")
        self.assertEqual(items[0]["otherwise"]["line"].tokens, ["notify", "order"])

    def test_otherwise_closes_a_guarded_pipeline_and_owns_the_next_item(self):
        decls = parse(workflow("    when order.qty > 0\n"
                               "    pipeline place\n"
                               "        validate order\n"
                               "        notify order\n"
                               "    otherwise\n"
                               "    notify order\n"
                               "    validate order\n"))
        items = only_workflow(decls).items
        self.assertEqual([i["item"] for i in items], ["guard", "step"])
        self.assertEqual(len(items[0]["guarded"]["block"]["steps"]), 2)
        self.assertEqual(items[0]["otherwise"]["line"].tokens, ["notify", "order"])

    def test_otherwise_can_own_a_block(self):
        decls = parse(workflow("    when order.qty > 0\n"
                               "    validate order\n"
                               "    otherwise\n"
                               "    parallel\n"
                               "        notify order\n"
                               "        validate order\n"
                               "    merge\n"))
        items = only_workflow(decls).items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["otherwise"]["block"]["type"], "parallel")
        self.assertEqual(len(items[0]["otherwise"]["block"]["steps"]), 2)

    def test_otherwise_after_a_guard_with_alternatives_is_accepted(self):
        decls = parse(workflow("    when order.qty > 10\n"
                               "    or order.qty < 0\n"
                               "    validate order\n"
                               "    otherwise\n"
                               "    notify order\n"))
        item = only_workflow(decls).items[0]
        self.assertEqual(item["guard"]["alternatives"], ["order.qty < 0"])
        self.assertEqual(item["otherwise"]["line"].tokens, ["notify", "order"])

    def test_a_guard_without_otherwise_carries_none(self):
        decls = parse(workflow("    when order.qty > 0\n"
                               "    validate order\n"
                               "    notify order\n"))
        items = only_workflow(decls).items
        self.assertEqual([i["item"] for i in items], ["guard", "step"])
        self.assertIsNone(items[0]["otherwise"])

    def test_no_parse_scratch_state_survives(self):
        decls = parse(workflow("    when order.qty > 0\n"
                               "    validate order\n"
                               "    otherwise\n"
                               "    notify order\n"))
        self.assertEqual(
            [k for k in only_workflow(decls).extra if k.startswith("_")], [])

    # ---- errors ----

    def test_otherwise_with_no_preceding_guard_is_rejected(self):
        for body in ("    otherwise\n    notify order\n",
                     # a plain step between the guard's item and `otherwise`
                     # ends the guard's reach
                     "    when order.qty > 0\n    validate order\n"
                     "    notify order\n    otherwise\n    notify order\n"):
            with self.subTest(body=body):
                with self.assertRaises(ParseError) as ctx:
                    parse(workflow(body))
                self.assertIn("no preceding guard", str(ctx.exception))

    def test_a_second_otherwise_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    when order.qty > 0\n"
                           "    validate order\n"
                           "    otherwise\n"
                           "    notify order\n"
                           "    otherwise\n"
                           "    validate order\n"))
        message = str(ctx.exception)
        self.assertIn("line 18", message)
        self.assertIn("a second `otherwise`", message)
        self.assertIn("line 16", message)            # the first one

    def test_two_otherwise_lines_back_to_back_are_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    when order.qty > 0\n"
                           "    validate order\n"
                           "    otherwise\n"
                           "    otherwise\n"
                           "    notify order\n"))
        self.assertIn("a second `otherwise`", str(ctx.exception))

    def test_otherwise_inside_parallel_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    when order.qty > 0\n"
                           "    parallel\n"
                           "        validate order\n"
                           "        otherwise\n"
                           "        notify order\n"
                           "    merge\n"))
        message = str(ctx.exception)
        self.assertIn("cannot appear inside a `parallel` block", message)
        self.assertIn("close it with `merge` first", message)

    def test_otherwise_after_until_or_repeat_is_rejected(self):
        for guard in ("until order.qty > 0", "repeat 3"):
            with self.subTest(guard=guard):
                with self.assertRaises(ParseError) as ctx:
                    parse(workflow("    %s\n" % guard
                                   + "    validate order\n"
                                   + "    otherwise\n"
                                   + "    notify order\n"))
                message = str(ctx.exception)
                self.assertIn("`%s` guard on line 14" % guard.split()[0], message)
                self.assertIn("only a `when` guard can own an `otherwise`", message)

    def test_otherwise_indented_into_an_open_pipeline_is_rejected(self):
        """Known-true-positive for RFC-0060's rule extended to `otherwise`."""
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    when order.qty > 0\n"
                           "    pipeline place\n"
                           "        validate order\n"
                           "        otherwise\n"
                           "        notify order\n"))
        message = str(ctx.exception)
        self.assertIn("runs outside the pipeline", message)
        self.assertIn("this `otherwise`", message)
        self.assertIn("wrap the following steps in a new `pipeline`", message)

    def test_otherwise_between_a_guard_and_its_item_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    when order.qty > 0\n"
                           "    validate order\n"
                           "    when order.qty > 5\n"
                           "    otherwise\n"
                           "    notify order\n"))
        message = str(ctx.exception)
        self.assertIn("guard on line 16", message)
        self.assertIn("has no item yet", message)

    def test_a_guard_cannot_be_the_item_otherwise_owns(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    when order.qty > 0\n"
                           "    validate order\n"
                           "    otherwise\n"
                           "    when order.qty > 5\n"
                           "    notify order\n"))
        self.assertIn("follows the `otherwise` on line 16", str(ctx.exception))

    def test_otherwise_takes_no_words(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    when order.qty > 0\n"
                           "    validate order\n"
                           "    otherwise notify order\n"))
        self.assertIn("`otherwise` takes no words", str(ctx.exception))

    # ---- boundaries ----

    def test_otherwise_that_owns_nothing_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    when order.qty > 0\n"
                           "    validate order\n"
                           "    otherwise\n"))
        self.assertIn("ends with an `otherwise` that owns nothing",
                      str(ctx.exception))

    def test_otherwise_deeper_than_its_guarded_step_is_rejected(self):
        """The guarded step sits deeper than its guard, so a deeper
        `otherwise` reads as inside the guard — `_check_guard_layout`'s rule."""
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    when order.qty > 0\n"
                           "        validate order\n"
                           "        otherwise\n"
                           "        notify order\n"))
        self.assertIn("indented as if it were inside the `when` guard",
                      str(ctx.exception))

    def test_otherwise_and_its_item_at_column_zero_are_accepted(self):
        decls = parse(HEAD + "\nworkflow Restock\nwhen order.qty > 0\n"
                      "validate order\notherwise\nnotify order\n")
        items = only_workflow(decls).items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["otherwise"]["line"].tokens, ["notify", "order"])


SPEC_BLOCK = ("    spec\n"
              "        given\n"
              "            valid order\n"
              "        when\n"
              "            restock\n"
              "        expect\n"
              "            completed\n")


class TestSpecIsLast(unittest.TestCase):
    """N-5: RFC-0002 puts workflow items before `spec` (WorkflowItem* SpecClause?).

    A step written after the block was absorbed into whichever section was open,
    so it never became a workflow item and never ran — the same silent drop as
    N-3, one clause further along.
    """

    def test_a_step_after_the_spec_block_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    validate order\n" + SPEC_BLOCK + "    notify order\n"))
        message = str(ctx.exception)
        self.assertIn("line 22", message)      # the `notify order` line
        self.assertIn("spec", message)

    def test_a_step_after_a_spec_block_with_only_one_section_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse(workflow("    validate order\n"
                           "    spec\n"
                           "        given\n"
                           "            valid order\n"
                           "    notify order\n"))
        self.assertIn("spec", str(ctx.exception))

    # ---- non-breaking ----

    def test_a_workflow_ending_in_a_spec_block_still_parses(self):
        decls = parse(workflow("    validate order\n" + SPEC_BLOCK))
        wf = only_workflow(decls)
        self.assertEqual(len(wf.items), 1)
        block = wf.extra["specs"][0]
        self.assertEqual([len(block[k]) for k in ("given", "when", "expect")],
                         [1, 1, 1])

    def test_two_spec_blocks_still_parse(self):
        decls = parse(workflow("    validate order\n" + SPEC_BLOCK + SPEC_BLOCK))
        self.assertEqual(len(only_workflow(decls).extra["specs"]), 2)

    def test_a_flat_layout_spec_block_is_untouched(self):
        """Layout carries no signal when nothing is indented — stay out of it."""
        decls = parse(HEAD + "\nworkflow Restock\nvalidate order\n"
                      "spec\ngiven\nvalid order\nwhen\nrestock\nexpect\ncompleted\n")
        wf = only_workflow(decls)
        self.assertEqual(len(wf.items), 1)
        self.assertEqual(len(wf.extra["specs"][0]["expect"]), 1)

    # ---- boundaries ----

    def test_an_empty_spec_block_is_left_to_the_spec_builder(self):
        decls = parse(workflow("    validate order\n    spec\n"))
        wf = only_workflow(decls)
        self.assertEqual(len(wf.extra["specs"]), 1)
        self.assertEqual(wf.extra["specs"][0]["given"], [])

    def test_a_deeply_indented_spec_section_line_is_still_content(self):
        decls = parse(workflow("    spec\n        given\n"
                               "                    valid order\n"))
        self.assertEqual(len(only_workflow(decls).extra["specs"][0]["given"]), 1)
