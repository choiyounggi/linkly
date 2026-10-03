"""Issue #102 — `run_workflow`'s `result["emissions"]` clause.

`spec.py`'s `emitted` assertion already reads `interp.outbox` directly,
unconditional of the run's final `status` (RFC-0003: the synchronous part of
`emit` ends at *registering* the publish, not at the workflow finishing). This
clause surfaces that same list on the JSON result, so a caller without spec
access sees what spec already sees — "fake 백엔드에서도 이벤트 관측 가능"
(D5). A workflow that never emits gets no `emissions` key at all — not an
empty list — so it is byte-identical to before this feature existed, the same
`respond`/`response` precedent issue #96 set (D4/D5 there).
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

from lnpl import cli
from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import MASK, Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUARDED_LNPL = os.path.join(REPO, "examples", "guarded.lnpl")

EMIT_SRC = """entity Order
    field
        id UUID
        status Text

event OrderPlaced on Order create

workflow PlaceOrder
    create order
    emit orderPlaced
"""

NO_EMIT_SRC = """entity Order
    field
        id UUID
        status Text

workflow PlaceOrder
    create order
"""

# A later step failing must not un-register an emit that already ran —
# RFC-0003's "registering the publish" happens synchronously at the `emit`
# step, before whatever runs after it. `cache order` with no `performance
# cache` TTL budget raises at run time (the same fixture shape
# test_respond_verb.py's own later-step-failure case uses).
EMIT_THEN_FAIL_SRC = """capability redis

entity Order
    field
        id UUID
        status Text

event OrderPlaced on Order create

workflow PlaceOrder
    create order
    emit orderPlaced
    cache order
"""

# issue #178, RFC-0049: `emit ... with` maps the payload from a create-as
# binding and the run's input instead of the raw masked input. `internalNote`
# is a declared field never referenced by `with` -- R8 requires it does NOT
# leak into the mapped payload the way it would into the plain-`emit` path.
EMIT_WITH_MAP_SRC = """capability postgres

entity Order
    field
        id UUID
        customerId Text
        internalNote Text

event OrderPlaced

service Orders
    policy
        timeout 5s

workflow Checkout
    create order as newOrder
    emit orderPlaced with newOrder.id input.customerId
"""

# The create-as step sits behind a guard that is false whenever `customerId`
# IS given -- so a payload that provides it skips `create`, leaving `newOrder`
# unbound. The `emit` step itself is NOT inside the guard (RFC-0002's Guard
# node holds exactly one guarded child), so it still runs.
EMIT_WITH_MAP_GUARDED_SRC = """capability postgres

entity Order
    field
        id UUID
        customerId Text

event OrderPlaced

service Orders
    policy
        timeout 5s

workflow CheckoutGuarded
    when customerId missing
    create order as newOrder
    emit orderPlaced with newOrder.id
"""


# issue #204: `total` is `derived` (the client cannot send it) and the
# workflow fills it with `set` before the `emit` -- the issue's own source.
EMIT_DERIVED_SRC = """capability postgres

entity Order
    field
        id UUID
        quantity Integer
        total Integer derived

event OrderPlaced

service ShopService
    policy
        retry 0

workflow PlaceOrder
    create order as o
    set o.total to input.quantity * 2
    emit orderPlaced with o.id o.total
