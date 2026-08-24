"""Issue #94 — the `format` verb: States.Format-style string assembly as a
closed-vocabulary verb, not an expression extension (RFC-0028's "computation
an expression can't do gets absorbed as a verb" rule, first applied).

`format <target> from "<template>" [with <ref> [<ref>...]]` derives an
Assignment Effect (RFC-0015's binding rule: the target is a field of a row
this workflow read). The template carries positional `{}` placeholders only
— no names, no padding, no precision — and their count must equal the
argument count at compile time. Every argument is a Reference
(`<binding>.<field>` or `input.<field>`); a Password-typed argument is a
compile error, closing the one route that would let issue #43's masking
chokepoint be bypassed by assembling a masked field into an unmasked one.

Mode B needs no new MLIR: RFC-0025 §10 already established that mode B does
not model Assignment VALUES at all (`_render_std` holds no computed value in
an SSA register) — it only records that an `Assignment` effect occurred and
whether the step ran. `format` derives the same `Assignment` kind `set`
does, so the existing generic effect-kind recording covers it; this file's
differential test is what confirms that rather than assumes it.
"""

import os
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.interp import Interpreter
from lnpl.lower import LowerError, lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HAS_TOOLS = backend.toolchain_available()
NEEDS_TOOLS = unittest.skipUnless(
    HAS_TOOLS, "MLIR/LLVM toolchain not installed (brew install llvm)")

RUN_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

# The issue's own example, verbatim: `format order.label from "ORD-{}-{}"
# with product.name input.quantity`. `secret` (Password) rides along for the
# masking-chokepoint tests below — it is never read by the workflow shipped
# in this fixture, only referenced by the mutated sources the error tests build.
FORMAT_SRC = """capability postgres

entity Product
    field
        id UUID
        name Text
        secret Password

entity Order
    field
        id UUID
        label Text
        quantity Integer

service Orders
    policy
        retry 0

workflow LabelOrder
    find product
    find order
    format order.label from "ORD-{}-{}" with product.name input.quantity
"""


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


def format_interp(name, quantity):
    doc = compile_doc(FORMAT_SRC)
    payload = {"id": RUN_ID, "name": name, "quantity": quantity}
    rows = {
        "entity.product": {row_key("entity.product", payload):
                           {"id": RUN_ID, "name": name, "secret": "s3cret"}},
        "entity.order": {row_key("entity.order", payload):
                         {"id": RUN_ID, "label": "", "quantity": quantity}},
    }
    return Interpreter(doc, repo_rows=rows), payload


class TestFormatCompiles(unittest.TestCase):
    """The issue's example, compiled: an Assignment with the template intact."""

    def test_derives_an_assignment_effect(self):
        doc = compile_doc(FORMAT_SRC)
        assigns = [a for a in nodes_of(doc, "Assignment")
                  if a["target"] == "order.label"]
        self.assertEqual(len(assigns), 1)
        self.assertIn("ORD-{}-{}", assigns[0]["expression"])
        self.assertIn("product.name", assigns[0]["expression"])
        self.assertIn("input.quantity", assigns[0]["expression"])

    def test_workflow_step_owns_the_assignment_as_a_child(self):
        doc = compile_doc(FORMAT_SRC)
        steps = nodes_of(doc, "WorkflowStep")
        format_step = next(s for s in steps if s["name"].startswith("format "))
        assign = next(a for a in nodes_of(doc, "Assignment")
                     if a["target"] == "order.label")
        self.assertIn(assign["id"], format_step["children"])


class TestFormatRuns(unittest.TestCase):
    """Issue #94's completion criterion 1: compiles, runs, traces as Assignment."""

    def test_assembles_the_string_and_persists_it(self):
        interp, payload = format_interp("Widget", 7)
        result = interp.run_workflow("wf.label.order", payload)
        self.assertEqual(result["status"], "completed")
        order_row = interp.repo.rows["entity.order"][
            row_key("entity.order", payload)]
        self.assertEqual(order_row["label"], "ORD-Widget-7")

    def test_the_trace_records_an_assignment_effect(self):
        interp, payload = format_interp("Widget", 7)
        interp.run_workflow("wf.label.order", payload)
        kinds = [child.kind for span in interp.trace.root.children
                for child in span.children]
        self.assertIn("Assignment", kinds)

    def test_a_different_quantity_produces_a_different_string(self):
        interp, payload = format_interp("Gadget", 3)
        interp.run_workflow("wf.label.order", payload)
        order_row = interp.repo.rows["entity.order"][
            row_key("entity.order", payload)]
        self.assertEqual(order_row["label"], "ORD-Gadget-3")


