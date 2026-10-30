"""Ported benchmarks/token/scenarios/schedule.lnpl behaviour (issue #251), run against the FastAPI port.

Loud skip as in test_equiv_spec.py: fastapi/httpx live only in
benchmarks/token/.venv, so a project-venv run skips with a visible reason.

Case <-> source:
  test_route_shape                     <- `lnpl openapi` paths + `on schedule` trigger route
  test_trigger_valid_report            <- BuildReport spec 1 (valid report), via the trigger route
  test_trigger_empty_repository_is_404 <- BuildReport spec 2 (empty repository)
  test_count_ignores_zero_totals       <- boundary: `list report where total > 0` excludes total 0
  test_workflow_route_matches_trigger  <- forcing input: both POST routes run the same workflow
  test_get_report_by_id                <- derived GET /rollup-service/report/{id}
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "equiv"))

try:
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    import schedule_fastapi

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
TRIGGER_PATH = "/-/schedules/daily-rollup"
WORKFLOW_PATH = "/rollup-service/build-report"


@NEEDS_FASTAPI
class ScheduleEquivSpecTest(unittest.TestCase):
    def setUp(self):
        self.app = schedule_fastapi.create_app()
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.rid = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    def seed(self, rid, total, store=None):
        row = {"id": rid, "total": total}
        (store or self.store).reports[rid] = row
        return row

    def test_route_shape(self):
        routes = {(m, r.path) for r in self.app.routes if isinstance(r, APIRoute) for m in r.methods}
        self.assertEqual(
            routes,
            {("POST", WORKFLOW_PATH), ("POST", TRIGGER_PATH), ("GET", "/rollup-service/report/{id}")},
        )
        others = {r.path for r in self.app.routes if not isinstance(r, APIRoute)}
        self.assertLessEqual(others, DEFAULT_ROUTES)
        self.assertEqual(schedule_fastapi.SCHEDULE, "daily at 00:00 UTC")

    def test_trigger_valid_report(self):
        # spec: given valid report / when buildReport / expect completed, rows Report 1
        self.seed(self.rid, 7)
        response = self.client.post(TRIGGER_PATH, json={"id": self.rid, "total": 7})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "completed"})
        self.assertEqual(len(self.store.reports), 1)
        self.assertEqual(self.store.reports[self.rid]["total"], 1)

    def test_trigger_empty_repository_is_404(self):
        # spec: given empty repository / when buildReport / expect failed, rows Report 0
        response = self.client.post(TRIGGER_PATH, json={"id": self.rid, "total": 7})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"code": "not-found", "detail": "repository read found no row for entity.report"},
        )
        self.assertEqual(len(self.store.reports), 0)

    def test_count_ignores_zero_totals(self):
        other = "00000000-0000-0000-0000-000000000003"
        self.seed(self.rid, 0)
        self.seed(other, 3)
        response = self.client.post(TRIGGER_PATH, json={"id": self.rid})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.reports[self.rid]["total"], 1)
        self.assertEqual(self.store.reports[other]["total"], 3)

    def test_workflow_route_matches_trigger(self):
        totals = []
        for path in (WORKFLOW_PATH, TRIGGER_PATH):
            app = schedule_fastapi.create_app()
            self.seed(self.rid, 7, store=app.state.store)
            response = TestClient(app).post(path, json={"id": self.rid, "total": 7})
            self.assertEqual(response.status_code, 200)
            totals.append(app.state.store.reports[self.rid]["total"])
        self.assertEqual(totals, [1, 1])

    def test_get_report_by_id(self):
        row = self.seed(self.rid, 7)
        response = self.client.get(f"/rollup-service/report/{self.rid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), row)
        response = self.client.get("/rollup-service/report/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not-found")


if __name__ == "__main__":
    unittest.main()
