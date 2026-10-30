"""issue #241 (t5): the audit trail — Interpreter.repo_ops, the record schema, the sinks, the WSGI emission and the serve/build_app wiring."""

import contextlib
import copy
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

import jsonschema

from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows
from lnpl import cli, wsgi
from lnpl.drivers import HmacTokenProvider, SqliteRepositoryDriver
from lnpl.wsgi import JsonLinesAuditSink, make_wsgi_app, open_audit_sink
from tests.fixtures import VALUE_PAYMENT
from tests.test_observability_json_log import PAYMENT_SRC, CARD, _doc as _payment_doc, _payload
from tests.test_role_gate import ROLE_GATED_SRC, SECRET, AUDIENCE, ORDER_ID, PATH as ROLE_PATH
from tests.test_serve_sse import TWO_EVENT_SRC, compile_src
from tests.test_wsgi_contract import call_wsgi
from tests.test_wsgi_event_consume import (SRC as EVENT_SRC, _doc as _event_doc, _envelope,
                                           _post as _event_post, EVENTS_PATH_CREATE)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA_PATH = os.path.join(REPO, "schemas", "audit-record.schema.json")

CHARGE_SRC = """capability postgres

entity Account
    field
        id UUID
        balance Integer

entity Charge
    field
        id UUID
        cardNumber Password
        amountCents Integer

service ChargeService
    security
        jwt
    policy
        retry 0

workflow Pay
    find account by input.cardNumber
    update account
"""


def _compile(src, module="t"):
    return lower(parse(src), module).to_document()


def _node_id(doc, kind, name):
    return next(n["id"] for n in doc["nodes"] if n["kind"] == kind and n.get("name") == name)


def _schema():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _tmpdir(test):
    root = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(root, exist_ok=True)
    path = tempfile.mkdtemp(dir=root)
    test.addCleanup(shutil.rmtree, path, True)
    return path


# Synthetic — every value is made up (no production output reused).
VALID_RECORD = {
    "record_type": "lnpl.audit", "schema_version": 1,
    "timestamp": "2026-01-02T03:04:05.006Z",
    "correlation_id": "req-000000000001", "trace_id": None, "span_id": None,
    "actor": {"subject": "alice", "role": "clerk"},
    "action": {"method": "POST", "route": "/order-service/approve-order",
               "kind": "workflow", "workflow": "wf.synthetic"},
    "resource": [{"entity": "entity.order", "op": "read", "key": "entity.order#***"}],
    "outcome": {"status": 403, "code": "forbidden", "failed_step": None, "replay": False},
    "duration_ms": 1.234,
}


class RepoOpsHookTest(unittest.TestCase):
    """D3: one (entity, op, key, lookup_ref) per repository call, in order,
    cleared (never rebound) at the start of every run."""

    def test_normal_payment_run_lists_read_then_update(self):
        doc = _payment_doc()
        wf = _node_id(doc, "Workflow", "Approval")
        pid = _node_id(doc, "Entity", "Payment")
        interp = Interpreter(doc, repo_rows=default_rows(doc, wf, _payload()))
        result = interp.run_workflow(wf, _payload())
        self.assertEqual(result["status"], "completed")
        key = pid + "#3f2504e0-4f89-41d3-9a0c-0305e82c3301"
        self.assertEqual([(e, op, k) for e, op, k, _l in interp.repo_ops],
                         [(pid, "read", key), (pid, "update", key)])

    def test_boundary_second_run_starts_from_an_empty_list_on_the_same_object(self):
        doc = _payment_doc()
        wf = _node_id(doc, "Workflow", "Approval")
        interp = Interpreter(doc, repo_rows=default_rows(doc, wf, _payload()))
        interp.run_workflow(wf, _payload())
        first = list(interp.repo_ops)
        ident = id(interp.repo_ops)
        interp.run_workflow(wf, _payload())
        self.assertEqual(interp.repo_ops, first)
        self.assertEqual(id(interp.repo_ops), ident)

    def test_error_a_failing_driver_call_is_still_listed_with_its_lookup_ref(self):
        doc = _compile(CHARGE_SRC)
        wf = _node_id(doc, "Workflow", "Pay")
        aid = _node_id(doc, "Entity", "Account")
        payload = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "cardNumber": CARD,
                   "amountCents": 5}
        interp = Interpreter(doc, repo_rows=default_rows(doc, wf, payload))
        result = interp.run_workflow(wf, payload)
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(interp.repo_ops[0], (aid, "read", aid + "#" + CARD, "input.cardNumber"))
        self.assertEqual(interp.repo_ops[-1][:2], (aid, "update"))


