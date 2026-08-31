"""Issue #65 / RFC-0025 — row sets and aggregation, the lowering-time contract.

Scope is Task 03 of the row-set effort: the `list` verb, the `sum`/`count`
grammar, the static rejections and the `aggregation-orphaned-list` warning
(RFC-0025 §1-§4, §6), and the IR schema gate (RFC-0025 §D10). Mode A execution
(binding a RowSet at run time, evaluating an aggregate) is a later task's file;
nothing here runs a workflow.
"""

import os
import subprocess
import sys
import unittest

from lnpl.condition import (Aggregate, ConditionError, parse_assignment,
                            parse_value, parse_value_or_aggregate, references,
                            value_to_string)
from lnpl.diagnostics import CODES, SEVERITY_OF
from lnpl.lower import VERB_LEXICON, LowerError, READ_VERBS, lower
from lnpl.parser import parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def compile_doc(source, module="m"):
    return lower(parse(source), module)


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


def clicks_source(body, field="clicks Integer"):
    """`Link`/`Report` fixture — the click-summary workflow RFC-0025 §Examples
    uses, parameterised on the workflow body and `Link.clicks`'s declared type
    (for the Money static-rejection case)."""
    return """capability postgres

entity Link
    field
        id UUID
        %s

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
%s
""" % (field, body)


class TestListVerb(unittest.TestCase):
    """RFC-0025 §1: `list` is the 18th `VERB_LEXICON` entry, reusing `query`."""

    def test_list_is_in_the_lexicon(self):
        self.assertIn("list", VERB_LEXICON)
        self.assertEqual(VERB_LEXICON["list"],
                         ("RepositoryCall", {"operation": "query"}))

    def test_the_lexicon_has_twenty_one_entries(self):
        # `format` (issue #94) widened this to 19 after RFC-0025 fixed it at
        # 18; `respond` (issue #96) widened it to 20; `note` (issue #111)
        # widens it again to 21.
        self.assertEqual(len(VERB_LEXICON), 21)

    def test_list_lowers_to_a_query_repository_call(self):
        mod = compile_doc(clicks_source("    list link\n"))
        doc = mod.to_document()
        calls = [n for n in nodes_of(doc, "RepositoryCall")
                 if n["entity"] == "entity.link"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["operation"], "query")
        self.assertEqual(mod.diagnostics.all(), [],
                         "a bare `list` on its own must not diagnose anything")

    def test_list_is_not_a_read_verb(self):
        """RFC-0025 §6.1/§6.2: `list` binds a RowSet, not a row, so the verb
        that repairs a failed single-row reference must never suggest it."""
        self.assertNotIn("list", READ_VERBS)
        self.assertEqual(set(READ_VERBS),
                         {"authenticate", "load", "find", "read"})

    def test_list_on_an_undeclared_entity_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(clicks_source("    list widget\n"))
        self.assertIn("declares 2", str(ctx.exception))


