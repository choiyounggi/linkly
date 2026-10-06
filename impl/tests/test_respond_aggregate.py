"""Issue #210 / RFC-0059 — `respond` answers a count, a sum or a bounded list
without writing anything.

Before RFC-0059 a read-only workflow had to `create` a row to hold its
answer, so the read wrote to the store and the second identical call failed
409. `respond` now takes two more term kinds next to `<binding>.<field>`:

  * a named aggregate term `<name> as <func> <ref>` (the five existing
    aggregates only), answered as a flat key `{"<name>": value}`;
  * a list term `respond list <binding>`, alone on its line, answered as the
    `{"items": [...], "next": null}` envelope. The RowSet must be bounded:
    every `list` feeding it declares `limit`.

Neither writes a row. Mode B refuses both (RFC-0059 §Mode B), after `fail`,
in `build` and `diff` alike.
"""

import contextlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from lnpl import backend, cli, differential
from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import MASK, Interpreter
from lnpl.lower import LowerError, lower
from lnpl.openapi import TYPE_SCHEMA, _response_schema, generate
from lnpl.parser import parse
from lnpl.repo_policy import default_rows, row_key
from lnpl.spec import extract, run_manifest
from tests.test_wsgi_contract import call_wsgi
from lnpl.wsgi import make_wsgi_app

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Synthetic ids — obviously fake, never copied from a store.
CUSTOMER_A = "00000000-0000-4000-8000-0000000000a1"
CUSTOMER_B = "00000000-0000-4000-8000-0000000000b2"
WORKFLOW = "wf.order.stats"
PATH = "/order-service/order-stats"

HEAD = """capability postgres

entity Order
    field
        id UUID
        customerId UUID
        quantity Integer
        total Money
        secret Password

entity Customer
    field
        id UUID
        tier Integer

service OrderService
    policy
        timeout 5s

workflow OrderStats
"""

LIST_A = "list order where customerId == input.customerId limit 50"
AGG_STEPS = (LIST_A,
             "respond orderCount as count order revenue as sum order.total")
LIST_STEPS = ("list order where customerId == input.customerId "
              "order by quantity limit 50",
              "respond list order")


# RFC-0056: a `fail` must sit under a guard.
CLOSED = "    when input.quantity > 0\n    fail stats-closed\n"


def source(*steps):
    return HEAD + "".join("    %s\n" % step for step in steps)


def compile_doc(src):
    return lower(parse(src), "shop").to_document()


def response_node(doc):
    found = [n for n in doc["nodes"] if n["kind"] == "Response"]
    assert len(found) == 1, found
    return found[0]


def order_id(i):
    return "00000000-0000-4000-8000-%012d" % i


def order_row(i, customer, quantity, amount, secret="pw-synthetic"):
    return {"id": order_id(i), "customerId": customer, "quantity": quantity,
            "total": {"amount": amount, "currency": "USD"}, "secret": secret}


def order_rows(*rows):
    return {"entity.order": {row_key("entity.order", r): r for r in rows}}


THREE_FOR_A = (order_row(1, CUSTOMER_A, 3, "1.25"),
               order_row(2, CUSTOMER_A, 1, "2.50"),
               order_row(3, CUSTOMER_A, 2, "0.25"),
               order_row(4, CUSTOMER_B, 9, "9.00"))


def run(src, rows=(), payload=None):
    interp = Interpreter(compile_doc(src), repo_rows=order_rows(*rows))
    return interp.run_workflow(WORKFLOW, payload or {"customerId": CUSTOMER_A})


def tmp_dir(test):
    base = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    path = tempfile.mkdtemp(prefix="t210-", dir=base)
    test.addCleanup(shutil.rmtree, path, True)
    return path


# ---- grammar, static checks, IR (RFC-0059 §1-§3) ---------------------------

