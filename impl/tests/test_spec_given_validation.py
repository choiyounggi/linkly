"""Issue #54 [3]: a `given` the runner cannot build is refused at manifest time.

Before this, `extract()` only joined the tokens back into strings — nothing looked
at them until `run_manifest` interpreted them. So `lnpl spec source.lnpl` (no
`--run`) happily wrote a manifest whose cases could never execute, and the author
learned about the typo only on the run that used it (r1 F-8).

The check runs inside `extract()` because that is the manifest stage and because
`extract(decls, module_name)` has twelve call sites, all passing two positional
arguments — one of them `cli.py`, which this task does not own. The check
therefore judges only what `decls` can answer: the SHAPE of each given form and
whether the names it uses are declared. Types and coercion stay at run time,
where the refinement index exists.
"""

import unittest

from lnpl.parser import parse
from lnpl.spec import SpecError, extract

SRC = """
capability postgres

entity Product
    field
        id UUID
        name Text
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

workflow PlaceOrder
    find product
    when product.stock >= input.quantity
    create order
    spec
        given
            %s
        when
            place order
        expect
            completed
"""

NO_ENTITY = """
capability postgres

workflow Ping
    notify operator
    spec
        given
            %s
        when
            ping
        expect
            completed
"""


def extract_with(given_line, template=SRC):
    return extract(parse(template % given_line), "m")


class TestUndeclaredNamesAreRefusedEarly(unittest.TestCase):

    def test_an_undeclared_input_field_is_refused_by_extract(self):
        with self.assertRaises(SpecError) as ctx:
            extract_with("input.nosuchfield 1")
        self.assertIn("nosuchfield", str(ctx.exception))

    def test_an_undeclared_bare_field_is_refused_by_extract(self):
        with self.assertRaises(SpecError) as ctx:
            extract_with("nosuchfield 1")
        self.assertIn("nosuchfield", str(ctx.exception))

    def test_the_message_locates_the_block_that_holds_it(self):
        # The author has to know WHICH spec block to open; a bare field name is
        # not enough when a workflow declares several blocks.
        with self.assertRaises(SpecError) as ctx:
            extract_with("input.nosuchfield 1")
        self.assertIn("PlaceOrder", str(ctx.exception))

    def test_the_message_names_the_accepted_set(self):
        with self.assertRaises(SpecError) as ctx:
            extract_with("input.nosuchfield 1")
        message = str(ctx.exception)
        self.assertIn("quantity", message)
        self.assertIn("stock", message)


class TestFormErrors(unittest.TestCase):

    def test_an_unrecognized_shape_lists_the_known_forms(self):
        with self.assertRaises(SpecError) as ctx:
            extract_with("frobnicate all the widgets now")
        message = str(ctx.exception)
        self.assertIn("unsupported given", message)
        for form in ("input.<field> <value>", "no input.<field>",
                     "stored <entity> <field> <value>", "empty repository"):
            self.assertIn(form, message)

    def test_a_lone_token_is_refused(self):
        with self.assertRaises(SpecError):
            extract_with("quantity")

    def test_stored_with_the_wrong_arity_is_refused(self):
        with self.assertRaises(SpecError) as ctx:
            extract_with("stored Product stock")
        self.assertIn("stored", str(ctx.exception))


class TestStoredNameChecks(unittest.TestCase):

    def test_an_undeclared_entity_is_refused(self):
        with self.assertRaises(SpecError) as ctx:
            extract_with("stored NoSuchEntity stock 5")
        self.assertIn("is not a declared entity", str(ctx.exception))

    def test_an_undeclared_field_keeps_the_pinned_wording(self):
        # test_spec_given_types.py asserts this exact substring; issue #46 chose
        # it after the runner called a DECLARED entity undeclared.
        with self.assertRaises(SpecError) as ctx:
            extract_with("stored Product nosuchfield 5")
        self.assertIn("does not declare", str(ctx.exception))

    def test_the_binding_name_is_accepted_like_the_declared_name(self):
        # `stored product ...` and `stored Product ...` are the same thing
        # (issue #46, t1 F-8) — the early check must not re-narrow it.
        self.assertEqual(len(extract_with("stored product stock 5")["cases"]), 1)

    def test_empty_repository_and_stored_together_are_refused(self):
        with self.assertRaises(SpecError) as ctx:
            extract_with("empty repository\n            stored Product stock 5")
        self.assertIn("contradict", str(ctx.exception))


