"""repo_policy: the one seed/key rule both execution modes read (issue #35).

The seed rule is role-based, so these tests pin *which* entities get a row as
much as they pin the shape of the store: an entity the workflow only creates
must start empty, or a read-then-create workflow can never succeed under any
seed — the defect issue #35 reports.
"""

import os
import shutil
import tempfile
import unittest

from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import FakeRepository, Interpreter, RunError, sample_payload
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import (apply_predicate, default_rows, lookup_key_source,
                              repository_calls, row_key, seeded_entities)

# Product is READ, Order is only CREATED — the two roles the seed must tell apart.
CHECKOUT = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
entity Order
    field
        id UUID
        total Money
service CheckoutService
    policy
        retry 3
workflow Checkout
    find product
    create order
"""

# The same module with the read guarded. Reachability is structural: a guard's
# truth is payload-dependent, and mode B derives its outcome statically
# (RFC-0004 §Execution modes), so a guarded read still seeds its entity.
GUARDED = CHECKOUT.replace("    find product\n",
                           "    when total missing\n    find product\n")

# No RepositoryCall at all — the zero-entity-table boundary.
NO_REPO = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
service CheckoutService
workflow Checkout
    validate product
"""


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def doc(src, name="checkout"):
    return lower(parse(src), name).to_document()


def payload_for(document):
    return sample_payload([n for n in document["nodes"] if n["kind"] == "Entity"])


def _tmp_store_dir(test):
    """A per-test sqlite directory under `.claude/tmp`, removed on teardown.

    `.claude/tmp`, never `/tmp`/`$TMPDIR`: repo policy, enforced for `mkdtemp`
    by `test_tmp_hygiene.py`. Mirrors `test_repo_state.py`'s `_tmp_workdir`.
    """
    base = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    path = tempfile.mkdtemp(prefix="lnpl-t174-", dir=base)
    test.addCleanup(shutil.rmtree, path, True)
    return path


class TestSeedRule(unittest.TestCase):
    def test_only_entities_the_workflow_reads_are_seeded(self):
        # Order is created, never read — seeding it would make `create order`
        # conflict on every run, which is exactly issue #35.
        self.assertEqual(seeded_entities(doc(CHECKOUT), "wf.checkout"),
                         {"entity.product"})

    def test_repository_calls_are_returned_in_declared_order(self):
        self.assertEqual(repository_calls(doc(CHECKOUT), "wf.checkout"),
                         [("entity.product", "read"), ("entity.order", "create")])

    def test_a_guarded_read_still_seeds_its_entity(self):
        d = doc(GUARDED)
        self.assertEqual(repository_calls(d, "wf.checkout"),
                         [("entity.product", "read"), ("entity.order", "create")])
        self.assertEqual(seeded_entities(d, "wf.checkout"), {"entity.product"})

    def test_workflow_without_repository_calls_seeds_nothing(self):
        d = doc(NO_REPO)
        self.assertEqual(repository_calls(d, "wf.checkout"), [])
        self.assertEqual(seeded_entities(d, "wf.checkout"), set())
        self.assertEqual(default_rows(d, "wf.checkout", payload_for(d)), {})

    def test_unknown_workflow_id_yields_no_calls_rather_than_raising(self):
        # Reporting a dangling workflow id belongs to the caller (the CLI already
        # does it); this module answering "no calls" keeps it a pure function.
        d = doc(CHECKOUT)
        self.assertEqual(repository_calls(d, "wf.nope"), [])
        self.assertEqual(seeded_entities(d, "wf.nope"), set())
        self.assertEqual(default_rows(d, "wf.nope", payload_for(d)), {})


class TestDefaultRows(unittest.TestCase):
    def test_seeded_store_is_keyed_per_entity_and_per_row(self):
        d = doc(CHECKOUT)
        payload = payload_for(d)
        rows = default_rows(d, "wf.checkout", payload)
        self.assertEqual(set(rows), {"entity.product"})
        self.assertEqual(list(rows["entity.product"]),
                         [row_key("entity.product", payload)])
        self.assertEqual(rows["entity.product"][row_key("entity.product", payload)],
                         payload)

    def test_the_seeded_row_is_a_copy_of_the_payload(self):
        # A shared fixture object mutated through the store would leak across runs.
        d = doc(CHECKOUT)
        payload = payload_for(d)
        rows = default_rows(d, "wf.checkout", payload)
        rows["entity.product"][row_key("entity.product", payload)]["stock"] = 999
        self.assertNotEqual(payload.get("stock"), 999)


