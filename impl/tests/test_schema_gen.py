"""issue #147 D2/D3: the payload-internal `_schema_gen` schema-generation
stamp — `interp.schema_generation`'s digest, `interp.strip_schema_gen`'s
read-side hygiene, and the two `Interpreter._run_effect` write sites
(`Assignment`, `RepositoryCall` create) that inject it. `lnpl migrate`'s own
re-stamping is covered in test_migrate.py; wsgi.py's second strip (the
`lnpl serve` GET surface, which bypasses interp.py entirely) is covered in
test_wsgi_schema_gen.py.

No DDL changes ride along with this: every assertion below reads the stamp
out of the SAME `payload` TEXT column `lnpl_rows` already had.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

from lnpl import cli
from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import SCHEMA_GEN_KEY, schema_generation, strip_schema_gen
from lnpl.repo_policy import row_key

from tests.fixtures import VALUE_INVENTORY

WIDGET_SRC = """capability postgres

entity Widget
    field
        id UUID
        label Text

service WidgetService
    policy
        timeout 5s

workflow Fetch
    read widget
"""

WIDGET_ID = "44444444-4444-4444-4444-444444444444"


def _entity_node(doc, name):
    return next(n for n in doc["nodes"]
               if n["kind"] == "Entity" and n["name"] == name)


class SchemaGenerationDigestTest(unittest.TestCase):
    """`schema_generation` on its own — no store, no run."""

    def _node(self, fields):
        return {"kind": "Entity", "name": "T", "fields": fields}

    def test_is_a_twelve_hex_digest(self):
        digest = schema_generation(self._node([{"name": "id", "type": "UUID"}]))

        self.assertEqual(12, len(digest))
        int(digest, 16)  # raises ValueError if it is not hex

    def test_is_deterministic_across_calls(self):
        node = self._node([{"name": "id", "type": "UUID"},
                           {"name": "label", "type": "Text"}])

        self.assertEqual(schema_generation(node), schema_generation(node))

    def test_field_declaration_order_does_not_change_it(self):
        forward = self._node([{"name": "id", "type": "UUID"},
                              {"name": "label", "type": "Text"}])
        backward = self._node([{"name": "label", "type": "Text"},
                               {"name": "id", "type": "UUID"}])

        self.assertEqual(schema_generation(forward), schema_generation(backward))

    def test_a_different_field_set_changes_it(self):
        base = self._node([{"name": "id", "type": "UUID"}])
        extra = self._node([{"name": "id", "type": "UUID"},
                            {"name": "label", "type": "Text"}])

        self.assertNotEqual(schema_generation(base), schema_generation(extra))

    def test_a_different_declared_type_changes_it(self):
        as_text = self._node([{"name": "n", "type": "Text"}])
        as_integer = self._node([{"name": "n", "type": "Integer"}])

        self.assertNotEqual(schema_generation(as_text), schema_generation(as_integer))

    def test_derived_fields_are_excluded(self):
        without_derived = self._node([{"name": "id", "type": "UUID"}])
        with_derived = self._node([{"name": "id", "type": "UUID"},
                                   {"name": "total", "type": "Integer",
                                    "derived": True}])

        self.assertEqual(schema_generation(without_derived),
                         schema_generation(with_derived))


class StripSchemaGenTest(unittest.TestCase):

    def test_removes_the_key(self):
        row = {"id": "a", SCHEMA_GEN_KEY: "abc123"}

        stripped = strip_schema_gen(row)

        self.assertNotIn(SCHEMA_GEN_KEY, stripped)
        self.assertEqual("a", stripped["id"])

    def test_is_a_noop_when_the_key_is_absent(self):
        row = {"id": "a"}

        self.assertEqual({"id": "a"}, strip_schema_gen(row))

    def test_passes_through_non_dict_values_unchanged(self):
        self.assertIsNone(strip_schema_gen(None))
        self.assertEqual({"affected": 1}, strip_schema_gen({"affected": 1}))


class CliTestCase(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.db = os.path.join(self.dir, "store.db")

    def write_source(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def payload_file(self, payload):
        path = os.path.join(self.dir, "payload.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()


class WriteInjectionTest(CliTestCase):
    """Both write sites `_run_effect` stamps: `create` (Order, seeded fields)
    and `Assignment` (Product, `set ... to ...`) — VALUE_INVENTORY's
    `PlaceOrder` exercises both in one run."""

    def setUp(self):
        super().setUp()
        self.source = self.write_source("inventory.lnpl", VALUE_INVENTORY)
        self.doc = cli.compile_source([self.source])
        self.product_id = _entity_node(self.doc, "Product")["id"]
        self.order_id = _entity_node(self.doc, "Order")["id"]

    def _raw_row(self, entity_id, key):
        driver = SqliteRepositoryDriver(self.db)
        try:
            found = driver._conn.execute(
                "SELECT payload FROM lnpl_rows WHERE entity_id = ? AND row_key = ?",
                (entity_id, key)).fetchone()
        finally:
            driver.close()
        self.assertIsNotNone(found, "no stored row for %s %s" % (entity_id, key))
        return json.loads(found[0])

    def test_the_created_and_the_assigned_row_are_both_stamped(self):
        payload = self.payload_file({"id": "p-1", "stock": 9, "quantity": 4})

        rc, out, err = self.run_cli(
            ["run", self.source, "--payload", payload, "--json",
             "--backend", "sqlite:" + self.db])

        self.assertEqual(0, rc, err)
        self.assertEqual("completed", json.loads(out)["result"]["status"])
        product_row = self._raw_row(self.product_id, row_key(self.product_id, {"id": "p-1"}))
        order_row = self._raw_row(self.order_id, row_key(self.order_id, {"id": "p-1"}))
        self.assertEqual(schema_generation(_entity_node(self.doc, "Product")),
                         product_row[SCHEMA_GEN_KEY])
        self.assertEqual(schema_generation(_entity_node(self.doc, "Order")),
                         order_row[SCHEMA_GEN_KEY])
        # Different entities, different declared fields -> different stamps —
        # the digest tracks the entity's own shape, not a document-wide constant.
        self.assertNotEqual(product_row[SCHEMA_GEN_KEY], order_row[SCHEMA_GEN_KEY])

    def test_the_stamp_never_reaches_stdout(self):
        payload = self.payload_file({"id": "p-1", "stock": 9, "quantity": 4})

        rc, out, err = self.run_cli(
            ["run", self.source, "--payload", payload, "--json",
             "--backend", "sqlite:" + self.db])

        self.assertEqual(0, rc, err)
        self.assertNotIn(SCHEMA_GEN_KEY, out)


class ReadPathTest(CliTestCase):
    """issue #147 D3's regression to guard against: a row carrying
    `_schema_gen` must read back exactly like one that does not — no
    `stored-row-shape-mismatch` diagnostic, no rejection."""

    def setUp(self):
        super().setUp()
        self.source = self.write_source("widget.lnpl", WIDGET_SRC)
        self.doc = cli.compile_source([self.source])
        self.entity_id = _entity_node(self.doc, "Widget")["id"]

    def _seed(self, row):
        driver = SqliteRepositoryDriver(self.db)
        try:
            driver.seed({self.entity_id: {row_key(self.entity_id, row): row}})
        finally:
            driver.close()

    def _read(self):
        payload = self.payload_file({"id": WIDGET_ID})
        return self.run_cli(
            ["run", self.source, "--payload", payload, "--json",
             "--backend", "sqlite:" + self.db])

    def test_a_legacy_row_without_the_stamp_reads_cleanly(self):
        self._seed({"id": WIDGET_ID, "label": "widget-1"})

        rc, out, err = self._read()

        self.assertEqual(0, rc, err)
        body = json.loads(out)
        self.assertEqual("completed", body["result"]["status"])
        self.assertEqual([], body["diagnostics"])

    def test_a_stamped_row_reads_cleanly_and_is_never_shown(self):
        stamped = {"id": WIDGET_ID, "label": "widget-2",
                  SCHEMA_GEN_KEY: schema_generation(_entity_node(self.doc, "Widget"))}
        self._seed(stamped)

        rc, out, err = self._read()

        self.assertEqual(0, rc, err)
        body = json.loads(out)
        self.assertEqual("completed", body["result"]["status"])
        codes = [d["code"] for d in body["diagnostics"]]
        self.assertNotIn("stored-row-shape-mismatch", codes)
        self.assertNotIn(SCHEMA_GEN_KEY, out)


if __name__ == "__main__":
    unittest.main()
