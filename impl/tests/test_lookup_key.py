"""Issue #175 / RFC-0052 §Runtime — the `by <ref>` lookup key at run time.

Scope: mode A only. The key a `find|read|load|authenticate|update|delete
<Entity> by <ref>` step executes under is the ref's resolved value
(`row_key(entity_id, {"id": value})`), a row read that way is persisted under
that same key by a later `set`, and a ref that resolves to nothing fails the
step instead of falling back to the payload `id` or the `"-"` sentinel. The
F-3/F-6 acceptance scenario (probe-v0.8 s1: two orders against one product,
stock decremented on each) runs on both `FakeRepository` and
`SqliteRepositoryDriver`, values read back through the repository.

Lowering and the static ref rule live in `test_create_binding.py` /
`test_lower.py` (Track A); the seed-key rule in `test_repo_policy.py`; mode B
in `test_backend.py` / `test_differential_skips.py`.
"""

import copy
import os
import shutil
import tempfile
import unittest

from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

PRODUCT = "entity.product"
STOCK = "entity.stock"
ORDER = "entity.order"
WORKFLOW = "wf.place.order"

HEADER = """capability postgres

entity Product
    field
        id Text
        name Text
        code Integer
        sku Text

entity Stock
    field
        id Text
        productId Text
        onHand Integer

entity Order
    field
        id Text
        productId Text
        qty Integer

service OrderPlatform
    policy
        retry 0

workflow PlaceOrder
"""

# The brief's F-3/F-6 program, verbatim.
F3_BODY = ("    find product by input.productId\n"
           "    find stock by input.productId\n"
           "    set stock.onHand to stock.onHand - input.qty\n"
           "    update stock by input.productId\n"
           "    create order as newOrder\n")


def compile_doc(body):
    return lower(parse(HEADER + body), "orders").to_document()


def seed_rows():
    """Product P1 and its stock, both under the PRODUCT id — never under an
    order id. Explicit rows (not `default_rows`, whose seed is a copy of the
    order payload and carries no `onHand`)."""
    return {
        PRODUCT: {row_key(PRODUCT, {"id": "P1"}): {"id": "P1", "name": "Widget"}},
        STOCK: {row_key(STOCK, {"id": "P1"}): {"id": "S1", "productId": "P1",
                                              "onHand": 5}},
    }


def repo_spans(interp):
    return [c for step in interp.trace.root.children
            for c in step.children if c.kind == "RepositoryCall"]