class TestAggregateGrammar(unittest.TestCase):
    """RFC-0025 §2: `set <ref> to sum|count <ref>` parses to an `Aggregate`,
    parsed and rendered by the same `condition.py` machinery a plain `Value`
    assignment uses — a second parser is a second grammar (RFC-0015's own
    reason for the split, unchanged here).
    """

    def test_sum_parses_to_an_aggregate(self):
        target, rhs = parse_assignment("set report.totalClicks to sum link.clicks")
        self.assertEqual(target, "report.totalClicks")
        self.assertEqual(rhs, Aggregate("sum", rhs.ref))
        self.assertEqual(rhs.ref.name, "link.clicks")

    def test_count_parses_to_an_aggregate(self):
        target, rhs = parse_assignment("set report.linkCount to count link")
        self.assertEqual(target, "report.linkCount")
        self.assertIsInstance(rhs, Aggregate)
        self.assertEqual(rhs.func, "count")
        self.assertEqual(rhs.ref.name, "link")

    def test_value_to_string_round_trips_both_forms(self):
        self.assertEqual(value_to_string(Aggregate("sum", parse_value("link.clicks"))),
                         "sum link.clicks")
        self.assertEqual(value_to_string(Aggregate("count", parse_value("link"))),
                         "count link")

    def test_references_collects_the_aggregates_ref(self):
        _, rhs = parse_assignment("set report.totalClicks to sum link.clicks")
        self.assertEqual(references(rhs), ("link.clicks",))

    def test_parse_value_or_aggregate_reads_both_shapes(self):
        self.assertIsInstance(parse_value_or_aggregate("sum link.clicks"), Aggregate)
        self.assertEqual(parse_value_or_aggregate("product.stock - input.quantity"),
                         parse_value("product.stock - input.quantity"))

    def test_plain_parse_value_refuses_an_aggregate_string(self):
        """`parse_value` is for a caller that specifically cannot handle an
        `Aggregate` — it must fail loudly, not silently hand one back."""
        with self.assertRaises(ConditionError):
            parse_value("sum link.clicks")

    def test_sum_does_not_combine_with_arithmetic(self):
        with self.assertRaises(ConditionError):
            parse_assignment("set report.totalClicks to sum link.clicks + 1")

    def test_aggregate_needs_exactly_one_reference(self):
        with self.assertRaises(ConditionError):
            parse_assignment("set report.totalClicks to sum link.clicks link")

    def test_aggregate_reference_must_be_a_reference_shape(self):
        with self.assertRaises(ConditionError):
            parse_assignment("set report.totalClicks to sum 1")

    def test_avg_min_max_parse_to_aggregates(self):
        """RFC-0045 §1: `AGG_FUNCS` widens to include `avg`/`min`/`max`, and
        `condition.py` needs no change to parse them (F1/F2)."""
        for func in ("avg", "min", "max"):
            with self.subTest(func=func):
                target, rhs = parse_assignment(
                    "set report.stat to %s link.clicks" % func)
                self.assertEqual(target, "report.stat")
                self.assertIsInstance(rhs, Aggregate)
                self.assertEqual(rhs.func, func)
                self.assertEqual(rhs.ref.name, "link.clicks")


class TestAggregateLowering(unittest.TestCase):
    """RFC-0025 §2: the full `list` + `sum`/`count` workflow lowers to
    `Assignment` nodes carrying the normalized expression string."""

    def test_the_golden_click_summary_lowers(self):
        doc = compile_doc(clicks_source(
            "    list link\n"
            "    set report.totalClicks to sum link.clicks\n"
            "    set report.linkCount to count link\n"
            "    update report\n")).to_document()
        assigns = {n["target"]: n for n in nodes_of(doc, "Assignment")}
        self.assertEqual(assigns["report.totalClicks"]["expression"],
                         "sum link.clicks")
        self.assertEqual(assigns["report.totalClicks"]["entity"], "entity.report")
        self.assertEqual(assigns["report.linkCount"]["expression"], "count link")