# issue #175 / RFC-0052 §4: the order's own id is the payload `id`; stock is
# addressed by the product id instead.
LOOKUP = """
capability postgres
entity Stock
    field
        id Text
        productId Text
        onHand Integer
entity Order
    field
        id Text
        productId Text
service Orders
workflow Place
%s    create order as placed
"""
LOOKUP_PAYLOAD = {"id": "O1", "productId": "P1", "onHand": 5}


class TestLookupSeedKey(unittest.TestCase):
    """RFC-0052 §4: `by` changes WHICH KEY a seeded entity's row lives under,
    never WHICH entities seed."""

    def _rows(self, body):
        d = doc(LOOKUP % body, "place")
        return d, default_rows(d, "wf.place", dict(LOOKUP_PAYLOAD))

    def test_a_first_read_by_input_field_seeds_under_that_fields_value(self):
        d, rows = self._rows("    find stock by input.productId\n")
        self.assertEqual(rows, {"entity.stock": {
            row_key("entity.stock", {"id": "P1"}): LOOKUP_PAYLOAD}})
        self.assertEqual(lookup_key_source(d, "wf.place", "entity.stock"),
                         "input.productId")

    def test_only_the_first_read_decides_the_key(self):
        _d, rows = self._rows("    find stock by input.productId\n"
                              "    find stock\n")
        self.assertEqual(list(rows["entity.stock"]), ["entity.stock#P1"])
        _d, rows = self._rows("    find stock\n"
                              "    find stock by input.productId\n")
        self.assertEqual(list(rows["entity.stock"]), ["entity.stock#O1"])

    def test_a_by_less_first_read_keeps_the_payload_id_key(self):
        _d, rows = self._rows("    find stock\n")
        self.assertEqual(list(rows["entity.stock"]),
                         [row_key("entity.stock", LOOKUP_PAYLOAD)])

    def test_bound_bare_and_caller_lookups_keep_the_payload_id_key(self):
        """D10: only `input.<field>` is payload-derivable by the seed rule; a
        bound ref (`placed.productId`), a bare ref and `caller.*` are not
        specially seeded — negative controls."""
        for ref in ("placed.productId", "productId", "caller.subject"):
            with self.subTest(ref=ref):
                d, rows = self._rows("    find stock by %s\n" % ref)
                self.assertEqual(list(rows["entity.stock"]), ["entity.stock#O1"])
                self.assertEqual(lookup_key_source(d, "wf.place", "entity.stock"),
                                 ref)

    def test_a_guarded_first_read_still_decides_the_key(self):
        _d, rows = self._rows("    when onHand > 0\n"
                              "        find stock by input.productId\n")
        self.assertEqual(list(rows["entity.stock"]), ["entity.stock#P1"])

    def test_seeded_entities_is_unchanged_by_by(self):
        for body in ("    find stock by input.productId\n", "    find stock\n"):
            with self.subTest(body=body):
                d = doc(LOOKUP % body, "place")
                self.assertEqual(seeded_entities(d, "wf.place"), {"entity.stock"})

    def test_a_payload_without_the_lookup_field_seeds_no_row_for_that_entity(self):
        """Coordinator ruling (t175b Task 10): no `entity#None` row and no
        fallback to the payload-id key — the entity is simply not seeded;
        every other seeded entity is seeded exactly as before."""
        src = LOOKUP.replace("entity Order\n",
                             "entity Product\n    field\n        id Text\n"
                             "entity Order\n")
        d = doc(src % "    find stock by input.productId\n    find product\n",
                "place")
        payload = {"id": "O1", "onHand": 5}
        rows = default_rows(d, "wf.place", payload)
        self.assertEqual(rows, {"entity.product": {
            row_key("entity.product", payload): payload}})
        self.assertEqual(seeded_entities(d, "wf.place"),
                         {"entity.stock", "entity.product"})

    def test_lookup_key_source_edges(self):
        d = doc(LOOKUP % "    find stock by input.productId\n", "place")
        # an entity never read, and a workflow id that does not exist
        self.assertIsNone(lookup_key_source(d, "wf.place", "entity.order"))
        self.assertIsNone(lookup_key_source(d, "wf.nope", "entity.stock"))
        self.assertEqual(default_rows(d, "wf.nope", LOOKUP_PAYLOAD), {})