def _tmp_store_dir(test):
    """A per-test sqlite directory under `.claude/tmp`, removed on teardown
    (repo policy: never `/tmp`, enforced by `test_tmp_hygiene.py`)."""
    base = os.path.join(REPO_ROOT, ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    path = tempfile.mkdtemp(prefix="lnpl-t175-", dir=base)
    test.addCleanup(shutil.rmtree, path, True)
    return path


class TestKeyDerivation(unittest.TestCase):
    """RFC-0052 §3: which key a `by` step executes under."""

    def test_a_by_read_binds_the_row_under_the_lookup_value_not_the_payload_id(self):
        doc = compile_doc("    find product by input.productId\n")
        interp = Interpreter(doc, repo_rows=seed_rows())
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["product"]["name"], "Widget")
        # Nothing lives under the payload id — a fallback would have failed.
        self.assertNotIn(row_key(PRODUCT, {"id": "O1"}), interp.repo.rows[PRODUCT])

    def test_the_span_records_the_lookup_ref_text_only(self):
        """D6: `attrs["lookup"]` is the ref text — never the resolved key or
        value (nothing to mask). A by-less call carries no such attr."""
        doc = compile_doc("    find product by input.productId\n"
                          "    find stock by input.productId\n"
                          "    update stock by input.productId\n"
                          "    delete stock by input.productId\n")
        interp = Interpreter(doc, repo_rows=seed_rows())
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1"})
        self.assertEqual(result["status"], "completed")
        spans = repo_spans(interp)
        self.assertEqual(len(spans), 4)
        for span in spans:
            self.assertEqual(span.attrs["lookup"], "input.productId")
            self.assertNotIn("P1", repr(span.attrs))

        plain = Interpreter(compile_doc("    find product\n"), repo_rows={
            PRODUCT: {row_key(PRODUCT, {"id": "O1"}): {"id": "O1"}}})
        self.assertEqual(plain.run_workflow(WORKFLOW, {"id": "O1"})["status"],
                         "completed")
        self.assertNotIn("lookup", repo_spans(plain)[0].attrs)

    def test_an_absent_lookup_value_fails_the_step_and_writes_nothing(self):
        # `sku` is declared (the static check admits it) but not in the payload.
        doc = compile_doc("    find stock by input.productId\n"
                          "    set stock.onHand to 1\n"
                          "    update product by input.sku\n")
        rows = seed_rows()
        interp = Interpreter(doc, repo_rows=copy.deepcopy(rows))
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1"})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "update product by input.sku")
        self.assertIn("repository entity.product: lookup key 'input.sku' "
                      "resolved to no value", result["failure_reason"])
        # Never the "-" sentinel, and no row anywhere changed (the earlier
        # `set` rolled back with the failed run).
        self.assertNotIn(row_key(PRODUCT, {}), interp.repo.rows[PRODUCT])
        self.assertEqual(interp.repo.rows[PRODUCT], rows[PRODUCT])

    def test_a_non_string_lookup_value_is_stringified_like_row_key(self):
        doc = compile_doc("    find stock by input.code\n")
        self.assertEqual(row_key(STOCK, {"id": 7}), "entity.stock#7")
        interp = Interpreter(doc, repo_rows={
            STOCK: {"entity.stock#7": {"id": "S7", "onHand": 1}}})
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "code": 7})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["stock"]["id"], "S7")

    def test_a_set_after_a_by_read_persists_under_the_lookup_key(self):
        """D7 + the brief's two-row control: `find stock by input.productId`
        and a later plain `find stock` (payload id) address DIFFERENT rows —
        the `set` lands on the lookup-keyed row, the payload-keyed row stays
        as seeded, and the plain read then rebinds to the payload-keyed row."""
        doc = compile_doc("    find stock by input.productId\n"
                          "    set stock.onHand to 4\n"
                          "    find stock\n")
        rows = seed_rows()
        rows[STOCK][row_key(STOCK, {"id": "O1"})] = {"id": "O1", "onHand": 99}
        interp = Interpreter(doc, repo_rows=rows)
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1"})
        self.assertEqual(result["status"], "completed")
        table = interp.repo.rows[STOCK]
        self.assertEqual(table["entity.stock#P1"]["onHand"], 4)
        self.assertEqual(table["entity.stock#O1"]["onHand"], 99)
        self.assertEqual(result["bindings"]["stock"]["onHand"], 99)
        self.assertEqual(sorted(table), ["entity.stock#O1", "entity.stock#P1"])

    def test_a_by_read_inside_a_parallel_block_persists_under_its_key(self):
        """The parallel path threads the per-run key map too: a `set` after
        a `by` read in a `parallel` branch lands on the lookup-keyed row."""
        doc = compile_doc("    parallel\n"
                          "        find stock by input.productId\n"
                          "        find product by input.productId\n"
                          "    merge\n"
                          "    set stock.onHand to 2\n")
        interp = Interpreter(doc, repo_rows=seed_rows())
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1"})
        self.assertEqual(result["status"], "completed", result.get("failure_reason"))
        self.assertEqual(interp.repo.rows[STOCK]["entity.stock#P1"]["onHand"], 2)
        self.assertEqual(sorted(interp.repo.rows[STOCK]), ["entity.stock#P1"])

    def test_a_binding_used_before_its_create_step_fails_at_run_time(self):
        """Coordinator ruling r1: the static G12.5 c gate is order-blind, so
        `by o.productId` ahead of `create order as o` compiles — and fails
        here, at the step, because `o` is not bound yet."""
        doc = compile_doc("    find product by placed.productId\n"
                          "    create order as placed\n")
        rows = seed_rows()
        interp = Interpreter(doc, repo_rows=copy.deepcopy(rows))
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1"})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "find product by placed.productId")
        self.assertIn("lookup key 'placed.productId' resolved to no value",
                      result["failure_reason"])
        self.assertEqual(interp.repo.rows.get(ORDER, {}), {})
        self.assertEqual(interp.repo.rows[PRODUCT], rows[PRODUCT])

    def test_a_binding_created_earlier_supplies_the_key(self):
        """The same ref, bound first, resolves — the positive control for
        the use-before-bind failure above."""
        doc = compile_doc("    create order as placed\n"
                          "    find product by placed.productId\n")
        interp = Interpreter(doc, repo_rows=seed_rows())
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["product"]["id"], "P1")


