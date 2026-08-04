"""Single-source-of-truth semantic type registry (issue #24).

Type knowledge used to live in three places that drifted apart:
`interp.check_semantic_type` (validation), `openapi.TYPE_SCHEMA` (schema), and
`interp.SAMPLE_VALUES` (fixture defaults). `lnpl.types.SEMANTIC_TYPES` is now the
one source; the others are projections of it. These tests lock that in and guard
against re-drift from RFC-0001's fixed 18-type table.
"""

import unittest

from lnpl import interp, openapi
from lnpl.interp import RunError, check_semantic_type, refinement_index
from lnpl.refinements import BASE_CATEGORY
from lnpl.types import SEMANTIC_TYPES

# The exact set RFC-0001 §Semantic Type 시스템 fixes (13 domain + 5 auxiliary).
RFC0001_TYPES = {"UUID", "Money", "Email", "Phone", "Password", "Address",
                 "Image", "File", "Currency", "GeoLocation", "Json", "Html",
                 "Markdown", "Text", "Integer", "Decimal", "Boolean", "DateTime"}


class TestRegistryShape(unittest.TestCase):
    def test_registry_keys_are_exactly_the_rfc0001_types(self):
        self.assertEqual(set(SEMANTIC_TYPES), RFC0001_TYPES)

    def test_every_entry_has_openapi_and_sample(self):
        for name, spec in SEMANTIC_TYPES.items():
            self.assertIn("openapi", spec, name)
            self.assertIn("sample", spec, name)


class TestProjectionsStayInSync(unittest.TestCase):
    """The three former sites must now be derived from the one registry."""

    def test_openapi_type_schema_matches_registry(self):
        self.assertEqual(set(openapi.TYPE_SCHEMA), set(SEMANTIC_TYPES))
        for name, spec in SEMANTIC_TYPES.items():
            self.assertEqual(openapi.TYPE_SCHEMA[name], spec["openapi"], name)

    def test_sample_values_match_registry(self):
        self.assertEqual(set(interp.SAMPLE_VALUES), set(SEMANTIC_TYPES))
        for name, spec in SEMANTIC_TYPES.items():
            self.assertEqual(interp.SAMPLE_VALUES[name], spec["sample"], name)


class TestValidationPreserved(unittest.TestCase):
    """Validation behavior must be identical to the pre-refactor rules."""

    def test_valid_values_pass(self):
        for name, spec in SEMANTIC_TYPES.items():
            check_semantic_type(name, spec["sample"], name)   # must not raise

    def test_malformed_uuid_is_rejected(self):
        with self.assertRaises(RunError):
            check_semantic_type("UUID", "not-a-uuid", "id")

    def test_malformed_email_is_rejected(self):
        with self.assertRaises(RunError):
            check_semantic_type("Email", "nope", "email")

    def test_integer_rejects_bool(self):
        with self.assertRaises(RunError):
            check_semantic_type("Integer", True, "count")

    def test_null_is_rejected(self):
        with self.assertRaises(RunError):
            check_semantic_type("Text", None, "slug")

    def test_unknown_type_passes_through(self):
        # A non-base type string (e.g. a future refinement) is not the registry's
        # to judge — RFC-0001 owns the table. Non-null values pass.
        check_semantic_type("Urlish", "https://x", "u")

    def test_a_refinement_of_the_document_no_longer_passes_through(self):
        # The other side of the boundary (issue #31): once the caller supplies
        # the document's own Refinement nodes, the same name IS the registry's to
        # judge and its facets are enforced. Resolving a name that matches
        # nothing stays the compiler's job (부록 A.7 ⓐ), which is why the test
        # above still passes unchanged.
        index = refinement_index({"nodes": [
            {"kind": "Refinement", "id": "refine.urlish", "name": "Urlish",
             "base": "Text", "facets": {"pattern": "^https://"}}]})
        check_semantic_type("Urlish", "https://x", "u", index)   # must not raise
        with self.assertRaises(RunError) as ctx:
            check_semantic_type("Urlish", "ftp://x", "u", index)
        self.assertIn("pattern", str(ctx.exception))


class TestRefinementProjectionStaysInSync(unittest.TestCase):
    """`interp` projects a third view from a second registry.

    Facet enforcement dispatches on `refinements.BASE_CATEGORY[base]`, so that
    table and `SEMANTIC_TYPES` must name the same 18 types. The two checks below
    are deliberately separate: coverage asks whether every type has a category,
    validity asks whether every category is one the runtime can dispatch on. A
    set-equality check on names alone would be blind to a typo'd category value.
    """

    def test_the_source_registry_is_the_expected_18(self):
        # Assert the source list first: if SEMANTIC_TYPES parsed to nothing, the
        # set comparison below would pass vacuously.
        self.assertEqual(len(SEMANTIC_TYPES), 18)

    def test_every_semantic_type_has_a_runtime_category(self):
        # Coverage. Without this a refinement of a newly added base would reach
        # `_check_facets` and die with a KeyError instead of validating.
        self.assertEqual(set(BASE_CATEGORY), set(SEMANTIC_TYPES))

    def test_every_category_is_one_the_runtime_dispatches_on(self):
        # Value validity, separate from coverage above.
        self.assertEqual(set(BASE_CATEGORY.values()),
                         {"text", "numeric", "boolean", "composite"})

    def test_a_refinement_of_any_base_dispatches_without_error(self):
        # The behavioural form of the two checks above: every one of the 18 can
        # sit under a refinement without the category dispatch raising. Facets
        # are empty here because `boolean` and `composite` admit none (A.6.3);
        # this probes the dispatch, not the facets.
        for name, spec in SEMANTIC_TYPES.items():
            index = {"Refined": {"base": name, "facets": {}}}
            check_semantic_type("Refined", spec["sample"], name, index)


if __name__ == "__main__":
    unittest.main()