class TestRowKey(unittest.TestCase):
    def test_the_key_is_scoped_by_entity(self):
        # sample_payload merges every entity's fields into one flat dict, so a
        # single `id` value serves both entities. Only the scoping keeps their
        # rows apart.
        payload = payload_for(doc(CHECKOUT))
        self.assertNotEqual(row_key("entity.product", payload),
                            row_key("entity.order", payload))

    def test_the_same_payload_always_yields_the_same_key(self):
        payload = payload_for(doc(CHECKOUT))
        self.assertEqual(row_key("entity.product", payload),
                         row_key("entity.product", dict(payload)))

    def test_a_payload_without_an_id_falls_back_to_the_sentinel(self):
        self.assertEqual(row_key("entity.product", {}), "entity.product#-")

    def test_a_non_string_id_is_stringified(self):
        self.assertEqual(row_key("entity.product", {"id": 7}), "entity.product#7")


class TestReadThenCreate(unittest.TestCase):
    """Issue #35's headline: a workflow that reads one entity and creates another.

    Under the old seed-every-entity rule this could not pass under ANY seed —
    the default seed made `create order` conflict, and `--no-row` made
    `find product` miss.
    """

    def _run(self, src, rows=None, workflow="wf.checkout"):
        d = doc(src)
        payload = payload_for(d)
        if rows is None:
            rows = default_rows(d, workflow, payload)
        interp = Interpreter(d, repo_rows=rows)
        return interp, interp.run_workflow(workflow, payload), payload

    def test_read_then_create_completes_under_the_default_seed(self):
        interp, result, payload = self._run(CHECKOUT)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["find product", "create order"])
        # It completes *because* Order is not seeded — state the reason, so the
        # test fails loudly if the seed rule silently widens again.
        self.assertEqual(seeded_entities(doc(CHECKOUT), "wf.checkout"),
                         {"entity.product"})
        self.assertNotIn("entity.order",
                         default_rows(doc(CHECKOUT), "wf.checkout", payload))

    def test_an_empty_repository_fails_the_read_with_the_documented_message(self):
        interp, result, _payload = self._run(CHECKOUT, rows={})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "find product")
        reasons = [e.get("reason") for e in interp.trace.logs
                   if e["message"] == "step failed"]
        self.assertEqual(reasons, ["repository read found no row for entity.product"])
        # a read is idempotent, so `retry 3` did replay it: 1 initial + 3 retries
        found = [s for s in result["steps"] if s["step"] == "find product"][0]
        self.assertEqual(found["attempts"], 4)

    def test_an_explicitly_seeded_create_target_still_conflicts(self):
        # D2's reachable conflict, and the case that keeps the "never retry a
        # non-idempotent effect" rule observable.
        d = doc(CHECKOUT)
        payload = payload_for(d)
        rows = default_rows(d, "wf.checkout", payload)
        rows["entity.order"] = {row_key("entity.order", payload): dict(payload)}
        interp = Interpreter(d, repo_rows=rows)
        result = interp.run_workflow("wf.checkout", payload)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "create order")
        created = [s for s in result["steps"] if s["step"] == "create order"][0]
        self.assertEqual(created["attempts"], 1,
                         "a non-idempotent effect was retried")

    def test_creating_the_same_key_twice_in_one_workflow_conflicts(self):
        # Nothing is seeded here (Order is never read), so the first create must
        # succeed and the second must fail — which only holds if create inserts.
        src = CHECKOUT.replace("    find product\n    create order\n",
                               "    create order\n    create order\n")
        _interp, result, _payload = self._run(src)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "create order")
        self.assertEqual([s["attempts"] for s in result["steps"]], [1, 1])
        self.assertEqual(len(result["steps"]), 2, "the first create must have passed")

    def test_a_row_created_in_the_workflow_is_visible_to_a_later_read(self):
        # Seeded explicitly empty, NOT via default_rows: because this workflow
        # reads Order, the role-based rule would seed it and the first create
        # would conflict. Starting empty is what isolates "the create inserted"
        # from "the seed was already there".
        src = CHECKOUT.replace("    find product\n    create order\n",
                               "    create order\n    read order\n")
        interp, result, _payload = self._run(src, rows={})
        self.assertEqual(result["status"], "completed")
        repo_spans = [c for step in interp.trace.root.children
                      for c in step.children if c.kind == "RepositoryCall"]
        self.assertEqual([c.attrs["found"] for c in repo_spans], [True, True])

    def test_creating_an_entity_before_its_first_read_does_not_seed_it(self):
        # Order-aware (issue #174): `create order` runs before any `read
        # order`, so Order's FIRST operation is `create` -- it is excluded
        # from the default seed, and the create inserts instead of colliding
        # with a seed that was never placed. Still decidable from the
        # document alone: mode B (`backend.py`) and `differential.py`
        # inherit this rule because both call `seeded_entities` directly,
        # with no separate edit needed there. (Previously named
        # test_reading_an_entity_makes_it_seeded_even_when_it_is_also_created
        # and asserted the opposite, pre-#174 behavior -- "Role, not
        # declaration order" -- which issue #174 reports as the defect.)
        src = CHECKOUT.replace("    find product\n    create order\n",
                               "    create order\n    read order\n")
        d = doc(src)
        self.assertEqual(seeded_entities(d, "wf.checkout"), set())
        _interp, result, _payload = self._run(src)
        self.assertEqual(result["status"], "completed")

    def test_creating_an_entity_before_its_first_read_completes_on_a_real_sqlite_store(self):
        # DoD item 1's SQLite half of the same create-before-read case the
        # method above proves on the Fake repository.
        src = CHECKOUT.replace("    find product\n    create order\n",
                               "    create order\n    read order\n")
        d = doc(src)
        payload = payload_for(d)
        db_path = os.path.join(_tmp_store_dir(self), "store.db")
        driver = SqliteRepositoryDriver(db_path)
        self.addCleanup(driver.close)
        driver.seed(default_rows(d, "wf.checkout", payload))
        interp = Interpreter(d, repo_rows={}, repository=driver)
        result = interp.run_workflow("wf.checkout", payload)
        self.assertEqual(result["status"], "completed")

    def test_the_seed_dict_handed_to_the_interpreter_is_not_mutated(self):
        d = doc(CHECKOUT)
        payload = payload_for(d)
        rows = default_rows(d, "wf.checkout", payload)
        Interpreter(d, repo_rows=rows).run_workflow("wf.checkout", payload)
        self.assertEqual(set(rows), {"entity.product"},
                         "the create leaked into the caller's seed dict")