class TestSeedWithoutTheLookupField(unittest.TestCase):
    """Coordinator ruling (t175b Task 10): when the payload lacks the field a
    first `by input.<field>` read names, the default seed skips that entity —
    on a persistent store too, so no stray `entity#None` row outlives the
    failed run."""

    def test_the_run_fails_by_name_and_the_store_gets_no_stray_row(self):
        from lnpl.repo_policy import default_rows
        doc = compile_doc("    find product\n"
                          "    find stock by input.productId\n")
        payload = {"id": "O1"}
        rows = default_rows(doc, WORKFLOW, payload)
        self.assertEqual(set(rows), {PRODUCT})
        driver = SqliteRepositoryDriver(os.path.join(_tmp_store_dir(self), "s.db"))
        self.addCleanup(driver.close)
        interp = Interpreter(doc, repo_rows=rows, repository=driver)
        result = interp.run_workflow(WORKFLOW, payload)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "find stock by input.productId")
        self.assertIn("lookup key 'input.productId' resolved to no value",
                      result["failure_reason"])
        self.assertEqual(driver.query(STOCK), [])
        self.assertIsNone(driver.execute(STOCK, "read", "entity.stock#None"))
        self.assertIsNotNone(driver.execute(PRODUCT, "read", "entity.product#O1"))


