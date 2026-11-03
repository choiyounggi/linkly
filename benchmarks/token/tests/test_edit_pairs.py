"""Edit-pair checks (issue #251): baselines, routes, and the m3/m4 FastAPI afters.

Loud skip as in test_measure_tokens.py / test_equiv_spec.py: tiktoken and
fastapi/httpx live only in benchmarks/token/.venv.

Case <-> source:
  test_before_files_match_their_scenario      <- every *_before is a byte copy of its scenario (no stale baseline)
  test_every_kind_has_a_baseline               <- EDIT_BASELINES covers EDIT_KINDS
  test_edit_files_expose_expected_routes       <- each before/after FastAPI file builds the planned route set
  test_m3_save_product_empty_repository        <- m3 lnpl_after SaveProduct spec (empty repository -> rows Product 1)
  test_m3_save_product_duplicate_conflicts     <- forcing input: `create product` on an existing id
  test_m3_save_product_invalid_payload_is_400  <- forcing input: `validate input`, Integer as string
  test_m4_fulfil_fills_order_cache             <- m4 lnpl_after `find order cached` fills the cache
"""

import importlib.util
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import tiktoken  # noqa: F401

    import measure_tokens

    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

try:
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

NEEDS_TIKTOKEN = unittest.skipUnless(
    HAS_TIKTOKEN,
    "tiktoken not installed — run from benchmarks/token/.venv "
    "(python3.13 -m venv benchmarks/token/.venv && "
    "benchmarks/token/.venv/bin/pip install tiktoken==0.14.0 fastapi httpx pytest)",
)
NEEDS_FASTAPI = unittest.skipUnless(
    HAS_FASTAPI,
    "fastapi/httpx not installed — run from benchmarks/token/.venv "
    "(python3.13 -m venv benchmarks/token/.venv && "
    "benchmarks/token/.venv/bin/pip install tiktoken==0.14.0 fastapi httpx pytest)",
)

EDITS_DIR = Path(__file__).resolve().parent.parent / "edits"
LINKHUB_ROUTES = {("POST", "/bookmarks"), ("GET", "/bookmarks/{bookmark_id}")}
CACHED_ROUTES = {("POST", "/catalog-service/get-product"), ("GET", "/catalog-service/product/{id}")}
CONSUME_ROUTES = {
    ("POST", "/fulfillment-service/fulfill-order"),
    ("GET", "/fulfillment-service/order/{id}"),
    ("GET", "/fulfillment-service/shipment/{id}"),
    ("POST", "/-/events/order-placed"),
}
SCHEDULE_ROUTES = {
    ("POST", "/rollup-service/build-report"),
    ("POST", "/-/schedules/daily-rollup"),
    ("GET", "/rollup-service/report/{id}"),
}
EXPECTED_ROUTES = {
    "m1_note_field": (LINKHUB_ROUTES, LINKHUB_ROUTES),
    "m2_duplicate_guard": (LINKHUB_ROUTES, LINKHUB_ROUTES),
    "m3_add_workflow": (CACHED_ROUTES, CACHED_ROUTES | {("POST", "/catalog-service/save-product")}),
    "m4_cached_read": (CONSUME_ROUTES, CONSUME_ROUTES),
    "m5_timeout_policy": (SCHEDULE_ROUTES, SCHEDULE_ROUTES),
}
PID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # @dataclass under `from __future__ import annotations` looks its module up in sys.modules
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_edit(kind, stage):
    return load(EDITS_DIR / kind / f"fastapi_{stage}.py", f"edit_{kind}_{stage}")


@NEEDS_TIKTOKEN
class EditBaselineTest(unittest.TestCase):
    def test_before_files_match_their_scenario(self):
        for kind in measure_tokens.EDIT_KINDS:
            scenario = measure_tokens.SCENARIOS[measure_tokens.EDIT_BASELINES[kind]]
            for side in ("lnpl", "fastapi"):
                with self.subTest(kind=kind, side=side):
                    before = measure_tokens.EDIT_TASKS[kind][side][0]
                    self.assertEqual(before.read_bytes(), scenario[side].read_bytes())

    def test_every_kind_has_a_baseline(self):
        self.assertEqual(set(measure_tokens.EDIT_BASELINES), set(measure_tokens.EDIT_KINDS))


@NEEDS_FASTAPI
class EditFastapiTest(unittest.TestCase):
    def setUp(self):
        self.m3 = load_edit("m3_add_workflow", "after")
        self.m3_app = self.m3.create_app()
        self.m3_client = TestClient(self.m3_app)

    def test_edit_files_expose_expected_routes(self):
        for kind, (before_routes, after_routes) in EXPECTED_ROUTES.items():
            for stage, expected in (("before", before_routes), ("after", after_routes)):
                with self.subTest(kind=kind, stage=stage):
                    app = load_edit(kind, stage).create_app()
                    routes = {(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods}
                    self.assertEqual(routes, expected)

    def test_m3_save_product_empty_repository(self):
        # spec: given empty repository / when saveProduct / expect completed, rows Product 1
        response = self.m3_client.post("/catalog-service/save-product", json={"id": PID, "stock": 5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "completed"})
        self.assertEqual(self.m3_app.state.store.products, {PID: {"id": PID, "stock": 5}})

    def test_m3_save_product_duplicate_conflicts(self):
        self.m3_app.state.store.products[PID] = {"id": PID, "stock": 1}
        response = self.m3_client.post("/catalog-service/save-product", json={"id": PID, "stock": 5})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "conflict")
        self.assertEqual(self.m3_app.state.store.products, {PID: {"id": PID, "stock": 1}})

    def test_m3_save_product_invalid_payload_is_400(self):
        response = self.m3_client.post("/catalog-service/save-product", json={"id": PID, "stock": "3"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "validation-failed")
        self.assertEqual(len(self.m3_app.state.store.products), 0)

    def test_m4_fulfil_fills_order_cache(self):
        app = load_edit("m4_cached_read", "after").create_app()
        store = app.state.store
        store.orders[PID] = {"id": PID, "status": "placed"}
        response = TestClient(app).post("/fulfillment-service/fulfill-order", json={"id": PID, "status": "placed"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"order:{PID}", store.cache)
        self.assertEqual(store.cache[f"order:{PID}"]["value"], {"id": PID, "status": "placed"})
        self.assertEqual(len(store.shipments), 1)


if __name__ == "__main__":
    unittest.main()