class TestRespondTermGrammar(unittest.TestCase):

    def test_named_aggregate_terms_lower_to_agg_terms(self):
        node = response_node(compile_doc(source(*AGG_STEPS)))
        self.assertEqual(
            [{"name": "orderCount", "func": "count", "ref": "order"},
             {"name": "revenue", "func": "sum", "ref": "order.total",
              "agg_field_type": "Money"}],
            node["aggTerms"])
        # aggregate-only: no `refs` key at all, no `listTerm`
        self.assertNotIn("refs", node)
        self.assertNotIn("listTerm", node)

    def test_bare_refs_and_named_terms_mix_on_one_line(self):
        node = response_node(compile_doc(source(
            "find customer", LIST_A,
            "respond customer.tier orderCount as count order customer.id")))
        self.assertEqual(["customer.tier", "customer.id"], node["refs"])
        self.assertEqual([{"name": "orderCount", "func": "count",
                           "ref": "order"}], node["aggTerms"])

    def test_list_term_lowers_to_list_term(self):
        node = response_node(compile_doc(source(*LIST_STEPS)))
        self.assertEqual({"binding": "order"}, node["listTerm"])
        self.assertNotIn("refs", node)
        self.assertNotIn("aggTerms", node)

    def test_the_existing_form_keeps_its_exact_node_shape(self):
        node = response_node(compile_doc(source(
            "find customer", "respond customer.id customer.tier")))
        self.assertEqual({"kind", "id", "refs", "line"}, set(node))
        self.assertEqual(["customer.id", "customer.tier"], node["refs"])

    def test_an_unnamed_aggregate_is_the_existing_bare_name_error(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source(LIST_A, "respond count order"))
        self.assertIn(
            "respond reference 'count' must name a bound row's field "
            "(`<binding>.<field>`), not a bare name", str(ctx.exception))

    def test_an_unknown_aggregate_function_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source(LIST_A, "respond x as total order"))
        msg = str(ctx.exception)
        self.assertIn("'total'", msg)
        self.assertIn("sum", msg)

    def test_a_duplicate_term_name_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source(
                LIST_A, "respond n as count order n as sum order.quantity"))
        self.assertIn("'n'", str(ctx.exception))
        self.assertIn("more than once", str(ctx.exception))

    def test_a_term_named_like_a_binding_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source(LIST_A, "respond order as count order"))
        self.assertIn("'order'", str(ctx.exception))
        self.assertIn("binding", str(ctx.exception))

    def test_a_term_name_must_be_lower_camel(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source(LIST_A, "respond Total as count order"))
        self.assertIn("'Total'", str(ctx.exception))

    def test_a_truncated_term_is_refused(self):
        for tail in ("n as count", "n as"):
            with self.subTest(tail=tail):
                with self.assertRaises(LowerError) as ctx:
                    compile_doc(source(LIST_A, "respond " + tail))
                self.assertIn("`as`", str(ctx.exception))

    def test_the_aggregate_type_rules_are_the_set_rules(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source(LIST_A, "respond s as sum order.secret"))
        self.assertIn("neither Integer nor Money", str(ctx.exception))
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source(LIST_A, "respond c as count order.quantity"))
        self.assertIn("`count` takes an entity", str(ctx.exception))

    def test_a_list_term_without_limit_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source(
                "list order where customerId == input.customerId",
                "respond list order"))
        msg = str(ctx.exception)
        self.assertIn("limit", msg)
        self.assertIn("RFC-0059", msg)

    def test_every_list_feeding_the_list_term_needs_limit(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source(LIST_A, "list order where quantity > 0",
                               "respond list order"))
        self.assertIn("limit", str(ctx.exception))

    def test_an_aggregate_term_needs_no_limit(self):
        node = response_node(compile_doc(source(
            "list order where quantity > 0", "respond n as count order")))
        self.assertEqual("n", node["aggTerms"][0]["name"])

    def test_the_list_term_stands_alone(self):
        for line in ("respond list order n as count order",
                     "respond n as count order list order",
                     "respond list order customer.id",
                     "respond list",
                     "respond list order order"):
            with self.subTest(line=line):
                with self.assertRaises(LowerError) as ctx:
                    compile_doc(source("find customer", LIST_A, line))
                self.assertIn("list", str(ctx.exception))

    def test_a_list_term_is_the_workflows_only_respond(self):
        for other in ("respond n as count order", "respond list order"):
            with self.subTest(other=other):
                with self.assertRaises(LowerError) as ctx:
                    compile_doc(source(*LIST_STEPS, other))
                self.assertIn("only `respond` step", str(ctx.exception))
                self.assertIn("has 2", str(ctx.exception))
        # two aggregate-term lines still merge, like two bare-ref lines
        node_ids = [n["id"] for n in compile_doc(source(
            LIST_A, "respond n as count order", "respond m as count order"))[
            "nodes"] if n["kind"] == "Response"]
        self.assertEqual(2, len(node_ids))

    def test_a_list_term_must_name_an_entity_binding(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source(LIST_A, "respond list nosuch"))
        self.assertIn("'nosuch'", str(ctx.exception))

    def test_terms_cannot_read_a_create_as_binding(self):
        """A RowSet lives only under an entity's own binding name; a
        `create ... as o` name is a single row, never a RowSet."""
        for line in ("respond n as count o", "respond list o"):
            with self.subTest(line=line):
                with self.assertRaises(LowerError) as ctx:
                    compile_doc(source("when input.quantity > 0",
                                       "create order as o", line))
                self.assertIn("'o'", str(ctx.exception))

    def test_a_never_listed_rowset_warns_orphaned_list(self):
        for line in ("respond n as count order", "respond list order"):
            with self.subTest(line=line):
                module = lower(parse(source(line)), "shop")
                found = list(module.diagnostics.by_code(
                    "aggregation-orphaned-list"))
                self.assertEqual(1, len(found))
                self.assertIn(line, found[0].subject)

    def test_the_ir_validates_against_the_schema(self):
        import jsonschema
        with open(os.path.join(REPO, "schemas", "lir.schema.json"),
                  encoding="utf-8") as fh:
            schema = json.load(fh)
        for steps in (AGG_STEPS, LIST_STEPS,
                      ("find customer", "respond customer.id")):
            with self.subTest(steps=steps):
                jsonschema.validate(compile_doc(source(*steps)), schema)
        doc = compile_doc(source(*AGG_STEPS))
        node = response_node(doc)
        del node["aggTerms"]                 # none of refs/aggTerms/listTerm
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(doc, schema)