class TestF3F6Scenario(unittest.TestCase):
    """The issue #175 acceptance scenario, on both backends: two orders with
    different ids against one product; no create conflict; stock 5 -> 3 -> 0."""

    def _assert_two_orders(self, repository_factory, read_back):
        doc = compile_doc(F3_BODY)
        first = Interpreter(doc, repo_rows=seed_rows(), **repository_factory())
        run1 = first.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1", "qty": 2})
        self.assertEqual(run1["status"], "completed", run1.get("failure_reason"))
        self.assertEqual(read_back(first.repo, STOCK, "entity.stock#P1")["onHand"], 3)

        second = Interpreter(doc, repository=first.repo)
        run2 = second.run_workflow(WORKFLOW, {"id": "O2", "productId": "P1", "qty": 3})
        self.assertEqual(run2["status"], "completed", run2.get("failure_reason"))
        self.assertEqual(read_back(second.repo, STOCK, "entity.stock#P1")["onHand"], 0)

        for order_id, qty in (("O1", 2), ("O2", 3)):
            order = read_back(second.repo, ORDER, row_key(ORDER, {"id": order_id}))
            self.assertIsNotNone(order, order_id)
            self.assertEqual(order["productId"], "P1")
            self.assertEqual(order["qty"], qty)
        return second.repo

    def test_fake_repository(self):
        repo = self._assert_two_orders(
            lambda: {}, lambda r, e, k: r.rows.get(e, {}).get(k))
        self.assertEqual(sorted(repo.rows[ORDER]),
                         ["entity.order#O1", "entity.order#O2"])

    def test_sqlite_repository(self):
        driver = SqliteRepositoryDriver(os.path.join(_tmp_store_dir(self), "s.db"))
        self.addCleanup(driver.close)
        driver.seed(seed_rows())
        self._assert_two_orders(
            lambda: {"repository": driver},
            lambda r, e, k: r.execute(e, "read", k))
        # Two runs, each a `set` persist plus an `update` on the stock row
        # (both bump `_version`, drivers.py): 0 -> 4, all under the lookup key.
        self.assertEqual(driver.execute(STOCK, "read", "entity.stock#P1")
                         .observed_version, 4)

    def test_two_sets_in_one_run_both_persist_under_the_lookup_key_on_sqlite(self):
        """t174's contract under the lookup key: the second persist sees the
        first persist's own version bump, not a phantom write conflict.

        (A `set` after an `update` of the same bound row still conflicts on
        SQLite with or without `by` — `update` bumps `_version` without
        advancing the bound row's `observed_version`; pre-existing, recorded
        for a follow-up, coordinator ruling on #175 DoD 1.)"""
        doc = compile_doc("    find stock by input.productId\n"
                          "    set stock.onHand to stock.onHand - input.qty\n"
                          "    set stock.onHand to stock.onHand - input.qty\n"
                          "    update stock by input.productId\n")
        driver = SqliteRepositoryDriver(os.path.join(_tmp_store_dir(self), "s.db"))
        self.addCleanup(driver.close)
        driver.seed(seed_rows())
        interp = Interpreter(doc, repo_rows={}, repository=driver)
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1",
                                                "qty": 2})
        self.assertEqual(result["status"], "completed", result.get("failure_reason"))
        stock = driver.execute(STOCK, "read", "entity.stock#P1")
        self.assertEqual(stock["onHand"], 1)
        self.assertEqual(stock.observed_version, 3)
        # The order-id key was never written.
        self.assertIsNone(driver.execute(STOCK, "read", "entity.stock#O1"))

    def test_delete_by_removes_exactly_the_addressed_row_on_sqlite(self):
        doc = compile_doc("    delete stock by input.productId\n")
        rows = seed_rows()
        rows[STOCK]["entity.stock#P2"] = {"id": "S2", "productId": "P2",
                                          "onHand": 8}
        driver = SqliteRepositoryDriver(os.path.join(_tmp_store_dir(self), "s.db"))
        self.addCleanup(driver.close)
        driver.seed(rows)
        interp = Interpreter(doc, repo_rows={}, repository=driver)
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1"})
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(driver.execute(STOCK, "read", "entity.stock#P1"))
        self.assertEqual(driver.execute(STOCK, "read", "entity.stock#P2")["onHand"], 8)
        self.assertEqual([r["id"] for r in driver.query(STOCK)], ["S2"])

    def test_delete_by_on_the_fake_touches_no_other_row(self):
        """`FakeRepository` never removes a row on `delete` (it answers 1
        unconditionally — pre-existing, with or without `by`; coordinator
        ruling on #175 DoD 1). What the lookup key must still guarantee
        there: the run completes, the other row is untouched, and nothing is
        written under the payload id or the `"-"` sentinel."""
        doc = compile_doc("    delete stock by input.productId\n")
        rows = seed_rows()
        rows[STOCK]["entity.stock#P2"] = {"id": "S2", "productId": "P2",
                                          "onHand": 8}
        interp = Interpreter(doc, repo_rows=copy.deepcopy(rows))
        result = interp.run_workflow(WORKFLOW, {"id": "O1", "productId": "P1"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(interp.repo.rows[STOCK]["entity.stock#P2"],
                         rows[STOCK]["entity.stock#P2"])
        self.assertEqual(sorted(interp.repo.rows[STOCK]), sorted(rows[STOCK]))

if __name__ == "__main__":
    unittest.main()
