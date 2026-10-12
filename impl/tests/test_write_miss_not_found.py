"""Issue #215 / RFC-0064: an `update`/`delete` that affects 0 rows fails its step
with `failure_kind == "not-found"` on `fake` and `sqlite:` -- the same outcome as
#197's read miss (serve 404, consume path 422). A present row behaves as before.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import Interpreter
from lnpl.repo_policy import default_rows
from lnpl.wsgi import make_wsgi_app
from tests.test_persistent_read_miss import (
    REPO_ROOT, compile_source, stored_row_count, workflow_id)
from tests.test_wsgi_contract import call_wsgi

STOCK = "entity.stock"
ROW_ID = "00000000-0000-4000-8000-0000000000b1"
PRODUCT_ID = "00000000-0000-4000-8000-0000000000b2"
OTHER_PRODUCT_ID = "00000000-0000-4000-8000-0000000000b3"
PAYLOAD = {"id": ROW_ID, "productId": PRODUCT_ID, "quantity": 5}
RESTOCK_STEP = "update stock by input.productId"
REMOVE_STEP = "delete stock by input.productId"
STOCK_SERVICE = """
entity Stock
    field
        id UUID
        productId UUID
        quantity Integer

service StockService

workflow Restock
    update stock by input.productId

workflow Remove
    delete stock by input.productId
"""
BARE_STOCK = STOCK_SERVICE.replace(" by input.productId", "")
PLACE_THEN_RESTOCK = """
entity Order
    field
        id UUID
        quantity Integer

entity Stock
    field
        id UUID
        productId UUID
        quantity Integer

service StockService

workflow PlaceAndRestock
    create order
    update stock by input.productId