class TestFormatStaticRejections(unittest.TestCase):
    """Issue #94's completion criteria 2 and 3: two compile-time refusals."""

    def test_placeholder_count_mismatch_is_a_compile_error(self):
        src = FORMAT_SRC.replace(
            'format order.label from "ORD-{}-{}" with product.name input.quantity',
            'format order.label from "ORD-{}-{}" with product.name')
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("placeholder", str(ctx.exception))

    def test_password_argument_is_a_compile_error(self):
        src = FORMAT_SRC.replace(
            'format order.label from "ORD-{}-{}" with product.name input.quantity',
            'format order.label from "S-{}" with product.secret')
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("Password", str(ctx.exception))

    def test_non_text_target_is_a_compile_error(self):
        # D3(c): format writes only to a Text-family field — `order.quantity`
        # is Integer, so this is refused the same way `set`'s target check
        # refuses a Text field (the two verbs partition the field space).
        src = FORMAT_SRC.replace(
            'format order.label from "ORD-{}-{}" with product.name input.quantity',
            'format order.quantity from "{}" with product.name')
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("Text", str(ctx.exception))

    def test_an_undeclared_target_field_is_still_refused(self):
        # Not format-specific: the underlying binding rule (shared with
        # `set`) must still catch a target this workflow never read.
        src = FORMAT_SRC.replace(
            'format order.label from "ORD-{}-{}" with product.name input.quantity',
            'format product.label from "ORD-{}-{}" with product.name input.quantity')
        with self.assertRaises(LowerError):
            compile_doc(src)


class TestFormatBoundaries(unittest.TestCase):
    """D6 boundary set: zero arguments, an empty template, a repeated reference."""

    def test_zero_placeholders_needs_no_with_clause(self):
        src = FORMAT_SRC.replace(
            'format order.label from "ORD-{}-{}" with product.name input.quantity',
            'format order.label from "READY"')
        doc = compile_doc(src)
        assign = next(a for a in nodes_of(doc, "Assignment")
                     if a["target"] == "order.label")
        payload = {"id": RUN_ID, "name": "Widget", "quantity": 7}
        rows = {"entity.product": {row_key("entity.product", payload):
                                   {"id": RUN_ID, "name": "Widget", "secret": "x"}},
               "entity.order": {row_key("entity.order", payload):
                                {"id": RUN_ID, "label": "", "quantity": 7}}}
        interp = Interpreter(doc, repo_rows=rows)
        result = interp.run_workflow("wf.label.order", payload)
        self.assertEqual(result["status"], "completed")
        order_row = interp.repo.rows["entity.order"][
            row_key("entity.order", payload)]
        self.assertEqual(order_row["label"], "READY")
        self.assertEqual(assign["expression"].count("{}"), 0)

    def test_empty_template_is_accepted(self):
        src = FORMAT_SRC.replace(
            'format order.label from "ORD-{}-{}" with product.name input.quantity',
            'format order.label from ""')
        doc = compile_doc(src)
        assign = next(a for a in nodes_of(doc, "Assignment")
                     if a["target"] == "order.label")
        self.assertIsNotNone(assign)

    def test_the_same_reference_may_be_used_twice(self):
        src = FORMAT_SRC.replace(
            'format order.label from "ORD-{}-{}" with product.name input.quantity',
            'format order.label from "{}-{}" with product.name product.name')
        doc = compile_doc(src)
        payload = {"id": RUN_ID, "name": "Widget", "quantity": 7}
        rows = {"entity.product": {row_key("entity.product", payload):
                                   {"id": RUN_ID, "name": "Widget", "secret": "x"}},
               "entity.order": {row_key("entity.order", payload):
                                {"id": RUN_ID, "label": "", "quantity": 7}}}
        interp = Interpreter(doc, repo_rows=rows)
        interp.run_workflow("wf.label.order", payload)
        order_row = interp.repo.rows["entity.order"][
            row_key("entity.order", payload)]
        self.assertEqual(order_row["label"], "Widget-Widget")


class TestFormatModeBEquivalence(unittest.TestCase):
    """Issue #94's completion criterion 4: mode B differential EQUIVALENT."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-format-diff-", dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    @NEEDS_TOOLS
    def test_the_issues_example_is_equivalent(self):
        doc = compile_doc(FORMAT_SRC)
        payload = {"id": RUN_ID, "name": "Widget", "quantity": 7}
        rows = {"entity.product": {row_key("entity.product", payload):
                                   {"id": RUN_ID, "name": "Widget", "secret": "x"}},
               "entity.order": {row_key("entity.order", payload):
                                {"id": RUN_ID, "label": "", "quantity": 7}}}
        ok, report = differential.verify(doc, "wf.label.order", payload,
                                         rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))

    @NEEDS_TOOLS
    def test_an_unread_target_entity_is_equivalent_too(self):
        # `--no-row`: both modes must agree the run fails at `find product`,
        # before the format step is ever reached.
        doc = compile_doc(FORMAT_SRC)
        payload = {"id": RUN_ID, "name": "Widget", "quantity": 7}
        ok, report = differential.verify(doc, "wf.label.order", payload,
                                         {}, self.workdir, seeded=frozenset())
        self.assertTrue(ok, "\n".join(report))


if __name__ == "__main__":
    unittest.main()
