"""Issue #96 — the `respond` verb: a FieldMask-style response declaration.

`respond <ref> [<ref>...]` names a flat list of References (`<binding>.
<field>`, RFC-0012 §G12.1) as the workflow's response body. It derives a new
`Response` IR node (not an Assignment — nothing is written), and at the end
of a *successful* run the interpreter assembles `result["response"]` from the
bindings those references name, grouped `{"<binding>": {"<field>": value}}`
(D3). serve's 200 body and `run --json` both carry it because both send
`run_workflow`'s result verbatim — no code change was needed in either
module, which is what `TestRespondServe`/`TestRespondCliJson` confirm rather
than assume.

A Password-typed reference is a compile error (issue #43's masking
chokepoint, extended to the response surface — the same rule `format`'s
argument check already applies). A workflow with no `respond` gets no
`response` key at all — not even an empty one — so it is byte-identical to
before this feature existed (D4).
"""

import contextlib
import glob
import io
import json
import os
import shutil
import tempfile
import unittest

from lnpl import backend, cli, differential
from lnpl.interp import Interpreter
from lnpl.lower import LowerError, lower
from lnpl.openapi import generate
from lnpl.parser import parse
from lnpl.repo_policy import row_key
from lnpl.serve import serve
from tests.test_serve import ServerTestCase

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HAS_TOOLS = backend.toolchain_available()
NEEDS_TOOLS = unittest.skipUnless(
    HAS_TOOLS, "MLIR/LLVM toolchain not installed (brew install llvm)")

RUN_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

RESPOND_SRC = """capability postgres

entity Order
    field
        id UUID
        status Text
        total Integer
        secret Password

service Orders
    policy
        retry 0

workflow ShowOrder
    find order
    respond order.id order.status order.total
"""

RESPOND_STEP = "respond order.id order.status order.total"


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


def respond_interp(status="new", total=100, secret="s3cret"):
    doc = compile_doc(RESPOND_SRC)
    payload = {"id": RUN_ID, "status": status, "total": total}
    rows = {"entity.order": {row_key("entity.order", payload):
                             {"id": RUN_ID, "status": status, "total": total,
                              "secret": secret}}}
    return Interpreter(doc, repo_rows=rows), payload


class TestRespondCompiles(unittest.TestCase):
    """The verb derives a `Response` node, owned by its `WorkflowStep`."""

    def test_derives_a_response_node(self):
        doc = compile_doc(RESPOND_SRC)
        responses = nodes_of(doc, "Response")
        self.assertEqual(1, len(responses))
        self.assertEqual(["order.id", "order.status", "order.total"],
                         responses[0]["refs"])

    def test_workflow_step_owns_the_response_as_a_child(self):
        doc = compile_doc(RESPOND_SRC)
        steps = nodes_of(doc, "WorkflowStep")
        respond_step = next(s for s in steps if s["name"] == RESPOND_STEP)
        response = nodes_of(doc, "Response")[0]
        self.assertIn(response["id"], respond_step["children"])


class TestRespondRuns(unittest.TestCase):
    """Issue #96's completion criterion 1: `result["response"]`, both
    surfaces that consume it verbatim (serve 200, `run --json`), and the
    existing trace keys unchanged alongside it."""

    def test_run_workflow_result_carries_a_response_clause(self):
        interp, payload = respond_interp(status="new", total=100)
        result = interp.run_workflow("wf.show.order", payload)
        self.assertEqual("completed", result["status"])
        self.assertEqual(
            {"order": {"id": RUN_ID, "status": "new", "total": 100}},
            result["response"])

    def test_existing_trace_keys_are_unchanged_alongside_response(self):
        interp, payload = respond_interp()
        result = interp.run_workflow("wf.show.order", payload)
        for key in ("status", "steps", "skipped", "failed_step",
                   "failure_reason", "bindings", "duration_ms",
                   "correlation_id"):
            self.assertIn(key, result)

    def test_a_different_run_produces_a_different_response(self):
        interp, payload = respond_interp(status="shipped", total=42)
        result = interp.run_workflow("wf.show.order", payload)
        self.assertEqual(
            {"order": {"id": RUN_ID, "status": "shipped", "total": 42}},
            result["response"])

    def test_a_later_step_failing_drops_the_response_too(self):
        # D3: assembled "at execution end, on success only" — a respond step
        # that ran is not enough if a LATER step fails the whole run. `cache`
        # with no `performance cache` TTL budget raises at run time (the same
        # fixture shape `test_serve.py`'s CACHE_SRC uses for its own M8 case).
        src = RESPOND_SRC.replace(RESPOND_STEP, RESPOND_STEP + "\n    cache order")
        doc = compile_doc(src)
        payload = {"id": RUN_ID, "status": "new", "total": 100}
        rows = {"entity.order": {row_key("entity.order", payload):
                                 {"id": RUN_ID, "status": "new", "total": 100,
                                  "secret": "s"}}}
        result = Interpreter(doc, repo_rows=rows).run_workflow(
            "wf.show.order", payload)
        self.assertEqual("failed", result["status"])
        self.assertNotIn("response", result)


