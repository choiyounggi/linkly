"""A workflow read that misses on a persistent backend (issue #197).

`Interpreter` used to call `seed()` on every repository it was handed, so on
`sqlite:` (or any `lnpl.drivers` driver) the request payload was inserted as
a stored row whenever the key was absent: a read of a missing row never
failed, and it left a phantom row behind. Seeding is the `fake` backend's
fixture rule (issue #35) and stays there. On a persistent store the read
verb now fails its step with the typed `failure_kind` `not-found`, and the
store is left exactly as it was.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import FakeRepository, Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows
from lnpl.wsgi import make_wsgi_app, map_consume_result, map_result

from tests.test_wsgi_contract import call_wsgi

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

ORDER = "entity.order"
ORDER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
FIND_STEP = "find order by input.id"
CANCEL_PATH = "/order-service/cancel-order"
EVENT_PATH = "/-/events/order-cancel-requested"

CANCEL_ORDER = """
entity Order
    field
        id UUID
        quantity Integer

service OrderService

workflow CancelOrder
    find order by input.id
    set order.quantity to 0
    update order by input.id
"""

# The same workflow, reached through the `consume by` ingress instead.
CANCEL_ORDER_CONSUMED = CANCEL_ORDER.replace(
    "service OrderService\n",
    "service OrderService\n\nevent OrderCancelRequested\n"
    "    consume by CancelOrder\n")


def compile_source(source, module="mod"):
    return lower(parse(source), module).to_document()


def workflow_id(doc, name):
    return next(n["id"] for n in doc["nodes"]
                if n["kind"] == "Workflow" and n["name"] == name)


def order_key(order_id):
    return "%s#%s" % (ORDER, order_id)


def stored_row_count(path):
    """`lnpl_rows`, counted through a connection of its own after the run --
    never through the interpreter's bindings or a reference taken mid-run."""
    conn = sqlite3.connect(path)
    try:
        return conn.execute("select count(*) from lnpl_rows").fetchone()[0]
    finally:
        conn.close()


