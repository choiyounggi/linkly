"""The refinement preset registry (RFC-0001 Appendix A.6.3/A.6.4, issue #31).

Three properties are checked separately, because they can fail independently:

  coverage    every one of the 18 semantic types has a category
  vocabulary  each category's allowed facets stay inside the closed 6
  values      the categories and presets hold exactly the RFC's values

`refinements.py` may not import the rest of `lnpl`, so it carries its own copy
of the 18 base names. That copy is what `TestCategoryCoverage` binds back to
`types.SEMANTIC_TYPES` — the drift the no-import rule would otherwise allow.
"""

import ast
import os
import unittest

from lnpl.lexer import tokenize
from lnpl.refinements import (BASE_CATEGORY, CATEGORY_FACETS, FACET_NAMES,
                              PRESETS, facets_for_base, preset)
from lnpl.types import SEMANTIC_TYPES

MODULE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "lnpl", "refinements.py")


class TestCategoryCoverage(unittest.TestCase):
    """Coverage — is every base classified? (not: is the classification right)"""

    def test_source_list_is_the_expected_18(self):
        # Assert the source list's size BEFORE comparing sets: a source that
        # parsed to zero items would make every set comparison below pass
        # vacuously.
        self.assertEqual(len(SEMANTIC_TYPES), 18)

    def test_every_semantic_type_has_a_category(self):
        self.assertEqual(set(BASE_CATEGORY), set(SEMANTIC_TYPES))

    def test_category_sizes_match_the_rfc(self):
        sizes = {}
        for category in BASE_CATEGORY.values():
            sizes[category] = sizes.get(category, 0) + 1
        self.assertEqual(sizes, {"text": 9, "numeric": 2, "boolean": 1,
                                 "composite": 6})
        self.assertEqual(sum(sizes.values()), 18)


class TestFacetVocabulary(unittest.TestCase):
    """Vocabulary — the closed enumeration of 6 and what each category admits."""

    def test_vocabulary_is_closed_at_six(self):
        self.assertEqual(len(FACET_NAMES), 6)
        self.assertEqual(len(set(FACET_NAMES)), 6)
        self.assertEqual(set(FACET_NAMES),
                         {"minLength", "maxLength", "pattern", "min", "max", "enum"})

    def test_category_facets_are_inside_the_vocabulary(self):
        for category, allowed in CATEGORY_FACETS.items():
            self.assertLessEqual(set(allowed), set(FACET_NAMES),
                                 "%s admits a facet outside the closed 6" % category)

    def test_category_facets_match_the_rfc(self):
        self.assertEqual(CATEGORY_FACETS["text"],
                         frozenset(("minLength", "maxLength", "pattern", "enum")))
        self.assertEqual(CATEGORY_FACETS["numeric"], frozenset(("min", "max", "enum")))
        self.assertEqual(CATEGORY_FACETS["boolean"], frozenset())
        self.assertEqual(CATEGORY_FACETS["composite"], frozenset())

    def test_facets_for_base_projects_its_category(self):
        # Stated against CATEGORY_FACETS rather than literal facet names, so this
        # test owns the base -> category -> facets wiring and nothing else.
        self.assertEqual(facets_for_base("Text"), CATEGORY_FACETS["text"])
        self.assertEqual(facets_for_base("Integer"), CATEGORY_FACETS["numeric"])
        self.assertEqual(facets_for_base("Boolean"), CATEGORY_FACETS["boolean"])
        self.assertEqual(facets_for_base("Money"), CATEGORY_FACETS["composite"])

    def test_boolean_and_composite_admit_nothing(self):
        for base in ("Boolean", "Money", "GeoLocation", "Address", "Image",
                     "File", "Json"):
            self.assertEqual(facets_for_base(base), frozenset(),
                             "%s must admit no facets in v0.1" % base)

    def test_unknown_base_raises_key_error(self):
        with self.assertRaises(KeyError):
            facets_for_base("Slugg")


class TestPresets(unittest.TestCase):
    """The three built-ins (A.6.4) — exact values, and no shared mutable state."""

    def test_preset_values_match_the_rfc(self):
        self.assertEqual(set(PRESETS), {"Url", "Slug", "PositiveInteger"})
        self.assertEqual(PRESETS["Url"],
                         {"base": "Text",
                          "facets": {"pattern": r"^https?://[^\s]+$",
                                     "maxLength": 2048}})
        self.assertEqual(PRESETS["Slug"],
                         {"base": "Text",
                          "facets": {"pattern": r"^[a-z0-9-]{1,64}$",
                                     "maxLength": 64}})
        self.assertEqual(PRESETS["PositiveInteger"],
                         {"base": "Integer", "facets": {"min": 1}})

    def test_positive_integer_min_is_an_int_not_a_float(self):
        # The canonical fragment writes `1`; a float would serialize as 1.0 and
        # stop matching the RFC's node.
        self.assertIsInstance(PRESETS["PositiveInteger"]["facets"]["min"], int)
        self.assertNotIsInstance(PRESETS["PositiveInteger"]["facets"]["min"], bool)

    def test_preset_bases_are_semantic_types(self):
        for name, spec in PRESETS.items():
            self.assertIn(spec["base"], SEMANTIC_TYPES,
                          "%s refines a name that is not one of the 18" % name)

    def test_preset_facets_are_applicable_to_their_base(self):
        # A preset that broke A.6.3's applicability table would be a spec the
        # compiler could not reproduce from a user declaration.
        for name, spec in PRESETS.items():
            allowed = facets_for_base(spec["base"])
            self.assertLessEqual(set(spec["facets"]), set(allowed),
                                 "%s uses a facet its base does not admit" % name)

    def test_preset_returns_the_entry(self):
        self.assertEqual(preset("Slug"),
                         {"base": "Text",
                          "facets": {"pattern": r"^[a-z0-9-]{1,64}$",
                                     "maxLength": 64}})

    def test_unknown_name_is_not_a_preset(self):
        self.assertIsNone(preset("Nope"))
        self.assertIsNone(preset("Text"))

    def test_preset_result_is_a_copy(self):
        got = preset("Slug")
        got["facets"]["maxLength"] = 1
        got["base"] = "Integer"
        self.assertEqual(PRESETS["Slug"]["facets"]["maxLength"], 64)
        self.assertEqual(PRESETS["Slug"]["base"], "Text")
        self.assertEqual(preset("Slug")["facets"]["maxLength"], 64)

    def test_preset_patterns_survive_tokenization(self):
        # RFC-0002 §Full grammar: `Regex` excludes space/tab/`#` because the
        # lexer splits on whitespace and drops from `#`. Each preset pattern must
        # therefore round-trip as a single token.
        for name, spec in PRESETS.items():
            pattern = spec["facets"].get("pattern")
            if pattern is None:
                continue
            lines = tokenize("pattern " + pattern)
            self.assertEqual([l.tokens for l in lines], [["pattern", pattern]],
                             "%s's pattern does not survive tokenization" % name)


class TestRegistryDiscipline(unittest.TestCase):
    """`refinements.py` is a leaf: consumers project from it, never the reverse."""

    def test_module_imports_nothing_from_lnpl(self):
        with open(MODULE_PATH, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=MODULE_PATH)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level > 0 or (node.module or "").split(".")[0] == "lnpl":
                    offenders.append(node.module or ".")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "lnpl":
                        offenders.append(alias.name)
        self.assertEqual(offenders, [],
                         "refinements.py must not import from lnpl: %r" % offenders)


if __name__ == "__main__":
    unittest.main()
