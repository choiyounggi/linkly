"""Issue #113: GET single carries an `ETag` (weak validator, `_version`-
based); a state-changing POST's `If-Match` conditions on the FIRST entity
the workflow reads (there is no single targeted resource the way a REST
PUT/PATCH has one) and a mismatch is 412. D12's opt-in (`observed_version`)
is the SAME attribute `drivers.py`'s `persist()` already reads -- no new
check invented, just reused the other direction.
"""

import json
import os
import tempfile
import unittest

from lnpl.drivers import DriverError, SqliteRepositoryDriver
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app

from tests.fixtures import VALUE_INVENTORY, VALUE_PAYMENT
from tests.test_wsgi_contract import call_wsgi

PROD = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
PRODUCT_PATH = "/order-service/product/%s" % PROD
PLACE_ORDER_PATH = "/order-service/place-order"


def compile_source(source, module="mod"):
    return lower(parse(source), module).to_document()


class EtagIfMatchTest(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")
        self.doc = compile_source(VALUE_INVENTORY)
        self.app = make_wsgi_app(
            self.doc, repository_factory=lambda: SqliteRepositoryDriver(self.path))
        seed = SqliteRepositoryDriver(self.path)
        seed.seed({"entity.product": {"entity.product#%s" % PROD:
                                      {"id": PROD, "stock": 100}}})
        seed.close()

    def _get_product(self):
        return call_wsgi(self.app, "GET", PRODUCT_PATH)

    def _place_order(self, headers=None):
        payload = {"id": PROD, "quantity": 1}
        return call_wsgi(self.app, "POST", PLACE_ORDER_PATH,
                         body=json.dumps(payload).encode("utf-8"),
                         headers=headers or {})

    # -- normal --------------------------------------------------------

    def test_get_single_carries_an_etag_matching_version(self):
        status, headers, body = self._get_product()

        self.assertEqual(200, status)
        self.assertEqual('W/"0"', headers.get("ETag"))

    def test_if_match_hit_lets_the_write_through(self):
        _, headers, _ = self._get_product()
        etag = headers["ETag"]

        status, _, body = self._place_order({"If-Match": etag})

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

    def test_the_version_advances_after_a_write(self):
        self._place_order()
        _, headers, _ = self._get_product()

        self.assertEqual('W/"1"', headers.get("ETag"))

    # -- error: stale If-Match -------------------------------------------

    def test_if_match_miss_is_412(self):
        _, headers, _ = self._get_product()
        stale_etag = headers["ETag"]
        self._place_order()                       # advances the version

        status, _, body = self._place_order({"If-Match": stale_etag})

        self.assertEqual(412, status)
        self.assertEqual("precondition-failed", body["code"])

    def test_malformed_if_match_is_400_not_412(self):
        """Decided (task boundary): a value this server never issued as its
        own ETag is a request-format error (400), not a failed precondition
        (412) -- the server cannot even evaluate the condition. Several
        malformed shapes, not just one -- an unquoted number, RFC 9110's
        `*` (not produced by this server's own GET, so not accepted), and
        a multi-value If-Match list (also not produced here)."""
        for bad in ("not-an-etag", "0", "*", 'W/"0", W/"1"', 'w/"0"'):
            with self.subTest(if_match=bad):
                status, _, body = self._place_order({"If-Match": bad})
                self.assertEqual(400, status)
                self.assertEqual("precondition-invalid", body["code"])

    def test_a_repository_error_during_the_precondition_read_defers_to_the_workflow(self):
        """`_check_if_match` (wsgi.py) swallows a `DriverError` from its own
        pre-read and lets the request proceed -- the workflow's own read of
        the same entity hits the same broken driver right after and surfaces
        the fault the normal way (M8/M14), rather than this check
        translating it a second time under a different code."""
        class _BrokenReadDriver(SqliteRepositoryDriver):
            def execute(self, entity_id, operation, key):
                if operation == "read":
                    raise DriverError("the store is unreachable")
                return super().execute(entity_id, operation, key)

        app = make_wsgi_app(
            self.doc, repository_factory=lambda: _BrokenReadDriver(self.path))
        payload = {"id": PROD, "quantity": 1}

        status, _, body = call_wsgi(app, "POST", PLACE_ORDER_PATH,
                                    body=json.dumps(payload).encode("utf-8"),
                                    headers={"If-Match": 'W/"0"'})

        # Not 400/412 (the precondition check itself never rejected this) --
        # the workflow's own read hits the same broken driver and the
        # failure surfaces as an ordinary failed run (never a 500 from an
        # escaped exception).
        self.assertNotIn(status, (400, 412))
        self.assertIn(status, (500, 409))

    # -- boundary: no read step -> nothing to condition on ----------------

    def test_if_match_on_a_workflow_with_no_read_step_is_ignored(self):
        """`VALUE_PAYMENT`'s `Approve` never reads anything -- If-Match has
        no row to check against, so it is skipped, not rejected."""
        doc = compile_source(VALUE_PAYMENT)
        app = make_wsgi_app(doc, repository_factory=lambda: SqliteRepositoryDriver(self.path))
        payload = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3302", "amount": 500}

        status, _, body = call_wsgi(app, "POST", "/payment-service/approve",
                                    body=json.dumps(payload).encode("utf-8"),
                                    headers={"If-Match": 'W/"999"'})

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

    # -- boundary: no observed_version (fake backend, D12) -----------------

    def test_fake_backend_never_issues_an_etag(self):
        doc = compile_source(VALUE_INVENTORY)
        app = make_wsgi_app(doc)  # no repository_factory -> fake

        status, headers, body = call_wsgi(app, "GET", PRODUCT_PATH)

        self.assertEqual(404, status)          # fake seeds nothing per request
        self.assertNotIn("ETag", headers)

    def test_fake_backend_ignores_if_match_and_runs_normally(self):
        doc = compile_source(VALUE_PAYMENT)
        app = make_wsgi_app(doc)
        payload = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3303", "amount": 500}

        status, _, body = call_wsgi(app, "POST", "/payment-service/approve",
                                    body=json.dumps(payload).encode("utf-8"),
                                    headers={"If-Match": 'W/"0"'})

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

    # -- regression: no If-Match is byte-identical (D13) --------------------

    def test_no_if_match_runs_exactly_as_before(self):
        status, _, body = self._place_order()

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])