class AuditSchemaTest(unittest.TestCase):
    """D4: schemas/audit-record.schema.json — all keys required, no extras."""

    def test_normal_schema_is_valid_2020_12_and_accepts_the_synthetic_record(self):
        jsonschema.Draft202012Validator.check_schema(_schema())
        jsonschema.validate(VALID_RECORD, _schema())
        self.assertEqual(VALID_RECORD["record_type"], "lnpl.audit")

    def test_error_every_required_key_deleted_in_turn_is_rejected(self):
        schema = _schema()
        self.assertEqual(set(schema["required"]), set(VALID_RECORD))
        for key in schema["required"]:
            with self.subTest(key=key):
                record = copy.deepcopy(VALID_RECORD)
                del record[key]
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(record, schema)

    def test_error_an_extra_key_is_rejected_at_top_level_and_nested(self):
        schema = _schema()
        for where in ("top", "action", "outcome", "resource"):
            with self.subTest(where=where):
                record = copy.deepcopy(VALID_RECORD)
                target = {"top": record, "action": record["action"],
                          "outcome": record["outcome"],
                          "resource": record["resource"][0]}[where]
                target["evil"] = 1
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(record, schema)

    def test_boundary_null_actor_empty_resource_and_no_prev_hash(self):
        record = copy.deepcopy(VALID_RECORD)
        record["actor"] = None
        record["resource"] = []
        jsonschema.validate(record, _schema())
        self.assertNotIn("prev_hash", _schema()["properties"])


class AuditSinkTest(unittest.TestCase):
    """D10/D11: exactly `stderr-json` and `file:<path>`; one line per record."""

    def test_normal_file_sink_appends_one_json_line_per_record_with_mode_0600(self):
        path = os.path.join(_tmpdir(self), "audit.jsonl")
        sink = open_audit_sink("file:" + path)
        self.addCleanup(sink.close)
        sink.export(VALID_RECORD)
        sink.export(VALID_RECORD)
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertEqual(json.loads(line), VALID_RECORD)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_boundary_a_new_sink_on_an_existing_file_keeps_its_history(self):
        # review t5-r1 F2: a restarted process appends (O_APPEND), never
        # rewrites from offset 0.
        path = os.path.join(_tmpdir(self), "audit.jsonl")
        earlier = dict(VALID_RECORD, correlation_id="req-000000000000")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(earlier) + "\n")
        sink = open_audit_sink("file:" + path)
        self.addCleanup(sink.close)
        sink.export(VALID_RECORD)
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), earlier)
        self.assertEqual(json.loads(lines[1]), VALID_RECORD)

    def test_normal_stderr_json_writes_one_parseable_line(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            open_audit_sink("stderr-json").export(VALID_RECORD)
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), VALID_RECORD)

    def test_error_unknown_spec_empty_spec_and_exporter_name_are_refused(self):
        for spec in ("nope", "", "otlp", "file"):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError) as ctx:
                    open_audit_sink(spec)
                self.assertIn("accepted: stderr-json, file:<path>", str(ctx.exception))

    def test_error_file_spec_without_path_or_in_a_missing_dir_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            open_audit_sink("file:")
        self.assertIn("needs a path", str(ctx.exception))
        missing = os.path.join(_tmpdir(self), "missing", "a.jsonl")
        with self.assertRaises(ValueError) as ctx:
            open_audit_sink("file:" + missing)
        self.assertIn("cannot be opened for append", str(ctx.exception))

    def test_boundary_none_is_no_sink_and_export_after_close_raises(self):
        self.assertIsNone(open_audit_sink(None))
        sink = open_audit_sink("file:" + os.path.join(_tmpdir(self), "a.jsonl"))
        sink.close()
        sink.close()
        with self.assertRaises(OSError):
            sink.export(VALID_RECORD)


PAY_PATH = "/payment-service/approval"
PAY_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


class _CaptureSink:
    def __init__(self):
        self.records = []

    def export(self, record):
        self.records.append(record)


def _post_json(app, path, payload, headers=None):
    return call_wsgi(app, "POST", path, body=json.dumps(payload).encode("utf-8"),
                     headers=headers)


