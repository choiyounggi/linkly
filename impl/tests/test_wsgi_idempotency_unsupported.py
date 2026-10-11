"""Issue #228: an `Idempotency-Key` the configured repository driver cannot
honour is refused (501 `idempotency-unsupported`), never silently ignored.

`_idempotency_mode` (wsgi.py) decides: a `RepositoryDriver` claims when
`supports_idempotency()` is True and refuses when it is False; anything
else (None for the fake backend, `interp.FakeRepository`-style doubles)
takes the LEGACY pre-#228 path (coordinator ruling t2 D1 r2).
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

from lnpl import wsgi
from lnpl.drivers import DriverError, SqliteRepositoryDriver
from lnpl.interp import FakeRepository
from lnpl.wsgi import make_wsgi_app

from tests.driver_spi_fixture import DemoRepositoryDriver
from tests.fixtures import VALUE_PAYMENT
from tests.test_idempotency import PAYMENT_PATH, compile_source
from tests.test_wsgi_contract import call_wsgi
from tests.test_wsgi_event_consume import (EVENTS_PATH_CREATE, SRC, _doc,
                                           _envelope, _post)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
DRIVER_NAME = "tests.test_wsgi_idempotency_unsupported._CountingDemoDriver"
PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b", "amount": 5}

WRITES = []           # every write-method call, as (method, detail)
PREDICATE_CALLS = []  # one entry per supports_idempotency() call
OPENED = []           # every _CountingDemoDriver instance, in order
CLOSED = []           # every close(), in order
LEGACY_CLAIMS = []    # _LegacyClaimingDouble's claim calls


class _CountingDemoDriver(DemoRepositoryDriver):
    """A real `RepositoryDriver` whose predicate is False (none of the
    three claim methods), recording every write and every predicate call."""

    def __init__(self, arg=None):
        super().__init__(arg)
        OPENED.append(self)

    def seed(self, rows):
        WRITES.append(("seed", None))
        return super().seed(rows)

    def execute(self, entity_id, operation, key):
        WRITES.append(("execute", operation))
        return super().execute(entity_id, operation, key)

    def persist(self, entity_id, key, row):
        WRITES.append(("persist", entity_id))
        return super().persist(entity_id, key, row)

    def record_emission(self, emission):
        WRITES.append(("record_emission", None))
        return super().record_emission(emission)

    def supports_idempotency(self):
        PREDICATE_CALLS.append(1)
        return super().supports_idempotency()

    def close(self):
        CLOSED.append(self)
        return super().close()


class _PredicateOnlyDouble(FakeRepository):
    """Not a RepositoryDriver, but defines the predicate (answering False):
    still LEGACY -- the type decides, not the method."""

    def supports_idempotency(self):
        return False


class _LegacyClaimingDouble(FakeRepository):
    """Not a RepositoryDriver, but has the claim methods: LEGACY claims."""

    def idempotency_begin(self, workflow_id, key, now_ms, ttl_ms):
        LEGACY_CLAIMS.append(("begin", key))
        return "started", None

    def idempotency_finish(self, workflow_id, key, http_status, body):
        LEGACY_CLAIMS.append(("finish", http_status))

    def idempotency_release(self, workflow_id, key):
        LEGACY_CLAIMS.append(("release", key))


def _build(doc, factory=None):
    """`make_wsgi_app` with stderr captured -> (app, stderr text)."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        app = make_wsgi_app(doc, repository_factory=factory)
    return app, err.getvalue()


def _post_payment(app, key=None):
    headers = {} if key is None else {"Idempotency-Key": key}
    return call_wsgi(app, "POST", PAYMENT_PATH,
                     body=json.dumps(PAYLOAD).encode("utf-8"),
                     headers=headers)


