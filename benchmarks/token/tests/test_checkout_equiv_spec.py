"""Ported examples/checkout.lnpl behaviour (issue #251), run against the FastAPI port.

Loud skip as in test_equiv_spec.py: fastapi/httpx live only in
benchmarks/token/.venv, so a project-venv run skips with a visible reason.

Case <-> source:
  test_route_shape                              <- `lnpl openapi examples/checkout.lnpl` paths
  test_checkout_valid_product                   <- Checkout spec block (valid product)
  test_checkout_without_authorization_is_401    <- forcing input: `security jwt`, no header
  test_checkout_empty_repository_is_404         <- forcing input: empty repository
  test_checkout_out_of_stock_guard_skips_create <- forcing input: `when product.stock > 0` false (boundary 0)
  test_checkout_invalid_stock_is_400            <- forcing input: `validate product`, Integer as string
  test_checkout_hyphenless_uuid_is_400          <- forcing input: `validate product`, non-canonical UUID
  test_checkout_money_accepts_any_non_null      <- forcing input: Money is unchecked beyond non-null
  test_get_product_by_id                        <- derived GET /checkout-service/product/{id}
  test_get_order_by_id                          <- derived GET /checkout-service/order/{id}
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "equiv"))

try:
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    import checkout_fastapi

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


@NEEDS_FASTAPI
class CheckoutEquivSpecTest(unittest.TestCase):
    def setUp(self):
        self.app = checkout_fastapi.create_app()
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.auth = {"Authorization": "Bearer any"}
        self.pid = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    def seed(self, stock=5):
        row = {"id": self.pid, "name": "pen", "stock": stock, "price": "12.50"}
        self.store.products[self.pid] = row
        return row

    def checkout(self, payload, headers=None):
        return self.client.post("/checkout-service/checkout", json=payload, headers=headers)

    def test_route_shape(self):
        routes = {(m, r.path) for r in self.app.routes if isinstance(r, APIRoute) for m in r.methods}
        self.assertEqual(
            routes,
            {
                ("POST", "/checkout-service/checkout"),
                ("GET", "/checkout-service/product/{id}"),
                ("GET", "/checkout-service/order/{id}"),
            },
        )
        others = {r.path for r in self.app.routes if not isinstance(r, APIRoute)}
        self.assertLessEqual(others, DEFAULT_ROUTES)

    def test_checkout_valid_product(self):
        # spec: given valid product / when checkout
        # expect completed, cache written, result product.stock > 0, rows Order 1
        payload = self.seed()
        response = self.checkout(payload, self.auth)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["skipped"], [])
        self.assertIs(body["slo_met"], True)
        self.assertEqual(len(self.store.orders), 1)
        self.assertEqual(self.store.orders[self.pid], {"id": self.pid})
        self.assertIn(f"product:{self.pid}", self.store.cache)
        self.assertEqual(self.store.cache[f"product:{self.pid}"]["value"], payload)
        self.assertGreater(self.store.products[self.pid]["stock"], 0)

    def test_checkout_without_authorization_is_401(self):
        payload = self.seed()
        response = self.checkout(payload)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "auth-missing")
        self.assertEqual(len(self.store.orders), 0)
        self.assertEqual(len(self.store.cache), 0)

    def test_checkout_empty_repository_is_404(self):
        payload = {"id": self.pid, "name": "pen", "stock": 5, "price": "12.50"}
        response = self.checkout(payload, self.auth)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"code": "not-found", "detail": "repository read found no row for entity.product"},
        )
        self.assertEqual(len(self.store.orders), 0)
        self.assertEqual(len(self.store.cache), 0)

    def test_checkout_out_of_stock_guard_skips_create(self):
        payload = self.seed(stock=0)
        response = self.checkout(payload, self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["skipped"], ["product.stock > 0"])
        self.assertEqual(len(self.store.orders), 0)
        self.assertIn(f"product:{self.pid}", self.store.cache)

    def test_checkout_invalid_stock_is_400(self):
        payload = dict(self.seed(), stock="3")
        response = self.checkout(payload, self.auth)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"code": "validation-failed", "detail": "field 'stock' is not a valid Integer"},
        )
        self.assertEqual(len(self.store.orders), 0)

    def test_checkout_hyphenless_uuid_is_400(self):
        row = self.seed()
        bare = self.pid.replace("-", "")
        self.store.products[bare] = dict(row, id=bare)
        response = self.checkout(dict(row, id=bare), self.auth)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "validation-failed")
        self.assertEqual(len(self.store.orders), 0)

    def test_checkout_money_accepts_any_non_null(self):
        payload = dict(self.seed(), price={"a": 1})
        response = self.checkout(payload, self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.store.orders), 1)

    def test_get_product_by_id(self):
        row = self.seed()
        path = f"/checkout-service/product/{self.pid}"
        response = self.client.get(path, headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), row)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "auth-missing")
        response = self.client.get("/checkout-service/product/00000000-0000-0000-0000-000000000000", headers=self.auth)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not-found")
        self.assertEqual(len(self.store.products), 1)

    def test_get_order_by_id(self):
        self.store.orders[self.pid] = {"id": self.pid}
        path = f"/checkout-service/order/{self.pid}"
        response = self.client.get(path, headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": self.pid})
        response = self.client.get(path)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "auth-missing")
        response = self.client.get("/checkout-service/order/00000000-0000-0000-0000-000000000000", headers=self.auth)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not-found")
        self.assertEqual(len(self.store.orders), 1)


if __name__ == "__main__":
    unittest.main()