def _role_app(**kwargs):
    return make_wsgi_app(_compile(ROLE_GATED_SRC), token_provider=HmacTokenProvider(SECRET),
                         **kwargs)


def _bearer(subject="alice", role="clerk", audience=AUDIENCE):
    token = HmacTokenProvider(SECRET).issue(subject, audience, role=role)
    return token, {"Authorization": "Bearer " + token}


class AuditRecordingRuleTest(unittest.TestCase):
    """D1: every POST to a workflow/event-consume route plus every 401/403."""

    def test_normal_write_is_recorded_and_successful_read_is_not(self):
        sink = _CaptureSink()
        doc = _payment_doc()
        app = make_wsgi_app(doc, audit_sink=sink)
        status, _h, body = _post_json(app, PAY_PATH, _payload())
        self.assertEqual(status, 200)
        get_status, _h, _b = call_wsgi(app, "GET", "/payment-service/payment/" + PAY_ID)
        self.assertNotIn(get_status, (401, 403))
        self.assertEqual(len(sink.records), 1)
        record = sink.records[0]
        pid = _node_id(doc, "Entity", "Payment")
        self.assertEqual(record["outcome"],
                         {"status": 200, "code": "ok", "failed_step": None, "replay": False})
        self.assertEqual(record["action"], {"method": "POST", "route": PAY_PATH,
                                            "kind": "workflow",
                                            "workflow": _node_id(doc, "Workflow", "Approval")})
        self.assertEqual(record["resource"],
                         [{"entity": pid, "op": "read", "key": pid + "#" + PAY_ID},
                          {"entity": pid, "op": "update", "key": pid + "#" + PAY_ID}])
        self.assertEqual(record["correlation_id"], body["correlation_id"])

    def test_normal_forbidden_post_and_get_are_recorded_with_the_verified_actor(self):
        sink = _CaptureSink()
        app = _role_app(audit_sink=sink)
        _token, headers = _bearer()
        status, _h, body = _post_json(app, ROLE_PATH, {"id": ORDER_ID}, headers)
        self.assertEqual(status, 403)
        get_status, _h, _b = call_wsgi(app, "GET", "/order-service/order/" + ORDER_ID,
                                       headers=headers)
        self.assertEqual(get_status, 403)
        self.assertEqual(len(sink.records), 2)
        first, second = sink.records
        self.assertEqual(first["actor"], {"subject": "alice", "role": "clerk"})
        self.assertEqual(first["outcome"],
                         {"status": 403, "code": "forbidden", "failed_step": None,
                          "replay": False})
        self.assertEqual(first["resource"], [])
        self.assertEqual(first["correlation_id"], body["correlation_id"])
        self.assertEqual(second["action"], {"method": "GET", "route": "/order-service/order/{id}",
                                            "kind": "get-single", "workflow": None})

    def test_error_unauthenticated_post_has_null_actor_and_no_bearer_text(self):
        sink = _CaptureSink()
        app = _role_app(audit_sink=sink)
        status, _h, _b = _post_json(app, ROLE_PATH, {"id": ORDER_ID})
        self.assertEqual(status, 401)
        self.assertEqual(len(sink.records), 1)
        record = sink.records[0]
        self.assertIsNone(record["actor"])
        self.assertEqual(record["outcome"]["code"], "auth-missing")
        self.assertNotIn("Bearer", json.dumps(record))

    def test_boundary_unmatched_path_and_ops_path_produce_no_record(self):
        sink = _CaptureSink()
        app = make_wsgi_app(_payment_doc(), audit_sink=sink)
        unmatched, _h, _b = call_wsgi(app, "GET", "/no/such/path")
        healthz, _h, _b = call_wsgi(app, "GET", "/-/healthz")
        self.assertEqual(unmatched, 404)
        self.assertEqual(healthz, 200)
        self.assertEqual(sink.records, [])

    def test_boundary_get_on_a_workflow_route_is_405_and_not_recorded(self):
        # review t5-r1 F1: D1 is "POST to a workflow route", not "any
        # method on one" — the 405 a GET gets there is not a write.
        sink = _CaptureSink()
        app = make_wsgi_app(_payment_doc(), audit_sink=sink)
        status, _h, _b = call_wsgi(app, "GET", PAY_PATH)
        self.assertEqual(status, 405)
        self.assertEqual(sink.records, [])
        self.assertEqual(_post_json(app, PAY_PATH, _payload())[0], 200)
        self.assertEqual(len(sink.records), 1)

    def test_normal_event_consume_write_is_recorded(self):
        sink = _CaptureSink()
        app = make_wsgi_app(_event_doc(EVENT_SRC), audit_sink=sink)
        status, _h, _b = _event_post(app, EVENTS_PATH_CREATE, _envelope(
            event_id="evt-1", event_type="OrderCreated",
            data={"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b", "amount": 1}))
        self.assertEqual(status, 200)
        self.assertEqual(len(sink.records), 1)
        record = sink.records[0]
        self.assertEqual(record["action"]["kind"], "event-consume")
        self.assertEqual(record["resource"][0]["op"], "create")
        self.assertEqual(record["resource"][0]["entity"], "entity.order")

    def test_boundary_idempotency_replay_is_marked_and_has_no_resource(self):
        sink = _CaptureSink()
        path = os.path.join(_tmpdir(self), "store.db")
        app = make_wsgi_app(_compile(VALUE_PAYMENT, "mod"),
                            repository_factory=lambda: SqliteRepositoryDriver(path),
                            audit_sink=sink)
        for _ in range(2):
            status, _h, _b = _post_json(app, "/payment-service/approve",
                                        {"id": "p-1", "amount": 500}, {"Idempotency-Key": "k1"})
            self.assertEqual(status, 200)
        self.assertEqual(len(sink.records), 2)
        self.assertIs(sink.records[0]["outcome"]["replay"], False)
        self.assertNotEqual(sink.records[0]["resource"], [])
        self.assertIs(sink.records[1]["outcome"]["replay"], True)
        self.assertEqual(sink.records[1]["resource"], [])