class _Base(unittest.TestCase):

    def setUp(self):
        for log in (WRITES, PREDICATE_CALLS, OPENED, CLOSED, LEGACY_CLAIMS):
            del log[:]

    def store_path(self):
        base = os.path.join(REPO_ROOT, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        box = tempfile.TemporaryDirectory(prefix="lnpl-t228-", dir=base)
        self.addCleanup(box.cleanup)
        return os.path.join(box.name, "store.db")

    def assert_nothing_ran(self):
        self.assertEqual([], WRITES)
        self.assertTrue(all(driver.rows == {} for driver in OPENED))


class RequestPathRefusalTest(_Base):

    def setUp(self):
        super().setUp()
        self.app, _ = _build(compile_source(VALUE_PAYMENT),
                             lambda: _CountingDemoDriver())

    def test_normal_keyed_post_on_a_driver_without_idempotency_is_501_and_runs_nothing(self):
        status, headers, body = _post_payment(self.app, key="k1")
        self.assertEqual(501, status)
        self.assertEqual("application/problem+json", headers["Content-Type"])
        self.assertEqual("idempotency-unsupported", body["code"])
        self.assertEqual(501, body["status"])
        self.assertEqual(wsgi._TITLES["idempotency-unsupported"], body["title"])
        self.assertTrue(body["correlation_id"].startswith("req-"))
        self.assertIn(DRIVER_NAME, body["detail"])
        self.assertIn("Idempotency-Key", body["detail"])
        self.assert_nothing_ran()

    def test_boundary_an_empty_key_value_still_counts_as_present(self):
        status, _headers, body = _post_payment(self.app, key="")
        self.assertEqual(501, status)
        self.assertEqual("idempotency-unsupported", body["code"])
        self.assert_nothing_ran()

    def test_boundary_unkeyed_post_on_that_driver_runs_as_before(self):
        before = len(PREDICATE_CALLS)
        status, _headers, body = _post_payment(self.app)
        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])
        self.assertIn(("execute", "create"), WRITES)
        # the helper is not consulted without the header
        self.assertEqual(before, len(PREDICATE_CALLS))


class ConsumePathRefusalTest(_Base):

    def setUp(self):
        super().setUp()
        self.app, _ = _build(_doc(SRC), lambda: _CountingDemoDriver())

    def test_error_consume_on_a_driver_without_idempotency_is_501_and_runs_nothing(self):
        status, headers, body = _post(
            self.app, EVENTS_PATH_CREATE,
            _envelope(event_type="OrderCreated",
                      data={"id": "ord-228", "amount": 1}))
        self.assertEqual(501, status)
        self.assertEqual("application/problem+json", headers["Content-Type"])
        self.assertEqual("idempotency-unsupported", body["code"])
        self.assertTrue(body["correlation_id"].startswith("req-"))
        self.assertIn(DRIVER_NAME, body["detail"])
        self.assertIn("CloudEvents id", body["detail"])
        self.assert_nothing_ran()
        # the route's `finally` still closed the request's driver
        self.assertEqual(len(OPENED), len(CLOSED))

    def test_boundary_an_envelope_without_id_is_still_400(self):
        envelope = _envelope(event_type="OrderCreated",
                             data={"id": "ord-228", "amount": 1})
        del envelope["id"]
        status, _headers, body = _post(self.app, EVENTS_PATH_CREATE, envelope)
        self.assertEqual(400, status)
        self.assertEqual("cloudevents-invalid", body["code"])
        self.assert_nothing_ran()


class LegacyAndFakeBoundaryTest(_Base):

    def test_boundary_fake_backend_with_a_key_still_runs_and_never_501s(self):
        app, err = _build(compile_source(VALUE_PAYMENT))
        status1, _h1, body1 = _post_payment(app, key="k1")
        status2, _h2, body2 = _post_payment(app, key="k1")
        self.assertEqual(200, status1)
        self.assertEqual(200, status2)
        self.assertNotEqual(body1["correlation_id"], body2["correlation_id"])
        self.assertEqual(1, err.count("Idempotency-Key support is disabled"))
        self.assertNotIn("idempotency: unsupported", err)

    def test_boundary_a_fake_repository_double_keeps_the_pre_228_no_claim_path(self):
        app, _ = _build(compile_source(VALUE_PAYMENT), lambda: FakeRepository())
        status1, _h1, body1 = _post_payment(app, key="k1")
        status2, _h2, body2 = _post_payment(app, key="k1")
        self.assertEqual(200, status1)
        self.assertEqual(200, status2)
        self.assertNotEqual(body1["correlation_id"], body2["correlation_id"])

    def test_boundary_a_double_defining_the_predicate_is_still_legacy(self):
        app, _ = _build(compile_source(VALUE_PAYMENT),
                        lambda: _PredicateOnlyDouble())
        status, _headers, body = _post_payment(app, key="k1")
        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

    def test_normal_a_legacy_double_with_the_claim_methods_still_claims(self):
        app, _ = _build(compile_source(VALUE_PAYMENT),
                        lambda: _LegacyClaimingDouble())
        status, _headers, _body = _post_payment(app, key="k1")
        self.assertEqual(200, status)
        self.assertEqual([("begin", "k1"), ("finish", 200)], LEGACY_CLAIMS)