"""


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


class TestEmissionsRuns(unittest.TestCase):

    def test_run_workflow_result_carries_an_emissions_clause(self):
        doc = compile_doc(EMIT_SRC)
        payload = {"id": "o-1", "status": "new"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", payload)

        self.assertEqual("completed", result["status"])
        self.assertEqual(1, len(result["emissions"]))
        emission = result["emissions"][0]
        self.assertEqual("event.order.placed", emission["event"])
        self.assertEqual(payload, emission["payload"])
        self.assertIn("emission_id", emission)

    def test_emissions_is_the_same_list_spec_emitted_already_reads(self):
        """No second bookkeeping mechanism — `result["emissions"]` and
        `spec.py`'s `emitted` assertion must agree because they read the
        same object, not two derivations that could drift."""
        doc = compile_doc(EMIT_SRC)
        payload = {"id": "o-1", "status": "new"}
        interp = Interpreter(doc, repo_rows={})

        result = interp.run_workflow("wf.place.order", payload)

        self.assertEqual(interp.outbox, result["emissions"])

    def test_a_workflow_that_never_emits_carries_no_emissions_key(self):
        doc = compile_doc(NO_EMIT_SRC)
        payload = {"id": "o-1", "status": "new"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", payload)

        self.assertEqual("completed", result["status"])
        self.assertNotIn("emissions", result)

    def test_existing_trace_keys_are_unchanged_alongside_emissions(self):
        doc = compile_doc(EMIT_SRC)
        payload = {"id": "o-1", "status": "new"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", payload)

        for key in ("status", "steps", "skipped", "failed_step",
                   "failure_reason", "bindings", "duration_ms",
                   "correlation_id"):
            self.assertIn(key, result)

    def test_an_emit_survives_a_later_steps_failure(self):
        doc = compile_doc(EMIT_THEN_FAIL_SRC)
        payload = {"id": "o-1", "status": "new"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", payload)

        self.assertEqual("failed", result["status"])
        self.assertEqual(1, len(result["emissions"]))


class TestEmitWithMappedPayload(unittest.TestCase):
    """issue #178, RFC-0049: `emit ... with` builds the emitted payload from
    the mapped refs instead of the raw masked input."""

    def test_happy_path_carries_exactly_the_mapped_fields(self):
        # R8: a create-as field and an input field, no other declared field
        # (`internalNote`, never referenced) leaks through.
        doc = compile_doc(EMIT_WITH_MAP_SRC)
        payload = {"id": "o-1", "customerId": "cust-42",
                  "internalNote": "do-not-emit"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.checkout", payload)

        self.assertEqual("completed", result["status"])
        emission = result["emissions"][0]
        self.assertEqual(emission["payload"], {"id": "o-1", "customerId": "cust-42"})

    def test_a_set_filled_derived_field_carries_its_computed_value(self):
        # issue #204, R1's runtime half: the `set` mutates the SAME dict
        # object the binding holds (interp.py's Assignment branch), and
        # `resolve_reference` reads that dict live at emit time.
        doc = compile_doc(EMIT_DERIVED_SRC)

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", {"id": "o-1", "quantity": 21})

        self.assertEqual("completed", result["status"])
        self.assertEqual(result["emissions"][0]["payload"],
                         {"id": "o-1", "total": 42})

    def test_a_zero_quantity_still_carries_the_computed_zero_total(self):
        # boundary: a computed 0 is a value, not an absent field -- the
        # payload must carry `total: 0`, not drop it or map it to null.
        doc = compile_doc(EMIT_DERIVED_SRC)

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", {"id": "o-1", "quantity": 0})

        self.assertEqual("completed", result["status"])
        self.assertEqual(result["emissions"][0]["payload"],
                         {"id": "o-1", "total": 0})

    def test_the_sqlite_outbox_row_carries_the_computed_derived_value(self):
        # issue #204's completion criterion names the outbox payload: the
        # persisted `lnpl_outbox` row, read back through the driver, holds
        # the same computed `total` the in-memory emission does.
        doc = compile_doc(EMIT_DERIVED_SRC)
        # A file in a per-test directory, the same way
        # `test_driver_contract.ContractTestCase` isolates its sqlite stores.
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        driver = SqliteRepositoryDriver(os.path.join(box.name, "store.db"))
        self.addCleanup(driver.close)

        result = Interpreter(doc, repo_rows={}, repository=driver).run_workflow(
            "wf.place.order", {"id": "o-1", "quantity": 21})

        self.assertEqual("completed", result["status"])
        rows = driver.drain_outbox()
        self.assertEqual(1, len(rows))
        self.assertEqual("event.order.placed", rows[0]["event"])
        self.assertEqual(rows[0]["payload"], {"id": "o-1", "total": 42})

    def test_guard_skipped_binding_maps_to_null_not_a_run_error(self):
        # D6: the static check only guarantees the reference names something
        # real in the document, not that the step ran on this execution.
        doc = compile_doc(EMIT_WITH_MAP_GUARDED_SRC)
        payload = {"id": "o-1", "customerId": "cust-1"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.checkout.guarded", payload)

        self.assertEqual("completed", result["status"])
        self.assertEqual(result["emissions"][0]["payload"], {"id": None})

    def test_a_non_password_mapped_field_is_not_masked(self):
        # D4 negative control, paired with a Password field in the SAME
        # payload map: `emit ... with` cannot compile a Password ref
        # (lower.py's own static rejection, test_lower.py's
        # test_a_password_field_ref_is_refused), so this exercises interp.py's
        # own defense-in-depth masking directly at the IR level -- the same
        # layering `scripts/validate_ir.py --self-test`'s hand-built
        # negatives already use to test one layer at a time.
        doc = compile_doc("""capability postgres

