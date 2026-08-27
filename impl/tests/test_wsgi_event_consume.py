"""`POST /-/events/<slug>` — the CloudEvents ingress route for `consume by`
(issue #118, D4-D7).

Same reserved space and merge pattern as `/-/schedules/<slug>` (issue #81):
kept out of `build_routes`'s OpenAPI-contract assertion, same auth lookup
(the CONSUMING workflow's own owning service's `security` declaration).

D5 — the request body must be a CloudEvents v1.0 structured-mode envelope:
`specversion`/`id`/`source`/`type` non-empty strings, `specversion == "1.0"`,
an optional `datacontenttype` accepted only as `application/json`, no
`data_base64` (binary mode refused). Anything else -> 400.

D6 — `id` is the idempotency key, reusing #113's `lnpl_idempotency` table/
API/TTL exactly: a redelivered `id` replays the first stored response
instead of re-running the workflow.

D7 — the execution outcome maps to exactly one of three buckets: success
-> 200; a transient failure (deadline, or a failed step whose effect is a
`RepositoryCall`/`NetworkCall` — the two effect kinds a `DriverError` funnels
through) -> 503 + `Retry-After: 1`; anything else (Validation rejection,
business/guard RunError, conflict) -> 422, permanent.
"""

import json
import os
import tempfile
import time
import unittest

from lnpl.drivers import DriverError, SqliteRepositoryDriver
from lnpl.interp import FakeRepository
from lnpl.lower import lower
from lnpl.openapi import generate
from lnpl.parser import parse
from lnpl.wsgi import build_event_consume_routes, make_wsgi_app

from tests.test_wsgi_contract import call_wsgi

EVENTS_PATH_VALIDATE = "/-/events/order-validated"
EVENTS_PATH_CREATE = "/-/events/order-created"

SRC = """
capability postgres

entity Order
    field
        id UUID
        amount Integer

service OrderService

event OrderValidated
    consume by ValidateOrder

event OrderCreated
    consume by CreateOrder

event OrderNoted

workflow ValidateOrder
    validate order

workflow CreateOrder
    create order
"""

# The consuming workflow's owning service declares `security jwt` (issue
# #118, D4: the SAME auth rule the workflow's own POST route already uses).
SECURED_SRC = """
capability postgres

entity Order
    field
        id UUID

service OrderService
    security
        jwt

event OrderValidated
    consume by ValidateOrder

workflow ValidateOrder
    validate order
"""


def _doc(src, module="t"):
    return lower(parse(src), module).to_document()


def _envelope(event_id="evt-1", event_type="OrderValidated", data=None, **extra):
    body = {"specversion": "1.0", "id": event_id, "source": "test",
           "type": event_type}
    if data is not None:
        body["data"] = data
    body.update(extra)
    return body


def _post(app, path, envelope):
    return call_wsgi(app, "POST", path,
                     body=json.dumps(envelope).encode("utf-8"))


class TestRouteRegistration(unittest.TestCase):
    """D4 — the route table, and its OpenAPI carve-out."""

    def test_a_consume_event_gets_a_reserved_space_route(self):
        doc = _doc(SRC)
        routes = build_event_consume_routes(doc)
        self.assertIn(EVENTS_PATH_VALIDATE, routes)
        route = routes[EVENTS_PATH_VALIDATE]
        self.assertEqual("event-consume", route["kind"])
        self.assertEqual("wf.validate.order", route["workflow"])

    def test_an_event_without_consume_by_gets_no_route(self):
        doc = _doc(SRC)
        routes = build_event_consume_routes(doc)
        self.assertNotIn("/-/events/order-noted", routes)

    def test_boundary_no_consume_events_at_all_yields_an_empty_table(self):
        doc = _doc("entity User\n    field\n        id UUID\n"
                   "service S\nworkflow W\n    load user\n")
        self.assertEqual({}, build_event_consume_routes(doc))

    def test_the_route_is_kept_out_of_the_openapi_contract(self):
        doc = _doc(SRC)
        # `make_wsgi_app`'s own `build_routes` assertion would already have
        # raised at construction if this route leaked into the contract
        # check; this asserts the positive fact directly too.
        self.assertNotIn(EVENTS_PATH_VALIDATE, generate(doc)["paths"])

    def test_undeclared_slug_is_404(self):
        app = make_wsgi_app(_doc(SRC))
        status, _headers, body = _post(app, "/-/events/no-such-event",
                                       _envelope())
        self.assertEqual(404, status)
        self.assertEqual("not-found", body["code"])

    def test_auth_is_inherited_from_the_consuming_workflows_service(self):
        app = make_wsgi_app(_doc(SECURED_SRC))
        status, _headers, body = _post(app, EVENTS_PATH_VALIDATE, _envelope())
        self.assertEqual(401, status)
        self.assertEqual("auth-missing", body["code"])


