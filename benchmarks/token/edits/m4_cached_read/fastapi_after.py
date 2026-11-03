"""FastAPI equivalent of benchmarks/token/scenarios/consume.lnpl (issue #251 token benchmark).
Equivalence: equiv/MAPPING.md section "consume"."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

RETRY = 3
CACHE_TTL_SECONDS = 5 * 60
MAX_EVENT_ID_BYTES = 255
ENVELOPE_REQUIRED = ("specversion", "id", "source", "type")
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CHECKS = {
    "UUID": lambda v: bool(UUID_PATTERN.match(str(v))),
    "Text": lambda v: isinstance(v, str),
    "Integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "Money": lambda v: True,
}
ORDER_FIELDS = {"id": "UUID", "status": "Text"}
SHIPMENT_FIELDS = ("id", "status")


class WorkflowFailed(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass
class Store:
    orders: dict = field(default_factory=dict)
    shipments: dict = field(default_factory=dict)
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


def with_retry(fn):
    for attempt in range(1 + RETRY):
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


def create_shipment(store: Store, payload: dict) -> None:
    key = payload.get("id")
    if key in store.shipments:
        raise WorkflowFailed(409, "conflict", "repository create conflicts: entity.shipment already exists")
    store.shipments[key] = {n: payload[n] for n in SHIPMENT_FIELDS if n in payload}


def find_order_cached(store, payload):
    key = f"order:{payload['id']}"
    entry = store.cache.get(key)
    if entry and entry["expires_at"] > time.monotonic():
        return entry["value"]
    row = with_retry(lambda: get_row(store.orders, payload["id"], "order"))
    store.cache[key] = {"value": row, "expires_at": time.monotonic() + CACHE_TTL_SECONDS}
    return row


def fulfill_order(store: Store, payload: dict) -> dict:
    validate(payload, ORDER_FIELDS)
    find_order_cached(store, payload)
    create_shipment(store, payload)
    return {"status": "completed"}


def check_envelope(envelope: dict) -> None:
    for name in ENVELOPE_REQUIRED:
        value = envelope.get(name)
        if not isinstance(value, str) or not value:
            raise WorkflowFailed(400, "cloudevents-invalid", f"envelope attribute {name!r} must be a non-empty string")
    try:
        envelope["id"].encode("utf-8")
    except UnicodeEncodeError:
        raise WorkflowFailed(400, "cloudevents-invalid", "envelope attribute 'id' is not valid UTF-8") from None
    if envelope["specversion"] != "1.0":
        raise WorkflowFailed(400, "cloudevents-invalid", "envelope specversion must be '1.0'")
    if "data_base64" in envelope:
        raise WorkflowFailed(400, "cloudevents-invalid", "binary data (data_base64) is not supported")
    datacontenttype = envelope.get("datacontenttype")
    if datacontenttype is not None and (
        not isinstance(datacontenttype, str) or datacontenttype.split(";", 1)[0].strip() != "application/json"
    ):
        raise WorkflowFailed(400, "cloudevents-invalid", "datacontenttype must be application/json")
    if not isinstance(envelope.get("data", {}), dict):
        raise WorkflowFailed(400, "cloudevents-invalid", "envelope data must be a JSON object")
    if len(envelope["id"].encode("utf-8")) > MAX_EVENT_ID_BYTES:
        raise WorkflowFailed(400, "cloudevents-id-too-long", f"envelope id exceeds {MAX_EVENT_ID_BYTES} bytes")


def create_app() -> FastAPI:
    app = FastAPI(title="consume-fastapi")
    app.state.store = Store()

    def fail(exc: WorkflowFailed) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.detail})

    @app.post("/fulfillment-service/fulfill-order")
    def fulfill_order_route(payload: dict = Body(...)):
        try:
            return fulfill_order(app.state.store, payload)
        except WorkflowFailed as exc:
            return fail(exc)

    @app.get("/fulfillment-service/order/{id}")
    def get_order(id: str):
        try:
            return get_row(app.state.store.orders, id, "order")
        except WorkflowFailed as exc:
            return fail(exc)

    @app.get("/fulfillment-service/shipment/{id}")
    def get_shipment(id: str):
        try:
            return get_row(app.state.store.shipments, id, "shipment")
        except WorkflowFailed as exc:
            return fail(exc)

    @app.post("/-/events/order-placed")
    def order_placed(envelope: dict = Body(...)):
        try:
            check_envelope(envelope)
        except WorkflowFailed as exc:
            return fail(exc)
        try:
            return fulfill_order(app.state.store, envelope.get("data") or {})
        except WorkflowFailed as exc:
            return fail(WorkflowFailed(422, "event-rejected", exc.detail))

    return app


app = create_app()
