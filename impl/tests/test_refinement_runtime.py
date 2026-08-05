"""Runtime enforcement of semantic type refinements (issue #31, Wave 3).

Wave 1 froze the notation (RFC-0001 부록 A.6) and Wave 2 made the compiler emit a
`Refinement` node per refinement in use. This module covers what the *interpreter*
does with those nodes: a refinement-typed value must satisfy its base type's own
rule AND every facet, and a derived fixture must never hold a value that fails
the very validation it exists to satisfy.

Refinements are read from the running document's `Refinement` nodes, never from
`refinements.PRESETS` — a built-in preset a field uses is already emitted into the
document as a structurally identical node (A.6.4), while a user-declared `refine`
exists only there. Every test below therefore lowers its own module inline and
owns the resulting index.
"""

import json
import os
import shutil
import unittest
from argparse import Namespace

from lnpl import cli
from lnpl.interp import (Interpreter, RunError, check_semantic_type,
                         refinement_index, sample_for_type, sample_payload)
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import _payload_from_given

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# One declaration per facet, all six of the closed vocabulary (A.6.3). None of
# these names is a built-in preset: the registry has never heard of `Short`,
# `Tiny`, `Code`, `Score` or `Status`, so enforcing them proves user-declared
# refinements take the same path presets do.
FACETS = """
refine Short of Text
    minLength 3
refine Tiny of Text
    maxLength 2
refine Code of Text
    pattern ^[A-Z]{3}$
refine Score of Integer
    min 1
    max 10
refine Status of Text
    enum draft live
entity Thing
    field
        id UUID
"""

# The shortener probe: `Slug` and `URL` are built-in presets, so lowering emits
# their Refinement nodes on use (A.6.4 emit-on-use). `validate slug` copies the
# field's type name into `Validation.rule`, which is the interpreter's input.
SHORTENER = """
capability postgres
entity Link
    field
        id UUID
        slug Slug
        target URL
service ShortenService
    policy
        retry 0
workflow Shorten
    validate slug
    create link
"""

UUID_SAMPLE = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


# Five refinements plus three plain base fields — eight fields the derived
# fixture has to cover. `Code`'s pattern is satisfied by no base sample but by
# `Currency`'s "USD", which is why the candidate ladder consults the registry's
# other string samples rather than only the field's own base sample.
EVERY_SHAPE = """
refine Short of Text
    minLength 3
refine Code of Text
    pattern ^[A-Z]{3}$
refine Score of Integer
    min 1
    max 10
refine Status of Text
    enum draft live
refine Price of Decimal
    min 1
entity Thing
    field
        id UUID
        name Text
        count Integer
        short Short
        code Code
        score Score
        status Status
        price Price
"""


def ir(src):
    return lower(parse(src), "m").to_document()


def refs(src):
    return refinement_index(ir(src))


def entities(doc):
    return [n for n in doc["nodes"] if n["kind"] == "Entity"]


def fixture(src):
    """The derived fixture for `src`, plus the document it came from."""
    doc = ir(src)
    return doc, sample_payload(entities(doc), refinement_index(doc))


class TestFacetEnforcement(unittest.TestCase):
    """Each of the six facets: one value that passes, one that fails.

    The failing cases assert the exception type AND the message fragment that
    names the offending facet — the whole point of refinements is a diagnostic
    more precise than "invalid".
    """

    def setUp(self):
        self.refs = refs(FACETS)

    # ---- minLength ----
    def test_minlength_accepts_a_long_enough_value(self):
        check_semantic_type("Short", "abc", "s", self.refs)   # must not raise

    def test_minlength_rejects_a_short_value(self):
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Short", "ab", "s", self.refs)
        self.assertIn("minLength", str(ctx.exception))
        self.assertIn("'s'", str(ctx.exception))

    # ---- maxLength ----
    def test_maxlength_accepts_a_short_enough_value(self):
        check_semantic_type("Tiny", "ab", "t", self.refs)

    def test_maxlength_rejects_a_long_value(self):
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Tiny", "abc", "t", self.refs)
        self.assertIn("maxLength", str(ctx.exception))

    # ---- pattern ----
    def test_pattern_accepts_a_matching_value(self):
        check_semantic_type("Code", "ABC", "c", self.refs)

    def test_pattern_rejects_a_non_matching_value(self):
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Code", "abc", "c", self.refs)
        self.assertIn("pattern", str(ctx.exception))

    # ---- min ----
    def test_min_accepts_a_value_at_the_limit(self):
        check_semantic_type("Score", 1, "n", self.refs)

    def test_min_rejects_a_value_below_the_limit(self):
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Score", 0, "n", self.refs)
        self.assertIn("min 1", str(ctx.exception))

    # ---- max ----
    def test_max_accepts_a_value_at_the_limit(self):
        check_semantic_type("Score", 10, "n", self.refs)

    def test_max_rejects_a_value_above_the_limit(self):
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Score", 11, "n", self.refs)
        self.assertIn("max 10", str(ctx.exception))

    # ---- enum ----
    def test_enum_accepts_a_declared_member(self):
        check_semantic_type("Status", "draft", "st", self.refs)
        check_semantic_type("Status", "live", "st", self.refs)

    def test_enum_rejects_an_undeclared_value(self):
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Status", "archived", "st", self.refs)
        self.assertIn("enum", str(ctx.exception))