class AuditSingleEmissionTest(unittest.TestCase):
    """D2: one record per response, whatever path the response took."""

    def test_normal_three_due_responses_reach_the_sink_three_times(self):
        sink = _CaptureSink()
        pay = make_wsgi_app(_payment_doc(), audit_sink=sink)
        self.assertEqual(_post_json(pay, PAY_PATH, _payload())[0], 200)
        _token, headers = _bearer()
        self.assertEqual(_post_json(_role_app(audit_sink=sink), ROLE_PATH,
                                    {"id": ORDER_ID}, headers)[0], 403)
        sse = make_wsgi_app(compile_src(TWO_EVENT_SRC), audit_sink=sink)
        self.assertEqual(call_wsgi(sse, "GET", "/orders/events/order-placed")[0], 401)
        self.assertEqual(len(sink.records), 3)

    def test_boundary_no_sink_means_no_audit_state_on_the_app(self):
        app = make_wsgi_app(_payment_doc())
        self.assertIsNone(app.audit_sink)
        self.assertEqual(_post_json(app, PAY_PATH, _payload())[0], 200)


class AuditSchemaRealRecordTest(unittest.TestCase):
    """D4: records the app really emits validate against the fixed schema."""

    def test_normal_real_records_validate_against_the_schema(self):
        sink = _CaptureSink()
        self.assertEqual(_post_json(make_wsgi_app(_payment_doc(), audit_sink=sink),
                                    PAY_PATH, _payload())[0], 200)
        _token, headers = _bearer()
        self.assertEqual(_post_json(_role_app(audit_sink=sink), ROLE_PATH,
                                    {"id": ORDER_ID}, headers)[0], 403)
        self.assertEqual(len(sink.records), 2)
        for record in sink.records:
            jsonschema.validate(record, _schema())


class AuditMaskingTest(unittest.TestCase):
    """D9: the token, the Authorization header and Password-sourced keys
    never reach the audit line; the verified subject does (negative control)."""

    def _charge_line(self):
        doc = _compile(CHARGE_SRC)
        provider = HmacTokenProvider(SECRET)
        token = provider.issue("alice", "charge-service", role="clerk")
        app = make_wsgi_app(doc, token_provider=provider, audit_sink=JsonLinesAuditSink())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            status, _h, body = _post_json(
                app, "/charge-service/pay",
                {"id": PAY_ID, "cardNumber": CARD, "amountCents": 5},
                {"Authorization": "Bearer " + token})
        self.assertEqual(status, 404, body)
        lines = [ln for ln in err.getvalue().splitlines() if '"record_type": "lnpl.audit"' in ln]
        self.assertEqual(len(lines), 1)
        return doc, token, lines[0]

    def test_normal_verified_token_and_card_stay_out_while_subject_is_present(self):
        doc, token, line = self._charge_line()
        aid = _node_id(doc, "Entity", "Account")
        self.assertNotIn(CARD, line)
        self.assertNotIn(token, line)
        self.assertNotIn("Bearer", line)
        self.assertIn('"alice"', line)
        record = json.loads(line)
        self.assertEqual(record["actor"], {"subject": "alice", "role": "clerk"})
        self.assertEqual(record["resource"][0], {"entity": aid, "op": "read", "key": aid + "#***"})

    def test_boundary_unmasked_source_keeps_its_key(self):
        doc, _token, line = self._charge_line()
        aid = _node_id(doc, "Entity", "Account")
        self.assertEqual(json.loads(line)["resource"][1],
                         {"entity": aid, "op": "update", "key": aid + "#" + PAY_ID})