# ---- runtime assembly (RFC-0059 §4) ---------------------------------------

class TestRespondTermRuntime(unittest.TestCase):

    def test_aggregate_terms_answer_flat_keys(self):
        result = run(source(*AGG_STEPS), THREE_FOR_A)
        self.assertEqual("completed", result["status"])
        self.assertEqual({"orderCount": 3,
                          "revenue": {"amount": "4.00", "currency": "USD"}},
                         result["response"])

    def test_an_empty_rowset_counts_zero(self):
        result = run(source(LIST_A, "respond orderCount as count order"))
        self.assertEqual({"orderCount": 0}, result["response"])

    def test_mixed_terms_keep_the_grouped_refs(self):
        src = source("find customer", LIST_A,
                     "respond customer.tier orderCount as count order")
        rows = order_rows(*THREE_FOR_A)
        rows["entity.customer"] = {
            row_key("entity.customer", {"id": CUSTOMER_A}):
                {"id": CUSTOMER_A, "tier": 2}}
        result = Interpreter(compile_doc(src), repo_rows=rows).run_workflow(
            WORKFLOW, {"id": CUSTOMER_A, "customerId": CUSTOMER_A})
        self.assertEqual({"customer": {"tier": 2}, "orderCount": 3},
                         result["response"])

    def test_list_term_answers_the_envelope_with_masked_rows(self):
        result = run(source(*LIST_STEPS), THREE_FOR_A)
        items = result["response"]["items"]
        self.assertEqual([order_id(2), order_id(3), order_id(1)],
                         [item["id"] for item in items])
        self.assertIsNone(result["response"]["next"])
        self.assertEqual({"items", "next"}, set(result["response"]))
        for item in items:
            self.assertEqual(MASK, item["secret"])      # Password masked
            self.assertNotIn("pw-synthetic", json.dumps(item))
        self.assertEqual([1, 2, 3], [item["quantity"] for item in items])

    def test_without_the_mask_call_the_secret_would_leak(self):
        """Negative control: the list term's own `mask_payload` call is what
        hides the planted value — with it neutralised, the same assertion
        above would see the raw secret."""
        with mock.patch("lnpl.interp.mask_payload", lambda row, _view: row):
            result = run(source(*LIST_STEPS), THREE_FOR_A)
        self.assertEqual(["pw-synthetic"] * 3,
                         [item["secret"] for item in result["response"]["items"]])

    def test_an_empty_rowset_answers_empty_items(self):
        result = run(source(*LIST_STEPS))
        self.assertEqual({"items": [], "next": None}, result["response"])

    def test_a_rowset_exactly_at_limit_still_has_no_next(self):
        src = source("list order where customerId == input.customerId limit 3",
                     "respond list order")
        result = run(src, THREE_FOR_A)
        self.assertEqual(3, len(result["response"]["items"]))
        self.assertIsNone(result["response"]["next"])

    def test_an_unevaluable_term_fails_its_step_not_the_process(self):
        """`avg` of an empty RowSet has no value (RFC-0045 §3): the run
        fails on the `respond` step and rolls back — no exception escapes
        `run_workflow`, the same outcome `set ... to avg ...` gets."""
        src = source("create customer", LIST_A,
                     "respond mean as avg order.quantity")
        interp = Interpreter(compile_doc(src), repo_rows=order_rows())
        result = interp.run_workflow(
            WORKFLOW, {"id": CUSTOMER_A, "customerId": CUSTOMER_A, "tier": 1})
        self.assertEqual("failed", result["status"])
        self.assertEqual("respond mean as avg order.quantity",
                         result["failed_step"])
        self.assertIn("avg-of-empty-rowset", result["failure_reason"])
        self.assertNotIn("response", result)
        self.assertEqual({}, interp.repo.rows.get("entity.customer", {}))

    def test_avg_min_max_terms_answer_values(self):
        result = run(source(LIST_A, "respond mean as avg order.quantity "
                                    "low as min order.quantity "
                                    "high as max order.quantity"),
                     THREE_FOR_A)
        self.assertEqual({"mean": 2, "low": 1, "high": 3}, result["response"])

    def test_a_failed_run_carries_no_response(self):
        src = source(*AGG_STEPS) + CLOSED
        result = run(src, THREE_FOR_A,
                     {"customerId": CUSTOMER_A, "quantity": 1})
        self.assertEqual("failed", result["status"])
        self.assertNotIn("response", result)

    def test_terms_inside_parallel_match_the_sequential_run(self):
        for first, respond in ((LIST_A, AGG_STEPS[1]), LIST_STEPS):
            with self.subTest(respond=respond):
                other = "list customer where tier > 0 limit 5"
                sequential = run(source(first, respond, other), THREE_FOR_A)
                parallel = run(source(first, "parallel", "    " + respond,
                                      "    " + other, "merge"),
                               THREE_FOR_A)
                self.assertEqual("completed", sequential["status"])
                self.assertEqual("completed", parallel["status"])
                self.assertEqual(sequential["response"], parallel["response"])
                self.assertIn(
                    "orderCount" if "as" in respond else "items",
                    parallel["response"])