entity Account
    field
        id UUID
        secret Password

event AccountRegistered

service Signup
    policy
        timeout 5s

workflow Register
    create account as newAccount
    emit accountRegistered
""")
        emit_node = next(n for n in doc["nodes"] if n["kind"] == "EventEmit")
        emit_node["payloadMap"] = [
            {"field": "id", "ref": "newAccount.id"},
            {"field": "secret", "ref": "newAccount.secret"},
        ]
        payload = {"id": "a-1", "secret": "s3cr3t"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.register", payload)

        self.assertEqual("completed", result["status"])
        emitted = result["emissions"][0]["payload"]
        self.assertEqual(emitted["id"], "a-1")
        self.assertEqual(emitted["secret"], MASK)

    def test_plain_emit_still_carries_the_full_masked_input(self):
        # R2 regression, same shape as the file's own pre-#178 test above.
        doc = compile_doc(EMIT_SRC)
        payload = {"id": "o-1", "status": "new"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", payload)

        self.assertEqual("completed", result["status"])
        self.assertEqual(result["emissions"][0]["payload"], payload)


class TestEmissionsByteIdenticalWhenAbsent(unittest.TestCase):
    """D4/D5's non-destructive guarantee, over a real shipped file rather
    than a synthetic fixture: `examples/guarded.lnpl` declares no `emit` at
    all, so its `run --json` output must gain nothing new."""

    def run_cli_json(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(argv)
        return rc, json.loads(out.getvalue())

    def test_guarded_example_gets_no_emissions_key(self):
        rc, doc = self.run_cli_json(["run", GUARDED_LNPL, "--json"])

        self.assertEqual(0, rc)
        self.assertEqual("completed", doc["result"]["status"])
        self.assertNotIn("emissions", doc["result"])


def optional_emit_src(steps, extra_entity=""):
    """RFC-0055 fixture: `note` is optional on Order."""
    return """capability postgres

entity Order
    field
        id UUID
        customerId Text
        note Text optional
%s
event OrderPlaced

service Orders
    policy
        timeout 5s

