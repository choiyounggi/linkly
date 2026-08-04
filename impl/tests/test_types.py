"""Single-source-of-truth semantic type registry (issue #24).

Type knowledge used to live in three places that drifted apart:
`interp.check_semantic_type` (validation), `openapi.TYPE_SCHEMA` (schema), and
`interp.SAMPLE_VALUES` (fixture defaults). `lnpl.types.SEMANTIC_TYPES` is now the
one source; the others are projections of it. These tests lock that in and guard
against re-drift from RFC-0001's fixed 18-type table.
"""

import unittest

from lnpl import interp, openapi
from lnpl.interp import RunError, check_semantic_type
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


if __name__ == "__main__":
    unittest.main()
