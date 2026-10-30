"""FastAPI equivalent of examples/checkout.lnpl (issue #251 token benchmark).
Equivalence: equiv/MAPPING.md section "checkout"."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from fastapi import Body, FastAPI, Header
from fastapi.responses import JSONResponse

RETRY = 3
TIMEOUT_SECONDS = 3
CACHE_TTL_SECONDS = 5 * 60
SLO_MS = 50
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CHECKS = {
    "UUID": lambda v: bool(UUID_PATTERN.match(str(v))),
    "Text": lambda v: isinstance(v, str),
    "Integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "Money": lambda v: True,
}
PRODUCT_FIELDS = {"id": "UUID", "name": "Text", "stock": "Integer", "price": "Money"}
ORDER_FIELDS = ("id", "quantity", "total", "placedAt")


class WorkflowFailed(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass
class Store:
    products: dict = field(default_factory=dict)
    orders: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)


def validate(payload: dict, fields: dict) -> None:
    for name, type_name in fields.items():
        if name not in payload:
            raise WorkflowFailed(400, "validation-failed", f"missing required field {name!r}")
        value = payload[name]
        if value is None:
            raise WorkflowFailed(400, "validation-failed", f"field {name!r} is null")
        if not CHECKS[type_name](value):
            raise WorkflowFailed(400, "validation-failed", f"field {name!r} is not a valid {type_name}")


def check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise WorkflowFailed(504, "deadline-exceeded", "workflow deadline exceeded")


def with_retry(fn, deadline: float):
    for attempt in range(1 + RETRY):
        check_deadline(deadline)
        try:
            return fn()
        except WorkflowFailed as exc:
            if exc.code != "not-found" or attempt == RETRY:
                raise


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


def checkout(store: Store, payload: dict) -> dict:
    start = time.monotonic()
    deadline = start + TIMEOUT_SECONDS
    check_deadline(deadline)
    validate(payload, PRODUCT_FIELDS)
    row = with_retry(lambda: get_row(store.products, payload.get("id"), "product"), deadline)
    check_deadline(deadline)
    cache_product(store, row)
    skipped = []
    check_deadline(deadline)
    if row["stock"] > 0:
        create_order(store, payload)
    else:
        skipped.append("product.stock > 0")
    elapsed_ms = (time.monotonic() - start) * 1000
    return {"status": "completed", "skipped": skipped, "slo_met": elapsed_ms <= SLO_MS}


def create_app() -> FastAPI:
    app = FastAPI(title="checkout-fastapi")
    app.state.store = Store()

    def fail(exc: WorkflowFailed) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.detail})

    def require_auth(authorization: str | None) -> None:
        if authorization is None:
            raise WorkflowFailed(401, "auth-missing", "the service declares security jwt; send an Authorization header")

    @app.post("/checkout-service/checkout")
    def checkout_route(payload: dict = Body(...), authorization: str | None = Header(default=None)):
        try:
            require_auth(authorization)
            return checkout(app.state.store, payload)
        except WorkflowFailed as exc:
            return fail(exc)

    @app.get("/checkout-service/product/{id}")
    def get_product(id: str, authorization: str | None = Header(default=None)):
        try:
            require_auth(authorization)
            return get_row(app.state.store.products, id, "product")
        except WorkflowFailed as exc:
            return fail(exc)

    @app.get("/checkout-service/order/{id}")
    def get_order(id: str, authorization: str | None = Header(default=None)):
        try:
            require_auth(authorization)
            return get_row(app.state.store.orders, id, "order")
        except WorkflowFailed as exc:
            return fail(exc)

    return app


app = create_app()
