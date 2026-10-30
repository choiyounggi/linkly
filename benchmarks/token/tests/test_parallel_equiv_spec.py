"""Ported benchmarks/token/scenarios/parallel.lnpl behaviour (issue #251), run against the FastAPI port.

Loud skip as in test_equiv_spec.py: fastapi/httpx live only in
benchmarks/token/.venv, so a project-venv run skips with a visible reason.

Case <-> source:
  test_route_shape                     <- `lnpl openapi` paths
  test_restock_valid_product           <- Restock spec 1 (valid product)
  test_restock_empty_repository_is_404 <- Restock spec 2 (empty repository)
  test_restock_existing_order_conflicts <- forcing input: `create order` on an existing id inside `parallel`
  test_get_product_by_id               <- derived GET /fan-out-service/product/{id}
  test_get_order_by_id                 <- derived GET /fan-out-service/order/{id}
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "equiv"))

try:
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    import parallel_fastapi

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
RESTOCK_PATH = "/fan-out-service/restock"


@NEEDS_FASTAPI
class ParallelEquivSpecTest(unittest.TestCase):
    def setUp(self):
        self.app = parallel_fastapi.create_app()
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.pid = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    def seed(self):
        row = {"id": self.pid, "stock": 5}
        self.store.products[self.pid] = row
        return row

    def test_route_shape(self):
        routes = {(m, r.path) for r in self.app.routes if isinstance(r, APIRoute) for m in r.methods}
        self.assertEqual(
            routes,
            {
                ("POST", RESTOCK_PATH),
                ("GET", "/fan-out-service/product/{id}"),
                ("GET", "/fan-out-service/order/{id}"),
            },
        )
        others = {r.path for r in self.app.routes if not isinstance(r, APIRoute)}
        self.assertLessEqual(others, DEFAULT_ROUTES)

    def test_restock_valid_product(self):
        # spec: given valid product / when restock / expect completed, rows Order 1, cache written
        row = self.seed()
        response = self.client.post(RESTOCK_PATH, json=row)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "completed"})
        self.assertEqual(self.store.orders, {self.pid: {"id": self.pid}})
        self.assertIn(f"product:{self.pid}", self.store.cache)
        self.assertEqual(self.store.cache[f"product:{self.pid}"]["value"], row)

    def test_restock_empty_repository_is_404(self):
        # spec: given empty repository / when restock / expect failed, rows Order 0
        response = self.client.post(RESTOCK_PATH, json={"id": self.pid, "stock": 5})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"code": "not-found", "detail": "repository read found no row for entity.product"},
        )
        self.assertEqual(len(self.store.orders), 0)
        self.assertEqual(len(self.store.cache), 0)

    def test_restock_existing_order_conflicts(self):
        row = self.seed()
        self.store.orders[self.pid] = {"id": self.pid}
        response = self.client.post(RESTOCK_PATH, json=row)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "conflict")
        self.assertEqual(self.store.orders, {self.pid: {"id": self.pid}})
        # the sibling `cache product` already ran, as in the LNPL interpreter on the same seed
        self.assertIn(f"product:{self.pid}", self.store.cache)

    def test_get_product_by_id(self):
        row = self.seed()
        response = self.client.get(f"/fan-out-service/product/{self.pid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), row)
        response = self.client.get("/fan-out-service/product/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not-found")

    def test_get_order_by_id(self):
        self.store.orders[self.pid] = {"id": self.pid, "quantity": 2}
        response = self.client.get(f"/fan-out-service/order/{self.pid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": self.pid, "quantity": 2})
        response = self.client.get("/fan-out-service/order/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not-found")


if __name__ == "__main__":
    unittest.main()