class TestEnvelopeValidation(unittest.TestCase):
    """D5 — the CloudEvents structured-mode envelope."""

    def setUp(self):
        self.app = make_wsgi_app(_doc(SRC))

    def test_normal_a_valid_envelope_is_accepted(self):
        status, _headers, body = _post(
            self.app, EVENTS_PATH_VALIDATE,
            _envelope(data={"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b",
                            "amount": 5}))
        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

    def test_missing_required_field_is_400_naming_the_field(self):
        envelope = _envelope()
        del envelope["source"]
        status, _headers, body = _post(self.app, EVENTS_PATH_VALIDATE, envelope)
        self.assertEqual(400, status)
        self.assertEqual("cloudevents-invalid", body["code"])
        self.assertIn("source", body["detail"])

    def test_empty_string_required_field_is_rejected(self):
        status, _headers, body = _post(
            self.app, EVENTS_PATH_VALIDATE, _envelope(event_id=""))
        self.assertEqual(400, status)
        self.assertIn("id", body["detail"])

    def test_wrong_specversion_is_rejected(self):
        status, _headers, body = _post(
            self.app, EVENTS_PATH_VALIDATE, _envelope(specversion="0.3"))
        self.assertEqual(400, status)
        self.assertIn("specversion", body["detail"])

    def test_data_base64_binary_mode_is_rejected(self):
        envelope = _envelope()
        envelope["data_base64"] = "eyJhIjogMX0="
        status, _headers, body = _post(self.app, EVENTS_PATH_VALIDATE, envelope)
        self.assertEqual(400, status)
        self.assertIn("data_base64", body["detail"])

    def test_datacontenttype_non_string_is_rejected_not_a_500(self):
        # Regression: `.split(";", 1)` on a non-string value raised an
        # uncaught AttributeError before this was guarded -- a malformed
        # envelope must still get a clean 400, never a crash.
        status, _headers, body = _post(
            self.app, EVENTS_PATH_VALIDATE, _envelope(datacontenttype=123))
        self.assertEqual(400, status)
        self.assertIn("datacontenttype", body["detail"])

    def test_datacontenttype_other_than_application_json_is_rejected(self):
        status, _headers, body = _post(
            self.app, EVENTS_PATH_VALIDATE,
            _envelope(datacontenttype="application/xml"))
        self.assertEqual(400, status)
        self.assertIn("datacontenttype", body["detail"])

    def test_datacontenttype_application_json_with_parameters_is_accepted(self):
        status, _headers, _body = _post(
            self.app, EVENTS_PATH_VALIDATE,
            _envelope(datacontenttype="application/json; charset=utf-8",
                     data={"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b",
                          "amount": 1}))
        self.assertEqual(200, status)

    def test_boundary_absent_data_defaults_to_an_empty_object(self):
        # `ValidateOrder` runs `validate order` against `{}` -- no `id`
        # field at all fails semantic-types the same way a wrong-typed one
        # does (422, D7), proving `data` really defaulted to `{}` and the
        # route did not choke on its absence.
        status, _headers, body = _post(self.app, EVENTS_PATH_VALIDATE,
                                       _envelope())
        self.assertEqual(422, status)
        self.assertEqual("event-rejected", body["code"])

    def test_non_object_data_is_rejected(self):
        status, _headers, body = _post(
            self.app, EVENTS_PATH_VALIDATE, _envelope(data="not-an-object"))
        self.assertEqual(400, status)
        self.assertIn("data", body["detail"])