class SqlitePathTest(_Base):

    def test_normal_sqlite_keyed_repeat_still_replays(self):
        path = self.store_path()
        app, _ = _build(compile_source(VALUE_PAYMENT),
                        lambda: SqliteRepositoryDriver(path))
        status1, _h1, body1 = _post_payment(app, key="k-sqlite")
        status2, _h2, body2 = _post_payment(app, key="k-sqlite")
        self.assertEqual(200, status1)
        self.assertEqual(200, status2)
        # replayed: the identical body, same correlation_id included
        self.assertEqual(body1, body2)



def _unreachable_store():
    raise DriverError("store unreachable")


class ReadyzCapabilityTest(_Base):

    def test_normal_readyz_reports_true_on_sqlite(self):
        path = self.store_path()
        app, _ = _build(compile_source(VALUE_PAYMENT),
                        lambda: SqliteRepositoryDriver(path))
        status, _h, body = call_wsgi(app, "GET", "/-/readyz")
        self.assertEqual(200, status)
        self.assertEqual({"status": "ok", "capabilities": {"idempotency": True}},
                         body)

    def test_normal_readyz_reports_false_on_a_driver_without_it(self):
        app, _ = _build(compile_source(VALUE_PAYMENT),
                        lambda: _CountingDemoDriver())
        status, _h, body = call_wsgi(app, "GET", "/-/readyz")
        self.assertEqual(200, status)
        self.assertEqual({"status": "ok", "capabilities": {"idempotency": False}},
                         body)

    def test_boundary_readyz_reports_false_with_no_backend(self):
        app, _ = _build(compile_source(VALUE_PAYMENT))
        status, _h, body = call_wsgi(app, "GET", "/-/readyz")
        self.assertEqual(200, status)
        self.assertEqual({"status": "ok", "capabilities": {"idempotency": False}},
                         body)

    def test_boundary_readyz_omits_capabilities_for_a_legacy_double(self):
        app, _ = _build(compile_source(VALUE_PAYMENT), lambda: FakeRepository())
        status, _h, body = call_wsgi(app, "GET", "/-/readyz")
        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)

    def test_error_readyz_503_is_unchanged_when_the_store_is_unreachable(self):
        app, _ = _build(compile_source(VALUE_PAYMENT), _unreachable_store)
        status, _h, body = call_wsgi(app, "GET", "/-/readyz")
        self.assertEqual(503, status)
        self.assertEqual("not-ready", body["code"])
        self.assertEqual(["repository"], body["checks"])
        self.assertNotIn("capabilities", body)

    def test_boundary_a_shutting_down_server_carries_no_capabilities(self):
        app, _ = _build(compile_source(VALUE_PAYMENT))
        app.shutting_down = True
        status, _h, body = call_wsgi(app, "GET", "/-/readyz")
        self.assertEqual(503, status)
        self.assertEqual(["shutting-down"], body["checks"])
        self.assertNotIn("capabilities", body)



class BootLineTest(_Base):

    def boot_lines(self, err):
        return [line for line in err.splitlines()
                if "idempotency: unsupported" in line]

    def test_normal_a_driver_without_idempotency_prints_one_line_naming_it(self):
        _, err = _build(compile_source(VALUE_PAYMENT),
                        lambda: _CountingDemoDriver())
        lines = self.boot_lines(err)
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].startswith(
            "lnpl serve: repository driver " + DRIVER_NAME
            + " -- idempotency: unsupported"), lines[0])

    def test_normal_the_boot_probe_closes_what_it_opens(self):
        _build(compile_source(VALUE_PAYMENT), lambda: _CountingDemoDriver())
        self.assertEqual(1, len(OPENED))
        self.assertEqual(OPENED, CLOSED)

    def test_boundary_sqlite_prints_no_line(self):
        path = self.store_path()
        _, err = _build(compile_source(VALUE_PAYMENT),
                        lambda: SqliteRepositoryDriver(path))
        self.assertEqual([], self.boot_lines(err))

    def test_boundary_fake_prints_only_the_d11_notice(self):
        _, err = _build(compile_source(VALUE_PAYMENT))
        self.assertEqual([], self.boot_lines(err))
        self.assertEqual(1, err.count("Idempotency-Key support is disabled"))

    def test_boundary_a_legacy_double_prints_no_line(self):
        _, err = _build(compile_source(VALUE_PAYMENT), lambda: FakeRepository())
        self.assertEqual([], self.boot_lines(err))

    def test_error_an_unreachable_store_at_boot_prints_nothing_and_construction_succeeds(self):
        app, err = _build(compile_source(VALUE_PAYMENT), _unreachable_store)
        self.assertEqual([], self.boot_lines(err))
        status, _h, body = call_wsgi(app, "GET", "/-/readyz")
        self.assertEqual(503, status)
        self.assertEqual(["repository"], body["checks"])


if __name__ == "__main__":
    unittest.main()
