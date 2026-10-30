"""Ported benchmarks/token/scenarios/cached.lnpl behaviour (issue #251), run against the FastAPI port.

Loud skip as in test_equiv_spec.py: fastapi/httpx live only in
benchmarks/token/.venv, so a project-venv run skips with a visible reason.

Case <-> source:
  test_route_shape                           <- `lnpl openapi` paths
  test_get_product_valid_product             <- GetProduct spec 1 (valid product)
  test_get_product_empty_repository_is_404   <- GetProduct spec 2 (empty repository)
  test_warm_cache_hit_skips_store            <- forcing input: cold then warm read, store row deleted between
  test_get_product_missing_stock_is_400      <- forcing input: `validate input`, required field missing
  test_get_product_hyphenless_uuid_is_400    <- forcing input: `validate input`, non-canonical UUID
  test_get_product_by_id                     <- derived GET /catalog-service/product/{id}
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "equiv"))

try:
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    import cached_fastapi

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
GET_PATH = "/catalog-service/get-product"


@NEEDS_FASTAPI
class CachedEquivSpecTest(unittest.TestCase):
    def setUp(self):
        self.app = cached_fastapi.create_app()
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.pid = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    def seed(self):
        row = {"id": self.pid, "stock": 5}
        self.store.products[self.pid] = row
        return row

    def test_route_shape(self):
        routes = {(m, r.path) for r in self.app.routes if isinstance(r, APIRoute) for m in r.methods}
        self.assertEqual(routes, {("POST", GET_PATH), ("GET", "/catalog-service/product/{id}")})
        others = {r.path for r in self.app.routes if not isinstance(r, APIRoute)}
        self.assertLessEqual(others, DEFAULT_ROUTES)

    def test_get_product_valid_product(self):
        # spec: given valid product / when getProduct / expect completed, cache written
        row = self.seed()
        response = self.client.post(GET_PATH, json=row)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "completed"})
        self.assertEqual(len(self.store.cache), 1)
        self.assertEqual(self.store.cache[f"product:{self.pid}"]["value"], row)

    def test_get_product_empty_repository_is_404(self):
        # spec: given empty repository / when getProduct / expect failed, rows Product 0
        response = self.client.post(GET_PATH, json={"id": self.pid, "stock": 5})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"code": "not-found", "detail": "repository read found no row for entity.product"},
        )
        self.assertEqual(len(self.store.products), 0)
        self.assertEqual(len(self.store.cache), 0)

    def test_warm_cache_hit_skips_store(self):
        row = self.seed()
        self.assertEqual(self.client.post(GET_PATH, json=row).status_code, 200)
        del self.store.products[self.pid]
        response = self.client.post(GET_PATH, json=row)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.store.cache), 1)
        self.assertEqual(len(self.store.products), 0)

    def test_get_product_missing_stock_is_400(self):
        self.seed()
        response = self.client.post(GET_PATH, json={"id": self.pid})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"code": "validation-failed", "detail": "missing required field 'stock'"},
        )
        self.assertEqual(len(self.store.cache), 0)

    def test_get_product_hyphenless_uuid_is_400(self):
        row = self.seed()
        bare = self.pid.replace("-", "")
        self.store.products[bare] = dict(row, id=bare)
        response = self.client.post(GET_PATH, json=dict(row, id=bare))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "validation-failed")
        self.assertEqual(len(self.store.cache), 0)

    def test_get_product_by_id(self):
        row = self.seed()
        response = self.client.get(f"/catalog-service/product/{self.pid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), row)
        response = self.client.get("/catalog-service/product/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not-found")
        self.assertEqual(len(self.store.cache), 0)


if __name__ == "__main__":
    unittest.main()