class TestRespondStaticRejections(unittest.TestCase):
    """Issue #96's completion criterion 2: the Password compile error, plus
    the underlying Reference checks (#45) `respond` inherits unchanged."""

    def test_password_reference_is_a_compile_error(self):
        src = RESPOND_SRC.replace(RESPOND_STEP, "respond order.id order.secret")
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("Password", str(ctx.exception))

    def test_an_undeclared_field_is_refused(self):
        src = RESPOND_SRC.replace(RESPOND_STEP, "respond order.nonesuch")
        with self.assertRaises(LowerError):
            compile_doc(src)

    def test_an_undeclared_binding_is_refused(self):
        src = RESPOND_SRC.replace(RESPOND_STEP, "respond invoice.id")
        with self.assertRaises(LowerError):
            compile_doc(src)

    def test_a_bare_reference_is_refused(self):
        # No dot: not a `<binding>.<field>` — respond's schema derivation
        # (D6) needs a declared field type, which a bare reference has none of.
        src = RESPOND_SRC.replace(RESPOND_STEP, "respond status")
        with self.assertRaises(LowerError):
            compile_doc(src)

    def test_no_references_at_all_is_refused(self):
        src = RESPOND_SRC.replace(RESPOND_STEP, "respond")
        with self.assertRaises(LowerError):
            compile_doc(src)

    def test_an_entity_this_workflow_never_read_is_refused(self):
        # Same "never reads it" rule `set`'s target and `format`'s target
        # already enforce (issue #45) — respond invents no new check.
        src = RESPOND_SRC.replace("find order", "create order")
        with self.assertRaises(LowerError):
            compile_doc(src)


class TestRespondBoundaries(unittest.TestCase):
    """D8 boundary set: no `respond` is byte-identical, a repeated reference,
    and every field enumerated."""

    def test_a_workflow_without_respond_carries_no_response_key(self):
        src = RESPOND_SRC.replace(RESPOND_STEP, "find order")
        # `find order` twice is harmless; simplest way to drop the verb line
        # without leaving the workflow empty.
        doc = compile_doc(src)
        self.assertEqual([], nodes_of(doc, "Response"))
        payload = {"id": RUN_ID, "status": "new", "total": 100}
        rows = {"entity.order": {row_key("entity.order", payload):
                                 {"id": RUN_ID, "status": "new", "total": 100,
                                  "secret": "s"}}}
        result = Interpreter(doc, repo_rows=rows).run_workflow(
            "wf.show.order", payload)
        self.assertEqual("completed", result["status"])
        self.assertNotIn("response", result)

    def test_no_shipped_example_declares_respond_yet(self):
        # A stronger form of the same D4 guarantee, over every example this
        # repo ships: none of them can regress because none of them uses the
        # new verb at all.
        for path in sorted(glob.glob(os.path.join(REPO, "examples", "*.lnpl"))):
            with open(path, encoding="utf-8") as fh:
                doc = compile_doc(fh.read(), os.path.basename(path))
            self.assertEqual([], nodes_of(doc, "Response"), path)

    def test_the_same_field_may_be_referenced_twice(self):
        src = RESPOND_SRC.replace(RESPOND_STEP, "respond order.id order.id")
        doc = compile_doc(src)
        payload = {"id": RUN_ID, "status": "new", "total": 100}
        rows = {"entity.order": {row_key("entity.order", payload):
                                 {"id": RUN_ID, "status": "new", "total": 100,
                                  "secret": "s"}}}
        result = Interpreter(doc, repo_rows=rows).run_workflow(
            "wf.show.order", payload)
        self.assertEqual({"order": {"id": RUN_ID}}, result["response"])

    def test_every_declared_field_may_be_listed(self):
        src = RESPOND_SRC.replace(
            RESPOND_STEP, "respond order.id order.status order.total order.secret")
        # Every field including the Password one is still a compile error —
        # "list them all" does not create an exception to the masking rule.
        with self.assertRaises(LowerError):
            compile_doc(src)