# ---- zero writes on a persistent store (issue #210 DoD) --------------------

class TestRespondTermWritesNothing(unittest.TestCase):

    def setUp(self):
        self.dir = tmp_dir(self)
        self.db = os.path.join(self.dir, "store.db")
        self.src = source(*AGG_STEPS)
        driver = SqliteRepositoryDriver(self.db)
        try:
            driver.seed(order_rows(*THREE_FOR_A))
        finally:
            driver.close()

    def row_count(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute("select count(*) from lnpl_rows").fetchone()[0]
        finally:
            con.close()

    def test_lnpl_run_twice_completes_twice_and_adds_no_row(self):
        path = os.path.join(self.dir, "stats.lnpl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.src)
        payload = os.path.join(self.dir, "payload.json")
        with open(payload, "w", encoding="utf-8") as fh:
            json.dump({"customerId": CUSTOMER_A}, fh)
        before = self.row_count()
        self.assertEqual(4, before)
        for attempt in (1, 2):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = cli.main(["run", path, "--workflow", WORKFLOW,
                               "--payload", payload, "--json",
                               "--backend", "sqlite:" + self.db])
            with self.subTest(attempt=attempt):
                self.assertEqual(0, rc, out.getvalue())
                result = json.loads(out.getvalue())["result"]
                self.assertEqual("completed", result["status"])
                self.assertEqual(3, result["response"]["orderCount"])
        self.assertEqual(before, self.row_count())

    def test_serve_twice_answers_200_twice_and_adds_no_row(self):
        doc = compile_doc(self.src)
        app = make_wsgi_app(
            doc, repository_factory=lambda: SqliteRepositoryDriver(self.db))
        before = self.row_count()
        body = json.dumps({"customerId": CUSTOMER_A}).encode("utf-8")
        answers = [call_wsgi(app, "POST", PATH, body=body) for _ in (1, 2)]
        for status, _headers, parsed in answers:
            self.assertEqual(200, status, parsed)
            self.assertEqual({"orderCount": 3,
                              "revenue": {"amount": "4.00", "currency": "USD"}},
                             parsed["response"])
        self.assertEqual(answers[0][2]["response"], answers[1][2]["response"])
        self.assertEqual(before, self.row_count())


# ---- OpenAPI (RFC-0059 §5) -------------------------------------------------

def schema_200(src):
    spec = generate(compile_doc(src))
    op = spec["paths"][PATH]["post"]["responses"]["200"]
    return op["content"]["application/json"]["schema"]


class TestRespondTermOpenApi(unittest.TestCase):

    def test_aggregate_terms_are_flat_typed_properties(self):
        body = schema_200(source(*AGG_STEPS))
        self.assertEqual(["orderCount", "revenue"], body["required"])
        self.assertEqual(TYPE_SCHEMA["Integer"], body["properties"]["orderCount"])
        self.assertEqual(TYPE_SCHEMA["Money"], body["properties"]["revenue"])
        self.assertFalse(body["additionalProperties"])

    def test_min_of_an_integer_field_is_integer(self):
        body = schema_200(source(LIST_A, "respond low as min order.quantity"))
        self.assertEqual({"low": TYPE_SCHEMA["Integer"]}, body["properties"])

    def test_mixed_terms_sit_beside_the_grouped_binding(self):
        body = schema_200(source("find customer", LIST_A,
                                 "respond customer.tier n as count order"))
        self.assertEqual(["customer", "n"], body["required"])
        self.assertEqual(["tier"],
                         body["properties"]["customer"]["required"])

    def test_list_term_is_the_items_next_envelope(self):
        body = schema_200(source(*LIST_STEPS))
        self.assertEqual(
            {"type": "object",
             "properties": {
                 "items": {"type": "array",
                           "items": {"$ref": "#/components/schemas/Order"}},
                 "next": {"type": "null"}},
             "required": ["items", "next"],
             "additionalProperties": False},
            body)

    def test_no_respond_still_has_no_schema(self):
        doc = compile_doc(source(LIST_A))
        wf = next(n for n in doc["nodes"] if n["kind"] == "Workflow")
        nodes = {n["id"]: n for n in doc["nodes"]}
        steps = [nodes[c] for c in wf["children"]]
        entities = [n for n in doc["nodes"] if n["kind"] == "Entity"]
        self.assertIsNone(_response_schema(steps, nodes, entities, {}))


# ---- spec `result <name>` (RFC-0059 §6) ------------------------------------

SPEC_TAIL = """    spec
        given
            input.customerId %s
            stored Order[0] customerId %s
            stored Order[0] total 1.50USD
            stored Order[1] customerId %s
            stored Order[1] total 2.25USD
            stored Order[2] customerId %s
            stored Order[2] total 9.00USD
        when
            orderStats
        expect
%s
"""


def run_spec(*expects):
    src = source(*AGG_STEPS) + SPEC_TAIL % (
        CUSTOMER_A, CUSTOMER_A, CUSTOMER_A, CUSTOMER_B,
        "\n".join("            %s" % e for e in expects))
    decls = parse(src)
    return run_manifest(extract(decls, "shop"), lower(decls, "shop").to_document())


class TestRespondTermSpec(unittest.TestCase):

    def test_result_asserts_a_named_count(self):
        passed, failed, lines = run_spec("completed", "result orderCount == 2")
        self.assertEqual((2, 0), (passed, failed), lines)

    def test_a_wrong_count_fails_the_case(self):
        passed, failed, lines = run_spec("result orderCount == 3")
        self.assertEqual((0, 1), (passed, failed), lines)

    def test_result_asserts_a_named_money_sum(self):
        passed, failed, lines = run_spec("result revenue == 3.75USD",
                                         "result revenue != 3.76USD")
        self.assertEqual((2, 0), (passed, failed), lines)

    def test_a_term_name_absent_from_the_response_fails(self):
        passed, failed, lines = run_spec("result nosuch == 2")
        self.assertEqual((0, 1), (passed, failed), lines)


# ---- mode B (RFC-0059 §7) -------------------------------------------------

class TestRespondTermModeB(unittest.TestCase):

    def _no_toolchain(self):
        real = backend.toolchain_available
        backend.toolchain_available = lambda: False
        self.addCleanup(setattr, backend, "toolchain_available", real)

    def _forbid_tool(self):
        real = backend.tool

        def _guard(*_a, **_k):
            raise AssertionError("tool() called before the mode B refusal")
        backend.tool = _guard
        self.addCleanup(setattr, backend, "tool", real)

    def build_refusal(self, doc):
        self._forbid_tool()
        with self.assertRaises(backend.BackendError) as ctx:
            backend.build(doc, WORKFLOW, tmp_dir(self), seeded=frozenset())
        return str(ctx.exception)

    def diff_refusal(self, doc):
        self._no_toolchain()
        payload = {"customerId": CUSTOMER_A}
        with self.assertRaises(differential.DifferentialError) as ctx:
            differential.verify(doc, WORKFLOW, payload,
                                default_rows(doc, WORKFLOW, payload),
                                tmp_dir(self))
        msg = str(ctx.exception)
        self.assertNotIn("toolchain unavailable", msg)
        return msg

    def test_build_and_diff_refuse_both_term_kinds(self):
        for steps, kind in ((AGG_STEPS, "aggregate"), (LIST_STEPS, "list")):
            doc = compile_doc(source(*steps))
            self.assertTrue(
                backend.workflow_uses_respond_aggregate_or_list(doc, WORKFLOW))
            for name, msg in (("build", self.build_refusal(doc)),
                              ("diff", self.diff_refusal(doc))):
                with self.subTest(kind=kind, cmd=name):
                    self.assertIn("RFC-0059", msg)
                    self.assertIn("`respond` %s term" % kind, msg)

    def test_fail_is_refused_first_in_both(self):
        doc = compile_doc(source(*AGG_STEPS) + CLOSED)
        for msg in (self.build_refusal(doc), self.diff_refusal(doc)):
            self.assertIn("RFC-0056", msg)
            self.assertNotIn("RFC-0059", msg)

    def test_the_existing_form_is_not_this_refusal(self):
        doc = compile_doc(source("find customer", "respond customer.tier"))
        self.assertFalse(
            backend.workflow_uses_respond_aggregate_or_list(doc, WORKFLOW))

    def test_an_unknown_workflow_raises(self):
        doc = compile_doc(source(*AGG_STEPS))
        with self.assertRaises(backend.BackendError):
            backend.workflow_uses_respond_aggregate_or_list(doc, "wf.nope")

    def test_lnpl_build_and_diff_exit_4(self):
        workdir = tmp_dir(self)
        path = os.path.join(workdir, "stats.lnpl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source(*AGG_STEPS))
        for cmd in ("build", "diff"):
            with self.subTest(cmd=cmd):
                err = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(err):
                    rc = cli.main([cmd, path, "--workdir", workdir,
                                   "--workflow", WORKFLOW])
                self.assertEqual(4, rc, err.getvalue())
                self.assertIn("RFC-0059", err.getvalue())


if __name__ == "__main__":
    unittest.main()