class TestKeyedStore(unittest.TestCase):
    """FakeRepository holds one keyed table per entity, not one row per entity."""

    def test_create_inserts_when_the_key_is_free(self):
        repo = FakeRepository()
        self.assertEqual(repo.execute("entity.order", "create", "entity.order#1"),
                         {"affected": 1})
        self.assertIsNotNone(repo.execute("entity.order", "read", "entity.order#1"))

    def test_create_conflicts_only_on_a_duplicate_key(self):
        repo = FakeRepository({"entity.order": {"entity.order#1": {"id": "1"}}})
        with self.assertRaises(RunError) as ctx:
            repo.execute("entity.order", "create", "entity.order#1")
        self.assertIn("already exists", str(ctx.exception))
        # a different key in the same entity is free
        self.assertEqual(repo.execute("entity.order", "create", "entity.order#2"),
                         {"affected": 1})

    def test_a_row_in_one_entity_does_not_block_a_create_in_another(self):
        # The whole of issue #35: reading Product must not make creating Order fail.
        repo = FakeRepository({"entity.product": {"entity.product#1": {"id": "1"}}})
        self.assertEqual(repo.execute("entity.order", "create", "entity.order#1"),
                         {"affected": 1})

    def test_read_returns_the_row_on_a_hit_and_none_on_a_miss(self):
        row = {"id": "1"}
        repo = FakeRepository({"entity.product": {"entity.product#1": row}})
        self.assertEqual(repo.execute("entity.product", "read", "entity.product#1"), row)
        self.assertIsNone(repo.execute("entity.product", "read", "entity.product#9"))
        self.assertIsNone(repo.execute("entity.nope", "read", "entity.nope#1"))

    def test_query_uses_the_same_lookup_as_read(self):
        row = {"id": "1"}
        repo = FakeRepository({"entity.product": {"entity.product#1": row}})
        self.assertEqual(repo.execute("entity.product", "query", "entity.product#1"), row)

    def test_the_callers_seed_dict_is_not_mutated_by_a_create(self):
        # `create` writes into the table now, so aliasing the caller's seed would
        # leak one run's writes into the next.
        seed = {"entity.product": {"entity.product#1": {"id": "1"}}}
        repo = FakeRepository(seed)
        repo.execute("entity.product", "create", "entity.product#2")
        self.assertEqual(list(seed["entity.product"]), ["entity.product#1"])

    def test_update_and_delete_report_an_affected_row(self):
        # Unchanged by issue #35 — recorded so the non-goal is visible.
        repo = FakeRepository()
        self.assertEqual(repo.execute("entity.product", "update", "entity.product#1"),
                         {"affected": 1})
        self.assertEqual(repo.execute("entity.product", "delete", "entity.product#1"),
                         {"affected": 1})