class TestExecutionOutcomes(unittest.TestCase):
    """D7 — the 3-way status contract."""

    def test_success_is_200(self):
        app = make_wsgi_app(_doc(SRC))
        status, _headers, body = _post(
            app, EVENTS_PATH_VALIDATE,
            _envelope(data={"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b",
                            "amount": 1}))
        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

    def test_permanent_validation_failure_is_422(self):
        app = make_wsgi_app(_doc(SRC))
        status, _headers, body = _post(
            app, EVENTS_PATH_VALIDATE, _envelope(data={"id": "not-a-uuid"}))
        self.assertEqual(422, status)
        self.assertEqual("event-rejected", body["code"])

    def test_create_conflict_is_422_not_503(self):
        """D7 names a create conflict explicitly as PERMANENT — regression
        for a real bug: a conflict's failed step still carries a
        `RepositoryCall` effect, so a naive effects-only check misclassifies
        it as transient (503) and the relay retries forever, and a 503
        never finalizes the idempotency claim (D6) so it can never even
        replay cleanly either. Two envelopes, same `data.id`, same shared
        repository instance (a fresh one per request would never conflict).
        """
        shared_repo = FakeRepository()
        app = make_wsgi_app(_doc(SRC), repository_factory=lambda: shared_repo)
        first_status, _h1, _b1 = _post(
            app, EVENTS_PATH_CREATE,
            _envelope(event_id="evt-1", event_type="OrderCreated",
                     data={"id": "dup-order", "amount": 1}))
        second_status, _h2, second_body = _post(
            app, EVENTS_PATH_CREATE,
            _envelope(event_id="evt-2", event_type="OrderCreated",
                     data={"id": "dup-order", "amount": 2}))

        self.assertEqual(200, first_status)
        self.assertEqual(422, second_status)
        self.assertEqual("event-rejected", second_body["code"])

    def test_transient_driver_error_is_503_with_retry_after(self):
        class _AlwaysFailsRepository(FakeRepository):
            def execute(self, entity_id, operation, key):
                if operation == "create":
                    raise DriverError("the store is unreachable")
                return super().execute(entity_id, operation, key)

        app = make_wsgi_app(_doc(SRC),
                            repository_factory=_AlwaysFailsRepository)
        status, headers, body = _post(
            app, EVENTS_PATH_CREATE,
            _envelope(event_type="OrderCreated",
                     data={"id": "ord-1", "amount": 1}))
        self.assertEqual(503, status)
        self.assertEqual("event-retry-later", body["code"])
        self.assertEqual("1", headers["Retry-After"])

    def test_boundary_workflow_escape_is_also_transient_not_dropped(self):
        """An unexpected exception (not a normal `RunError`) must still get
        a well-formed 503 -- never an unhandled 500/crash out of the WSGI
        callable (mirrors `_respond`'s own escape handling)."""
        class _Explodes(FakeRepository):
            def execute(self, entity_id, operation, key):
                raise RuntimeError("boom")

        app = make_wsgi_app(_doc(SRC), repository_factory=_Explodes)
        status, headers, body = _post(
            app, EVENTS_PATH_CREATE,
            _envelope(event_type="OrderCreated", data={"id": "ord-1"}))
        self.assertEqual(503, status)
        self.assertEqual("event-retry-later", body["code"])
        self.assertEqual("1", headers["Retry-After"])


