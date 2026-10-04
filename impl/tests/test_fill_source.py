"""RFC-0057 (issue #209) — server-generated id and run-time field markers.

Scope: `id-required` (a `create` with no payload `id` fails instead of writing
under the `<entity>#-` sentinel key), the `derived generated` /
`derived clock` markers, the per-run context that fills them at `create`, and
the row-key / stored-`id` consequences.
"""

import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest

from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import map_consume_result, map_result

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def workflow_id(doc, name=None):
    wfs = [n for n in doc["nodes"] if n["kind"] == "Workflow"]
    if name is None:
        return wfs[0]["id"]
    return next(n["id"] for n in wfs if n["name"] == name)


def _tmp_store(test):
    """A per-test sqlite file under `.claude/tmp` (never `/tmp`), removed on
    teardown — the repo's tmp-hygiene rule."""
    base = os.path.join(REPO_ROOT, ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    path = tempfile.mkdtemp(prefix="lnpl-t209-", dir=base)
    test.addCleanup(shutil.rmtree, path, True)
    return os.path.join(path, "store.db")


def stored_rows(db_path, entity_id):
    """`{row_key: payload}` straight from the sqlite table — a fact about the
    store, not about `result`."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT row_key, payload FROM lnpl_rows WHERE entity_id = ?",
            (entity_id,)).fetchall()
    finally:
        conn.close()
    return {key: json.loads(text) for key, text in rows}


# The issue's own module, unmarked: `id UUID` with no fill source.
PLAIN_AUDIT_SRC = """entity AuditEntry
    field
        id UUID
        action Text

service AuditService

workflow Record
    create auditentry as a
    respond a.action
"""

# An entity that declares no `id` field at all — the ruling's GAP 1 case.
NO_ID_FIELD_SRC = """entity Note
    field
        body Text

service NoteService

workflow Jot
    create note as n
    respond n.body
"""


class TestIdRequired(unittest.TestCase):
    """Decision (4): a create with no payload `id` and no `derived generated`
    id fails `id-required` before any write."""

    def run_on_sqlite(self, source, payload, entity_id):
        db_path = _tmp_store(self)
        doc = compile_doc(source)
        driver = SqliteRepositoryDriver(db_path)
        self.addCleanup(driver.close)
        result = Interpreter(doc, repo_rows={}, repository=driver).run_workflow(
            workflow_id(doc), payload)
        return result, stored_rows(db_path, entity_id)

    def test_a_create_without_a_payload_id_fails_id_required_and_writes_nothing(self):
        result, rows = self.run_on_sqlite(
            PLAIN_AUDIT_SRC, {"action": "login"}, "entity.audit.entry")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_kind"], "id-required")
        self.assertIn("entity.audit.entry", result["failure_reason"])
        self.assertIn("id", result["failure_reason"])
        self.assertEqual(rows, {})

    def test_a_json_null_id_is_the_same_as_an_absent_one(self):
        result, rows = self.run_on_sqlite(
            PLAIN_AUDIT_SRC, {"id": None, "action": "login"}, "entity.audit.entry")
        self.assertEqual(result["failure_kind"], "id-required")
        self.assertEqual(rows, {})

    def test_an_entity_without_an_id_field_still_needs_a_payload_id(self):
        # Ruling GAP 1: whether or not the entity declares `id`, a payload
        # with no id would land on `entity.note#-` — refused the same way.
        result, rows = self.run_on_sqlite(
            NO_ID_FIELD_SRC, {"body": "hello"}, "entity.note")
        self.assertEqual(result["failure_kind"], "id-required")
        self.assertEqual(rows, {})

    def test_a_create_with_a_payload_id_is_unchanged(self):
        ident = "00000000-0000-4000-8000-000000000209"
        result, rows = self.run_on_sqlite(
            PLAIN_AUDIT_SRC, {"id": ident, "action": "login"}, "entity.audit.entry")
        self.assertEqual(result["status"], "completed", result["failure_reason"])
        self.assertEqual(list(rows), ["entity.audit.entry#" + ident])
        self.assertEqual(rows["entity.audit.entry#" + ident]["id"], ident)

    def test_the_fake_backend_refuses_too(self):
        doc = compile_doc(PLAIN_AUDIT_SRC)
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow(workflow_id(doc), {"action": "login"})
        self.assertEqual(result["failure_kind"], "id-required")
        self.assertEqual(interp.repo.rows.get("entity.audit.entry", {}), {})


class TestIdRequiredServing(unittest.TestCase):
    """`serve` maps id-required as a caller error (400) and a consumed event
    carrying it as permanently rejected (422) — retrying the identical payload
    fails identically."""

    def failed_result(self):
        doc = compile_doc(PLAIN_AUDIT_SRC)
        return Interpreter(doc, repo_rows={}).run_workflow(
            workflow_id(doc), {"action": "login"})

    def test_map_result_is_400_id_required(self):
        self.assertEqual(map_result(self.failed_result()), (400, "id-required"))

    def test_map_consume_result_is_422_event_rejected(self):
        self.assertEqual(map_consume_result(self.failed_result()),
                         (422, "event-rejected"))

    def test_the_problem_title_names_the_missing_id(self):
        from lnpl.wsgi import _TITLES
        self.assertIn("id", _TITLES["id-required"])

    def test_fail_cannot_reuse_the_id_required_code(self):
        # RFC-0058: an author's `fail <code>` may not collide with a code the
        # server already sends, and RFC-0057 added `id-required`.
        from lnpl.lower import LowerError
        src = AUDIT_SRC.replace(
            "    create auditentry as a\n",
            "    when input.action missing\n    fail id-required\n"
            "    create auditentry as a\n")
        with self.assertRaises(LowerError) as ctx:
            compile_doc(src)
        self.assertIn("reserved problem code", str(ctx.exception))
        self.assertIn("id-required", str(ctx.exception))



# The issue's module with both markers (RFC-0057 §1).
AUDIT_SRC = """entity AuditEntry
    field
        id UUID derived generated
        at DateTime derived clock
        action Text

service AuditService

workflow Record
    create auditentry as a
    respond a.action
"""


def audit_with_field(line):
    """AUDIT_SRC with its `at` field line replaced by `line`."""
    return AUDIT_SRC.replace("at DateTime derived clock", line)


def entity_fields(doc, name):
    ent = next(n for n in doc["nodes"]
               if n["kind"] == "Entity" and n["name"] == name)
    return {f["name"]: f for f in ent["fields"]}


class TestMarkerGrammar(unittest.TestCase):
    """RFC-0057 §1/§2: `derived generated` on a UUID base, `derived clock`
    on a DateTime base; the IR carries `fill_source`, absent otherwise."""

    def lower_fails(self, source, *fragments):
        from lnpl.lower import LowerError
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source)
        for fragment in fragments:
            self.assertIn(fragment, str(ctx.exception))

    def test_both_markers_lower_to_fill_source(self):
        fields = entity_fields(compile_doc(AUDIT_SRC), "AuditEntry")
        self.assertEqual(fields["id"], {"name": "id", "type": "UUID",
                                        "derived": True,
                                        "fill_source": "generated"})
        self.assertEqual(fields["at"]["fill_source"], "clock")
        self.assertTrue(fields["at"]["derived"])
        # absent, never a false/None placeholder
        self.assertNotIn("fill_source", fields["action"])

    def test_a_plain_derived_field_carries_no_fill_source(self):
        fields = entity_fields(
            compile_doc(audit_with_field("at DateTime derived")), "AuditEntry")
        self.assertEqual(fields["at"], {"name": "at", "type": "DateTime",
                                        "derived": True})

    def test_a_refinement_of_the_right_base_is_accepted(self):
        src = "refine AuditId of UUID\n    minLength 36\n\n" + AUDIT_SRC.replace(
            "id UUID derived generated", "id AuditId derived generated")
        fields = entity_fields(compile_doc(src), "AuditEntry")
        self.assertEqual(fields["id"]["fill_source"], "generated")

    def test_generated_on_a_non_uuid_field_is_refused(self):
        self.lower_fails(audit_with_field("at Text derived generated"),
                         "generated", "UUID", "Text")

    def test_clock_on_a_non_datetime_field_is_refused(self):
        self.lower_fails(audit_with_field("at Integer derived clock"),
                         "clock", "DateTime", "Integer")

    def test_a_marker_without_derived_is_refused(self):
        self.lower_fails(audit_with_field("at DateTime optional clock"),
                         "clock", "derived")
        self.lower_fails(audit_with_field("at DateTime clock"),
                         "clock", "derived")

    def test_an_id_keyed_by_the_clock_is_refused(self):
        # Every row of one virtual-clock run (and of two runs) would share
        # the instant, so a clock-filled id is never a unique key.
        self.lower_fails(AUDIT_SRC.replace("id UUID derived generated",
                                           "id DateTime derived clock"),
                         "'id'", "generated", "clock")

    def test_an_unknown_marker_names_the_closed_set(self):
        self.lower_fails(audit_with_field("at DateTime derived now"),
                         "now", "generated", "clock")

    def test_derived_never_assigned_skips_a_marked_field_only(self):
        from lnpl.parser import parse as _parse
        mod = lower(_parse(AUDIT_SRC), "m")
        self.assertEqual([d for d in mod.diagnostics.all()
                          if d.code == "derived-never-assigned"], [])
        mod = lower(_parse(audit_with_field("at DateTime derived")), "m")
        hits = [d for d in mod.diagnostics.all()
                if d.code == "derived-never-assigned"]
        self.assertEqual(len(hits), 1)
        self.assertIn("'at'", hits[0].message)



UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

# Synthetic pins, obviously fake.
PINNED_ID = "00000000-0000-4000-8000-000000000057"
PINNED_AT = "2030-01-02T03:04:05.006Z"


class TestFillAtCreate(unittest.TestCase):
    """RFC-0057 §3/§4 (ruling-1): values decided once per run, applied only
    at a create of the marked entity — never written into the payload."""

    def setUp(self):
        self.db_path = _tmp_store(self)
        self.doc = compile_doc(AUDIT_SRC)

    def run_once(self, payload=None, clock=None, run_context=None):
        driver = SqliteRepositoryDriver(self.db_path)
        try:
            interp = Interpreter(self.doc, repo_rows={}, repository=driver,
                                 clock=clock)
            payload = {"action": "login"} if payload is None else payload
            if run_context is None:
                return interp.run_workflow(workflow_id(self.doc), payload)
            return interp.run_workflow(workflow_id(self.doc), payload,
                                       run_context=run_context)
        finally:
            driver.close()

    def test_two_id_less_creates_land_under_two_uuid_keys(self):
        # The issue's acceptance: the same payload twice on sqlite.
        first = self.run_once()
        second = self.run_once()
        self.assertEqual(first["status"], "completed", first["failure_reason"])
        self.assertEqual(second["status"], "completed", second["failure_reason"])
        rows = stored_rows(self.db_path, "entity.audit.entry")
        self.assertEqual(len(rows), 2)
        for key, row in rows.items():
            self.assertTrue(key.startswith("entity.audit.entry#"))
            self.assertEqual(key, "entity.audit.entry#" + row["id"])
            self.assertRegex(row["id"], UUID4_RE)
            self.assertEqual(row["action"], "login")
            self.assertIn("at", row)
        ids = sorted(row["id"] for row in rows.values())
        self.assertNotEqual(ids[0], ids[1])

    def test_a_uuid_field_never_stores_a_row_key_string(self):
        self.run_once()
        rows = stored_rows(self.db_path, "entity.audit.entry")
        self.assertEqual(len(rows), 1)
        for row in rows.values():
            self.assertNotIn("#", row["id"])
            self.assertNotIn("entity.", row["id"])

    def test_the_created_binding_carries_the_filled_values(self):
        result = self.run_once()
        bound = result["bindings"]["a"]
        self.assertRegex(bound["id"], UUID4_RE)
        self.assertEqual(bound["at"], "1970-01-01T00:00:00.000Z")

    def test_the_payload_is_never_written(self):
        payload = {"action": "login"}
        result = self.run_once(payload)
        self.assertEqual(payload, {"action": "login"})
        self.assertNotIn("id", result.get("payload", {}))

    def test_a_virtual_clock_gives_a_deterministic_at(self):
        self.run_once()
        self.run_once()
        stamps = {row["at"] for row in
                  stored_rows(self.db_path, "entity.audit.entry").values()}
        self.assertEqual(stamps, {"1970-01-01T00:00:00.000Z"})

    def test_a_virtual_clock_reads_its_current_instant_at_run_start(self):
        from lnpl.interp import Clock
        clock = Clock()
        clock.advance(86_400_000 + 1)
        result = self.run_once(clock=clock)
        self.assertEqual(result["bindings"]["a"]["at"],
                         "1970-01-02T00:00:00.001Z")

    def test_a_real_clock_gives_the_wall_clock(self):
        import time
        from datetime import datetime
        from lnpl.interp import RealClock
        before = time.time()
        result = self.run_once(clock=RealClock())
        after = time.time()
        at = result["bindings"]["a"]["at"]
        self.assertRegex(at, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        stamp = datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()
        self.assertGreaterEqual(stamp, before - 0.001)
        self.assertLessEqual(stamp, after + 0.001)

    def test_a_run_context_pins_both_values(self):
        result = self.run_once(run_context={"generated": PINNED_ID,
                                            "clock": PINNED_AT})
        self.assertEqual(result["status"], "completed", result["failure_reason"])
        rows = stored_rows(self.db_path, "entity.audit.entry")
        self.assertEqual(list(rows), ["entity.audit.entry#" + PINNED_ID])
        self.assertEqual(rows["entity.audit.entry#" + PINNED_ID]["at"], PINNED_AT)

    def test_a_pinned_id_created_twice_conflicts(self):
        # Boundary: the pin is a real key, so the second create is a 409.
        pin = {"generated": PINNED_ID, "clock": PINNED_AT}
        self.run_once(run_context=pin)
        again = self.run_once(run_context=pin)
        self.assertEqual(again["failure_kind"], "conflict")

    def test_a_payload_id_does_not_replace_the_generated_one(self):
        # A `derived` field is server-owned: the payload cannot choose it.
        result = self.run_once({"id": PINNED_ID, "action": "login"})
        self.assertEqual(result["status"], "completed", result["failure_reason"])
        (row,) = stored_rows(self.db_path, "entity.audit.entry").values()
        self.assertNotEqual(row["id"], PINNED_ID)
        self.assertRegex(row["id"], UUID4_RE)

    def test_an_unknown_run_context_key_is_refused(self):
        from lnpl.interp import RunError
        with self.assertRaises(RunError) as ctx:
            self.run_once(run_context={"uuid": PINNED_ID})
        self.assertIn("uuid", str(ctx.exception))

    def test_an_empty_run_context_decides_both_values(self):
        result = self.run_once(run_context={})
        self.assertRegex(result["bindings"]["a"]["id"], UUID4_RE)


# Ruling-1's named case: a marked and an unmarked entity in one module.
MIXED_SRC = """entity AuditEntry
    field
        id UUID derived generated
        at DateTime derived clock
        action Text

entity Order
    field
        id UUID
        total Integer

service Shop

workflow Audit
    create auditentry as a
    respond a.action

workflow Place
    create order as o
    respond o.total

workflow PlaceAudited
    create order as o
    create auditentry as a
    respond o.total
"""

ORDER_ID = "00000000-0000-4000-8000-0000000000aa"


class TestMarkedAndUnmarkedEntities(unittest.TestCase):

    def setUp(self):
        self.db_path = _tmp_store(self)
        self.doc = compile_doc(MIXED_SRC)

    def run_wf(self, name, payload):
        driver = SqliteRepositoryDriver(self.db_path)
        try:
            return Interpreter(self.doc, repo_rows={}, repository=driver) \
                .run_workflow(workflow_id(self.doc, name), payload)
        finally:
            driver.close()

    def test_an_unmarked_create_still_needs_a_payload_id(self):
        audit = self.run_wf("Audit", {"action": "login"})
        place = self.run_wf("Place", {"total": 3})
        self.assertEqual(audit["status"], "completed", audit["failure_reason"])
        self.assertRegex(audit["bindings"]["a"]["id"], UUID4_RE)
        self.assertEqual(place["failure_kind"], "id-required")
        self.assertEqual(stored_rows(self.db_path, "entity.order"), {})

    def test_creating_both_with_the_order_id_gives_two_distinct_keys(self):
        result = self.run_wf("PlaceAudited",
                             {"id": ORDER_ID, "total": 3, "action": "order"})
        self.assertEqual(result["status"], "completed", result["failure_reason"])
        orders = stored_rows(self.db_path, "entity.order")
        audits = stored_rows(self.db_path, "entity.audit.entry")
        self.assertEqual(list(orders), ["entity.order#" + ORDER_ID])
        self.assertEqual(orders["entity.order#" + ORDER_ID]["id"], ORDER_ID)
        (audit_key,) = audits
        self.assertNotEqual(audits[audit_key]["id"], ORDER_ID)
        self.assertRegex(audits[audit_key]["id"], UUID4_RE)


class TestStoredIdIsTheKeyValue(unittest.TestCase):
    """RFC-0057 §4 (decision 5): the skeleton row both drivers write holds
    `{"id": <row key>}`; a declared `id` must end up holding the id value."""

    def test_an_id_only_payload_stores_the_id_not_the_row_key(self):
        src = PLAIN_AUDIT_SRC.replace("        action Text\n", "")
        src = src.replace("    respond a.action\n", "    respond a.id\n")
        db_path = _tmp_store(self)
        doc = compile_doc(src)
        driver = SqliteRepositoryDriver(db_path)
        self.addCleanup(driver.close)
        result = Interpreter(doc, repo_rows={}, repository=driver).run_workflow(
            workflow_id(doc), {"id": ORDER_ID})
        self.assertEqual(result["status"], "completed", result["failure_reason"])
        rows = stored_rows(db_path, "entity.audit.entry")
        self.assertEqual(rows["entity.audit.entry#" + ORDER_ID]["id"], ORDER_ID)



class TestDecodeInstant(unittest.TestCase):
    """`condition.decode_instant` — the `derived clock` value's text."""

    def test_round_trips_through_encode_instant(self):
        from lnpl.condition import decode_instant, encode_instant
        self.assertEqual(decode_instant(encode_instant(PINNED_AT, "x")), PINNED_AT)

    def test_zero_is_the_epoch(self):
        from lnpl.condition import decode_instant
        self.assertEqual(decode_instant(0), "1970-01-01T00:00:00.000Z")

    def test_out_of_range_and_non_integer_are_refused(self):
        from lnpl.condition import ConditionError, decode_instant
        with self.assertRaises(ConditionError):
            decode_instant(10 ** 18)
        with self.assertRaises(ConditionError):
            decode_instant(1.5)
        with self.assertRaises(ConditionError):
            decode_instant(True)



# `stamp`/`counter` exist so a `set` has a bound row to write.
BARE_SRC = """entity Stamp
    field
        id UUID
        at DateTime
        n Integer
        quantity Integer

service Stamps

workflow Touch
    read stamp
    set {line}
"""


class TestBareOperand(unittest.TestCase):
    """RFC-0057 §7 (decision 6): an undeclared bare name in a `set` value is a
    compile error; a marker-like one suggests the marker."""

    def lower_fails(self, line, *fragments):
        from lnpl.lower import LowerError
        with self.assertRaises(LowerError) as ctx:
            compile_doc(BARE_SRC.format(line=line))
        for fragment in fragments:
            self.assertIn(fragment, str(ctx.exception))
        return str(ctx.exception)

    def test_now_suggests_derived_clock(self):
        self.lower_fails("stamp.at to now", "'now'", "derived clock")

    def test_uuid_suggests_derived_generated(self):
        self.lower_fails("stamp.n to uuid", "'uuid'", "derived generated")

    def test_a_target_set_cannot_write_is_refused_for_that_first(self):
        # A UUID field is not `set`-able at all (RFC-0016 dimensions); that
        # refusal names the real problem, so it comes before this one.
        message = self.lower_fails("stamp.id to uuid",
                                   "neither Integer nor DateTime")
        self.assertNotIn("derived generated", message)

    def test_an_arithmetic_operand_is_checked_too(self):
        self.lower_fails("stamp.n to stamp.n + bogusname", "'bogusname'")

    def test_an_unrelated_name_gets_no_marker_suggestion(self):
        message = self.lower_fails("stamp.n to bogusname", "'bogusname'")
        self.assertNotIn("derived", message)

    def test_a_declared_bare_name_is_the_input_field(self):
        # RFC-0012 §G12.1: bare `quantity` names the payload field.
        doc = compile_doc(BARE_SRC.format(line="stamp.n to quantity + 1"))
        (node,) = [n for n in doc["nodes"] if n["kind"] == "Assignment"]
        self.assertEqual(node["expression"], "quantity + 1")

    def test_dotted_literal_and_aggregate_values_are_unaffected(self):
        for line in ("stamp.n to stamp.quantity", "stamp.n to 0",
                     "stamp.n to input.quantity", "stamp.n to count stamp"):
            doc = compile_doc(BARE_SRC.format(line=line))
            self.assertEqual(
                len([n for n in doc["nodes"] if n["kind"] == "Assignment"]), 1)

    def test_examples_still_compile(self):
        import glob
        paths = sorted(glob.glob(os.path.join(REPO_ROOT, "examples", "*.lnpl")))
        self.assertEqual(len(paths), 7)   # + staged.lnpl (RFC-0060)
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                compile_doc(fh.read())



# A guard on an optional field (RFC-0055 refusal) AND a fill-source create
# (RFC-0057 refusal) in one workflow — which refusal wins is the order.
BOTH_REFUSALS_SRC = AUDIT_SRC.replace(
    "        action Text\n", "        action Text\n        note Text optional\n"
).replace("    create auditentry as a\n",
          "    when input.note exists\n    create auditentry as a\n")

READ_ONLY_SRC = AUDIT_SRC.replace("workflow Record\n    create auditentry as a\n"
                                  "    respond a.action\n",
                                  "workflow Look\n    read auditentry\n")


def _workdir(test):
    base = os.path.join(REPO_ROOT, ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    path = tempfile.mkdtemp(prefix="lnpl-t209-b-", dir=base)
    test.addCleanup(shutil.rmtree, path, True)
    return path


class TestModeB(unittest.TestCase):
    """RFC-0057 §8: mode B refuses a workflow that creates a fill-source
    entity — `build`/`emit_mlir` and `diff` alike, each as the LAST check of
    its own refusal chain."""

    def refusals(self, source):
        from lnpl import backend, differential
        doc = compile_doc(source)
        wf = workflow_id(doc)
        with self.assertRaises(backend.BackendError) as built:
            backend.emit_mlir(doc, wf)
        real = backend.toolchain_available
        backend.toolchain_available = lambda: False
        self.addCleanup(setattr, backend, "toolchain_available", real)
        with self.assertRaises(differential.DifferentialError) as diffed:
            differential.verify(doc, wf, {"action": "login"}, {}, _workdir(self))
        return str(built.exception), str(diffed.exception)

    def test_build_and_diff_refuse_a_fill_source_create(self):
        built, diffed = self.refusals(AUDIT_SRC)
        for message in (built, diffed):
            self.assertIn("RFC-0057", message)
            self.assertIn("entity.audit.entry", message)
            self.assertNotIn("toolchain unavailable", message)

    def test_both_refuse_in_the_same_order(self):
        built, diffed = self.refusals(BOTH_REFUSALS_SRC)
        for message in (built, diffed):
            self.assertIn("RFC-0055", message)
            self.assertNotIn("RFC-0057", message)

    def test_reading_a_marked_entity_or_creating_an_unmarked_one_is_not_refused(self):
        from lnpl import backend
        for source in (READ_ONLY_SRC, PLAIN_AUDIT_SRC):
            doc = compile_doc(source)
            self.assertFalse(
                backend.workflow_uses_fill_source_create(doc, workflow_id(doc)))
        doc = compile_doc(AUDIT_SRC)
        self.assertTrue(
            backend.workflow_uses_fill_source_create(doc, workflow_id(doc)))

    def test_an_unknown_workflow_raises(self):
        from lnpl import backend
        with self.assertRaises(backend.BackendError):
            backend.workflow_uses_fill_source_create(compile_doc(AUDIT_SRC),
                                                     "wf.nope")

    @unittest.skipUnless(__import__("lnpl.backend").backend.toolchain_available(),
                         "MLIR/LLVM toolchain not installed (brew install llvm)")
    def test_an_id_less_plain_create_fails_the_same_way_in_both_modes(self):
        from lnpl import differential
        doc = compile_doc(PLAIN_AUDIT_SRC)
        ok, report = differential.verify(doc, workflow_id(doc),
                                         {"action": "login"}, {}, _workdir(self))
        self.assertTrue(ok, "\n".join(report))


if __name__ == "__main__":
    unittest.main()
