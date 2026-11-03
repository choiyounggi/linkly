"""FastAPI equivalent of benchmarks/token/scenarios/cached.lnpl (issue #251 token benchmark).
Equivalence: equiv/MAPPING.md section "cached"."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

CACHE_TTL_SECONDS = 5 * 60
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CHECKS = {
    "UUID": lambda v: bool(UUID_PATTERN.match(str(v))),
    "Text": lambda v: isinstance(v, str),
    "Integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "Money": lambda v: True,
}
PRODUCT_FIELDS = {"id": "UUID", "stock": "Integer"}


class WorkflowFailed(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass
class Store:
    products: dict = field(default_factory=dict)
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


def get_row(table: dict, key, entity: str) -> dict:
    row = table.get(key)
    if row is None:
        raise WorkflowFailed(404, "not-found", f"repository read found no row for entity.{entity}")
    return row


def get_product(store: Store, payload: dict) -> dict:
    validate(payload, PRODUCT_FIELDS)
    key = f"product:{payload['id']}"
    entry = store.cache.get(key)
    if entry and entry["expires_at"] > time.monotonic():
        return {"status": "completed"}
    row = get_row(store.products, payload["id"], "product")
    store.cache[key] = {"value": row, "expires_at": time.monotonic() + CACHE_TTL_SECONDS}
    return {"status": "completed"}


def create_product(store: Store, payload: dict) -> None:
    key = payload.get("id")
    if key in store.products:
        raise WorkflowFailed(409, "conflict", "repository create conflicts: entity.product already exists")
    store.products[key] = {n: payload[n] for n in PRODUCT_FIELDS if n in payload}


def save_product(store: Store, payload: dict) -> dict:
    validate(payload, PRODUCT_FIELDS)
    create_product(store, payload)
    return {"status": "completed"}


def create_app() -> FastAPI:
    app = FastAPI(title="cached-fastapi")
    app.state.store = Store()

    def fail(exc: WorkflowFailed) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.detail})

    @app.post("/catalog-service/get-product")
    def get_product_route(payload: dict = Body(...)):
        try:
            return get_product(app.state.store, payload)
        except WorkflowFailed as exc:
            return fail(exc)

    @app.post("/catalog-service/save-product")
    def save_product_route(payload: dict = Body(...)):
        try:
            return save_product(app.state.store, payload)
        except WorkflowFailed as exc:
            return fail(exc)

    @app.get("/catalog-service/product/{id}")
    def get_product_by_id(id: str):
        try:
            return get_row(app.state.store.products, id, "product")
        except WorkflowFailed as exc:
            return fail(exc)

    return app


app = create_app()