class SqliteStoreTestCase(unittest.TestCase):

    def setUp(self):
        base = os.path.join(REPO_ROOT, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        box = tempfile.mkdtemp(prefix="lnpl-t197-", dir=base)
        self.addCleanup(shutil.rmtree, box, True)
        self.path = os.path.join(box, "store.db")
        self.doc = compile_source(CANCEL_ORDER)
        self.workflow = workflow_id(self.doc, "CancelOrder")
        self.payload = {"id": ORDER_ID}

    def driver(self):
        driver = SqliteRepositoryDriver(self.path)
        self.addCleanup(driver.close)
        return driver

    def seed_order(self, order_id, quantity):
        seeder = SqliteRepositoryDriver(self.path)
        seeder.seed({ORDER: {order_key(order_id):
                             {"id": order_id, "quantity": quantity}}})
        seeder.close()

    def assert_find_missed(self, result):
        self.assertEqual("failed", result["status"])
        self.assertEqual(FIND_STEP, result["failed_step"])
        self.assertEqual("not-found", result["failure_kind"])
        self.assertEqual("repository read found no row for %s" % ORDER,
                         result["failure_reason"])


class ReadMissOnAPersistentStoreTest(SqliteStoreTestCase):

    def test_a_read_that_finds_its_row_runs_as_before(self):
        self.seed_order(ORDER_ID, 3)
        driver = self.driver()

        result = Interpreter(self.doc, repo_rows={}, repository=driver) \
            .run_workflow(self.workflow, self.payload)

        self.assertEqual("completed", result["status"], result.get("failure_reason"))
        self.assertNotIn("failure_kind", result)
        self.assertEqual([FIND_STEP, "set order.quantity to 0",
                          "update order by input.id"],
                         [entry["step"] for entry in result["steps"]])
        self.assertEqual({"id": ORDER_ID, "quantity": 0},
                         {k: v for k, v in
                          driver.execute(ORDER, "read", order_key(ORDER_ID)).items()
                          if not k.startswith("_")})
        self.assertEqual(1, stored_row_count(self.path))

    def test_a_miss_on_an_empty_store_fails_the_find_and_stores_nothing(self):
        """The issue's own scenario, with the rows the CLI and `serve` really
        pass: the request payload as a would-be seed row for `Order`."""
        rows = default_rows(self.doc, self.workflow, self.payload)
        self.assertEqual({ORDER: {order_key(ORDER_ID): {"id": ORDER_ID}}}, rows)
        driver = self.driver()

        result = Interpreter(self.doc, repo_rows=rows, repository=driver) \
            .run_workflow(self.workflow, self.payload)

        self.assert_find_missed(result)
        self.assertEqual([], driver.query(ORDER))
        self.assertEqual(0, stored_row_count(self.path))

    def test_a_miss_with_no_seed_rows_at_all_fails_the_same_way(self):
        """Boundary: `repo_rows` empty and absent -- the two spellings of
        "nothing to seed" -- give the same typed failure."""
        for rows in ({}, None):
            with self.subTest(repo_rows=rows):
                driver = self.driver()
                result = Interpreter(self.doc, repo_rows=rows, repository=driver) \
                    .run_workflow(self.workflow, self.payload)
                self.assert_find_missed(result)
                self.assertEqual(0, stored_row_count(self.path))

    def test_a_miss_beside_another_stored_row_leaves_that_row_alone(self):
        """Boundary: the store is not empty, only this key is absent."""
        self.seed_order(OTHER_ID, 7)
        driver = self.driver()
        rows = default_rows(self.doc, self.workflow, self.payload)

        result = Interpreter(self.doc, repo_rows=rows, repository=driver) \
            .run_workflow(self.workflow, self.payload)

        self.assert_find_missed(result)
        self.assertIsNone(driver.execute(ORDER, "read", order_key(ORDER_ID)))
        self.assertEqual(7, driver.execute(ORDER, "read", order_key(OTHER_ID))["quantity"])
        self.assertEqual(1, stored_row_count(self.path))

    def test_every_read_verb_misses_the_same_way_bare_or_by_ref(self):
        """`authenticate`/`load`/`find`/`read`, with and without `by <ref>`:
        one failure, one kind, nothing stored."""
        for verb in ("authenticate", "load", "find", "read"):
            for suffix in ("", " by input.id"):
                step = "%s order%s" % (verb, suffix)
                with self.subTest(step=step):
                    doc = compile_source(
                        CANCEL_ORDER.split("workflow CancelOrder")[0]
                        + "workflow CancelOrder\n    %s\n" % step)
                    workflow = workflow_id(doc, "CancelOrder")
                    rows = default_rows(doc, workflow, self.payload)
                    self.assertEqual({ORDER}, set(rows))
                    result = Interpreter(doc, repo_rows=rows,
                                         repository=self.driver()) \
                        .run_workflow(workflow, self.payload)
                    self.assertEqual("failed", result["status"])
                    self.assertEqual(step, result["failed_step"])
                    self.assertEqual("not-found", result["failure_kind"])
                    self.assertEqual(0, stored_row_count(self.path))

    def test_a_fake_repository_passed_explicitly_is_still_seeded(self):
        """The seed rule stays with the Fake, however it reaches the
        interpreter: an instance handed in is seeded like the built-in one."""
        rows = default_rows(self.doc, self.workflow, self.payload)

        result = Interpreter(self.doc, repo_rows=rows, repository=FakeRepository()) \
            .run_workflow(self.workflow, self.payload)

        self.assertEqual("completed", result["status"], result.get("failure_reason"))
        self.assertNotIn("failure_kind", result)


class NotFoundVerdictTest(unittest.TestCase):

    def test_not_found_verdict_survives_a_reworded_failure_reason(self):
        """Same proof as issue #113's conflict row: reword `failure_reason`
        completely, keep `failure_kind` -- 404 must still hold."""
        result = {
            "status": "failed", "failed_step": FIND_STEP,
            "failure_reason": "a totally reworded message that names neither "
                              "the entity nor what went wrong",
            "failure_kind": "not-found",
            "steps": [{"step": FIND_STEP, "effects": ["RepositoryCall"]}]}
        self.assertEqual((404, "not-found"), map_result(result))

    def test_the_same_wording_without_the_kind_stays_a_500(self):
        """The converse: the wording alone decides nothing."""
        result = {
            "status": "failed", "failed_step": FIND_STEP,
            "failure_reason": "repository read found no row for %s" % ORDER,
            "steps": [{"step": FIND_STEP, "effects": ["RepositoryCall"]}]}
        self.assertEqual((500, "workflow-failed"), map_result(result))


class ServeReadMissTest(SqliteStoreTestCase):
    """`lnpl serve --backend sqlite:<file>`, driven as the WSGI app it is."""

    def app(self, source=CANCEL_ORDER):
        return make_wsgi_app(
            compile_source(source),
            repository_factory=lambda: SqliteRepositoryDriver(self.path))

    def post(self, app):
        return call_wsgi(app, "POST", CANCEL_PATH,
                         body=json.dumps(self.payload).encode("utf-8"))

    def test_a_workflow_read_miss_is_a_404_and_stores_nothing(self):
        status, headers, body = self.post(self.app())

        self.assertEqual(404, status)
        self.assertEqual("application/problem+json", headers["Content-Type"])
        self.assertEqual("not-found", body["code"])
        self.assertEqual(404, body["status"])
        self.assertEqual(FIND_STEP, body["failed_step"])
        self.assertEqual(0, stored_row_count(self.path))

    def test_a_workflow_read_that_finds_its_row_is_still_a_200(self):
        self.seed_order(ORDER_ID, 3)

        status, _headers, body = self.post(self.app())

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])
        self.assertEqual(1, stored_row_count(self.path))

    def test_a_repeated_miss_stays_a_404_and_never_becomes_a_hit(self):
        """A phantom row would turn the second identical request into a 200."""
        app = self.app()
        statuses = [self.post(app)[0] for _ in range(2)]

        self.assertEqual([404, 404], statuses)
        self.assertEqual(0, stored_row_count(self.path))

    def test_a_consumed_event_whose_read_misses_is_permanent_not_transient(self):
        """`docs/serving.md` E7, deliberately not E6: the failed step's effect
        IS a `RepositoryCall`, but redelivering the same envelope can never
        turn a missing row into a hit -- 422, not 503."""
        envelope = {"specversion": "1.0", "id": "evt-t197-1", "source": "test",
                    "type": "OrderCancelRequested", "data": self.payload}

        status, headers, body = call_wsgi(
            self.app(CANCEL_ORDER_CONSUMED), "POST", EVENT_PATH,
            body=json.dumps(envelope).encode("utf-8"))

        self.assertEqual(422, status)
        self.assertEqual("event-rejected", body["code"])
        self.assertEqual(FIND_STEP, body["failed_step"])
        self.assertNotIn("Retry-After", headers)
        self.assertEqual(0, stored_row_count(self.path))


class ConsumeVerdictTest(unittest.TestCase):

    def test_not_found_is_decided_before_the_repository_effect_branch(self):
        result = {
            "status": "failed", "failed_step": FIND_STEP,
            "failure_reason": "reworded", "failure_kind": "not-found",
            "steps": [{"step": FIND_STEP, "effects": ["RepositoryCall"]}]}
        self.assertEqual((422, "event-rejected"), map_consume_result(result))

    def test_an_untyped_repository_failure_is_still_transient(self):
        """Boundary: E6 is unchanged for every other `RepositoryCall` failure."""
        result = {
            "status": "failed", "failed_step": FIND_STEP,
            "failure_reason": "repository read found no row for %s" % ORDER,
            "steps": [{"step": FIND_STEP, "effects": ["RepositoryCall"]}]}
        self.assertEqual((503, "event-retry-later"), map_consume_result(result))


if __name__ == "__main__":
    unittest.main()
