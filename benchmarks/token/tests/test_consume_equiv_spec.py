"""Ported benchmarks/token/scenarios/consume.lnpl behaviour (issue #251), run against the FastAPI port.

Loud skip as in test_equiv_spec.py: fastapi/httpx live only in
benchmarks/token/.venv, so a project-venv run skips with a visible reason.

Case <-> source:
  test_route_shape                          <- `lnpl openapi` paths + `consume by` event route
  test_event_valid_order                    <- FulfillOrder spec 1 (valid order), via the event route
  test_event_empty_repository_rejected      <- FulfillOrder spec 2 (empty repository), via the event route
  test_workflow_route_valid_order           <- FulfillOrder spec 1, via the workflow route
  test_event_invalid_order_rejected         <- forcing input: `validate order` fails inside an event (E7)
  test_workflow_route_invalid_order_is_400  <- forcing input: `validate order` fails on the workflow route
  test_envelope_missing_source_is_invalid   <- forcing input: E1 required attribute missing
  test_envelope_data_base64_is_invalid      <- forcing input: E2 binary data
  test_envelope_data_not_object_is_invalid  <- forcing input: E3 data not an object
  test_envelope_id_256_bytes_too_long       <- forcing input: E9 id over 255 bytes
  test_envelope_id_255_bytes_accepted       <- boundary: id of exactly 255 bytes (E5)
  test_get_order_by_id                      <- derived GET /fulfillment-service/order/{id}
  test_get_shipment_by_id                   <- derived GET /fulfillment-service/shipment/{id}
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "equiv"))

try:
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    import consume_fastapi

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

NEEDS_FASTAPI = unittest.skipUnless(
    HAS_FASTAPI,
    "fastapi/httpx not installed — run from benchmarks/token/.venv "
    "(python3.13 -m venv benchmarks/token/.venv && "
    "benchmarks/token/.venv/bin/pip install tiktoken==0.14.0 fastapi httpx pytest)",
)

DEFAULT_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
EVENT_PATH = "/-/events/order-placed"
WORKFLOW_PATH = "/fulfillment-service/fulfill-order"


@NEEDS_FASTAPI
class ConsumeEquivSpecTest(unittest.TestCase):
    def setUp(self):
        self.app = consume_fastapi.create_app()
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.pid = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    def seed(self):
        row = {"id": self.pid, "status": "placed"}
        self.store.orders[self.pid] = row
        return row

    def envelope(self, **overrides):
        envelope = {
            "specversion": "1.0",
            "id": "evt-1",
            "source": "urn:test",
            "type": "OrderPlaced",
            "data": {"id": self.pid, "status": "placed"},
        }
        envelope.update(overrides)
        return envelope

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.json()["code"], code)

    def test_route_shape(self):
        routes = {(m, r.path) for r in self.app.routes if isinstance(r, APIRoute) for m in r.methods}
        self.assertEqual(
            routes,
            {
                ("POST", WORKFLOW_PATH),
                ("GET", "/fulfillment-service/order/{id}"),
                ("GET", "/fulfillment-service/shipment/{id}"),
                ("POST", EVENT_PATH),
            },
        )
        others = {r.path for r in self.app.routes if not isinstance(r, APIRoute)}
        self.assertLessEqual(others, DEFAULT_ROUTES)

    def test_event_valid_order(self):
        # spec: given valid order / when fulfillOrder / expect completed, rows Shipment 1
        self.seed()
        response = self.client.post(EVENT_PATH, json=self.envelope())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "completed"})
        self.assertEqual(self.store.shipments, {self.pid: {"id": self.pid, "status": "placed"}})

    def test_event_empty_repository_rejected(self):
        # spec: given empty repository / when fulfillOrder / expect failed, rows Shipment 0
        response = self.client.post(EVENT_PATH, json=self.envelope())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json(),
            {"code": "event-rejected", "detail": "repository read found no row for entity.order"},
        )
        self.assertEqual(len(self.store.shipments), 0)

    def test_workflow_route_valid_order(self):
        row = self.seed()
        response = self.client.post(WORKFLOW_PATH, json=row)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.store.shipments), 1)

    def test_event_invalid_order_rejected(self):
        self.seed()
        response = self.client.post(EVENT_PATH, json=self.envelope(data={"id": self.pid}))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json(),
            {"code": "event-rejected", "detail": "missing required field 'status'"},
        )
        self.assertEqual(len(self.store.shipments), 0)

    def test_workflow_route_invalid_order_is_400(self):
        self.seed()
        response = self.client.post(WORKFLOW_PATH, json={"id": self.pid})
        self.assert_error(response, 400, "validation-failed")
        self.assertEqual(len(self.store.shipments), 0)

    def test_envelope_missing_source_is_invalid(self):
        self.seed()
        envelope = self.envelope()
        del envelope["source"]
        response = self.client.post(EVENT_PATH, json=envelope)
        self.assert_error(response, 400, "cloudevents-invalid")
        self.assertEqual(len(self.store.shipments), 0)

    def test_envelope_data_base64_is_invalid(self):
        self.seed()
        response = self.client.post(EVENT_PATH, json=self.envelope(data_base64="AAAA"))
        self.assert_error(response, 400, "cloudevents-invalid")
        self.assertEqual(len(self.store.shipments), 0)

    def test_envelope_data_not_object_is_invalid(self):
        self.seed()
        response = self.client.post(EVENT_PATH, json=self.envelope(data=[1]))
        self.assert_error(response, 400, "cloudevents-invalid")
        self.assertEqual(len(self.store.shipments), 0)

    def test_envelope_id_256_bytes_too_long(self):
        self.seed()
        response = self.client.post(EVENT_PATH, json=self.envelope(id="a" * 256))
        self.assert_error(response, 400, "cloudevents-id-too-long")
        self.assertEqual(len(self.store.shipments), 0)

    def test_envelope_id_255_bytes_accepted(self):
        self.seed()
        response = self.client.post(EVENT_PATH, json=self.envelope(id="a" * 255))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.store.shipments), 1)

    def test_get_order_by_id(self):
        row = self.seed()
        response = self.client.get(f"/fulfillment-service/order/{self.pid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), row)
        response = self.client.get("/fulfillment-service/order/00000000-0000-0000-0000-000000000000")
        self.assert_error(response, 404, "not-found")

    def test_get_shipment_by_id(self):
        row = {"id": self.pid, "status": "shipped"}
        self.store.shipments[self.pid] = row
        response = self.client.get(f"/fulfillment-service/shipment/{self.pid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), row)
        response = self.client.get("/fulfillment-service/shipment/00000000-0000-0000-0000-000000000000")
        self.assert_error(response, 404, "not-found")


if __name__ == "__main__":
    unittest.main()