class TestValidGivensSurvive(unittest.TestCase):

    def test_the_new_forms_pass_and_are_preserved_verbatim(self):
        cases = extract_with("input.quantity 0\n            no input.name")["cases"]
        self.assertEqual(cases[0]["given"], ["input.quantity 0", "no input.name"])

    def test_a_narrative_marker_passes(self):
        self.assertEqual(extract_with("valid order")["cases"][0]["given"],
                         ["valid order"])

    def test_a_block_with_no_given_section_passes(self):
        src = SRC.replace("        given\n            %s\n", "")
        self.assertEqual(len(extract(parse(src), "m")["cases"]), 1)


class TestNoEntityModule(unittest.TestCase):
    """The boundary: nothing is declared, so every field name is undeclared."""

    def test_a_field_given_is_refused_when_no_entity_is_declared(self):
        with self.assertRaises(SpecError):
            extract_with("input.anything 1", NO_ENTITY)

    def test_the_empty_accepted_set_is_spelled_out(self):
        # An empty list must not render as a dangling "Declared: " — the author
        # would read it as truncation rather than as "nothing is declared".
        with self.assertRaises(SpecError) as ctx:
            extract_with("input.anything 1", NO_ENTITY)
        self.assertIn("none", str(ctx.exception))

    def test_a_narrative_marker_still_passes(self):
        self.assertEqual(len(extract_with("valid thing", NO_ENTITY)["cases"]), 1)


class TestRunPathStillAgrees(unittest.TestCase):
    """The early check must not disagree with the runner it front-runs.

    The two stages read different sources — `_schema_from_decls` reads parsed
    field lines, `_schema_from_nodes` reads lowered IR nodes — so a drift between
    them would make `extract` reject a module the runner can run, or vice versa.
    """

    def test_the_two_schema_builders_describe_the_same_entities(self):
        from lnpl.lower import lower
        from lnpl.spec import _schema_from_decls, _schema_from_nodes

        decls = parse(SRC % "input.quantity 1")
        doc = lower(decls, "m").to_document()
        nodes = [n for n in doc["nodes"] if n["kind"] == "Entity"]
        self.assertEqual(_schema_from_decls(decls), _schema_from_nodes(nodes))

    def test_both_stages_agree_on_every_reachable_entity_spelling(self):
        # `stored` takes the declared name or the binding name; a builder that
        # disagreed on either would split accept/reject between the two stages.
        from lnpl.interp import refinement_index
        from lnpl.lower import lower
        from lnpl.spec import _payload_from_given

        for spelling, expected in (("Product", True), ("product", True),
                                   ("Order", True), ("Nope", False)):
            with self.subTest(spelling=spelling):
                line = "stored %s id x" % spelling
                decls = parse(SRC % line)
                doc = lower(decls, "m").to_document()
                nodes = [n for n in doc["nodes"] if n["kind"] == "Entity"]
                try:
                    extract(decls, "m")
                    early = True
                except SpecError:
                    early = False
                try:
                    _payload_from_given([line], nodes[0],
                                        refinement_index(doc), doc)
                    late = True
                except SpecError:
                    late = False
                self.assertEqual(early, expected)
                self.assertEqual(early, late)

    def test_what_extract_accepts_the_runner_also_accepts(self):
        from lnpl.interp import refinement_index
        from lnpl.lower import lower
        from lnpl.spec import _payload_from_given

        decls = parse(SRC % "input.quantity 2")
        doc = lower(decls, "m").to_document()
        manifest = extract(decls, "m")
        entity = next(n for n in doc["nodes"] if n["kind"] == "Entity")
        payload, _stored = _payload_from_given(
            manifest["cases"][0]["given"], entity, refinement_index(doc), doc)
        self.assertEqual(payload["quantity"], 2)


if __name__ == "__main__":
    unittest.main()
