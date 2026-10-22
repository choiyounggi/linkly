"""Issue #113: `Idempotency-Key` -- a same-key repeat replays the first
request's stored response and does not run the workflow a second time,
whether that first run succeeded or failed (Stripe's contract, D7/r1).

Design (t113.md, r1 -- corrects the plan's original D6, which asked for two
things that cannot both hold): claiming a key (INSERT `in-progress`) commits
immediately, independent of `run_workflow`'s own transaction; the final
disposition is a SEPARATE statement written AFTER `run_workflow` returns, so
neither step is vulnerable to `run_workflow`'s unconditional rollback-on-
failure leaving the key stuck at `in-progress` forever.
"""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest

from lnpl import wsgi
from lnpl.drivers import SqliteRepositoryDriver
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app

from tests.fixtures import VALUE_PAYMENT
from tests.test_ops_surface import JWT_PATH, JWT_SRC
from tests.test_wsgi_contract import call_wsgi

PAYMENT_PATH = "/payment-service/approve"


def compile_source(source, module="mod"):
    return lower(parse(source), module).to_document()


class _CountingSqliteDriver(SqliteRepositoryDriver):
    """Counts `execute()` calls into a list shared across every instance the
    factory hands out -- the decisive proof that a replay does not run the
    workflow a second time: if it had, this counter would grow."""

    def __init__(self, path, calls):
        super().__init__(path)
        self.calls = calls

    def execute(self, entity_id, operation, key):
        self.calls.append((entity_id, operation, key))
        return super().execute(entity_id, operation, key)