class TestBaseRuleStillApplies(unittest.TestCase):
    """A refinement STRENGTHENS its base; it never replaces the base's rule."""

    def setUp(self):
        self.refs = refs(FACETS)

    def test_text_refinement_rejects_a_non_string(self):
        # `Text`'s own rule is ("py", str). 12345 is long enough for minLength 3
        # if you only looked at str(value) — the base rule has to fire first.
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Short", 12345, "s", self.refs)
        self.assertIn("not a valid Text", str(ctx.exception))

    def test_integer_refinement_rejects_a_bool(self):
        # `Integer`'s rule excludes bool. True would satisfy `min 1` numerically.
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Score", True, "n", self.refs)
        self.assertIn("not a valid Integer", str(ctx.exception))

    def test_a_value_passing_the_base_still_fails_a_facet(self):
        # The converse: a perfectly good Text that the facet rejects.
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Code", "not-a-code", "c", self.refs)
        self.assertIn("pattern", str(ctx.exception))


class TestPresetAndDeclarationTakeTheSamePath(unittest.TestCase):
    """A built-in preset is not privileged (A.6.4): the same code enforces both."""

    def test_preset_slug_is_enforced(self):
        # Regression for the measured defect: this returned None (passed) before.
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Slug", "NOT A SLUG!!", "slug", refs(SHORTENER))
        self.assertIn("pattern", str(ctx.exception))

    def test_preset_url_is_enforced(self):
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("URL", "nope", "target", refs(SHORTENER))
        self.assertIn("pattern", str(ctx.exception))

    def test_declared_refinement_is_enforced_identically(self):
        # Same facets as the `Slug` preset under a name the registry never heard
        # of. If presets had a privileged path, only one of these two would fail.
        declared = refs("""
refine Handle of Text
    pattern ^[a-z0-9-]{1,64}$
    maxLength 64
entity Thing
    field
        id UUID
""")
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Handle", "NOT A SLUG!!", "h", declared)
        self.assertIn("pattern", str(ctx.exception))

    def test_a_valid_value_passes_under_both_names(self):
        declared = refs("""
refine Handle of Text
    pattern ^[a-z0-9-]{1,64}$
    maxLength 64
entity Thing
    field
        id UUID
""")
        check_semantic_type("Slug", "ok-slug", "slug", refs(SHORTENER))
        check_semantic_type("Handle", "ok-slug", "h", declared)


class TestRefinementIndex(unittest.TestCase):
    """`refinement_index(document)` is the one runtime resolution point."""

    def test_index_carries_base_and_facets_for_a_preset(self):
        self.assertEqual(refs(SHORTENER)["Slug"],
                         {"base": "Text",
                          "facets": {"pattern": "^[a-z0-9-]{1,64}$",
                                     "maxLength": 64}})

    def test_index_covers_declared_refinements_the_registry_never_heard_of(self):
        self.assertEqual(set(refs(FACETS)),
                         {"Short", "Tiny", "Code", "Score", "Status"})

    def test_a_module_with_no_refinements_yields_an_empty_index(self):
        empty = refs("""
entity Thing
    field
        id UUID
""")
        self.assertEqual(empty, {})

    def test_index_of_a_document_without_nodes_is_empty(self):
        self.assertEqual(refinement_index({}), {})


