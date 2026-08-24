"""Issue #97 / RFC-0012 Updates — `create <noun> as <name>`: extending
RFC-0027's result-binding notation to `create`, plus payload same-name field
seeding (derived excluded).

Scope: the lowering-time contract (reading the trailing tokens a `create`
step line carries past its object, binding a `result` field on the
`RepositoryCall` IR node, and the two static rejections RFC-0027 §2 already
established — shape, and collision with an entity's single-row binding
name), the runtime contract (payload seeding into the created row regardless
of `as`, derived fields excluded, and the `as` binding landing in
`bindings`/`result["bindings"]` so `set`/`format`/`respond` can address it
the same way a `read` binding can), and the regression this task's `as`-less
path must hold: byte-identical compiled output to before this issue.

Mirrors `test_network_binding.py`'s structure (RFC-0027's own lowering-time
test file) for the static half, and adds the runtime half `call`/`request`
never needed (a network result is never `set`-able).
"""

import os
import subprocess
import sys
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import MASK, Interpreter
from lnpl.lower import LowerError, VERB_LEXICON, lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
HAS_TOOLS = backend.toolchain_available()
NEEDS_TOOLS = unittest.skipUnless(
    HAS_TOOLS, "MLIR/LLVM toolchain not installed (brew install llvm)")


def compile_doc(source, module="m"):
    return lower(parse(source), module)


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


def order_source(body, extra_fields=""):
    """`Order` fixture — a camelCase binding name (`order`) available for the
    name-collision cases, and non-derived fields a payload can seed."""
    return """capability postgres

entity Order
    field
        id UUID
        quantity Integer
        total Money
%s
service Checkout
    policy
        timeout 5s

workflow Place
%s
""" % (extra_fields, body)


class TestUnboundCreateUnchanged(unittest.TestCase):
    """issue #97 §2: `as`-less `create`/`insert` is byte-for-byte what it was
    before this issue — no `result` field, no diagnostics, the SAME
    "never reads it" refusal on a subsequent `set`."""

    def test_create_with_no_trailing_tokens_carries_no_result_field(self):
        mod = compile_doc(order_source("    create order\n"))
        doc = mod.to_document()
        calls = nodes_of(doc, "RepositoryCall")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["entity"], "entity.order")
        self.assertEqual(calls[0]["operation"], "create")
        self.assertNotIn("result", calls[0])
        self.assertEqual(mod.diagnostics.all(), [],
                         "an unbound create must not diagnose anything")

    def test_insert_with_no_trailing_tokens_carries_no_result_field(self):
        mod = compile_doc(order_source("    insert order\n"))
        doc = mod.to_document()
        calls = nodes_of(doc, "RepositoryCall")
        self.assertNotIn("result", calls[0])

    def test_a_bare_create_then_set_is_still_refused(self):
        """The regression this task's D1 pins: `as`-less `create` grants no
        binding, so `set` on it fails exactly as before."""
        with self.assertRaises(LowerError) as ctx:
            compile_doc(order_source(
                "    create order\n    set order.quantity to 1\n"))
        self.assertIn("never reads it", str(ctx.exception))

    def test_the_lexicon_entry_itself_is_unchanged(self):
        """No new verb, no new Effect kind — `as` is read positionally by
        lowering, the same way RFC-0027 reads it for `call`/`request`."""
        self.assertEqual(VERB_LEXICON["create"], ("RepositoryCall", {"operation": "create"}))
        self.assertEqual(VERB_LEXICON["insert"], ("RepositoryCall", {"operation": "create"}))


class TestAsBinding(unittest.TestCase):
    """issue #97 §1: `create <noun> as <name>` binds the created row."""

    def test_create_as_binds_the_result_field(self):
        mod = compile_doc(order_source("    create order as newOrder\n"))
        doc = mod.to_document()
        calls = nodes_of(doc, "RepositoryCall")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["entity"], "entity.order")
        self.assertEqual(calls[0]["result"], "newOrder")
        self.assertEqual(mod.diagnostics.all(), [])

    def test_insert_as_binds_the_result_field_too(self):
        mod = compile_doc(order_source("    insert order as newOrder\n"))
        doc = mod.to_document()
        calls = nodes_of(doc, "RepositoryCall")
        self.assertEqual(calls[0]["result"], "newOrder")

    def test_update_and_delete_still_ignore_trailing_tokens(self):
        """`update`/`delete` answer an affected-row count, not a row — issue
        #97 extends the notation to `create` only, so trailing tokens after
        `update`/`delete` are ignored exactly as before (no `result` field,
        no error) rather than being read as an `as <name>` clause."""
        mod = compile_doc(order_source(
            "    find order\n"
            "    update order as somethingElse\n"))
        doc = mod.to_document()
        calls = nodes_of(doc, "RepositoryCall")
        update_call = next(c for c in calls if c["operation"] == "update")
        self.assertNotIn("result", update_call)


