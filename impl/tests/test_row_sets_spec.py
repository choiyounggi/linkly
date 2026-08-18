"""Issue #65 / RFC-0025 — row sets and aggregation, spec seeding (Task 05).

Scope: `given stored <entity>[<i>] <field> <value>` (RFC-0025 §8) and the
"no new expect vocabulary" decision (RFC-0025 §9) — multi-row seeding and
aggregate results asserted through the existing `result`/`rows` forms. Also
covers the `repo_policy.seeded_entities` fix this task needed (RFC-0025 §5):
an entity reached only through `list` must not get an auto-seeded default
row, or a 0-row spec case would silently see 1.
"""

import unittest

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import SpecError, _check_given, extract, run_manifest
from lnpl.repo_policy import default_rows, seeded_entities

CLICKS_SRC = """capability postgres

entity Link
    field
        id UUID
        clicks Integer

entity Report
    field
        id UUID
        totalClicks Integer
        linkCount Integer

service Analytics
    policy
        timeout 5s

workflow SummarizeClicks
    find report
    list link
    set report.totalClicks to sum link.clicks
    set report.linkCount to count link
    update report
    spec
%s
"""


def run_clicks(given, expect):
    """`CLICKS_SRC` with the given `given`/`expect` phrase lists installed
    into its `spec` block. -> (passed, failed, lines)."""
    given_lines = "\n".join("            %s" % g for g in given)
    expect_lines = "\n".join("            %s" % e for e in expect)
    src = CLICKS_SRC % ("        given\n%s\n        when\n            "
                        "summarizeClicks\n        expect\n%s"
                        % (given_lines, expect_lines))
    decls = parse(src)
    doc = lower(decls, "m").to_document()
    manifest = extract(decls, "m")
    return run_manifest(manifest, doc)


SCHEMA = (("Link", "link", frozenset({"id", "clicks"})),)


class TestIndexedFormParsing(unittest.TestCase):
    """`_check_given` classifies `stored <entity>[<i>] <field> <value>`."""

    def test_an_indexed_line_classifies_as_stored_indexed(self):
        form, parts = _check_given("stored Link[0] clicks 5", SCHEMA)
        self.assertEqual(form, "stored-indexed")
        self.assertEqual(parts, ("Link", "0", "clicks", "5"))

    def test_the_binding_name_is_accepted_too(self):
        form, parts = _check_given("stored link[3] clicks 9", SCHEMA)
        self.assertEqual(form, "stored-indexed")
        self.assertEqual(parts[0], "link")
        self.assertEqual(parts[1], "3")

    def test_a_non_numeric_index_falls_back_to_the_plain_form_and_is_refused(self):
        """`Link[abc]` is not `<entity>[<i>]` (the index must be digits), so it
        falls through to the plain `stored` path, where `Link[abc]` is simply
        not a declared entity name."""
        with self.assertRaises(SpecError) as ctx:
            _check_given("stored Link[abc] clicks 5", SCHEMA)
        self.assertIn("not a declared entity", str(ctx.exception))

    def test_an_undeclared_entity_is_refused(self):
        with self.assertRaises(SpecError):
            _check_given("stored Widget[0] clicks 5", SCHEMA)

    def test_an_undeclared_field_is_refused(self):
        with self.assertRaises(SpecError):
            _check_given("stored Link[0] nosuch 5", SCHEMA)


class TestPlainStoredIsUnchanged(unittest.TestCase):
    """RFC-0025 D7: the existing `stored <entity> <field> <value>` form's
    grammar and meaning are untouched — a negative control against the
    indexed-form addition regressing it."""

    def test_the_plain_form_still_classifies_as_stored(self):
        form, parts = _check_given("stored Link clicks 0", SCHEMA)
        self.assertEqual(form, "stored")
        self.assertEqual(parts, ("Link", "clicks", "0"))

    def test_a_plain_stored_spec_still_runs(self):
        """The `find`+`stored` path this form always supported, on the same
        module the indexed form now also seeds — proof the two coexist."""
        passed, failed, lines = run_clicks(
            ["stored Report id 1"],
            ["completed", "result report.totalClicks == 0"])
        self.assertEqual(failed, 0, lines)


class TestMultiRowSeedAndAggregation(unittest.TestCase):
    """RFC-0025 §8/§9: the full contract — multi-row seed, aggregate result,
    row count, all in one spec, with no new `expect` vocabulary."""

    def test_the_golden_click_summary(self):
        passed, failed, lines = run_clicks(
            ["stored Report id 1", "stored Link[0] clicks 5",
             "stored Link[1] clicks 3"],
            ["completed", "result report.totalClicks == 8",
             "result report.linkCount == 2", "rows Link 2"])
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 4)

    def test_the_same_index_accumulates_fields(self):
        passed, failed, lines = run_clicks(
            ["stored Report id 1", "stored Link[0] clicks 5"],
            ["completed", "rows Link 1", "result report.totalClicks == 5"])
        self.assertEqual(failed, 0, lines)

    def test_indices_need_not_be_contiguous_or_ordered(self):
        passed, failed, lines = run_clicks(
            ["stored Report id 1", "stored Link[7] clicks 4",
             "stored Link[2] clicks 6"],
            ["completed", "rows Link 2", "result report.totalClicks == 10"])
        self.assertEqual(failed, 0, lines)

    # ---- boundary: 0 rows -------------------------------------------------
    def test_zero_rows_boundary(self):
        passed, failed, lines = run_clicks(
            ["stored Report id 1"],
            ["completed", "result report.totalClicks == 0",
             "result report.linkCount == 0", "rows Link 0"])
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 4)

    # ---- error: contradiction ----------------------------------------------
    def test_indexed_stored_contradicts_empty_repository(self):
        with self.assertRaises(SpecError):
            run_clicks(["empty repository", "stored Link[0] clicks 5"],
                      ["completed"])


class TestSeededEntitiesDoesNotAutoSeedListOnlyEntities(unittest.TestCase):
    """RFC-0025 §5: the bug this task's fix closes. Before it, `default_rows`
    auto-seeded a field-less row for any entity the workflow only `list`s,
    which would have made the 0-row boundary case above silently see 1 row —
    and made a real `sum` fail on a row with no summed field at all.
    """

    def test_a_list_only_entity_is_not_in_seeded_entities(self):
        doc = lower(parse(CLICKS_SRC % (
            "        given\n            stored Report id 1\n"
            "        when\n            summarizeClicks\n"
            "        expect\n            completed")), "m").to_document()
        self.assertNotIn("entity.link", seeded_entities(doc, "wf.summarize.clicks"))
        self.assertIn("entity.report", seeded_entities(doc, "wf.summarize.clicks"))

    def test_default_rows_carries_no_entry_for_the_list_only_entity(self):
        doc = lower(parse(CLICKS_SRC % (
            "        given\n            stored Report id 1\n"
            "        when\n            summarizeClicks\n"
            "        expect\n            completed")), "m").to_document()
        rows = default_rows(doc, "wf.summarize.clicks", {"id": "r-1"})
        self.assertNotIn("entity.link", rows)


if __name__ == "__main__":
    unittest.main()