class TestValidationRuleAtRuntime(unittest.TestCase):
    """`Validation.rule` carries the refinement's name; the run must honour it."""

    def _run(self, payload, src=SHORTENER, workflow="wf.shorten"):
        doc = ir(src)
        interp = Interpreter(doc, repo_rows={})
        return interp, interp.run_workflow(workflow, payload)

    def test_bad_slug_fails_the_validate_step(self):
        _, result = self._run({"id": UUID_SAMPLE, "slug": "NOT A SLUG!!",
                               "target": "https://example.com/a"})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "validate slug")

    def test_good_slug_passes_the_validate_step(self):
        _, result = self._run({"id": UUID_SAMPLE, "slug": "ok-slug",
                               "target": "https://example.com/a"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate slug", "create link"])

    def test_validate_input_applies_refinements_to_every_field(self):
        src = SHORTENER.replace("    validate slug\n", "    validate input\n")
        _, result = self._run({"id": UUID_SAMPLE, "slug": "NOT A SLUG!!",
                               "target": "https://example.com/a"}, src=src)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "validate input")

    def test_validate_input_passes_when_every_refined_field_is_valid(self):
        src = SHORTENER.replace("    validate slug\n", "    validate input\n")
        _, result = self._run({"id": UUID_SAMPLE, "slug": "ok-slug",
                               "target": "https://example.com/a"}, src=src)
        self.assertEqual(result["status"], "completed")


class TestRefinementValueBoundaries(unittest.TestCase):
    """Boundary values per input type (empty, exactly-at-limit, one past)."""

    def setUp(self):
        self.refs = refs(FACETS)

    def test_none_in_a_refinement_typed_field_is_rejected(self):
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Short", None, "s", self.refs)
        self.assertIn("is null", str(ctx.exception))

    def test_empty_string_satisfies_minlength_zero(self):
        zero = refs("""
refine Anything of Text
    minLength 0
entity Thing
    field
        id UUID
""")
        check_semantic_type("Anything", "", "a", zero)   # must not raise

    def test_empty_string_fails_minlength_one(self):
        one = refs("""
refine NonEmpty of Text
    minLength 1
entity Thing
    field
        id UUID
""")
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("NonEmpty", "", "n", one)
        self.assertIn("minLength", str(ctx.exception))

    def test_value_exactly_at_maxlength_passes(self):
        check_semantic_type("Tiny", "ab", "t", self.refs)

    def test_value_one_over_maxlength_fails(self):
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Tiny", "abc", "t", self.refs)
        self.assertIn("maxLength", str(ctx.exception))

    def test_enum_with_a_single_member(self):
        single = refs("""
refine Only of Text
    enum draft
entity Thing
    field
        id UUID
""")
        check_semantic_type("Only", "draft", "o", single)
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Only", "live", "o", single)
        self.assertIn("enum", str(ctx.exception))

    def test_bool_does_not_satisfy_a_numeric_enum(self):
        # Python's True == 1, so an unguarded `value in [1]` would accept it.
        numeric = refs("""
refine OneOnly of Integer
    enum 1
entity Thing
    field
        id UUID
""")
        check_semantic_type("OneOnly", 1, "x", numeric)
        with self.assertRaises(RunError):
            check_semantic_type("OneOnly", True, "x", numeric)

    def test_decimal_min_compares_exactly_not_as_float(self):
        # float("0.9999999999999999999") rounds to 1.0 and would pass.
        price = refs("""
refine Price of Decimal
    min 1
entity Thing
    field
        id UUID
""")
        check_semantic_type("Price", "1", "p", price)
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Price", "0.9999999999999999999", "p", price)
        self.assertIn("min 1", str(ctx.exception))

    def test_a_non_numeric_value_under_a_numeric_facet_is_rejected(self):
        price = refs("""
refine Price of Decimal
    min 1
entity Thing
    field
        id UUID
""")
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Price", "not-a-number", "p", price)
        self.assertIn("not a number", str(ctx.exception))


class TestUnresolvedNamesStayTheCompilersProblem(unittest.TestCase):
    """The boundary that owns name resolution is the compiler, not the runtime.

    Wave 2 made an unresolvable `fields[].type` a `LowerError` (부록 A.7 ⓐ), so a
    name reaching the interpreter is either one of the 18 bases or a Refinement
    in the same document. Re-deciding that here would duplicate a check that
    already failed closed upstream; what the runtime closes is the *refinement*
    case, which nothing enforced before.
    """

    def test_a_name_that_is_not_a_refinement_here_still_passes(self):
        check_semantic_type("Urlish", "https://x", "u", refs(SHORTENER))

    def test_the_same_call_without_an_index_also_passes(self):
        check_semantic_type("Slug", "NOT A SLUG!!", "slug")

    def test_but_a_refinement_in_the_document_is_enforced(self):
        with self.assertRaises(RunError):
            check_semantic_type("Slug", "NOT A SLUG!!", "slug", refs(SHORTENER))


class TestSampleForRefinementTypes(unittest.TestCase):
    """`sample_for_type` proposes candidates and verifies each one; it never
    inverts a pattern, because deriving a string that satisfies an arbitrary
    regex is not decidable."""

    def test_preset_slug_and_url_both_get_values(self):
        # Regression for the measured defect: this fixture used to be {'id': ...}
        _, payload = fixture(SHORTENER)
        self.assertEqual(set(payload), {"id", "slug", "target"})

    def test_enum_refinement_takes_a_declared_member(self):
        self.assertIn(sample_for_type("Status", refs(EVERY_SHAPE)),
                      ("draft", "live"))

    def test_numeric_refinement_satisfies_its_min(self):
        self.assertGreaterEqual(sample_for_type("Score", refs(EVERY_SHAPE)), 1)

    def test_decimal_refinement_keeps_the_bases_string_shape(self):
        # `Decimal`'s own sample is the string "0", so its refinement stays a
        # string rather than turning into an int on the way through the facets.
        value = sample_for_type("Price", refs(EVERY_SHAPE))
        self.assertIsInstance(value, str)

    def test_a_base_type_is_unaffected(self):
        self.assertEqual(sample_for_type("Text", refs(EVERY_SHAPE)), "text")

    def test_an_unknown_name_has_no_sample(self):
        self.assertIsNone(sample_for_type("Nope", refs(EVERY_SHAPE)))


class TestEverySampleValidatesItself(unittest.TestCase):
    """The hard requirement: a derived fixture may never contain a value that
    fails its own validation. A wrong value is worse than an absent one — it
    turns a fixture into a false green."""

    def test_every_derived_value_passes_its_own_check(self):
        doc, payload = fixture(EVERY_SHAPE)
        index = refinement_index(doc)
        fields = entities(doc)[0]["fields"]
        # Assert the fixture is non-trivial FIRST: a payload that derived
        # nothing would make the loop below pass vacuously.
        self.assertEqual(len(payload), 8)
        self.assertEqual(len(fields), 8)
        for field in fields:
            check_semantic_type(field["type"], payload[field["name"]],
                                field["name"], index)

    def test_the_shortener_fixture_passes_its_own_check(self):
        doc, payload = fixture(SHORTENER)
        index = refinement_index(doc)
        self.assertEqual(len(payload), 3)
        for field in entities(doc)[0]["fields"]:
            check_semantic_type(field["type"], payload[field["name"]],
                                field["name"], index)

    def test_a_registry_sample_wins_when_the_base_sample_cannot(self):
        # `Code` needs ^[A-Z]{3}$; "text" fails it and "USD" (Currency's sample)
        # passes. Pinning the value keeps the ladder's order observable.
        _, payload = fixture(EVERY_SHAPE)
        self.assertEqual(payload["code"], "USD")


class TestFixtureBoundaries(unittest.TestCase):

    def test_facets_the_base_sample_cannot_satisfy_still_yield_a_value(self):
        _, payload = fixture("""
refine Long of Text
    minLength 40
entity Thing
    field
        long Long
""")
        self.assertGreaterEqual(len(payload["long"]), 40)

    def test_an_unsatisfiable_pattern_skips_the_field(self):
        # Nothing can be derived, so nothing is emitted. Emitting a violating
        # value here would be the false green this rule exists to prevent.
        doc, payload = fixture("""
refine Impossible of Text
    pattern ^[0-9]{5}-[A-Z]{3}$
entity Thing
    field
        id UUID
        code Impossible
""")
        self.assertNotIn("code", payload)
        self.assertEqual(set(payload), {"id"})

    def test_minlength_zero_and_maxlength_zero(self):
        _, payload = fixture("""
refine Anything of Text
    minLength 0
refine Empty of Text
    maxLength 0
entity Thing
    field
        a Anything
        e Empty
""")
        self.assertEqual(payload["e"], "")
        self.assertIsInstance(payload["a"], str)

    def test_a_value_exactly_at_maxlength_is_produced(self):
        _, payload = fixture("""
refine Tiny of Text
    maxLength 2
entity Thing
    field
        t Tiny
""")
        self.assertEqual(len(payload["t"]), 2)

    def test_no_entities_yields_an_empty_fixture(self):
        self.assertEqual(sample_payload([], refs(EVERY_SHAPE)), {})

    def test_falsy_samples_are_not_dropped(self):
        # `{}`, `0`-like and `False` are legitimate values; "no sample" is None,
        # so the caller must test `is None` rather than truthiness.
        _, payload = fixture("""
entity Thing
    field
        flag Boolean
        blob Json
        price Decimal
""")
        self.assertEqual(payload, {"flag": True, "blob": {}, "price": "0"})

    def test_without_an_index_the_old_behaviour_is_unchanged(self):
        # `sample_payload`'s pre-refinement contract, still intact for any caller
        # that has no document to hand: a refinement-typed field is skipped.
        doc = ir(SHORTENER)
        self.assertEqual(set(sample_payload(entities(doc))), {"id"})


class TestRefinementWorkflowEndToEnd(unittest.TestCase):
    """A module whose entity uses `slug Slug` / `target URL` runs to completion
    on nothing but its own derived fixture. This is the shape task 5's golden
    URL-shortener example needs; it is written inline here rather than against
    impl/tests/test_fixture.py, which task 5 owns."""

    def test_shortener_workflow_completes_on_its_derived_fixture(self):
        doc, payload = fixture(SHORTENER)
        # Completion alone would still be green if a field were missing, so pin
        # the coverage too.
        self.assertEqual(set(payload), {"id", "slug", "target"})
        result = Interpreter(doc, repo_rows={}).run_workflow("wf.shorten", payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate slug", "create link"])

    def test_validate_input_completes_on_the_derived_fixture(self):
        # `validate input` requires EVERY declared field to be present and valid,
        # so a fixture gap becomes a failure rather than a silent skip.
        src = SHORTENER.replace("    validate slug\n", "    validate input\n")
        doc, payload = fixture(src)
        result = Interpreter(doc, repo_rows={}).run_workflow("wf.shorten", payload)
        self.assertEqual(result["status"], "completed")

    def test_every_shape_module_completes_on_its_derived_fixture(self):
        src = EVERY_SHAPE + """
service S
    policy
        retry 0
workflow Check
    validate input
"""
        doc, payload = fixture(src)
        result = Interpreter(doc, repo_rows={}).run_workflow("wf.check", payload)
        self.assertEqual(result["status"], "completed")


class TestCliAndSpecUseTheRefinedFixture(unittest.TestCase):
    """The three `sample_payload` call sites must pass the document's refinements,
    or `run`/`diff`/`spec` keep deriving a fixture with holes in it."""

    def setUp(self):
        self.dir = os.path.join(REPO, ".claude", "tmp", "t3-refinement-cli")
        os.makedirs(self.dir, exist_ok=True)
        self.src = os.path.join(self.dir, "shorten.lnpl")
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write(SHORTENER)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _run_args(self, **over):
        base = dict(source=self.src, payload=None, workflow=None,
                    no_row=True, json=False)
        base.update(over)
        return Namespace(**base)

    def test_run_without_a_payload_completes_for_a_refined_entity(self):
        self.assertEqual(cli.cmd_run(self._run_args()), 0)

    def test_run_with_a_payload_that_violates_a_facet_fails(self):
        # The explicit-payload path is enforced too, not just the derived one.
        bad = os.path.join(self.dir, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            json.dump({"id": UUID_SAMPLE, "slug": "NOT A SLUG!!",
                       "target": "https://example.com/a"}, fh)
        self.assertEqual(cli.cmd_run(self._run_args(payload=bad)), 1)

    def test_spec_given_derives_a_refined_fixture(self):
        doc = ir(SHORTENER)
        entity = entities(doc)[0]
        payload, _stored = _payload_from_given(["valid link"], entity,
                                               refinement_index(doc))
        self.assertEqual(set(payload), {"id", "slug", "target"})

    def test_spec_given_without_an_index_keeps_its_old_shape(self):
        # Boundary: the parameter is optional, so existing 2-argument callers
        # (impl/tests/test_spec.py) keep working unchanged.
        doc = ir(SHORTENER)
        payload, _stored = _payload_from_given(["valid link"], entities(doc)[0])
        self.assertEqual(set(payload), {"id"})


if __name__ == "__main__":
    unittest.main()
