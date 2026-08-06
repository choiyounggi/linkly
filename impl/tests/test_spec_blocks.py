"""Issue #46 [1]: N `spec` blocks in one workflow -> N independent cases.

The QA probe (t1 F-7, t2 F-10, t3 F-5, t4 F-4) measured that a second spec
block's given/when/expect lines were silently appended to the first block's,
producing one self-contradictory case (`completed` and `failed` coexisting).
These tests pin the repaired contract: one case per block, indexed names for
multi-block workflows, and an explicit ParseError for the within-block
repetition t3 hit.
"""

import unittest

from lnpl.parser import ParseError, parse
from lnpl.spec import SpecError, extract

THREE_BLOCKS = """
entity Item
    field
        id UUID
        amount Integer
service ItemService
    policy
        retry 3
workflow Place
    validate item
    create item
    spec
        given
            valid item
        when
            place
        expect
            completed
            steps 2
    spec
        given
            empty repository
        when
            place
        expect
            failed
            attempts 4
    spec
        given
            amount 0
        when
            place
        expect
            completed
"""

ONE_BLOCK = """
entity Item
    field
        id UUID
service ItemService
    policy
        retry 3
workflow Place
    validate item
    spec
        given
            valid item
        when
            place
        expect
            completed
"""


class TestMultipleBlocksAreIndependentCases(unittest.TestCase):
    def test_three_blocks_yield_three_cases(self):
        manifest = extract(parse(THREE_BLOCKS), "items")
        self.assertEqual(len(manifest["cases"]), 3)

    def test_each_case_keeps_only_its_own_sections(self):
        cases = extract(parse(THREE_BLOCKS), "items")["cases"]
        self.assertEqual(cases[0]["given"], ["valid item"])
        self.assertEqual(cases[0]["expect"], ["completed", "steps 2"])
        self.assertEqual(cases[1]["given"], ["empty repository"])
        self.assertEqual(cases[1]["expect"], ["failed", "attempts 4"])
        self.assertEqual(cases[2]["given"], ["amount 0"])
        self.assertEqual(cases[2]["expect"], ["completed"])

    def test_multi_block_cases_carry_indexed_names(self):
        cases = extract(parse(THREE_BLOCKS), "items")["cases"]
        self.assertEqual([c["name"] for c in cases],
                         ["Place spec 1", "Place spec 2", "Place spec 3"])

    def test_every_case_targets_the_same_workflow(self):
        cases = extract(parse(THREE_BLOCKS), "items")["cases"]
        self.assertEqual({c["workflow"] for c in cases}, {"wf.place"})


class TestSingleBlockShapeIsUnchanged(unittest.TestCase):
    """The committed golden manifests assert extract() byte-equality; a single
    block must keep its exact pre-#46 name and shape."""

    def test_single_block_name_has_no_index(self):
        cases = extract(parse(ONE_BLOCK), "items")["cases"]
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["name"], "Place spec")

    def test_workflow_without_a_spec_yields_no_case(self):
        src = ONE_BLOCK[: ONE_BLOCK.index("    spec")]
        self.assertEqual(extract(parse(src), "items")["cases"], [])

    def test_a_block_without_a_given_section_runs_on_defaults(self):
        # `given` is optional: the case runs on the sample payload alone.
        src = ONE_BLOCK.replace("        given\n            valid item\n", "")
        cases = extract(parse(src), "items")["cases"]
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["given"], [])


class TestWithinBlockRepetitionIsRefused(unittest.TestCase):
    """t3 F-5: two given/when/expect sets inside ONE spec block merged
    silently. The repair is an explicit ParseError, not a second merge."""

    def test_a_second_given_in_one_block_is_a_parse_error(self):
        src = ONE_BLOCK.replace(
            "        expect\n            completed\n",
            "        expect\n            completed\n"
            "        given\n            amount 0\n")
        with self.assertRaisesRegex(ParseError, "open a new"):
            parse(src)

    def test_a_second_expect_in_one_block_is_a_parse_error(self):
        src = ONE_BLOCK + "        expect\n            failed\n"
        with self.assertRaisesRegex(ParseError, "open a new"):
            parse(src)

    def test_a_new_block_resets_the_section_tracker(self):
        # given/when/expect may of course reappear in the NEXT block.
        self.assertEqual(len(extract(parse(THREE_BLOCKS), "items")["cases"]), 3)


class TestExistingGuardsSurvive(unittest.TestCase):
    def test_content_directly_under_spec_is_still_rejected(self):
        src = ONE_BLOCK.replace("    spec\n", "    spec\n        stray line\n")
        with self.assertRaises(SpecError) as ctx:
            extract(parse(src), "items")
        self.assertIn("takes no content lines", str(ctx.exception))

    def test_a_block_without_expect_is_still_rejected(self):
        src = THREE_BLOCKS[: THREE_BLOCKS.index("        expect\n            failed")]
        with self.assertRaises(SpecError) as ctx:
            extract(parse(src), "items")
        self.assertIn("`expect` section", str(ctx.exception))

    def test_sections_before_the_first_spec_block_are_refused(self):
        # Pre-#46 these lines were silently merged into the case; dropping
        # them silently now would be the same sin in the other direction.
        src = ONE_BLOCK.replace(
            "    spec\n",
            "    given\n        amount 0\n    spec\n")
        with self.assertRaises(SpecError) as ctx:
            extract(parse(src), "items")
        self.assertIn("before the first `spec` block", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