class _Raising:
    def export(self, record):
        raise RuntimeError("disk full")


class AuditFailOpenTest(unittest.TestCase):
    """D12: a failing sink never changes the response (the role app's 401
    POST has no correlation id in its body, so bodies compare exactly)."""

    def _unauthenticated(self, app):
        return _post_json(app, ROLE_PATH, {"id": ORDER_ID})

    def test_error_raising_sink_leaves_the_response_unchanged_and_says_so_once(self):
        baseline = self._unauthenticated(_role_app())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            got = self._unauthenticated(_role_app(audit_sink=_Raising()))
        self.assertEqual(got, baseline)
        self.assertEqual(len([ln for ln in err.getvalue().splitlines()
                              if "audit sink" in ln and "disk full" in ln]), 1)

    def test_boundary_three_failures_give_three_lines(self):
        app = _role_app(audit_sink=_Raising())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            statuses = [self._unauthenticated(app)[0] for _ in range(3)]
        self.assertEqual(statuses, [401, 401, 401])
        self.assertEqual(len([ln for ln in err.getvalue().splitlines()
                              if "audit sink" in ln and "disk full" in ln]), 3)

    def test_error_sink_failure_that_breaks_stderr_does_not_escape(self):
        original = sys.stderr
        self.addCleanup(setattr, sys, "stderr", original)

        class _Broken(io.StringIO):
            def write(self, s):
                raise OSError("stderr closed")

        class _BreaksStderr:
            def export(self, record):
                sys.stderr = _Broken()
                raise OSError("stderr closed")

        baseline = self._unauthenticated(_role_app())
        got = self._unauthenticated(_role_app(audit_sink=_BreaksStderr()))
        self.assertEqual((got[0], got[2]), (baseline[0], baseline[2]))


def _json_lines_with_method(text):
    found = []
    for raw in text.splitlines():
        try:
            parsed = json.loads(raw)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "method" in parsed:
            found.append(parsed)
    return found


class AuditCanonicalJoinTest(unittest.TestCase):
    """D8: a record without a run or body id reuses the canonical line's ids."""

    def test_normal_json_mode_record_without_body_id_reuses_the_line_id(self):
        sink = _CaptureSink()
        app = _role_app(audit_sink=sink, log_format="json")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(_post_json(app, ROLE_PATH, {"id": ORDER_ID})[0], 401)
        lines = _json_lines_with_method(err.getvalue())
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(sink.records), 1)
        record = sink.records[0]
        self.assertIsNotNone(record["correlation_id"])
        self.assertEqual(record["correlation_id"], lines[0]["correlation_id"])
        self.assertEqual(record["trace_id"], lines[0]["trace_id"])
        self.assertEqual(record["span_id"], lines[0]["span_id"])

    def test_boundary_text_mode_record_without_any_id_is_null_and_no_line_is_printed(self):
        sink = _CaptureSink()
        app = _role_app(audit_sink=sink, log_format="text")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(_post_json(app, ROLE_PATH, {"id": ORDER_ID})[0], 401)
        self.assertEqual(len(sink.records), 1)
        self.assertIsNone(sink.records[0]["correlation_id"])
        self.assertEqual(_json_lines_with_method(err.getvalue()), [])


