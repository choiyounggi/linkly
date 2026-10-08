"""Issue #200 / RFC-0057 -- a body-mapping clause on call/request:
`call <Target> send <ref>... [with <ref>...] [as <name>]`.

Grammar and IR shape (lower.py), the shared reference rules (RFC-0049's,
reused), runtime assembly against a real local recording HTTP server, and
the no-clause default body, which leaves Password-family input fields out
(issue #214) -- see RFC-0057 and RFC-0063.
"""
import json
import unittest

from lnpl.drivers import FakeNetworkDriver, HttpNetworkDriver
from lnpl.interp import Interpreter, omit_masked_fields
from lnpl.lower import LowerError, lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key
from tests.test_network_driver import _make_handler, _ServerTestCase


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def network_call_node(doc):
    return next(n for n in doc["nodes"] if n["kind"] == "NetworkCall")


def workflow_id(doc):
    return next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")


# No `path`: `send` and `as` only.
PLAIN = """capability http PaymentGateway
    method post

entity Order
    field
        id UUID
        label Text
        total Integer

entity Payment
    field
        id UUID
        total Integer

entity Customer
    field
        id UUID
        secret Password

workflow Ping
    create order as o
"""

# A `path` with one placeholder, so `with <ref>` is legal.
WITH_PATH = """capability http PaymentGateway
    method post
    path "/orders/{}"

entity Order
    field
        id UUID
        label Text

workflow Ping
    create order as o
"""

# issue #204's fixture shape (test_lower.py DERIVED_EMIT_SRC): a plain
# `derived` field computable from an Integer input.
DERIVED = """capability http PaymentGateway
    method post

entity Order
    field
        id UUID
        quantity Integer
        total Integer derived

workflow PlaceOrder
    create order as o
"""


def step(source, line):
    return source + "    %s\n" % line


class SendClauseOrderTest(unittest.TestCase):

    def test_send_alone_builds_body_map(self):
        doc = compile_doc(step(PLAIN, "call PaymentGateway send o.id o.label as pay"))
        node = network_call_node(doc)
        self.assertEqual([{"field": "id", "ref": "o.id"},
                          {"field": "label", "ref": "o.label"}], node["bodyMap"])
        self.assertEqual("pay", node["result"])

    def test_send_without_as_builds_body_map_and_no_result(self):
        node = network_call_node(compile_doc(step(PLAIN, "call PaymentGateway send o.id")))
        self.assertEqual([{"field": "id", "ref": "o.id"}], node["bodyMap"])
        self.assertNotIn("result", node)

    def test_send_with_and_as_combine_in_order(self):
        node = network_call_node(compile_doc(
            step(WITH_PATH, "call PaymentGateway send o.id o.label with o.id as pay")))
        self.assertEqual([{"field": "id", "ref": "o.id"},
                          {"field": "label", "ref": "o.label"}], node["bodyMap"])
        self.assertEqual(["o.id"], node["path_args"])
        self.assertEqual("pay", node["result"])

    def test_with_before_send_is_a_compile_error(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(WITH_PATH, "call PaymentGateway with o.id send o.id"))
        self.assertIn("fixed order", str(ctx.exception))
        self.assertIn("'send'", str(ctx.exception))

    def test_as_before_send_is_a_compile_error(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(PLAIN, "call PaymentGateway as pay send o.id"))
        self.assertIn("fixed order", str(ctx.exception))

    def test_as_before_with_is_still_a_compile_error(self):
        # the pre-existing with/as order, now enforced by the same parser
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(WITH_PATH, "call PaymentGateway as pay with o.id"))
        self.assertIn("fixed order", str(ctx.exception))

    def test_send_twice_is_a_compile_error(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(PLAIN, "call PaymentGateway send o.id send o.label"))
        self.assertIn("fixed order", str(ctx.exception))

    def test_an_unknown_leading_word_is_a_compile_error(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(PLAIN, "call PaymentGateway body o.id"))
        msg = str(ctx.exception)
        self.assertIn("'send <ref>...', 'with <ref>...', 'as <name>'", msg)
        self.assertIn("('body', 'o.id')", msg)

    def test_send_with_no_references_is_a_compile_error(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(PLAIN, "call PaymentGateway send"))
        self.assertIn("`send` needs at least one reference", str(ctx.exception))

    def test_send_with_no_references_before_as_is_a_compile_error(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(PLAIN, "call PaymentGateway send as pay"))
        self.assertIn("`send` needs at least one reference", str(ctx.exception))

    def test_with_with_no_references_is_still_a_compile_error(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(WITH_PATH, "call PaymentGateway send o.id with as pay"))
        self.assertIn("`with` needs at least one reference", str(ctx.exception))

    def test_as_needs_exactly_one_name(self):
        for tail in ("as", "as pay extra"):
            with self.subTest(tail=tail):
                with self.assertRaises(LowerError) as ctx:
                    compile_doc(step(PLAIN, "call PaymentGateway send o.id %s" % tail))
                self.assertIn("`as` needs exactly one name", str(ctx.exception))

    def test_a_bare_name_in_send_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(PLAIN, "call PaymentGateway send o.id Unmapped"))
        self.assertIn("camelCase or binding.field", str(ctx.exception))

    def test_a_camel_case_bare_name_in_send_is_rejected(self):
        # shape-valid, so the scope check is the one that refuses it
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(PLAIN, "call PaymentGateway send unmappedWord"))
        msg = str(ctx.exception)
        self.assertIn("call/request send unmappedWord", msg)
        self.assertIn("not a bare name", msg)

    def test_a_duplicate_mapped_field_name_in_send_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(PLAIN + "    find payment\n",
                             "call PaymentGateway send o.total payment.total"))
        msg = str(ctx.exception)
        self.assertIn("`send` maps field 'total'", msg)
        self.assertIn("unique", msg)

    def test_a_call_with_no_clause_has_no_body_map_key(self):
        node = network_call_node(compile_doc(step(PLAIN, "call PaymentGateway")))
        self.assertEqual({"kind", "id", "target", "line"}, set(node))

    def test_existing_with_and_as_forms_have_no_body_map_key(self):
        node = network_call_node(compile_doc(
            step(WITH_PATH, "call PaymentGateway with o.id as pay")))
        self.assertNotIn("bodyMap", node)
        self.assertEqual(["o.id"], node["path_args"])
        self.assertEqual("pay", node["result"])

    def test_request_verb_gets_the_same_grammar(self):
        node = network_call_node(compile_doc(
            step(PLAIN, "request PaymentGateway send o.id o.label as pay")))
        self.assertEqual([{"field": "id", "ref": "o.id"},
                          {"field": "label", "ref": "o.label"}], node["bodyMap"])

    def test_send_is_an_ordinary_word_outside_the_call_line(self):
        # `send` is not a lexer keyword: it is still a legal field name.
        doc = compile_doc(
            "capability http PaymentGateway\n    method post\n\n"
            "entity Order\n    field\n        id UUID\n        send Integer\n\n"
            "workflow Ping\n    create order as o\n"
            "    call PaymentGateway send o.send\n")
        self.assertEqual([{"field": "send", "ref": "o.send"}],
                         network_call_node(doc)["bodyMap"])


