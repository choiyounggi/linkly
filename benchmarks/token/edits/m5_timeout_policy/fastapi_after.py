"""FastAPI equivalent of benchmarks/token/scenarios/schedule.lnpl (issue #251 token benchmark).
Equivalence: equiv/MAPPING.md section "schedule"."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

RETRY = 3
TIMEOUT_SECONDS = 2
SCHEDULE = "daily at 00:00 UTC"


class WorkflowFailed(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass
class Store:
    reports: dict = field(default_factory=dict)


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


def build_report(store: Store, payload: dict) -> dict:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    check_deadline(deadline)
    row = with_retry(lambda: get_row(store.reports, payload.get("id"), "report"), deadline)
    check_deadline(deadline)
    rows = [r for r in store.reports.values() if r["total"] > 0]
    check_deadline(deadline)
    report = dict(row)
    report["total"] = len(rows)
    check_deadline(deadline)
    store.reports[report["id"]] = report
    return {"status": "completed"}


def create_app() -> FastAPI:
    app = FastAPI(title="schedule-fastapi")
    app.state.store = Store()

    def fail(exc: WorkflowFailed) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.detail})

    @app.post("/rollup-service/build-report")
    def build_report_route(payload: dict = Body(...)):
        try:
            return build_report(app.state.store, payload)
        except WorkflowFailed as exc:
            return fail(exc)

    @app.post("/-/schedules/daily-rollup")
    def daily_rollup(payload: dict = Body(...)):
        try:
            return build_report(app.state.store, payload)
        except WorkflowFailed as exc:
            return fail(exc)

    @app.get("/rollup-service/report/{id}")
    def get_report(id: str):
        try:
            return get_row(app.state.store.reports, id, "report")
        except WorkflowFailed as exc:
            return fail(exc)

    return app


app = create_app()