class IdempotencyHttpTest(unittest.TestCase):
    """The full path -- HTTP POST -> claim/replay/finish -- via the plain
    WSGI callable, mirroring `test_wsgi_contract.py`'s `call_wsgi` and
    `test_conflict_409.py`'s per-request-fresh-driver convention (a shared
    instance cannot be reused across requests: `_run` closes it after
    every one, same as production's `repository_factory=lambda:
    open_repository(backend)`)."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")
        self.calls = []
        self.doc = compile_source(VALUE_PAYMENT)
        self.app = make_wsgi_app(
            self.doc,
            repository_factory=lambda: _CountingSqliteDriver(self.path, self.calls))

    def _post(self, payload, key=None):
        headers = {} if key is None else {"Idempotency-Key": key}
        return call_wsgi(self.app, "POST", PAYMENT_PATH,
                         body=json.dumps(payload).encode("utf-8"),
                         headers=headers)

    # -- normal --------------------------------------------------------

    def test_same_key_replays_the_first_response_without_reexecuting(self):
        payload = {"id": "p-1", "amount": 500}

        first_status, _, first_body = self._post(payload, key="k1")
        creates_after_first = sum(1 for c in self.calls if c[1] == "create")
        second_status, _, second_body = self._post(payload, key="k1")

        self.assertEqual(200, first_status)
        self.assertEqual(200, second_status)
        self.assertEqual(first_body, second_body)          # byte-identical
        # No second `create` reached the store -- the decisive proof.
        self.assertEqual(creates_after_first,
                         sum(1 for c in self.calls if c[1] == "create"))

    def test_a_new_key_executes_independently(self):
        payload1 = {"id": "p-1", "amount": 500}
        payload2 = {"id": "p-2", "amount": 500}

        _, _, body1 = self._post(payload1, key="k1")
        _, _, body2 = self._post(payload2, key="k2")

        self.assertNotEqual(body1["correlation_id"], body2["correlation_id"])

    # -- error: failed runs are ALSO replayed (D7, Stripe contract) ----

    def test_a_failed_first_request_is_replayed_not_reexecuted(self):
        """The decisive proof for D7/r1: pre-seed a conflict so the FIRST
        keyed request fails (409); then remove the row that caused the
        conflict. If a resend with the same key actually re-executed, it
        would now succeed (200) since nothing blocks it anymore. Getting
        the SAME 409 back proves the stored failure was replayed, not a
        fresh run."""
        payload = {"id": "p-dup", "amount": 500}
        seed = SqliteRepositoryDriver(self.path)
        seed.execute("entity.payment", "create", "entity.payment#p-dup")
        seed.close()

        first_status, _, first_body = self._post(payload, key="kf")

        clear = SqliteRepositoryDriver(self.path)
        clear.execute("entity.payment", "delete", "entity.payment#p-dup")
        clear.close()
        second_status, _, second_body = self._post(payload, key="kf")

        self.assertEqual(409, first_status)
        self.assertEqual("conflict", first_body["code"])
        self.assertEqual(409, second_status)
        self.assertEqual(first_body, second_body)

    # -- in-progress: D8 -------------------------------------------------

    def test_concurrent_same_key_gets_409_idempotency_in_progress(self):
        """Simulates the race directly at the claim layer (issue #113, D8):
        another connection has already claimed the key and not finished."""
        claimant = SqliteRepositoryDriver(self.path)
        status, _ = claimant.idempotency_begin(
            "wf.approve", "in-flight", int(time.time() * 1000), 24 * 3600 * 1000)
        self.assertEqual("started", status)

        status_code, _, body = self._post({"id": "p-2", "amount": 500},
                                          key="in-flight")

        self.assertEqual(409, status_code)
        self.assertEqual("idempotency-in-progress", body["code"])
        claimant.close()

    # -- TTL: D10 ----------------------------------------------------------

    def test_an_expired_claim_is_treated_as_a_fresh_miss(self):
        app = make_wsgi_app(
            self.doc,
            repository_factory=lambda: _CountingSqliteDriver(self.path, self.calls),
            idempotency_ttl_ms=1)
        payload = {"id": "p-3", "amount": 500}
        headers = {"Idempotency-Key": "expiring"}

        status1, _, body1 = call_wsgi(app, "POST", PAYMENT_PATH,
                                      body=json.dumps(payload).encode("utf-8"),
                                      headers=headers)
        time.sleep(0.05)
        status2, _, body2 = call_wsgi(app, "POST", PAYMENT_PATH,
                                      body=json.dumps(payload).encode("utf-8"),
                                      headers=headers)

        self.assertEqual(200, status1)
        # A fresh execution against the same already-created id conflicts --
        # exactly what re-running (not replaying) produces, which is the
        # point: the TTL made the second call a genuine miss.
        self.assertEqual(409, status2)
        self.assertNotEqual(body1["correlation_id"], body2.get("correlation_id"))

    # -- boundary: no key is byte-identical to pre-#113 (D9) --------------

    def test_no_key_is_unaffected_and_every_request_executes(self):
        payload = {"id": "p-4", "amount": 500}

        s1, _, b1 = self._post(payload, key=None)
        s2, _, b2 = self._post(payload, key=None)

        self.assertEqual(200, s1)
        # No key -> no dedup -- the second identical create conflicts, the
        # same pre-#113 behavior (now surfaced as 409 rather than 500, but
        # that mapping is Task 01's, not this feature's -- the point here is
        # that idempotency plays no part when no key is sent).
        self.assertEqual(409, s2)

    # -- boundary: empty-string keys and the 255-byte bound are decided and tested ---

    def test_an_empty_string_key_is_a_valid_literal_key(self):
        """Decided (not a special case): `Idempotency-Key: ` with an empty
        value is a key like any other, keyed as the literal empty string --
        no crash, no silent ignore."""
        payload = {"id": "p-5", "amount": 500}

        s1, _, b1 = self._post(payload, key="")
        s2, _, b2 = self._post(payload, key="")

        self.assertEqual(200, s1)
        self.assertEqual(200, s2)
        self.assertEqual(b1, b2)


class IdempotencyKeyBoundTest(unittest.TestCase):
    """Issue #258 (M23): an `Idempotency-Key` longer than 255 bytes is a 400
    `idempotency-key-too-long` before any repository driver is opened.
    `make_wsgi_app` itself opens one driver at construction (the #228 boot
    probe), so "no driver opened" is counted across the request only."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")
        self.calls = []
        self.opened = []
        path, calls, opened = self.path, self.calls, self.opened

        def factory():
            opened.append(1)
            return _CountingSqliteDriver(path, calls)

        self.app = make_wsgi_app(compile_source(VALUE_PAYMENT),
                                 repository_factory=factory)
        self.opened_at_boot = len(self.opened)

    def _post(self, payload, key):
        return call_wsgi(self.app, "POST", PAYMENT_PATH,
                         body=json.dumps(payload).encode("utf-8"),
                         headers={"Idempotency-Key": key})

    def assert_refused_before_any_driver(self, status, headers, body, length):
        self.assertEqual(400, status)
        self.assertEqual("application/problem+json", headers["Content-Type"])
        self.assertEqual("idempotency-key-too-long", body["code"])
        self.assertEqual(400, body["status"])
        self.assertEqual(wsgi._TITLES["idempotency-key-too-long"], body["title"])
        self.assertEqual(
            "Idempotency-Key is %d bytes long; the maximum is 255 bytes" % length,
            body["detail"])
        self.assertNotIn("correlation_id", body)
        self.assertEqual(self.opened_at_boot, len(self.opened))
        self.assertEqual([], self.calls)

    def test_error_a_256_byte_key_is_400_before_any_driver_is_opened(self):
        status, headers, body = self._post({"id": "p-256", "amount": 500}, "a" * 256)
        self.assert_refused_before_any_driver(status, headers, body, 256)

    def test_error_the_4096_byte_key_that_used_to_be_accepted_is_now_400(self):
        status, headers, body = self._post({"id": "p-6", "amount": 500}, "k" * 4096)
        self.assert_refused_before_any_driver(status, headers, body, 4096)

    def test_boundary_a_255_byte_key_is_claimed_and_replayed(self):
        payload = {"id": "p-255", "amount": 500}

        first_status, _, first_body = self._post(payload, "b" * 255)
        creates_after_first = sum(1 for c in self.calls if c[1] == "create")
        second_status, _, second_body = self._post(payload, "b" * 255)

        self.assertEqual(200, first_status)
        self.assertEqual(200, second_status)
        self.assertEqual(first_body, second_body)
        self.assertEqual(1, creates_after_first)
        self.assertEqual(creates_after_first,
                         sum(1 for c in self.calls if c[1] == "create"))

    def test_boundary_a_multibyte_key_is_counted_in_header_bytes(self):
        # PEP 3333: a WSGI server hands each raw header byte over as one
        # Latin-1 character, so 128 "é" sent as UTF-8 arrive as 256.
        key = "é".encode("utf-8").decode("latin-1") * 128
        self.assertEqual(256, len(key))
        status, headers, body = self._post({"id": "p-mb", "amount": 500}, key)
        self.assert_refused_before_any_driver(status, headers, body, 256)

    def test_boundary_the_fake_backend_refuses_the_same_256_byte_key(self):
        with contextlib.redirect_stderr(io.StringIO()):
            app = make_wsgi_app(compile_source(VALUE_PAYMENT))
        status, _, body = call_wsgi(
            app, "POST", PAYMENT_PATH,
            body=json.dumps({"id": "p-fake", "amount": 500}).encode("utf-8"),
            headers={"Idempotency-Key": "a" * 256})
        self.assertEqual(400, status)
        self.assertEqual("idempotency-key-too-long", body["code"])

    def test_error_authentication_still_runs_before_the_bound(self):
        with contextlib.redirect_stderr(io.StringIO()):
            app = make_wsgi_app(compile_source(JWT_SRC))
        status, _, body = call_wsgi(app, "POST", JWT_PATH, body=b"{}",
                                    headers={"Idempotency-Key": "a" * 256})
        self.assertEqual(401, status)
        self.assertEqual("auth-missing", body["code"])