GUARD_SKIP_RESPOND_SRC = """entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

service ShopService

workflow PlaceOrder
    find product
    when product.stock >= input.quantity
    create order as o
    respond o.id
"""

FIELD_MISSING = "respond-field-missing"


class TestRespondOmitsAGuardSkippedBinding(ServerTestCase):
    """Issue #198: `o` was never created because its guard was false — the
    run still completes, `skipped` explains it, `response` omits `o`
    entirely. No traceback on the interpreter, the CLI or serve."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-respond-skip-", dir=os.path.join(REPO, ".claude", "tmp"))
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)
        self.src_path = os.path.join(self.workdir, "placeorder.lnpl")
        with open(self.src_path, "w", encoding="utf-8") as fh:
            fh.write(GUARD_SKIP_RESPOND_SRC)

    def _payload_path(self, payload):
        path = os.path.join(self.workdir, "payload.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def _interp(self, stock, quantity):
        doc = compile_doc(GUARD_SKIP_RESPOND_SRC)
        payload = {"id": RUN_ID, "stock": stock, "quantity": quantity}
        rows = {"entity.product": {row_key("entity.product", payload):
                                   {"id": RUN_ID, "stock": stock}}}
        return Interpreter(doc, repo_rows=rows), payload

    def test_run_completes_with_no_o_in_response(self):
        interp, payload = self._interp(stock=1, quantity=5)
        result = interp.run_workflow("wf.place.order", payload)
        self.assertEqual("completed", result["status"])
        self.assertEqual(["create order as o"], result["skipped"][0]["steps"])
        self.assertEqual({}, result["response"])
        # D1: `skipped[]` already explains it — no second diagnostic.
        self.assertEqual([], interp.diagnostics.by_code(FIELD_MISSING))

    def test_the_guard_holding_still_responds_with_o(self):
        # The control for the test above: same source, the guard holds, so
        # the omission is the guard's doing and not a blanket drop of `o`.
        interp, payload = self._interp(stock=5, quantity=1)
        result = interp.run_workflow("wf.place.order", payload)
        self.assertEqual("completed", result["status"])
        self.assertEqual([], result["skipped"])
        self.assertEqual(["id"], list(result["response"]["o"]))

    def test_cli_run_exits_zero_without_a_traceback(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(["run", self.src_path, "--payload",
                           self._payload_path(
                               {"id": RUN_ID, "stock": 1, "quantity": 5}),
                           "--json"])
        self.assertEqual(0, rc)
        result = json.loads(out.getvalue())["result"]
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["skipped"])
        self.assertNotIn("o", result["response"])
        self.assertNotIn("Traceback", err.getvalue())

    def test_serve_200_with_no_o_in_response(self):
        port = self.start(compile_doc(GUARD_SKIP_RESPOND_SRC))
        resp, body = self.post_json(
            port, "/shop-service/place-order",
            {"id": RUN_ID, "stock": 1, "quantity": 5})
        self.assertEqual(200, resp.status)
        self.assertEqual("completed", body["status"])
        self.assertTrue(body["skipped"])
        self.assertNotIn("o", body["response"])


class TestRespondOmitsAMissingField(ServerTestCase):
    """Issue #198: the bound row exists but lacks a field `respond` names —
    the ref is omitted and exactly one `respond-field-missing` names it."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-respond-field-", dir=os.path.join(REPO, ".claude", "tmp"))
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)

    def _run(self, source, row):
        doc = compile_doc(source)
        payload = {"id": RUN_ID}
        rows = {"entity.order": {row_key("entity.order", payload): row}}
        interp = Interpreter(doc, repo_rows=rows)
        return interp, interp.run_workflow("wf.show.order", payload)

    def test_an_absent_field_is_omitted_with_one_warning(self):
        interp, result = self._run(
            RESPOND_SRC, {"id": RUN_ID, "total": 100, "secret": "s"})
        self.assertEqual("completed", result["status"])
        self.assertEqual({"order": {"id": RUN_ID, "total": 100}},
                         result["response"])
        found = interp.diagnostics.by_code(FIELD_MISSING)
        self.assertEqual(["order.status"], [d.subject for d in found])
        self.assertEqual("warning", found[0].severity)
        self.assertEqual("ShowOrder", found[0].where)
        self.assertIn("respond order.status", found[0].message)

    def test_each_absent_field_gets_its_own_warning(self):
        interp, result = self._run(RESPOND_SRC, {"id": RUN_ID, "secret": "s"})
        self.assertEqual({"order": {"id": RUN_ID}}, result["response"])
        self.assertEqual(
            ["order.status", "order.total"],
            [d.subject for d in interp.diagnostics.by_code(FIELD_MISSING)])

    def test_a_ref_repeated_in_respond_is_reported_once(self):
        src = RESPOND_SRC.replace(RESPOND_STEP,
                                  "respond order.status order.status")
        interp, result = self._run(src, {"id": RUN_ID, "total": 100})
        self.assertEqual({}, result["response"])
        self.assertEqual(
            ["order.status"],
            [d.subject for d in interp.diagnostics.by_code(FIELD_MISSING)])

    def test_a_present_null_field_is_kept_and_not_reported(self):
        # Boundary: a stored `null` is a value, not an absence.
        interp, result = self._run(
            RESPOND_SRC,
            {"id": RUN_ID, "status": None, "total": 0, "secret": "s"})
        self.assertEqual({"order": {"id": RUN_ID, "status": None, "total": 0}},
                         result["response"])
        self.assertEqual([], interp.diagnostics.by_code(FIELD_MISSING))

    def test_cli_run_exits_zero_and_strict_warning_gates_it(self):
        src_path = os.path.join(self.workdir, "respond.lnpl")
        with open(src_path, "w", encoding="utf-8") as fh:
            fh.write(RESPOND_SRC)
        payload_path = os.path.join(self.workdir, "payload.json")
        with open(payload_path, "w", encoding="utf-8") as fh:
            json.dump({"id": RUN_ID, "status": "new"}, fh)   # no `total`
        argv = ["run", src_path, "--payload", payload_path, "--json"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        self.assertEqual(0, rc)
        result = json.loads(out.getvalue())["result"]
        self.assertEqual({"order": {"id": RUN_ID, "status": "new"}},
                         result["response"])
        self.assertNotIn("Traceback", err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, cli.main(argv + ["--strict=warning"]))

    def test_serve_200_omits_the_absent_field(self):
        port = self.start(compile_doc(RESPOND_SRC))
        resp, body = self.post_json(port, "/orders/show-order",
                                    {"id": RUN_ID, "status": "new"})
        self.assertEqual(200, resp.status)
        self.assertEqual({"order": {"id": RUN_ID, "status": "new"}},
                         body["response"])


OPTIONAL_RESPOND_SRC = RESPOND_SRC.replace("status Text", "status Text optional")

CREATE_AS_OPTIONAL_SRC = OPTIONAL_RESPOND_SRC.replace(
    "    find order\n    " + RESPOND_STEP,
    "    create order as newOrder\n"
    "    respond newOrder.id newOrder.status newOrder.total")


class TestRespondOmitsAnOptionalField(unittest.TestCase):
    """RFC-0053: an absent or null `optional` field is simply omitted from
    the response — it is the declared shape, so no `respond-field-missing`."""

    def _run(self, source, row):
        doc = compile_doc(source)
        payload = {"id": RUN_ID}
        rows = {"entity.order": {row_key("entity.order", payload): row}}
        interp = Interpreter(doc, repo_rows=rows)
        return interp, interp.run_workflow("wf.show.order", payload)

    def test_respond_omits_absent_optional_field_no_diagnostic(self):
        interp, result = self._run(OPTIONAL_RESPOND_SRC,
                                   {"id": RUN_ID, "total": 100, "secret": "s"})
        self.assertEqual("completed", result["status"])
        self.assertEqual({"order": {"id": RUN_ID, "total": 100}},
                         result["response"])
        self.assertEqual([], interp.diagnostics.by_code(FIELD_MISSING))

    def test_respond_omits_null_optional_field_no_diagnostic(self):
        interp, result = self._run(
            OPTIONAL_RESPOND_SRC,
            {"id": RUN_ID, "status": None, "total": 100, "secret": "s"})
        self.assertEqual({"order": {"id": RUN_ID, "total": 100}},
                         result["response"])
        self.assertEqual([], interp.diagnostics.by_code(FIELD_MISSING))

    def test_respond_keeps_a_present_optional_field(self):
        _interp, result = self._run(
            OPTIONAL_RESPOND_SRC,
            {"id": RUN_ID, "status": "new", "total": 100, "secret": "s"})
        self.assertEqual({"order": {"id": RUN_ID, "status": "new", "total": 100}},
                         result["response"])

    def test_respond_absent_non_optional_field_still_warns(self):
        # Regression: `total` is required, so its absence is still reported.
        interp, result = self._run(OPTIONAL_RESPOND_SRC,
                                   {"id": RUN_ID, "secret": "s"})
        self.assertEqual({"order": {"id": RUN_ID}}, result["response"])
        self.assertEqual(["order.total"],
                         [d.subject for d in interp.diagnostics.by_code(FIELD_MISSING)])

    def test_respond_omits_an_optional_field_of_a_create_as_alias(self):
        # The alias is not an entity's default binding name, so the entity is
        # found through the created row's own `entity_id`.
        doc = compile_doc(CREATE_AS_OPTIONAL_SRC)
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow("wf.show.order", {"id": RUN_ID, "total": 7})
        self.assertEqual("completed", result["status"])
        self.assertEqual({"newOrder": {"id": RUN_ID, "total": 7}},
                         result["response"])
        self.assertEqual([], interp.diagnostics.by_code(FIELD_MISSING))


class TestRespondOpenApi(unittest.TestCase):
    """Issue #96's completion criterion 3: the 200 schema is derived from
    `respond`, grouped by binding, and absent when no `respond` exists."""

    def test_200_schema_is_derived_from_respond(self):
        doc = compile_doc(RESPOND_SRC)
        spec = generate(doc)
        schema = spec["paths"]["/orders/show-order"]["post"]["responses"]["200"]["content"]
        body = schema["application/json"]["schema"]
        self.assertEqual(["order"], body["required"])
        order = body["properties"]["order"]
        self.assertEqual({"id", "status", "total"}, set(order["properties"]))
        self.assertEqual({"type": "string", "format": "uuid"},
                         order["properties"]["id"])
        self.assertEqual({"type": "integer", "format": "int64"},
                         order["properties"]["total"])

    def test_a_workflow_without_respond_gets_no_200_content(self):
        src = RESPOND_SRC.replace(RESPOND_STEP, "find order")
        doc = compile_doc(src)
        spec = generate(doc)
        op200 = spec["paths"]["/orders/show-order"]["post"]["responses"]["200"]
        self.assertNotIn("content", op200)


class TestRespondServe(ServerTestCase):
    """serve's 200 body carries the same `response` clause — sent verbatim,
    with zero change needed in serve.py."""

    def test_serve_200_body_carries_the_response_clause(self):
        doc = compile_doc(RESPOND_SRC)
        port = self.start(doc)
        payload = {"id": RUN_ID, "status": "new", "total": 100}
        resp, body = self.post_json(port, "/orders/show-order", payload)
        self.assertEqual(200, resp.status)
        self.assertEqual(
            {"order": {"id": RUN_ID, "status": "new", "total": 100}},
            body["response"])
        self.assertIn("bindings", body)          # existing key, unchanged


class TestRespondCliJson(unittest.TestCase):
    """`lnpl run --json` carries the same `response` clause — sent verbatim,
    with zero change needed in cli.py."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-respond-cli-", dir=os.path.join(REPO, ".claude", "tmp"))
        self.src_path = os.path.join(self.workdir, "respond.lnpl")
        with open(self.src_path, "w", encoding="utf-8") as fh:
            fh.write(RESPOND_SRC)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_run_json_carries_the_response_clause(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["run", self.src_path, "--json"])
        self.assertEqual(0, rc)
        out = json.loads(buf.getvalue())
        self.assertEqual("completed", out["result"]["status"])
        self.assertIn("order", out["result"]["response"])
        self.assertIn("bindings", out["result"])


class TestRespondModeBEquivalence(unittest.TestCase):
    """Issue #96's D7: mode B needs no new MLIR — the generic effect-kind
    recording (`_lnpl_ops`) and runtime shim already handle any kind string,
    including a brand-new one. This differential test confirms that rather
    than assumes it (same rule format's own equivalence test states)."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-respond-diff-", dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    @NEEDS_TOOLS
    def test_the_fixture_is_equivalent(self):
        doc = compile_doc(RESPOND_SRC)
        payload = {"id": RUN_ID, "status": "new", "total": 100}
        rows = {"entity.order": {row_key("entity.order", payload):
                                 {"id": RUN_ID, "status": "new", "total": 100,
                                  "secret": "s"}}}
        ok, report = differential.verify(doc, "wf.show.order", payload,
                                         rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))

    @NEEDS_TOOLS
    def test_an_unread_entity_is_equivalent_too(self):
        doc = compile_doc(RESPOND_SRC)
        payload = {"id": RUN_ID, "status": "new", "total": 100}
        ok, report = differential.verify(doc, "wf.show.order", payload,
                                         {}, self.workdir, seeded=frozenset())
        self.assertTrue(ok, "\n".join(report))


if __name__ == "__main__":
    unittest.main()
