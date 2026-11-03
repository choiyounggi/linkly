"""FastAPI equivalent of benchmarks/token/scenarios/parallel.lnpl (issue #251 token benchmark).
Equivalence: equiv/MAPPING.md section "parallel"."""

from __future__ import annotations

import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

PARALLEL = 2
CACHE_TTL_SECONDS = 5 * 60
ORDER_FIELDS = ("id", "quantity")


class WorkflowFailed(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass
class Store:
    products: dict = field(default_factory=dict)
    orders: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)


def get_row(table: dict, key, entity: str) -> dict:
    row = table.get(key)
    if row is None:
        raise WorkflowFailed(404, "not-found", f"repository read found no row for entity.{entity}")
    return row


def cache_product(store: Store, row: dict) -> None:
    store.cache[f"product:{row['id']}"] = {"value": row, "expires_at": time.monotonic() + CACHE_TTL_SECONDS}


def create_order(store: Store, payload: dict) -> None:
    key = payload.get("id")
    if key in store.orders:
        raise WorkflowFailed(409, "conflict", "repository create conflicts: entity.order already exists")
    store.orders[key] = {n: payload[n] for n in ORDER_FIELDS if n in payload}


def restock(store: Store, payload: dict) -> dict:
    row = get_row(store.products, payload.get("id"), "product")
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        futures = [pool.submit(cache_product, store, row), pool.submit(create_order, store, payload)]
        done, pending = wait(futures, return_when=FIRST_EXCEPTION)
        for future in pending:
            future.cancel()
    for future in futures:
        if future.done() and future.exception():
            raise future.exception()
    return {"status": "completed"}


def create_app() -> FastAPI:
    app = FastAPI(title="parallel-fastapi")
    app.state.store = Store()

    def fail(exc: WorkflowFailed) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.detail})

    @app.post("/fan-out-service/restock")
    def restock_route(payload: dict = Body(...)):
        try:
            return restock(app.state.store, payload)
        except WorkflowFailed as exc:
            return fail(exc)

    @app.get("/fan-out-service/product/{id}")
    def get_product(id: str):
        try:
            return get_row(app.state.store.products, id, "product")
        except WorkflowFailed as exc:
            return fail(exc)

    @app.get("/fan-out-service/order/{id}")
    def get_order(id: str):
        try:
            return get_row(app.state.store.orders, id, "order")
        except WorkflowFailed as exc:
            return fail(exc)

    return app


app = create_app()