class IdempotencyFakeBackendTest(unittest.TestCase):
    """D11: the `fake` backend cannot durably record a claim (a fresh store
    is seeded per request), so idempotency is disabled and a startup
    warning fires -- never a crash, never a silent wrong answer."""

    def test_fake_backend_warns_once_at_construction(self):
        doc = compile_source(VALUE_PAYMENT)
        buf = io.StringIO()
        import sys
        real_stderr = sys.stderr
        sys.stderr = buf
        try:
            make_wsgi_app(doc)
        finally:
            sys.stderr = real_stderr
        self.assertIn("Idempotency-Key support is disabled", buf.getvalue())
        self.assertIn("fake", buf.getvalue())

    def test_fake_backend_ignores_the_header_and_always_executes(self):
        doc = compile_source(VALUE_PAYMENT)
        app = make_wsgi_app(doc)
        payload = {"id": "p-1", "amount": 500}

        _, _, body1 = call_wsgi(app, "POST", PAYMENT_PATH,
                                body=json.dumps(payload).encode("utf-8"),
                                headers={"Idempotency-Key": "k1"})
        _, _, body2 = call_wsgi(app, "POST", PAYMENT_PATH,
                                body=json.dumps(payload).encode("utf-8"),
                                headers={"Idempotency-Key": "k1"})

        self.assertNotEqual(body1["correlation_id"], body2["correlation_id"])