class TestStaticRejections(unittest.TestCase):
    """RFC-0025 §3 — one case per rejection row, plus a Money control."""

    def compile_fails(self, body, *fragments, field="clicks Integer"):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(clicks_source(body, field=field))
        message = str(ctx.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

    def test_count_with_a_field_is_refused(self):
        self.compile_fails(
            "    list link\n    set report.linkCount to count link.clicks\n",
            "`count` takes an entity, not a field")

    def test_sum_without_a_field_is_refused(self):
        self.compile_fails(
            "    list link\n    set report.totalClicks to sum link\n",
            "`sum` needs a field")

    def test_sum_of_an_undeclared_entity_is_refused(self):
        self.compile_fails(
            "    set report.totalClicks to sum widget.clicks\n",
            "widget", "not a declared entity")

    def test_count_of_an_undeclared_entity_is_refused(self):
        self.compile_fails(
            "    set report.linkCount to count widget\n",
            "widget", "not a declared entity")

    def test_summing_a_field_that_is_neither_integer_nor_money_is_refused(self):
        """RFC-0045 §2 widened `sum`'s legal types from Integer-only to
        Integer-or-Money — Decimal (still no evaluator) replaces Money as the
        rejected control here; Money's own legality is
        `test_summing_a_money_field_is_now_legal` below."""
        self.compile_fails(
            "    list link\n    set report.totalClicks to sum link.clicks\n",
            "neither Integer nor Money", "Decimal",
            field="clicks Decimal")

    def test_summing_a_datetime_field_is_still_refused(self):
        """RFC-0045 §2: `sum`(DateTime) stays rejected — a sum of instants is
        still meaningless, unchanged from RFC-0025."""
        self.compile_fails(
            "    list link\n    set report.totalClicks to sum link.clicks\n",
            "neither Integer nor Money",
            field="clicks DateTime")

    def test_summing_a_money_field_is_now_legal(self):
        """RFC-0045 §2: `sum` now accepts Money — the currency-mismatch rule
        is a runtime concern (RFC-0044 §5), not a compile-time one."""
        doc = compile_doc(clicks_source(
            "    list link\n"
            "    set report.totalClicks to sum link.clicks\n"
            "    update report\n", field="clicks Money")).to_document()
        self.assertEqual(len(nodes_of(doc, "Assignment")), 1)

    def test_averaging_a_datetime_field_is_refused(self):
        """RFC-0045 §Alternatives 2: `avg`(DateTime) is explicitly left
        closed this RFC — no measured need for "average instant"."""
        self.compile_fails(
            "    list link\n    set report.totalClicks to avg link.clicks\n",
            "neither Integer nor Money",
            field="clicks DateTime")

    def test_avg_without_a_field_is_refused(self):
        self.compile_fails(
            "    list link\n    set report.totalClicks to avg link\n",
            "`avg` needs a field")

    def test_min_max_without_a_field_is_refused(self):
        for func in ("min", "max"):
            with self.subTest(func=func):
                self.compile_fails(
                    "    list link\n    set report.totalClicks to %s link\n"
                    % func,
                    "`%s` needs a field" % func)

    def test_min_of_a_text_field_is_refused(self):
        """RFC-0045 §2: `min`/`max` accept Integer/DateTime/Money only — no
        order-comparison evaluator exists for Text."""
        self.compile_fails(
            "    list link\n    set report.totalClicks to min link.clicks\n",
            "none of Integer, DateTime, or Money",
            field="clicks Text")

    def test_max_of_a_decimal_field_is_refused(self):
        self.compile_fails(
            "    list link\n    set report.totalClicks to max link.clicks\n",
            "none of Integer, DateTime, or Money",
            field="clicks Decimal")

    def test_min_max_of_datetime_and_money_fields_are_now_legal(self):
        """RFC-0045 §2: `min`/`max`(DateTime) and `min`/`max`(Money) are new
        — RFC-0025 only ever opened Integer."""
        for field in ("clicks DateTime", "clicks Money"):
            with self.subTest(field=field):
                doc = compile_doc(clicks_source(
                    "    list link\n"
                    "    set report.totalClicks to min link.clicks\n"
                    "    update report\n", field=field)).to_document()
                self.assertEqual(len(nodes_of(doc, "Assignment")), 1)

    def test_summing_a_field_the_entity_does_not_declare_is_refused(self):
        self.compile_fails(
            "    list link\n    set report.totalClicks to sum link.nosuch\n",
            "which entity Link does not declare")

    def test_an_aggregate_assignment_to_an_unread_entity_is_still_refused(self):
        """RFC-0015's existing target rule applies unchanged: the write side
        of `set <target> to <Aggregate>` is exactly the write side of
        `set <target> to <Value>`."""
        src = """capability postgres

entity Link
    field
        id UUID
        clicks Integer

entity Report
    field
        id UUID
        totalClicks Integer

service Analytics
    policy
        timeout 5s

workflow SummarizeClicks
    list link
    set report.totalClicks to sum link.clicks
"""
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("never reads it", str(ctx.exception))

    # ---- control: the legal shape still compiles -----------------------
    def test_the_same_shapes_compile_when_they_are_legal(self):
        doc = compile_doc(clicks_source(
            "    list link\n"
            "    set report.totalClicks to sum link.clicks\n"
            "    set report.linkCount to count link\n"
            "    update report\n")).to_document()
        self.assertEqual(len(nodes_of(doc, "Assignment")), 2)


class TestOrphanAggregationDiagnostic(unittest.TestCase):
    """RFC-0025 §4: `sum`/`count` without a preceding unguarded `list` warns."""

    def test_no_preceding_list_warns(self):
        mod = compile_doc(clicks_source(
            "    set report.totalClicks to sum link.clicks\n"))
        codes = [d.code for d in mod.diagnostics]
        self.assertIn("aggregation-orphaned-list", codes)
        diag = mod.diagnostics.by_code("aggregation-orphaned-list")[0]
        self.assertEqual(diag.severity, "warning")
        self.assertIn("sum link.clicks", diag.message)

    def test_a_preceding_list_silences_it(self):
        mod = compile_doc(clicks_source(
            "    list link\n"
            "    set report.totalClicks to sum link.clicks\n"))
        self.assertEqual(mod.diagnostics.by_code("aggregation-orphaned-list"), [])

    def test_a_list_only_inside_a_guard_does_not_count(self):
        """RFC-0025 §4 / RFC-0023 §3: a guard's own `list` may never run, so it
        does not satisfy a later, unguarded aggregate."""
        mod = compile_doc(clicks_source(
            "    when input.clicks exists\n"
            "    list link\n"
            "    set report.totalClicks to sum link.clicks\n"))
        codes = [d.code for d in mod.diagnostics]
        self.assertIn("aggregation-orphaned-list", codes)

    def test_the_diagnostic_carries_a_source_line(self):
        mod = compile_doc(clicks_source(
            "    set report.totalClicks to sum link.clicks\n"))
        diag = mod.diagnostics.by_code("aggregation-orphaned-list")[0]
        self.assertIsNotNone(diag.line)
        self.assertEqual(diag.where, "line %d" % diag.line)

    def test_the_code_is_registered_and_graded(self):
        self.assertIn("aggregation-orphaned-list", CODES)
        self.assertEqual(SEVERITY_OF["aggregation-orphaned-list"], "warning")


class TestQualifiedReferenceScopeNarrowing(unittest.TestCase):
    """RFC-0025 §6.1/§6.2 (RFC-0012 §G12.2/§G12.4/§G12.5 updated): `list`
    binds a RowSet, not a row, so it must not satisfy a single-row qualified
    reference — the guard on `read_entities` this RFC narrows from
    `operation in READ_OPS` to `operation == "read"`.
    """

    def test_a_guard_on_a_list_only_entity_is_refused(self):
        src = """capability postgres

entity Link
    field
        id UUID
        clicks Integer

service Analytics
    policy
        timeout 5s

workflow W
    list link
    when link.clicks > 0
    update link
"""
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("never reads it", str(ctx.exception))

    def test_a_guard_on_a_read_entity_still_compiles(self):
        """Negative control: the narrowing must not touch `read`'s own case."""
        src = """capability postgres

entity Link
    field
        id UUID
        clicks Integer

service Analytics
    policy
        timeout 5s

workflow W
    find link
    when link.clicks > 0
    update link
"""
        doc = compile_doc(src).to_document()
        self.assertEqual(len(nodes_of(doc, "Guard")), 1)


class TestIrSchemaGate(unittest.TestCase):
    """RFC-0025 §D10: the `query` RepositoryCall branch, against
    schemas/lir.schema.json and the self-test gate itself.
    """

    def test_a_lowered_rowset_document_validates(self):
        import json
        import jsonschema
        with open(os.path.join(REPO_ROOT, "schemas", "lir.schema.json"),
                  encoding="utf-8") as fh:
            schema = json.load(fh)
        doc = compile_doc(clicks_source(
            "    list link\n"
            "    set report.totalClicks to sum link.clicks\n"
            "    update report\n")).to_document()
        jsonschema.validate(doc, schema)

    def test_the_schema_self_test_passes_including_the_new_fixture_and_negatives(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "validate_ir.py"),
             "--self-test"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ROWSET_FIXTURE", proc.stdout)
        for label in ("RepositoryCall.entity (query branch)",
                      "operation outside the enum: 'list'",
                      "undeclared property on a query RepositoryCall",
                      "entity is not a node id: 'Entity.Link'"):
            self.assertIn(label, proc.stdout,
                          "the gate no longer runs the %r negative" % label)


if __name__ == "__main__":
    unittest.main()