class TestStaticRejections(unittest.TestCase):
    """issue #97 §1/§4: malformed trailing tokens and unsafe names are
    compile errors — RFC-0027 §2's two checks, reused verbatim."""

    def test_a_third_keyword_that_is_not_as_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(order_source("    create order to newOrder\n"))
        self.assertIn("'as <name>'", str(ctx.exception))

    def test_as_with_no_name_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(order_source("    create order as\n"))
        self.assertIn("'as <name>'", str(ctx.exception))

    def test_a_pascal_case_name_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(order_source("    create order as NewOrder\n"))
        self.assertIn("camelCase", str(ctx.exception))

    def test_a_snake_case_name_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(order_source("    create order as new_order\n"))
        self.assertIn("camelCase", str(ctx.exception))

    def test_a_name_colliding_with_an_entitys_binding_name_is_refused(self):
        """`order` is `Order`'s single-row binding name (RFC-0012 §G12.2) —
        `<name>.field` and `<binding>.field` share the same grammar position,
        so the two cannot alias (RFC-0027 §2, reused for `create`)."""
        with self.assertRaises(LowerError) as ctx:
            compile_doc(order_source("    create order as order\n"))
        self.assertIn("Order", str(ctx.exception))


class TestPayloadSeeding(unittest.TestCase):
    """issue #97 §3: payload same-name fields (derived excluded) seed the
    created row at creation time — regardless of whether `as` is used."""

    def test_seeding_applies_without_as(self):
        doc = compile_doc(order_source("    create order\n")).to_document()
        interp = Interpreter(doc, repo_rows={})
        payload = {"id": "o-1", "quantity": 3, "total": 12}
        result = interp.run_workflow("wf.place", payload)
        self.assertEqual(result["status"], "completed")
        row = interp.repo.rows["entity.order"][row_key("entity.order", payload)]
        self.assertEqual(row, {"id": "o-1", "quantity": 3, "total": 12})

    def test_seeding_applies_with_as_too(self):
        doc = compile_doc(order_source("    create order as newOrder\n")).to_document()
        interp = Interpreter(doc, repo_rows={})
        payload = {"id": "o-1", "quantity": 3, "total": 12}
        result = interp.run_workflow("wf.place", payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["newOrder"],
                         {"id": "o-1", "quantity": 3, "total": 12})

    def test_a_derived_field_is_excluded_from_seeding(self):
        src = order_source("    create order as newOrder\n",
                           extra_fields="        bonus Integer derived\n")
        doc = compile_doc(src).to_document()
        interp = Interpreter(doc, repo_rows={})
        payload = {"id": "o-1", "quantity": 3, "total": 12, "bonus": 999}
        result = interp.run_workflow("wf.place", payload)
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("bonus", result["bindings"]["newOrder"],
                         "a derived field must never be seeded from the payload")

    def test_a_field_absent_from_the_payload_is_not_seeded(self):
        doc = compile_doc(order_source("    create order as newOrder\n")).to_document()
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow("wf.place", {"id": "o-1"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["newOrder"], {"id": "o-1"})


class TestAssignmentAndScope(unittest.TestCase):
    """issue #97 §1/§4: the `as` binding lands in the execution scope —
    `set` writes through it (same Assignment flush path RFC-0015 uses for a
    `read` binding), `respond`/`format` can reference it (t94/t96 Reference
    rule reuse)."""

    def test_set_persists_a_value_into_the_created_row(self):
        doc = compile_doc(order_source(
            "    create order as newOrder\n    set newOrder.quantity to 7\n"
        )).to_document()
        interp = Interpreter(doc, repo_rows={})
        payload = {"id": "o-1", "quantity": 3, "total": 12}
        result = interp.run_workflow("wf.place", payload)
        self.assertEqual(result["status"], "completed")
        row = interp.repo.rows["entity.order"][row_key("entity.order", payload)]
        self.assertEqual(row["quantity"], 7)
        self.assertEqual(result["bindings"]["newOrder"]["quantity"], 7)

    def test_set_on_a_created_row_persists_to_a_real_sqlite_store(self):
        """issue #97's DoD: `create X as y` + `set y.f to ...` compiles,
        runs, and the value survives in the real backend, not just the
        in-memory Fake (t92's persist path, drivers.py untouched)."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "store.db")
            doc = compile_doc(order_source(
                "    create order as newOrder\n    set newOrder.quantity to 9\n"
            )).to_document()
            driver = SqliteRepositoryDriver(db_path)
            self.addCleanup(driver.close)
            interp = Interpreter(doc, repo_rows={}, repository=driver)
            payload = {"id": "o-1", "quantity": 3, "total": 12}
            result = interp.run_workflow("wf.place", payload)
            self.assertEqual(result["status"], "completed")

            reread = driver.execute("entity.order", "read",
                                    row_key("entity.order", payload))
            self.assertEqual(reread["quantity"], 9)
            self.assertEqual(reread["total"], 12)

    def test_respond_can_reference_a_create_as_binding(self):
        doc = compile_doc(order_source(
            "    create order as newOrder\n    respond newOrder.id newOrder.quantity\n"
        )).to_document()
        interp = Interpreter(doc, repo_rows={})
        payload = {"id": "o-1", "quantity": 3, "total": 12}
        result = interp.run_workflow("wf.place", payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["response"],
                         {"newOrder": {"id": "o-1", "quantity": 3}})

    def test_format_can_write_into_a_create_as_binding(self):
        # `order_source`'s `total` is Money (arithmetic-typed); `format`
        # writes Text, so this uses a dedicated Text-field fixture instead.
        src = """capability postgres

entity Order
    field
        id UUID
        label Text

service Checkout
    policy
        timeout 5s

workflow Place
    create order as newOrder
    format newOrder.label from "hello"
"""
        doc = compile_doc(src).to_document()
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow("wf.place", {"id": "o-1"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["newOrder"]["label"], "hello")

    def test_a_password_field_seeded_via_as_is_still_masked(self):
        """issue #43's masking chokepoint must not have a gap for a row
        bound by `create ... as` — `result["bindings"]` is the outbound
        channel RFC-0003 requires every response to pass through masked."""
        src = """capability postgres

entity Account
    field
        id UUID
        secret Password

service Signup
    policy
        timeout 5s

workflow Register
    create account as newAccount
"""
        doc = compile_doc(src).to_document()
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow("wf.register", {"id": "a-1", "secret": "s3cr3t"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["newAccount"]["secret"], MASK)


class TestIrSchemaGate(unittest.TestCase):
    """issue #97 / RFC-0012 Updates: `result` is a new optional field on
    `nodeRepositoryCall` — the schema self-test must accept it and reject a
    malformed one (`scripts/validate_ir.py --self-test`)."""

    def test_a_compiled_document_with_result_validates_against_the_schema(self):
        import json
        import jsonschema

        doc = compile_doc(order_source("    create order as newOrder\n")).to_document()
        schema_path = os.path.join(REPO_ROOT, "schemas", "lir.schema.json")
        with open(schema_path, encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.validate(doc, schema)

    def test_the_validator_self_test_includes_create_negatives_and_passes(self):
        result = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "validate_ir.py"),
             "--self-test"],
            capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CREATE_FIXTURE", result.stdout)


class TestModeBEquivalence(unittest.TestCase):
    """Mode B needs no new MLIR — the generic effect-kind recording
    (`_lnpl_ops`) and runtime shim already handle `RepositoryCall`/`create`,
    `result` included (it never reaches the native trace, which records
    kind strings only). This differential test confirms that rather than
    assumes it (same rule `format`/`respond`'s own equivalence tests use)."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-create-as-diff-",
            dir=os.path.join(REPO_ROOT, ".claude", "tmp"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    @NEEDS_TOOLS
    def test_the_fixture_is_equivalent(self):
        doc = compile_doc(order_source(
            "    create order as newOrder\n    set newOrder.quantity to 7\n"
        )).to_document()
        payload = {"id": "o-1", "quantity": 3, "total": 12}
        ok, report = differential.verify(doc, "wf.place", payload, {}, self.workdir)
        self.assertTrue(ok, "\n".join(report))


if __name__ == "__main__":
    unittest.main()
