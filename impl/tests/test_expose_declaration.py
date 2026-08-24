"""Issue #99, D2 — the `expose` clause: opt-in cursor-paginated list surface.

`service ... expose / list <Entity> by <field>` is a closed grammar (RFC-0016
widening precedent): `list` is the only expose verb, and the sort field must
resolve to Integer or DateTime (RFC-0025's `list` keyword names something else
— a RowSet bound inside a workflow body — this is a different grammar
position, `service ... expose ...`, never a workflow step). No `expose`
clause -> no `Expose` node -> serve.py serves no list route for that entity
(D2's "default un-exposed" — checked in test_serve.py, not here).
"""

import unittest

from lnpl.lower import LowerError, lower
from lnpl.parser import ParseError, parse

ENTITY_SRC = """capability postgres

entity Order
    field
        id UUID
        placedAt DateTime
        total Integer
        note Text

service Orders
    policy
        retry 0
"""


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


class ExposeGrammarTest(unittest.TestCase):
    """Normal case: `expose` opens, `list <Entity> by <field>` lowers."""

    def test_expose_list_lowers_to_an_expose_node_in_service_children(self):
        src = ENTITY_SRC + "    expose\n        list Order by placedAt\n"
        doc = compile_doc(src)
        exposes = nodes_of(doc, "Expose")
        self.assertEqual(1, len(exposes))
        node = exposes[0]
        order_id = next(n["id"] for n in nodes_of(doc, "Entity")
                        if n["name"] == "Order")
        self.assertEqual(order_id, node["entity"])
        self.assertEqual("placedAt", node["field"])
        service = nodes_of(doc, "Service")[0]
        self.assertIn(node["id"], service["children"])

    def test_expose_list_accepts_an_integer_sort_field(self):
        src = ENTITY_SRC + "    expose\n        list Order by total\n"
        doc = compile_doc(src)
        self.assertEqual("total", nodes_of(doc, "Expose")[0]["field"])

    def test_two_expose_lines_yield_two_expose_nodes(self):
        src = (ENTITY_SRC + "    expose\n"
              "        list Order by placedAt\n"
              "        list Order by total\n")
        doc = compile_doc(src)
        fields = sorted(n["field"] for n in nodes_of(doc, "Expose"))
        self.assertEqual(["placedAt", "total"], fields)

    def test_no_expose_clause_yields_no_expose_node(self):
        doc = compile_doc(ENTITY_SRC)
        self.assertEqual([], nodes_of(doc, "Expose"))


class ExposeParseErrorTest(unittest.TestCase):
    def test_expose_clause_rejected_outside_service(self):
        with self.assertRaises(ParseError):
            parse("entity E\n    field\n        id UUID\n    expose\n"
                 "        list E by id\n")


class ExposeLowerErrorTest(unittest.TestCase):
    """Error cases: unknown verb, wrong shape, dangling entity/field, wrong type."""

    def test_unknown_expose_verb_is_rejected(self):
        src = ENTITY_SRC + "    expose\n        count Order by placedAt\n"
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("unknown expose verb", str(ctx.exception))

    def test_missing_by_keyword_is_rejected(self):
        src = ENTITY_SRC + "    expose\n        list Order placedAt\n"
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("needs `list <Entity> by <field>`", str(ctx.exception))

    def test_undeclared_entity_is_a_dangling_reference(self):
        src = ENTITY_SRC + "    expose\n        list Shipment by placedAt\n"
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("dangling reference", str(ctx.exception))

    def test_unknown_field_is_rejected(self):
        src = ENTITY_SRC + "    expose\n        list Order by shippedAt\n"
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("no field", str(ctx.exception))

    def test_non_sortable_field_type_is_rejected(self):
        # `note` is Text — D2 restricts the sort field to Integer|DateTime.
        src = ENTITY_SRC + "    expose\n        list Order by note\n"
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("Integer or DateTime", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