class TestIdempotency(unittest.TestCase):
    """D6 — same CloudEvents `id` redelivered -> replay, not a re-run."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")
        self.calls = []

    def _counting_app(self):
        calls = self.calls
        path = self.path

        class _CountingSqliteDriver(SqliteRepositoryDriver):
            def __init__(self):
                super().__init__(path)

            def execute(self, entity_id, operation, key):
                calls.append(operation)
                return super().execute(entity_id, operation, key)

        return make_wsgi_app(_doc(SRC), repository_factory=_CountingSqliteDriver)

    def test_same_id_redelivered_after_success_replays_without_rerunning(self):
        app = self._counting_app()
        envelope = _envelope(
            data={"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b", "amount": 1})

        first_status, _h, first_body = _post(app, EVENTS_PATH_VALIDATE, envelope)
        calls_after_first = len(self.calls)
        second_status, _h2, second_body = _post(app, EVENTS_PATH_VALIDATE, envelope)

        self.assertEqual(200, first_status)
        self.assertEqual(200, second_status)
        self.assertEqual(first_body, second_body)
        self.assertEqual(calls_after_first, len(self.calls))   # no re-run

    def test_same_id_redelivered_after_a_permanent_rejection_replays(self):
        app = self._counting_app()
        envelope = _envelope(data={"id": "not-a-uuid"})

        first_status, _h, first_body = _post(app, EVENTS_PATH_VALIDATE, envelope)
        second_status, _h2, second_body = _post(app, EVENTS_PATH_VALIDATE, envelope)

        self.assertEqual(422, first_status)
        self.assertEqual(422, second_status)
        self.assertEqual(first_body, second_body)

    def test_a_new_id_executes_independently(self):
        app = self._counting_app()
        status1, _h, _b1 = _post(app, EVENTS_PATH_VALIDATE, _envelope(
            event_id="evt-1",
            data={"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b", "amount": 1}))
        status2, _h2, _b2 = _post(app, EVENTS_PATH_VALIDATE, _envelope(
            event_id="evt-2",
            data={"id": "9c858901-8100-4b7f-a91c-c0b1c3ab6bb1", "amount": 2}))
        self.assertEqual(200, status1)
        self.assertEqual(200, status2)

    def test_a_transient_outcome_releases_the_claim_so_redelivery_reruns(self):
        """issue #118, D6 r2: a 503 RELEASES the idempotency claim (neither
        finishing it -- which would make #113 replay 503 forever for this
        key -- nor leaving it merely unfinished, which would strand the
        claim `in-progress` until the TTL, default 24h, turning one
        transient failure into an hours-long outage for this event id).
        The next delivery of the SAME CloudEvents id must therefore get a
        FRESH run, not a 409 collision and not a replayed 503 -- and that
        fresh run can actually succeed once the transient condition
        clears, which is the whole reason 503 exists."""
        path = self.path
        attempts = []

        class _FailsOnce(SqliteRepositoryDriver):
            def __init__(self):
                super().__init__(path)

            def execute(self, entity_id, operation, key):
                if operation == "create":
                    attempts.append(1)
                    if len(attempts) == 1:
                        raise DriverError("the store is unreachable")
                return super().execute(entity_id, operation, key)

        app = make_wsgi_app(_doc(SRC), repository_factory=_FailsOnce)
        envelope = _envelope(event_type="OrderCreated",
                             data={"id": "ord-1", "amount": 1})

        first_status, _h, _b = _post(app, EVENTS_PATH_CREATE, envelope)
        second_status, _h2, second_body = _post(app, EVENTS_PATH_CREATE, envelope)

        self.assertEqual(503, first_status)
        self.assertEqual(200, second_status)
        self.assertEqual("completed", second_body["status"])
        self.assertEqual(2, len(attempts))   # genuinely re-ran, not replayed

    def test_an_exception_escape_also_releases_the_claim(self):
        """The escape path (an exception `run_workflow` itself does not
        catch) is 503 too, and must release exactly like the normal 503
        branch -- proven the same way: redelivery gets a fresh run that can
        succeed, not a 409 or a replay."""
        path = self.path
        attempts = []

        class _ExplodesOnce(SqliteRepositoryDriver):
            def __init__(self):
                super().__init__(path)

            def execute(self, entity_id, operation, key):
                if operation == "create":
                    attempts.append(1)
                    if len(attempts) == 1:
                        raise RuntimeError("boom")
                return super().execute(entity_id, operation, key)

        app = make_wsgi_app(_doc(SRC), repository_factory=_ExplodesOnce)
        envelope = _envelope(event_type="OrderCreated",
                             data={"id": "ord-2", "amount": 1})

        first_status, _h, _b = _post(app, EVENTS_PATH_CREATE, envelope)
        second_status, _h2, second_body = _post(app, EVENTS_PATH_CREATE, envelope)

        self.assertEqual(503, first_status)
        self.assertEqual(200, second_status)
        self.assertEqual("completed", second_body["status"])
        self.assertEqual(2, len(attempts))

    def test_a_genuinely_concurrent_in_progress_claim_still_gets_409(self):
        """The release fix must not blur the OTHER meaning `in-progress`
        still carries: two requests racing the SAME key at the SAME time
        (not a sequential retry after a 503) is a real collision, and the
        second one must still be refused -- proven directly at the driver
        level, matching `test_idempotency.py`'s own concurrent-claim test,
        since reproducing a true race over HTTP is not deterministic."""
        driver = SqliteRepositoryDriver(self.path)
        now = int(time.time() * 1000)
        first = driver.idempotency_begin("wf.x", "concurrent-key", now, 3600_000)
        second = driver.idempotency_begin("wf.x", "concurrent-key", now, 3600_000)
        self.assertEqual(("started", None), first)
        self.assertEqual(("in-progress", None), second)
        driver.close()

    def test_fake_backend_has_no_dedup_and_always_reexecutes(self):
        app = make_wsgi_app(_doc(SRC))    # no repository_factory -> fake
        envelope = _envelope(
            data={"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b", "amount": 1})

        status1, _h, body1 = _post(app, EVENTS_PATH_VALIDATE, envelope)
        status2, _h2, body2 = _post(app, EVENTS_PATH_VALIDATE, envelope)

        self.assertEqual(200, status1)
        self.assertEqual(200, status2)
        # Independently executed -- a fresh correlation_id each time, the
        # same "no store, no dedup" signal `test_idempotency.py` pins for
        # the general workflow route.
        self.assertNotEqual(body1["correlation_id"], body2["correlation_id"])


if __name__ == "__main__":
    unittest.main()
