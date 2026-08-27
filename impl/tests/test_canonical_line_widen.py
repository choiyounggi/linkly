"""Issue #111, D6/D7/D8 — widening `--log-format json`'s canonical line.

Reuses test_trace_canonical_line.py's / test_observability_json_log.py's
established harness (`call_wsgi` + stderr capture) for driving a real request
through `LnplWsgiApp` and inspecting the emitted access-log line — the same
approach issue #107/#123 used to add `trace_id`/`span_id`, now applied to
`notes`/`effects`/`input_digest` and the `--capture-on-failure` snapshot.
"""

import contextlib
import hashlib
import io
import json
import unittest

from lnpl.drivers import DriverError
from lnpl.interp import MASK, FakeRepository
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app

from tests.test_wsgi_contract import call_wsgi

SOURCE = """capability postgres

entity Order
    field
        id UUID
        tier Text
        secret Password

service Checkout
    policy
        retry 0

workflow Ping
    find order
    note "picked-tier-{}" with order.tier
"""

PATH = "/checkout/ping"
RUN_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


def doc():
    return lower(parse(SOURCE), "m").to_document()


def payload():
    return {"id": RUN_ID, "tier": "gold", "secret": "raw-secret-value"}


def _expected_input_digest(masked):
    canonical = json.dumps(masked, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _AlwaysFailsRepository(FakeRepository):
    """`find order` fails with a `DriverError`, translated to a normal
    `RunError` -> `status: "failed"` — a real workflow failure, not an
    escaped exception (that path is `_EscapingRepository`'s job, reused from
    test_trace_canonical_line.py in `TestExceptionBeforeRespond` below)."""

    def execute(self, entity_id, operation, key):
        raise DriverError("the store is unreachable")


class _AuthBlowsUp:
    """Monkeypatch target: raises before `_respond` is ever reached, and
    before `_call_with_json_log`'s own try/finally existed to guard it
    (issue #111, D8) — the same class of bug `_check_auth` itself could have,
    or any future code `_do_post` runs ahead of `_run`/`_respond`."""

    def __call__(self, *args, **kwargs):
        raise RuntimeError("boom-before-respond")


def _post_json_lines(app, body=None):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        status, _headers, _body = call_wsgi(
            app, "POST", PATH,
            body=body if body is not None else json.dumps(payload()).encode("utf-8"))
    lines = []
    for ln in buf.getvalue().splitlines():
        if not ln.strip():
            continue
        try:
            lines.append(json.loads(ln))
        except ValueError:
            continue
    return status, lines


class TestCanonicalLineWidening(unittest.TestCase):
    """DoD 6: notes/effects/input_digest on a successful run."""

    def test_notes_and_effects_and_input_digest_are_present(self):
        app = make_wsgi_app(doc(), log_format="json")

        status, lines = _post_json_lines(app)

        self.assertEqual(200, status)
        self.assertEqual(1, len(lines), lines)
        line = lines[0]
        self.assertEqual(line["notes"],
                         [{"template": "picked-tier-{}", "values": ["gold"]}])
        self.assertEqual(line["effects"], {"RepositoryCall": 1})
        masked = dict(payload(), secret=MASK)
        self.assertEqual(line["input_digest"], _expected_input_digest(masked))

    def test_input_digest_is_over_the_masked_payload_not_the_raw_one(self):
        app = make_wsgi_app(doc(), log_format="json")

        status, lines = _post_json_lines(app)

        self.assertEqual(200, status)
        raw_digest = _expected_input_digest(payload())
        self.assertNotEqual(lines[0]["input_digest"], raw_digest)

    def test_a_route_with_no_payload_omits_input_digest(self):
        # Boundary: GET carries no request payload, so `_respond` never runs
        # and `log_sink` never gets `input_digest`/`notes`/`effects` at all
        # — the field is omitted, not present-and-null.
        app = make_wsgi_app(doc(), log_format="json")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            call_wsgi(app, "GET", "/checkout/order/" + RUN_ID)
        lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
        self.assertEqual(1, len(lines))
        self.assertNotIn("input_digest", lines[0])
        self.assertNotIn("notes", lines[0])
        self.assertNotIn("effects", lines[0])


class TestCaptureOnFailure(unittest.TestCase):
    """DoD 7: `--capture-on-failure` — on AND failed only."""

    def test_on_and_failed_includes_the_masked_input(self):
        app = make_wsgi_app(doc(), log_format="json",
                            repository_factory=lambda: _AlwaysFailsRepository(None),
                            capture_on_failure=True)

        status, lines = _post_json_lines(app)

        self.assertNotEqual(200, status)
        masked = dict(payload(), secret=MASK)
        self.assertEqual(lines[0]["input"], masked)
        self.assertNotIn("raw-secret-value", json.dumps(lines[0]["input"]))

    def test_on_and_succeeded_omits_the_input(self):
        app = make_wsgi_app(doc(), log_format="json", capture_on_failure=True)

        status, lines = _post_json_lines(app)

        self.assertEqual(200, status)
        self.assertNotIn("input", lines[0])

    def test_off_by_default_and_failed_still_omits_the_input(self):
        app = make_wsgi_app(doc(), log_format="json",
                            repository_factory=lambda: _AlwaysFailsRepository(None))

        status, lines = _post_json_lines(app)

        self.assertNotEqual(200, status)
        self.assertNotIn("input", lines[0])


class TestExceptionBeforeRespond(unittest.TestCase):
    """DoD 8: a request that dies before `_respond` is even reached still
    produces exactly one canonical line (Stripe's `ensure`-block guarantee,
    extended past the escape `_respond` already handled)."""

    def test_an_exception_before_respond_still_emits_one_line(self):
        app = make_wsgi_app(doc(), log_format="json")
        app._check_auth = _AuthBlowsUp()

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            with self.assertRaises(RuntimeError):
                call_wsgi(app, "POST", PATH,
                         body=json.dumps(payload()).encode("utf-8"))
        lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
        self.assertEqual(1, len(lines), lines)
        self.assertIn("correlation_id", lines[0])


class TestTextFormatByteInvariance(unittest.TestCase):
    """DoD 9: `--log-format text` (default) emits no access-log line at all —
    unchanged by this feature. `_call_with_json_log`/`_emit_request_log` are
    only ever reached when `self.log_format == "json"` (`LnplWsgiApp.__call__`
    dispatches on that check before either exists), so a `note`-carrying
    workflow cannot reach the new fields through the text path by
    construction; this pins that as an observed behavior too, the same
    `test_default_text_format_emits_no_log_line_at_all` precedent
    test_trace_canonical_line.py already established generically, now run
    against a fixture that specifically exercises `note`."""

    def test_a_note_carrying_workflow_still_emits_no_log_line_in_text_mode(self):
        app = make_wsgi_app(doc())  # log_format defaults to "text"
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            status, _headers, _body = call_wsgi(
                app, "POST", PATH, body=json.dumps(payload()).encode("utf-8"))

        self.assertEqual(200, status)
        self.assertEqual("", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
