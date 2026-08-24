"""Issue #81: the schedule trigger route (`POST /-/schedules/<event-slug>`).

RFC-0016 gave `event ... on schedule` a real IR/OpenAPI artifact and no
executor — `diagnostics.ENFORCEMENT[("event", "schedule")]` names issue #26
(the serving layer) as the owner. This is that surface: an external
scheduler (cron/systemd) calls the route, mode A runs the workflow the
schedule event is bound to, and the response/log path is the SAME one every
other workflow POST already uses (`_do_post` -> `_run` -> `_respond` ->
`map_result`) — no new status mapping, no new auth check.

Linkage (D1): an Event carries no owner in the IR (`lower.py`'s `owner_of`
is Workflow-only), so `resolve_schedule_triggers` applies the SAME
nearest-preceding-`service` rule (RFC-0002 A.2 R2) post-hoc, over the
compiled document's `line` fields. Exactly one workflow in that service is
required; 0 or 2+ is refused with `ServeError` at build time (`fail-closed`,
not a guess) — the built-in cron design explicitly rejected in the brief.

Normal: an authenticated trigger executes and observes (skipped[] in body,
one JSON log line). Error: no Authorization header on a `security jwt`
service is 401; an undeclared/non-schedule slug is 404; ambiguous linkage
(0 or 2+ candidate workflows) raises ServeError before the app is even
built. Boundary: a non-schedule (`on`-sourced) event never gets a
`/-/schedules/...` route at all.
"""

import contextlib
import io
import json
import unittest

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import (ServeError, build_schedule_routes, make_wsgi_app,
                       resolve_schedule_triggers)
from tests.test_wsgi_contract import call_wsgi

# `service` precedes the schedule event, one workflow inside it — the
# unambiguous case (mirrors test_cli_diagnostics.SCHEDULE_ONLY).
NORMAL_SRC = """
service Rollup
    security
        jwt

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    read report
"""

# No `security` clause: presence/verification is moot, used for the plain
# 200 assertions that are not about auth.
OPEN_SRC = """
service Rollup

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    read report
"""

# Two workflows in the schedule's owning service -> ambiguous (D1: reject,
# never guess).
TWO_WORKFLOWS_SRC = """
service Rollup

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    read report

workflow ListReports
    list report
"""

# The event precedes every `service` declaration -> no owner at all.
NO_SERVICE_SRC = """
entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

service Rollup

workflow GetReport
    read report
"""

# A service whose only child is NOT a workflow -> 0 candidates.
ZERO_WORKFLOWS_SRC = """
entity Report
    field
        id UUID
        createdAt DateTime

service Rollup
    expose
        list Report by createdAt

event DailyRollup on schedule daily at 00:00 UTC
"""

# A schedule event AND an `on`-sourced event in the same module — only the
# schedule one gets a trigger route.
MIXED_EVENTS_SRC = """
service Rollup

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC
event ReportCreated on Report create

workflow GetReport
    read report
    emit ReportCreated
"""


def _doc(src):
    return lower(parse(src), "rollup").to_document()


class NormalTest(unittest.TestCase):
    """D5 normal: the trigger route executes the linked workflow and
    observes it exactly like an OpenAPI-declared workflow POST does."""

    def test_normal_trigger_runs_the_linked_workflow_and_observes_it(self):
        app = make_wsgi_app(_doc(OPEN_SRC))

        status, _headers, body = call_wsgi(
            app, "POST", "/-/schedules/daily-rollup", body=b"{}")

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])
        self.assertEqual([], body["skipped"])
        self.assertTrue(body["correlation_id"].startswith("req-"))

    def test_normal_resolve_schedule_triggers_picks_the_one_workflow(self):
        doc = _doc(OPEN_SRC)
        nodes = {n["id"]: n for n in doc["nodes"]}
        event = next(n for n in doc["nodes"] if n["kind"] == "Event")

        triggers = resolve_schedule_triggers(doc)

        wid, service = triggers[event["id"]]
        self.assertEqual("wf.get.report", wid)
        self.assertEqual("Rollup", service["name"])

    def test_normal_json_log_emits_one_line_for_a_trigger_request(self):
        app = make_wsgi_app(_doc(OPEN_SRC), log_format="json")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            status, _headers, _body = call_wsgi(
                app, "POST", "/-/schedules/daily-rollup", body=b"{}")
        raw_lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        parsed = []
        for ln in raw_lines:
            try:
                parsed.append(json.loads(ln))
            except ValueError:
                continue

        self.assertEqual(200, status)
        self.assertEqual(1, len(parsed), parsed)
        self.assertEqual("/-/schedules/daily-rollup", parsed[0]["path"])
        self.assertEqual("wf.get.report", parsed[0]["workflow"])
        self.assertEqual(200, parsed[0]["status"])


class ErrorTest(unittest.TestCase):
    """D5 error: unauthenticated 401, undeclared/non-schedule slug 404,
    ambiguous linkage refused at build time."""

    def test_error_missing_authorization_is_401(self):
        app = make_wsgi_app(_doc(NORMAL_SRC))

        status, _headers, body = call_wsgi(
            app, "POST", "/-/schedules/daily-rollup", body=b"{}")

        self.assertEqual(401, status)
        self.assertEqual("auth-missing", body["code"])

    def test_error_undeclared_slug_is_404(self):
        app = make_wsgi_app(_doc(OPEN_SRC))

        status, _headers, body = call_wsgi(
            app, "POST", "/-/schedules/no-such-event", body=b"{}")

        self.assertEqual(404, status)
        self.assertEqual("not-found", body["code"])

    def test_error_two_candidate_workflows_raise_serve_error_at_build_time(self):
        with self.assertRaises(ServeError) as cm:
            make_wsgi_app(_doc(TWO_WORKFLOWS_SRC))
        self.assertIn("DailyRollup", str(cm.exception))

    def test_error_no_preceding_service_raises_serve_error(self):
        with self.assertRaises(ServeError):
            make_wsgi_app(_doc(NO_SERVICE_SRC))

    def test_error_zero_candidate_workflows_raise_serve_error(self):
        with self.assertRaises(ServeError):
            make_wsgi_app(_doc(ZERO_WORKFLOWS_SRC))


class BoundaryTest(unittest.TestCase):
    """D5 boundary: a non-schedule event never gets a trigger route."""

    def test_boundary_on_sourced_event_gets_no_schedule_route(self):
        doc = _doc(MIXED_EVENTS_SRC)

        routes = build_schedule_routes(doc)

        self.assertEqual(["/-/schedules/daily-rollup"], list(routes))

    def test_boundary_on_sourced_event_slug_is_404_via_the_app(self):
        app = make_wsgi_app(_doc(MIXED_EVENTS_SRC))

        status, _headers, body = call_wsgi(
            app, "POST", "/-/schedules/report-created", body=b"{}")

        self.assertEqual(404, status)
        self.assertEqual("not-found", body["code"])


if __name__ == "__main__":
    unittest.main()