class IdempotencyDriverTest(unittest.TestCase):
    """Unit-level proof for the claim/replay/finish state machine itself,
    independent of the HTTP layer."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")

    def test_a_second_claim_while_in_progress_sees_in_progress(self):
        d1 = SqliteRepositoryDriver(self.path)
        d2 = SqliteRepositoryDriver(self.path)
        now = int(time.time() * 1000)

        first = d1.idempotency_begin("wf.x", "k", now, 3600_000)
        second = d2.idempotency_begin("wf.x", "k", now, 3600_000)

        self.assertEqual(("started", None), first)
        self.assertEqual(("in-progress", None), second)
        d1.close()
        d2.close()

    def test_finish_makes_the_next_claim_replay_the_stored_result(self):
        d = SqliteRepositoryDriver(self.path)
        now = int(time.time() * 1000)
        d.idempotency_begin("wf.x", "k", now, 3600_000)

        d.idempotency_finish("wf.x", "k", 500, {"failure_reason": "boom"})
        result = d.idempotency_begin("wf.x", "k", now, 3600_000)

        self.assertEqual(("done", (500, {"failure_reason": "boom"})), result)
        d.close()

    def test_release_without_a_prior_claim_is_a_noop(self):
        """issue #118, D6 r2: releasing a key nothing ever claimed must not
        raise -- the escape/503 paths call this unconditionally whenever a
        claim exists, and a DELETE matching zero rows is exactly the shape
        that makes "no claim to release" and "already released" the same
        harmless case."""
        d = SqliteRepositoryDriver(self.path)
        d.idempotency_release("wf.x", "never-claimed")   # must not raise
        result = d.idempotency_begin("wf.x", "never-claimed",
                                     int(time.time() * 1000), 3600_000)
        self.assertEqual(("started", None), result)   # still a fresh miss
        d.close()

    def test_release_after_begin_lets_the_next_claim_start_fresh(self):
        """The whole point of D6 r2: releasing an in-progress claim clears
        it immediately -- unlike an expired claim (D10), this does not wait
        for the TTL. A `("started", None)` right after release proves the
        row is gone, not merely reachable at some future time."""
        d = SqliteRepositoryDriver(self.path)
        now = int(time.time() * 1000)
        d.idempotency_begin("wf.x", "k", now, 3600_000)

        d.idempotency_release("wf.x", "k")
        result = d.idempotency_begin("wf.x", "k", now, 3600_000)

        self.assertEqual(("started", None), result)
        d.close()