workflow Checkout
%s""" % (extra_entity, steps)


ORDER_ID = "0b6f1c2e-2222-4a2b-9c3d-000000000208"


class TestEmitWithOptionalField(unittest.TestCase):
    """RFC-0055: `emit ... with` omits an absent or null `optional` ref
    instead of inventing `"note": null`."""

    def emitted(self, steps, payload, extra_entity="", repo_rows=None):
        doc = compile_doc(optional_emit_src(steps, extra_entity))
        result = Interpreter(doc, repo_rows=repo_rows or {}).run_workflow(
            "wf.checkout", payload)
        self.assertEqual("completed", result["status"], result.get("failure_reason"))
        return result["emissions"][0]["payload"]

    def test_emit_with_omits_absent_optional_ref(self):
        payload = self.emitted(
            "    create order as newOrder\n"
            "    emit orderPlaced with newOrder.id input.note\n",
            {"id": ORDER_ID, "customerId": "c-1"})
        self.assertEqual({"id": ORDER_ID}, payload)

    def test_emit_with_omits_null_optional_ref(self):
        payload = self.emitted(
            "    create order as newOrder\n"
            "    emit orderPlaced with newOrder.id input.note\n",
            {"id": ORDER_ID, "customerId": "c-1", "note": None})
        self.assertEqual({"id": ORDER_ID}, payload)

    def test_emit_with_optional_create_as_alias_ref_omitted(self):
        payload = self.emitted(
            "    create order as newOrder\n"
            "    emit orderPlaced with newOrder.id newOrder.note\n",
            {"id": ORDER_ID, "customerId": "c-1"})
        self.assertEqual({"id": ORDER_ID}, payload)

    def test_emit_with_omits_an_absent_optional_ref_of_a_read_binding(self):
        payload = self.emitted(
            "    find order\n"
            "    emit orderPlaced with order.id order.note\n",
            {"id": ORDER_ID, "customerId": "c-1"},
            repo_rows={"entity.order": {
                row_key("entity.order", {"id": ORDER_ID}):
                    {"id": ORDER_ID, "customerId": "c-1"}}})
        self.assertEqual({"id": ORDER_ID}, payload)

    def test_emit_with_present_optional_ref_is_carried(self):
        payload = self.emitted(
            "    create order as newOrder\n"
            "    emit orderPlaced with newOrder.id newOrder.note\n",
            {"id": ORDER_ID, "customerId": "c-1", "note": "gift"})
        self.assertEqual({"id": ORDER_ID, "note": "gift"}, payload)

    def test_emit_with_mixed_optionality_input_field_assigns_null(self):
        # `Invoice.note` is required (declared last): under the AND rule
        # `input.note` is NOT uniformly optional, so it is treated as
        # required — the event payload gets "note": null, assigned, not
        # omitted (unchanged pre-RFC-0055 behaviour).
        payload = self.emitted(
            "    create order as newOrder\n"
            "    emit orderPlaced with newOrder.id input.note\n",
            {"id": ORDER_ID, "customerId": "c-1"},
            extra_entity="\nentity Invoice\n    field\n        id UUID\n"
                         "        note Text\n")
        self.assertEqual({"id": ORDER_ID, "note": None}, payload)

    def test_plain_emit_drops_a_null_optional_field(self):
        # Plain `emit` forwards the masked input; `run_workflow`'s boundary
        # normalization already removed the optional null.
        payload = self.emitted(
            "    create order\n    emit orderPlaced\n",
            {"id": ORDER_ID, "customerId": "c-1", "note": None})
        self.assertEqual({"id": ORDER_ID, "customerId": "c-1"}, payload)

    def test_plain_emit_keeps_a_null_required_field(self):
        # Regression: only an optional field's null is normalized away.
        payload = self.emitted(
            "    create order\n    emit orderPlaced\n",
            {"id": ORDER_ID, "customerId": None})
        self.assertEqual({"id": ORDER_ID, "customerId": None}, payload)


class TestEmissionsCliJson(unittest.TestCase):
    """`lnpl run --json` carries the same `emissions` clause — sent
    verbatim, with zero change needed in cli.py (the same non-change
    `respond`'s own CLI test confirms for `response`, issue #96)."""

    def setUp(self):
        import tempfile
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-emissions-cli-", dir=os.path.join(REPO, ".claude", "tmp"))
        self.src_path = os.path.join(self.workdir, "emit.lnpl")
        with open(self.src_path, "w", encoding="utf-8") as fh:
            fh.write(EMIT_SRC)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_run_json_carries_the_emissions_clause(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["run", self.src_path, "--json"])
        self.assertEqual(0, rc)
        doc = json.loads(out.getvalue())
        self.assertEqual(1, len(doc["result"]["emissions"]))
        self.assertEqual("event.order.placed",
                         doc["result"]["emissions"][0]["event"])


if __name__ == "__main__":
    unittest.main()