class AuditEntryPointWiringTest(unittest.TestCase):
    """D14: `serve(audit_sink=)` and `build_app()` via LNPL_AUDIT_SINK."""

    def setUp(self):
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.pop("LNPL_AUDIT_SINK", None)
        self.tmp = _tmpdir(self)
        self.src = os.path.join(self.tmp, "mod.lnpl")
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write(PAYMENT_SRC)

    def _build(self):
        with contextlib.redirect_stderr(io.StringIO()):
            return wsgi.build_app(sources=[self.src])

    def test_normal_env_stderr_json_gives_a_json_lines_sink(self):
        os.environ["LNPL_AUDIT_SINK"] = "stderr-json"
        self.assertIsInstance(self._build().audit_sink, JsonLinesAuditSink)

    def test_normal_env_file_sink_writes_records_for_a_write(self):
        path = os.path.join(self.tmp, "a.jsonl")
        os.environ["LNPL_AUDIT_SINK"] = "file:" + path
        app = self._build()
        self.addCleanup(app.audit_sink.close)
        self.assertEqual(_post_json(app, PAY_PATH, _payload())[0], 200)
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["outcome"]["status"], 200)

    def test_error_env_unknown_spec_is_a_config_error(self):
        os.environ["LNPL_AUDIT_SINK"] = "nope"
        with self.assertRaises(wsgi.WsgiConfigError) as ctx:
            self._build()
        self.assertIn("unknown audit sink", str(ctx.exception))

    def test_boundary_env_empty_or_unset_means_no_sink(self):
        os.environ["LNPL_AUDIT_SINK"] = ""
        self.assertIsNone(self._build().audit_sink)
        os.environ.pop("LNPL_AUDIT_SINK")
        self.assertIsNone(self._build().audit_sink)

    def test_normal_serve_forwards_the_sink_to_the_app(self):
        from lnpl.serve import serve
        sink = _CaptureSink()
        server = serve(_payment_doc(), port=0, audit_sink=sink)
        self.addCleanup(server.server_close)
        self.assertIs(server.get_app().audit_sink, sink)


class AuditCliTest(unittest.TestCase):
    """D10: `lnpl serve --audit-sink` — a bad spec is rc 2 before serve()."""

    def setUp(self):
        self.tmp = _tmpdir(self)
        self.src = os.path.join(self.tmp, "mod.lnpl")
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write(PAYMENT_SRC)

    def _serve(self, *extra):
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 0)
        server.serve_forever.side_effect = KeyboardInterrupt
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("lnpl.cli.serve", return_value=server) as factory, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(["serve", self.src] + list(extra))
        return rc, factory, out.getvalue(), err.getvalue()

    def test_normal_file_spec_reaches_serve_as_an_open_sink(self):
        path = os.path.join(self.tmp, "a.jsonl")
        rc, factory, _out, _err = self._serve("--audit-sink", "file:" + path)
        self.assertEqual(rc, 0)
        sink = factory.call_args.kwargs["audit_sink"]
        self.addCleanup(sink.close)
        self.assertIsInstance(sink, JsonLinesAuditSink)
        self.assertTrue(os.path.exists(path))

    def test_normal_stderr_json_spec_reaches_serve_as_a_stderr_sink(self):
        rc, factory, _out, _err = self._serve("--audit-sink", "stderr-json")
        self.assertEqual(rc, 0)
        sink = factory.call_args.kwargs["audit_sink"]
        self.assertIsInstance(sink, JsonLinesAuditSink)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            sink.export(VALID_RECORD)
        self.assertEqual(json.loads(err.getvalue()), VALID_RECORD)

    def test_error_unknown_and_exporter_names_are_rc_2_before_serve(self):
        for spec in ("nope", "otlp"):
            with self.subTest(spec=spec):
                rc, factory, _out, err = self._serve("--audit-sink", spec)
                self.assertEqual(rc, 2)
                self.assertFalse(factory.called)
                self.assertIn("accepted: stderr-json, file:<path>", err)

    def test_error_unopenable_file_is_rc_2_and_announces_nothing(self):
        missing = os.path.join(self.tmp, "missing", "a.jsonl")
        rc, factory, out, _err = self._serve("--audit-sink", "file:" + missing)
        self.assertEqual(rc, 2)
        self.assertFalse(factory.called)
        self.assertNotIn("serving", out)

    def test_boundary_omitted_flag_passes_none(self):
        rc, factory, _out, _err = self._serve()
        self.assertEqual(rc, 0)
        self.assertIsNone(factory.call_args.kwargs["audit_sink"])

    def test_boundary_empty_file_path_is_rc_2(self):
        rc, factory, _out, err = self._serve("--audit-sink", "file:")
        self.assertEqual(rc, 2)
        self.assertFalse(factory.called)
        self.assertIn("needs a path", err)


if __name__ == "__main__":
    unittest.main()