"""
RETRY_STOCK = BARE_STOCK.replace(
    "service StockService\n",
    "service StockService\n    policy\n        retry 2\n") \
    + "\nworkflow Audit\n    find stock\n"

RESTOCK_PATH = "/stock-service/restock"
REMOVE_PATH = "/stock-service/remove"
EVENT_PATH = "/-/events/stock-remove-requested"
STOCK_SERVICE_CONSUMED = STOCK_SERVICE.replace(
    "service StockService\n",
    "service StockService\n\nevent StockRemoveRequested\n"
    "    consume by Remove\n")


def stock_key(product_id):
    return "%s#%s" % (STOCK, product_id)


def stored_version(path, key):
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "select _version from lnpl_rows where entity_id = ? and row_key = ?",
            (STOCK, key)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


class StockStoreTestCase(unittest.TestCase):
    def setUp(self):
        base = os.path.join(REPO_ROOT, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        box = tempfile.mkdtemp(prefix="lnpl-t215-", dir=base)
        self.addCleanup(shutil.rmtree, box, True)
        self.path = os.path.join(box, "store.db")

    def driver(self):
        drv = SqliteRepositoryDriver(self.path)
        self.addCleanup(drv.close)
        return drv

    def seed_stock(self, product_id, quantity):
        drv = SqliteRepositoryDriver(self.path)
        try:
            drv.seed({STOCK: {stock_key(product_id): {
                "id": ROW_ID, "productId": product_id, "quantity": quantity}}})
        finally:
            drv.close()

    def run_sqlite(self, source, name):
        doc = compile_source(source)
        return Interpreter(doc, repo_rows={}, repository=self.driver()) \
            .run_workflow(workflow_id(doc, name), dict(PAYLOAD))

    def assert_write_missed(self, result, step, op):
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], step)
        self.assertEqual(result["failure_kind"], "not-found")
        self.assertEqual(result["failure_reason"],
                         "repository %s found no row for %s" % (op, STOCK))


class SqliteWriteMissTest(StockStoreTestCase):
    def test_restock_on_an_empty_store_fails_not_found_and_stores_nothing(self):
        result = self.run_sqlite(STOCK_SERVICE, "Restock")
        self.assert_write_missed(result, RESTOCK_STEP, "update")
        self.assertEqual(stored_row_count(self.path), 0)

    def test_remove_on_an_empty_store_fails_not_found(self):
        result = self.run_sqlite(STOCK_SERVICE, "Remove")
        self.assert_write_missed(result, REMOVE_STEP, "delete")
        self.assertEqual(stored_row_count(self.path), 0)

    def test_a_row_under_another_key_does_not_satisfy_the_update(self):
        self.seed_stock(OTHER_PRODUCT_ID, 1)
        before = stored_version(self.path, stock_key(OTHER_PRODUCT_ID))
        result = self.run_sqlite(STOCK_SERVICE, "Restock")
        self.assert_write_missed(result, RESTOCK_STEP, "update")
        self.assertEqual(stored_row_count(self.path), 1)
        self.assertEqual(
            stored_version(self.path, stock_key(OTHER_PRODUCT_ID)), before)

    def test_restock_of_a_present_row_completes_and_bumps_its_version(self):
        self.seed_stock(PRODUCT_ID, 1)
        before = stored_version(self.path, stock_key(PRODUCT_ID))
        result = self.run_sqlite(STOCK_SERVICE, "Restock")
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("failure_kind", result)
        self.assertEqual(stored_version(self.path, stock_key(PRODUCT_ID)),
                         before + 1)
        self.assertEqual(stored_row_count(self.path), 1)

    def test_remove_of_a_present_row_deletes_exactly_that_row(self):
        self.seed_stock(PRODUCT_ID, 1)
        self.seed_stock(OTHER_PRODUCT_ID, 2)
        result = self.run_sqlite(STOCK_SERVICE, "Remove")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(stored_row_count(self.path), 1)
        self.assertIsNone(stored_version(self.path, stock_key(PRODUCT_ID)))
        self.assertIsNotNone(
            stored_version(self.path, stock_key(OTHER_PRODUCT_ID)))

    def test_bare_update_and_delete_miss_the_same_way(self):
        result = self.run_sqlite(BARE_STOCK, "Restock")
        self.assert_write_missed(result, "update stock", "update")
        result = self.run_sqlite(BARE_STOCK, "Remove")
        self.assert_write_missed(result, "delete stock", "delete")
        self.assertEqual(stored_row_count(self.path), 0)

    def test_a_write_miss_rolls_back_the_create_before_it(self):
        result = self.run_sqlite(PLACE_THEN_RESTOCK, "PlaceAndRestock")
        self.assert_write_missed(result, RESTOCK_STEP, "update")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["create order", RESTOCK_STEP])
        self.assertEqual(stored_row_count(self.path), 0)


class FakeWriteMissTest(unittest.TestCase):
    def run_fake(self, source, name, rows):
        doc = compile_source(source)
        interp = Interpreter(doc, repo_rows=rows)
        return interp, interp.run_workflow(workflow_id(doc, name),
                                           dict(PAYLOAD))

    def assert_write_missed(self, result, step, op):
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], step)
        self.assertEqual(result["failure_kind"], "not-found")
        self.assertEqual(result["failure_reason"],
                         "repository %s found no row for %s" % (op, STOCK))

    def present_rows(self):
        return {STOCK: {
            stock_key(PRODUCT_ID): {"id": ROW_ID, "productId": PRODUCT_ID,
                                    "quantity": 1},
            stock_key(OTHER_PRODUCT_ID): {"id": ROW_ID,
                                          "productId": OTHER_PRODUCT_ID,
                                          "quantity": 2}}}

    def test_restock_and_remove_on_an_empty_fake_fail_not_found(self):
        _, result = self.run_fake(STOCK_SERVICE, "Restock", {})
        self.assert_write_missed(result, RESTOCK_STEP, "update")
        _, result = self.run_fake(STOCK_SERVICE, "Remove", {})
        self.assert_write_missed(result, REMOVE_STEP, "delete")

    def test_the_default_seed_holds_no_row_for_an_update_first_entity(self):
        doc = compile_source(STOCK_SERVICE)
        rows = default_rows(doc, workflow_id(doc, "Restock"), dict(PAYLOAD))
        self.assertEqual(rows, {})
        _, result = self.run_fake(STOCK_SERVICE, "Restock", rows)
        self.assert_write_missed(result, RESTOCK_STEP, "update")

    def test_present_rows_complete_as_before(self):
        _, result = self.run_fake(STOCK_SERVICE, "Restock", self.present_rows())
        self.assertEqual(result["status"], "completed")
        interp, result = self.run_fake(STOCK_SERVICE, "Remove",
                                       self.present_rows())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(list(interp.repo.rows[STOCK]),
                         [stock_key(OTHER_PRODUCT_ID)])

    def test_bare_writes_miss_on_an_empty_fake(self):
        _, result = self.run_fake(BARE_STOCK, "Restock", {})
        self.assert_write_missed(result, "update stock", "update")
        _, result = self.run_fake(BARE_STOCK, "Remove", {})
        self.assert_write_missed(result, "delete stock", "delete")

    def test_a_write_miss_rolls_back_the_fake_store(self):
        interp, result = self.run_fake(PLACE_THEN_RESTOCK, "PlaceAndRestock", {})
        self.assert_write_missed(result, RESTOCK_STEP, "update")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["create order", RESTOCK_STEP])
        self.assertEqual({e: t for e, t in interp.repo.rows.items() if t}, {})

    def test_a_retried_write_miss_costs_what_a_read_miss_costs(self):
        interp, result = self.run_fake(RETRY_STOCK, "Restock", {})
        last = result["steps"][-1]
        self.assertEqual(last["attempts"], 3)
        self.assertEqual(result["failure_kind"], "not-found")
        spans = [c for c in interp.trace.root.children[-1].children
                 if c.kind == "RepositoryCall"]
        self.assertEqual([c.duration_ms for c in spans], [1, 1, 1])
        self.assertEqual([c.attrs["found"] for c in spans],
                         [False, False, False])
        _, audit = self.run_fake(RETRY_STOCK, "Audit", {})
        self.assertEqual(audit["steps"][-1]["duration_ms"], last["duration_ms"])
        self.assertEqual(audit["steps"][-1]["attempts"], 3)


class ServeWriteMissTest(StockStoreTestCase):
    def app(self, source=STOCK_SERVICE):
        return make_wsgi_app(
            compile_source(source),
            repository_factory=lambda: SqliteRepositoryDriver(self.path))

    def post(self, app, path):
        return call_wsgi(app, "POST", path,
                         body=json.dumps(PAYLOAD).encode("utf-8"))

    def assert_not_found_problem(self, path, step):
        status, headers, body = self.post(self.app(), path)
        self.assertEqual(status, 404)
        self.assertEqual(headers["Content-Type"], "application/problem+json")
        self.assertEqual(body["code"], "not-found")
        self.assertEqual(body["status"], 404)
        self.assertEqual(body["failed_step"], step)
        self.assertEqual(stored_row_count(self.path), 0)

    def test_restock_on_an_empty_store_is_a_404_problem(self):
        self.assert_not_found_problem(RESTOCK_PATH, RESTOCK_STEP)

    def test_remove_on_an_empty_store_is_a_404_problem(self):
        self.assert_not_found_problem(REMOVE_PATH, REMOVE_STEP)

    def test_a_present_row_is_still_a_200(self):
        self.seed_stock(PRODUCT_ID, 1)
        status, _headers, body = self.post(self.app(), RESTOCK_PATH)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "completed")
        self.assertEqual(stored_row_count(self.path), 1)

    def test_a_repeated_write_miss_stays_a_404(self):
        app = self.app()
        statuses = [self.post(app, RESTOCK_PATH)[0] for _ in range(2)]
        self.assertEqual(statuses, [404, 404])
        self.assertEqual(stored_row_count(self.path), 0)

    def test_a_consumed_remove_that_misses_is_rejected_not_retried(self):
        envelope = {"specversion": "1.0", "id": "evt-t215-1", "source": "test",
                    "type": "StockRemoveRequested", "data": PAYLOAD}
        status, headers, body = call_wsgi(
            self.app(STOCK_SERVICE_CONSUMED), "POST", EVENT_PATH,
            body=json.dumps(envelope).encode("utf-8"))
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "event-rejected")
        self.assertEqual(body["failed_step"], REMOVE_STEP)
        self.assertNotIn("Retry-After", headers)
        self.assertEqual(stored_row_count(self.path), 0)


if __name__ == "__main__":
    unittest.main()