class SendClauseReferenceRulesTest(unittest.TestCase):

    def test_a_password_family_field_in_send_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(PLAIN + "    find customer\n",
                             "call PaymentGateway send customer.secret"))
        msg = str(ctx.exception)
        self.assertIn("call/request send customer.secret", msg)
        self.assertIn("Password", msg)
        self.assertIn("outbound payload", msg)

    def test_a_derived_field_without_a_preceding_set_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(DERIVED, "call PaymentGateway send o.id o.total"))
        msg = str(ctx.exception)
        self.assertIn("derived", msg)
        # DERIVED is 11 lines, so the call is line 12.
        self.assertIn("no `set`/`format` on o.total precedes this "
                      "`call/request` (line 12)", msg)
        self.assertIn("a send-clause may map", msg)

    def test_a_set_before_send_in_the_same_scope_admits_a_derived_field(self):
        doc = compile_doc(DERIVED + "    set o.total to input.quantity * 10\n"
                                    "    call PaymentGateway send o.id o.total\n")
        self.assertEqual([{"field": "id", "ref": "o.id"},
                          {"field": "total", "ref": "o.total"}],
                         network_call_node(doc)["bodyMap"])

    def test_a_set_in_another_guard_scope_does_not_admit_a_derived_field(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(DERIVED + "    when input.quantity > 0\n"
                                  "    set o.total to input.quantity * 10\n"
                                  "    call PaymentGateway send o.total\n")
        self.assertIn("same guard scope", str(ctx.exception))

    def test_an_unknown_reference_in_send_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(step(PLAIN, "call PaymentGateway send nope.field"))
        msg = str(ctx.exception)
        self.assertIn("nope", msg)
        self.assertIn("not a declared entity", msg)

    def test_input_and_earlier_call_results_are_admitted(self):
        doc = compile_doc(step(PLAIN + "    call PaymentGateway as quote\n",
                               "call PaymentGateway send input.label quote.price"))
        nodes = [n for n in doc["nodes"] if n["kind"] == "NetworkCall"]
        self.assertEqual([{"field": "label", "ref": "input.label"},
                          {"field": "price", "ref": "quote.price"}],
                         nodes[1]["bodyMap"])

    def test_a_fill_source_generated_id_is_usable_as_a_send_reference(self):
        doc = compile_doc(
            "capability http PaymentGateway\n    method post\n\n"
            "entity Order\n    field\n        id UUID derived generated\n\n"
            "workflow Ping\n    create order as o\n"
            "    call PaymentGateway send o.id\n")
        self.assertEqual([{"field": "id", "ref": "o.id"}],
                         network_call_node(doc)["bodyMap"])

    def test_emit_with_shares_the_fill_source_admission(self):
        # one shared check: `emit ... with` admits the same reference
        doc = compile_doc(
            "entity Order\n    field\n        id UUID derived generated\n\n"
            "event OrderPlaced\n\n"
            "workflow Ping\n    create order as o\n"
            "    emit orderPlaced with o.id\n")
        emit = next(n for n in doc["nodes"] if n["kind"] == "EventEmit")
        self.assertEqual([{"field": "id", "ref": "o.id"}], emit["payloadMap"])


PLACE_ORDER = """capability http PaymentGateway
    method post

entity Order
    field
        id UUID
        productId UUID
        customerId UUID
        quantity Integer
        total Integer
        status Text

workflow PlaceOrder
    create order as o
    set o.total to input.quantity * 10
    call PaymentGateway send o.id o.total as pay
"""


class SendClauseRuntimeAssemblyTest(_ServerTestCase):

    def _run(self, source, payload, run_context=None):
        handler = _make_handler(status=200, body={"ok": 1})
        url = self.start(handler)
        doc = compile_doc(source)
        driver = HttpNetworkDriver(endpoints={"PaymentGateway": url})
        self.addCleanup(driver.close)
        result = Interpreter(doc, repo_rows={}, network=driver).run_workflow(
            workflow_id(doc), payload, run_context=run_context)
        return handler, result

    def test_the_issue_s_place_order_scenario_sends_exactly_the_mapped_fields(self):
        payload = {"id": "o-1", "productId": "p-1", "customerId": "c-1",
                   "quantity": 2, "status": "pending"}
        handler, result = self._run(PLACE_ORDER, payload)
        self.assertEqual("completed", result["status"])
        # `total` is the computed 2 * 10, a value the input never carried
        self.assertEqual([{"id": "o-1", "total": 20}], handler.received)
        self.assertEqual({"ok": 1, "status": 200}, result["bindings"]["pay"])

    def test_a_generated_id_reaches_the_body(self):
        source = ("capability http PaymentGateway\n    method post\n\n"
                  "entity Order\n    field\n        id UUID derived generated\n"
                  "        quantity Integer\n\n"
                  "workflow Ping\n    create order as o\n"
                  "    call PaymentGateway send o.id input.quantity\n")
        generated = "00000000-0000-4000-8000-000000000001"
        handler, result = self._run(source, {"quantity": 3},
                                    run_context={"generated": generated})
        self.assertEqual("completed", result["status"])
        self.assertEqual([{"id": generated, "quantity": 3}], handler.received)

    def test_an_absent_optional_input_field_is_omitted(self):
        source = ("capability http PaymentGateway\n    method post\n\n"
                  "entity Order\n    field\n        id UUID\n"
                  "        label Text\n"
                  "        note Text optional\n\n"
                  "workflow Ping\n    create order as o\n"
                  "    call PaymentGateway send o.id input.note\n")
        # `label` is in the input but not listed, `note` is listed but
        # absent: neither key reaches the body, and no null is invented.
        handler, result = self._run(source, {"id": "o-1", "label": "x"})
        self.assertEqual("completed", result["status"])
        self.assertEqual([{"id": "o-1"}], handler.received)


# issue #214 / RFC-0063: no `find` step, so repo_rows={} is enough.
CALL_ONLY_SOURCE = ("capability http PaymentGateway\n    method post\n\n"
                    "entity Customer\n    field\n        id UUID\n"
                    "        secret Password\n\n"
                    "workflow Ping\n    call PaymentGateway as paymentResult\n")


class PasswordInDefaultBodyMeasurementTest(unittest.TestCase):
    """Issue #214 / RFC-0063: a plain call ... as (no send) leaves every
    Password-family input field out of the body -- the key is absent, never
    "***". The planted value is an obviously synthetic placeholder.
    """

    SOURCE = ("capability http PaymentGateway\n    method post\n\n"
              "entity Customer\n    field\n        id UUID\n"
              "        secret Password\n\n"
              "workflow Ping\n    find customer\n"
              "    call PaymentGateway as paymentResult\n")

    def test_a_plain_call_leaves_a_password_family_field_out(self):
        doc = compile_doc(self.SOURCE)
        payload = {"id": "c-1", "secret": "sw0rdfish-raw"}
        rows = {"entity.customer": {row_key("entity.customer", payload):
                                    {"id": "c-1", "secret": "sw0rdfish-raw"}}}
        rec = FakeNetworkDriver()
        result = Interpreter(doc, repo_rows=rows, network=rec).run_workflow(
            workflow_id(doc), payload)
        self.assertEqual("completed", result["status"])
        self.assertEqual([("PaymentGateway", {"id": "c-1"}, None)],
                         [(r["target"], r["payload"], r["path"]) for r in rec.received])
        self.assertNotIn("sw0rdfish-raw", repr(rec.received))
        self.assertNotIn("***", repr(rec.received))
        # the caller's dict is not mutated by the filter
        self.assertEqual({"id": "c-1", "secret": "sw0rdfish-raw"}, payload)

    def test_a_send_clause_leaves_the_password_field_out(self):
        # negative control: the same run with `send` carries only `id`
        doc = compile_doc(self.SOURCE.replace(
            "call PaymentGateway as paymentResult",
            "call PaymentGateway send customer.id as paymentResult"))
        payload = {"id": "c-1", "secret": "sw0rdfish-raw"}
        rows = {"entity.customer": {row_key("entity.customer", payload):
                                    {"id": "c-1", "secret": "sw0rdfish-raw"}}}
        rec = FakeNetworkDriver()
        Interpreter(doc, repo_rows=rows, network=rec).run_workflow(
            workflow_id(doc), payload)
        self.assertEqual([{"id": "c-1"}], [r["payload"] for r in rec.received])
        self.assertNotIn("sw0rdfish-raw", repr(rec.received))



GATEWAY = "capability http PaymentGateway\n    method post\n\n"
PING_CALL = "workflow Ping\n    call PaymentGateway as paymentResult\n"


class DefaultBodyPasswordExclusionTest(unittest.TestCase):

    def _sent(self, source, payload, rows=None):
        doc = compile_doc(source)
        rec = FakeNetworkDriver()
        result = Interpreter(doc, repo_rows=rows or {}, network=rec).run_workflow(
            workflow_id(doc), payload)
        self.assertEqual("completed", result["status"])
        return [(r["target"], r["payload"], r["path"]) for r in rec.received], rec

    def test_a_request_step_leaves_a_password_family_field_out(self):
        calls, rec = self._sent(
            CALL_ONLY_SOURCE.replace("call PaymentGateway", "request PaymentGateway"),
            {"id": "c-1", "secret": "sw0rdfish-raw"})
        self.assertEqual([("PaymentGateway", {"id": "c-1"}, None)], calls)
        self.assertNotIn("sw0rdfish-raw", repr(rec.received))

    def test_a_refinement_of_password_is_left_out_too(self):
        source = (GATEWAY + "refine ApiKey of Password\n    minLength 8\n\n"
                  "entity Customer\n    field\n        id UUID\n"
                  "        token ApiKey\n\n" + PING_CALL)
        calls, rec = self._sent(source, {"id": "c-1", "token": "tk-synthetic-1"})
        self.assertEqual([("PaymentGateway", {"id": "c-1"}, None)], calls)
        self.assertNotIn("tk-synthetic-1", repr(rec.received))

    def test_a_body_with_no_password_family_field_is_byte_identical(self):
        payload = {"id": "c-1", "tier": "gold"}
        calls, rec = self._sent(
            CALL_ONLY_SOURCE.replace("secret Password", "tier Text"), payload)
        self.assertEqual('{"id": "c-1", "tier": "gold"}',
                         json.dumps(rec.received[0]["payload"]))
        self.assertEqual([("PaymentGateway", {"id": "c-1", "tier": "gold"}, None)],
                         calls)
        self.assertIs(payload, rec.received[0]["payload"])

    def test_an_input_without_the_declared_password_field_is_sent_unchanged(self):
        payload = {"id": "c-1"}
        calls, rec = self._sent(CALL_ONLY_SOURCE, payload)
        self.assertEqual([("PaymentGateway", {"id": "c-1"}, None)], calls)
        self.assertIs(payload, rec.received[0]["payload"])

    def test_an_input_holding_only_a_password_family_field_sends_an_empty_body(self):
        calls, rec = self._sent(CALL_ONLY_SOURCE, {"secret": "sw0rdfish-raw"})
        self.assertEqual([("PaymentGateway", {}, None)], calls)
        self.assertNotIn("sw0rdfish-raw", repr(rec.received))

    def test_an_empty_input_sends_an_empty_body(self):
        calls, _ = self._sent(CALL_ONLY_SOURCE, {})
        self.assertEqual([("PaymentGateway", {}, None)], calls)

    def test_a_document_with_no_entity_sends_the_input_unchanged(self):
        calls, _ = self._sent(GATEWAY + PING_CALL,
                              {"id": "c-1", "note": "plain-note"})
        self.assertEqual(
            [("PaymentGateway", {"id": "c-1", "note": "plain-note"}, None)], calls)

    def test_a_password_field_on_the_first_entity_is_left_out(self):
        source = (GATEWAY + "entity Customer\n    field\n        id UUID\n"
                  "        secret Password\n\n"
                  "entity Order\n    field\n        id UUID\n        label Text\n\n"
                  + PING_CALL)
        calls, rec = self._sent(
            source, {"id": "c-1", "secret": "sw0rdfish-raw", "label": "l-1"})
        self.assertEqual([("PaymentGateway", {"id": "c-1", "label": "l-1"}, None)],
                         calls)
        self.assertNotIn("sw0rdfish-raw", repr(rec.received))

    def test_a_password_field_on_a_later_entity_is_left_out(self):
        source = (GATEWAY + "entity Order\n    field\n        id UUID\n"
                  "        label Text\n\n"
                  "entity Customer\n    field\n        id UUID\n"
                  "        secret Password\n\n"
                  "workflow Ping\n    find customer\n"
                  "    call PaymentGateway as paymentResult\n")
        payload = {"id": "c-1", "secret": "sw0rdfish-raw"}
        rows = {"entity.customer": {row_key("entity.customer", payload):
                                    {"id": "c-1", "secret": "sw0rdfish-raw"}}}
        calls, rec = self._sent(source, payload, rows)
        self.assertEqual([("PaymentGateway", {"id": "c-1"}, None)], calls)
        self.assertNotIn("sw0rdfish-raw", repr(rec.received))

    def test_a_name_that_is_password_on_any_entity_is_left_out(self):
        source = (GATEWAY + "entity Order\n    field\n        id UUID\n"
                  "        secret Text\n\n"
                  "entity Customer\n    field\n        id UUID\n"
                  "        secret Password\n\n" + PING_CALL)
        calls, rec = self._sent(source, {"id": "c-1", "secret": "sw0rdfish-raw"})
        self.assertEqual([("PaymentGateway", {"id": "c-1"}, None)], calls)
        self.assertNotIn("sw0rdfish-raw", repr(rec.received))


class OmitMaskedFieldsTest(unittest.TestCase):

    def test_a_non_dict_payload_comes_back_as_the_same_object(self):
        for value in (["secret", "x"], "secret", 7, None):
            with self.subTest(value=value):
                self.assertIs(value, omit_masked_fields(value, frozenset({"secret"})))

    def test_a_payload_with_no_masked_key_comes_back_as_the_same_object(self):
        payload = {"id": "c-1", "tier": "gold"}
        self.assertIs(payload, omit_masked_fields(payload, frozenset({"secret"})))
        self.assertIs(payload, omit_masked_fields(payload, frozenset()))

    def test_a_filtered_payload_keeps_input_order_and_leaves_the_input_alone(self):
        payload = {"z": 1, "secret": "sw0rdfish-raw", "a": 2}
        out = omit_masked_fields(payload, frozenset({"secret"}))
        self.assertEqual(["z", "a"], list(out))
        self.assertEqual({"z": 1, "a": 2}, out)
        self.assertEqual({"z": 1, "secret": "sw0rdfish-raw", "a": 2}, payload)


class DefaultBodyWireTest(_ServerTestCase):

    def test_the_wire_body_of_a_plain_call_leaves_the_password_field_out(self):
        handler = _make_handler(status=200, body={"ok": 1})
        url = self.start(handler)
        doc = compile_doc(CALL_ONLY_SOURCE)
        driver = HttpNetworkDriver(endpoints={"PaymentGateway": url})
        self.addCleanup(driver.close)
        result = Interpreter(doc, repo_rows={}, network=driver).run_workflow(
            workflow_id(doc), {"id": "c-1", "secret": "sw0rdfish-raw"})
        self.assertEqual("completed", result["status"])
        self.assertEqual([{"id": "c-1"}], handler.received)


if __name__ == "__main__":
    unittest.main()