class TestApplyPredicate(unittest.TestCase):
    """issue #116, D4/D5/D6: the shared filter/sort/limit semantics
    `interp.FakeRepository.query`'s native path and the non-pushdown driver
    fallback (`interp.Interpreter`) both defer to, so the two never
    silently disagree on what a predicate/order/limit means."""

    ROWS = [{"id": "a", "amount": 10}, {"id": "b", "amount": 30},
           {"id": "c", "amount": 20}]

    def test_no_predicate_order_or_limit_returns_rows_unchanged(self):
        self.assertEqual(apply_predicate(list(self.ROWS)), self.ROWS)

    def test_predicate_filters_by_a_single_term(self):
        rows = apply_predicate(list(self.ROWS), predicate=[("amount", ">", 15)])
        self.assertEqual([r["id"] for r in rows], ["b", "c"])

    def test_predicate_conjunction_requires_every_term(self):
        rows = apply_predicate(list(self.ROWS),
                               predicate=[("amount", ">", 15), ("amount", "<", 25)])
        self.assertEqual([r["id"] for r in rows], ["c"])

    def test_predicate_referencing_a_missing_field_matches_nothing(self):
        rows = apply_predicate(list(self.ROWS), predicate=[("nosuch", "==", 1)])
        self.assertEqual(rows, [])

    def test_predicate_with_an_unresolved_value_matches_nothing(self):
        rows = apply_predicate(list(self.ROWS), predicate=[("amount", "==", None)])
        self.assertEqual(rows, [])

    def test_order_ascending(self):
        rows = apply_predicate(list(self.ROWS), order=("amount", False))
        self.assertEqual([r["id"] for r in rows], ["a", "c", "b"])

    def test_order_descending(self):
        rows = apply_predicate(list(self.ROWS), order=("amount", True))
        self.assertEqual([r["id"] for r in rows], ["b", "c", "a"])

    def test_order_ties_keep_row_key_ascending_regardless_of_desc(self):
        tied = [{"id": "0", "amount": 5}, {"id": "1", "amount": 5},
               {"id": "2", "amount": 5}]
        self.assertEqual([r["id"] for r in apply_predicate(list(tied), order=("amount", True))],
                         ["0", "1", "2"])
        self.assertEqual([r["id"] for r in apply_predicate(list(tied), order=("amount", False))],
                         ["0", "1", "2"])

    def test_limit_caps_the_result(self):
        rows = apply_predicate(list(self.ROWS), order=("amount", False), limit=2)
        self.assertEqual([r["id"] for r in rows], ["a", "c"])

    # RFC-0053 §9: a row lacking the sort field (or holding null) sorts last,
    # ascending and descending alike, in row_key order among themselves.
    WITH_MISSING = [{"id": "a", "amount": 10}, {"id": "b"},
                    {"id": "c", "amount": 20}, {"id": "d", "amount": None}]

    def test_apply_predicate_missing_field_sorts_last_asc(self):
        rows = apply_predicate(list(self.WITH_MISSING), order=("amount", False))
        self.assertEqual([r["id"] for r in rows], ["a", "c", "b", "d"])

    def test_apply_predicate_missing_field_sorts_last_desc(self):
        rows = apply_predicate(list(self.WITH_MISSING), order=("amount", True))
        self.assertEqual([r["id"] for r in rows], ["c", "a", "b", "d"])

    def test_apply_predicate_every_row_missing_keeps_row_key_order(self):
        rows = apply_predicate([{"id": "x"}, {"id": "y"}], order=("amount", True))
        self.assertEqual([r["id"] for r in rows], ["x", "y"])

    def test_apply_predicate_limit_counts_missing_rows_last(self):
        rows = apply_predicate(list(self.WITH_MISSING), order=("amount", False),
                               limit=3)
        self.assertEqual([r["id"] for r in rows], ["a", "c", "b"])

    def test_limit_larger_than_the_row_count_is_not_an_error(self):
        rows = apply_predicate(list(self.ROWS), limit=100)
        self.assertEqual(len(rows), 3)

    def test_predicate_order_and_limit_compose(self):
        rows = apply_predicate(list(self.ROWS), predicate=[("amount", ">", 5)],
                               order=("amount", True), limit=1)
        self.assertEqual([r["id"] for r in rows], ["b"])

    def test_empty_rows_is_not_an_error(self):
        self.assertEqual(apply_predicate([], predicate=[("amount", ">", 0)],
                                        order=("amount", False), limit=5), [])


if __name__ == "__main__":
    unittest.main()
