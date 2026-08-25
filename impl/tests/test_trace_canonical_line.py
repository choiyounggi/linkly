"""`Trace.to_dict()` / `--log-format json` canonical line carry
`trace_id`/`span_id` (issue #107, Task 04).

Reuses test_observability_json_log.py's `--log-format json` harness
(`call_wsgi`, stderr capture) — that is the established way to drive a real
request through `LnplWsgiApp` and inspect the emitted access-log line.
"""

import contextlib
import io
import json
import unittest

from lnpl.drivers import DriverError
from lnpl.interp import FakeRepository, Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app

from tests.test_wsgi_contract import call_wsgi

SOURCE = """capability postgres
entity Order
    field
        id UUID
service Checkout
    policy
        retry 0
workflow Ping
    find order
"""

PATH = "/checkout/ping"
VALID = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def doc():
    return lower(parse(SOURCE), "m").to_document()


def payload():
    return {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301"}


class _EscapingRepository(FakeRepository):
    """Raises a raw (non-DriverError) exception -- an unexpected internal
    bug, not a translated driver fault -- so it escapes `run_workflow` and
    reaches `_respond`'s `except Exception:` branch (the 576-equivalent
    exception-path log line)."""

    def execute(self, entity_id, operation, key):
        raise RuntimeError("unexpected internal bug")


def _post_json_lines(app, headers=None, body=None):
    """-> (status, [parsed JSON access-log lines])."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        status, _headers, _body = call_wsgi(
            app, "POST", PATH,
            body=body if body is not None else json.dumps(payload()).encode("utf-8"),
            headers=headers or {})
    lines = []
    for ln in buf.getvalue().splitlines():
        if not ln.strip():
            continue
        try:
            lines.append(json.loads(ln))
        except ValueError:
            continue
    return status, lines


class JsonLogTraceIdTests(unittest.TestCase):
    def test_normal_valid_inbound_traceparent_trust_on_trace_id_matches(self):
        app = make_wsgi_app(doc(), log_format="json", trust_incoming_trace=True)

        status, lines = _post_json_lines(app, headers={"traceparent": VALID})

        self.assertEqual(200, status)
        self.assertEqual(1, len(lines), lines)
        self.assertEqual("4bf92f3577b34da6a3ce929d0e0e4736", lines[0]["trace_id"])

    def test_correlation_id_keeps_its_pre_existing_shape_on_the_same_line(self):
        app = make_wsgi_app(doc(), log_format="json")

        status, lines = _post_json_lines(app)

        self.assertEqual(200, status)
        self.assertRegex(lines[0]["correlation_id"], r"^req-[0-9a-f]{12}$")
        self.assertIn("trace_id", lines[0])

    def test_exception_path_still_emits_one_line_with_trace_id(self):
        app = make_wsgi_app(doc(), log_format="json",
                            repository_factory=lambda: _EscapingRepository(None))

        status, lines = _post_json_lines(app)

        self.assertEqual(500, status)
        self.assertEqual(1, len(lines), lines)
        self.assertIn("trace_id", lines[0])
        self.assertIsNotNone(lines[0]["trace_id"])

    def test_boundary_traceparent_absent_trace_id_is_a_fresh_value_key_present(self):
        app = make_wsgi_app(doc(), log_format="json")

        status, lines = _post_json_lines(app)

        self.assertEqual(200, status)
        self.assertIn("trace_id", lines[0])
        self.assertIsNotNone(lines[0]["trace_id"])

    def test_trust_off_default_valid_traceparent_records_a_link_different_trace_id(self):
        app = make_wsgi_app(doc(), log_format="json")  # trust_incoming_trace defaults off

        status, lines = _post_json_lines(app, headers={"traceparent": VALID})

        self.assertEqual(200, status)
        self.assertNotEqual("4bf92f3577b34da6a3ce929d0e0e4736", lines[0]["trace_id"])


class ToDictTests(unittest.TestCase):
    def test_trace_id_and_span_id_keys_present_when_set(self):
        interp = Interpreter(doc(), repo_rows={})
        interp.trace.trace_id = "a" * 32
        interp.trace.span_id = "b" * 16

        out = interp.trace.to_dict()

        self.assertEqual(out["trace_id"], "a" * 32)
        self.assertEqual(out["span_id"], "b" * 16)

    def test_boundary_non_http_run_has_no_trace_id_key_golden_byte_identical(self):
        interp = Interpreter(doc(), repo_rows={})

        out = interp.trace.to_dict()

        self.assertNotIn("trace_id", out)
        self.assertNotIn("span_id", out)
        self.assertNotIn("links", out)

    def test_trace_link_surfaces_as_links_key_only_when_set(self):
        interp = Interpreter(doc(), repo_rows={})
        interp.trace.trace_link = {"trace_id": "a" * 32, "parent_id": "b" * 16}

        out = interp.trace.to_dict()

        self.assertEqual(out["links"], {"trace_id": "a" * 32, "parent_id": "b" * 16})

    def test_tracestate_never_appears_in_to_dict_even_when_set(self):
        # D10: vendor extension + PII risk -- never surfaced.
        interp = Interpreter(doc(), repo_rows={})
        interp.trace.tracestate = "vendor1=value1"

        out = interp.trace.to_dict()

        self.assertNotIn("tracestate", out)


class TextFormatByteInvarianceTests(unittest.TestCase):
    def test_default_text_format_emits_no_log_line_at_all(self):
        app = make_wsgi_app(doc())  # log_format defaults to "text"
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            status, _headers, _body = call_wsgi(
                app, "POST", PATH, body=json.dumps(payload()).encode("utf-8"))

        self.assertEqual(200, status)
        self.assertEqual("", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
