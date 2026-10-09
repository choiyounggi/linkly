"""issue #188 / RFC-0062: the `cached` read-through clause in mode A."""

import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import drivers as drivers_module
from lnpl.drivers import DriverError, open_cache
from lnpl import interp as interp_module
from lnpl.interp import (Clock, FakeCache, FakeRepository, Interpreter,
                         RunError)
from lnpl.lower import LowerError, lower
from lnpl.parser import parse
from lnpl.spec import extract, run_manifest

HEAD = """
capability postgres
capability redis
entity Product
    field
        id Text
        sku Text
        name Text
        qty Integer
service Catalog
%s"""
BUDGET = "    performance\n        cache 5m\n"
WORKFLOW = "wf.g"
PRODUCT = "entity.product"
ROW = {PRODUCT: {"entity.product#p1": {"id": "p1", "sku": "S1",
                                       "name": "Widget", "qty": 5}}}
TWO_READS = "workflow G\n    find product cached\n    find product cached\n"


def compile_doc(body, budget=True):
    return lower(parse(HEAD % (BUDGET if budget else "") + body),
                 "m").to_document()


def repo_nodes(doc):
    return [n for n in doc["nodes"] if n["kind"] == "RepositoryCall"]


def repo_spans(interp):
    return [c for step in interp.trace.root.children
            for c in step.children if c.kind == "RepositoryCall"]


class TestLowering(unittest.TestCase):

    def test_cached_sets_the_flag_on_each_read_verb(self):
        for verb in ("find", "read", "load", "authenticate"):
            with self.subTest(verb=verb):
                (node,) = repo_nodes(compile_doc(
                    "workflow G\n    %s product cached\n" % verb))
                self.assertEqual(node["operation"], "read")
                self.assertIs(node["cached"], True)

    def test_by_then_cached_carries_both_fields(self):
        (node,) = repo_nodes(compile_doc(
            "workflow G\n    find product by input.sku cached\n"))
        self.assertEqual(node["lookup"], "input.sku")
        self.assertIs(node["cached"], True)

    def test_a_read_without_the_clause_has_no_cached_key(self):
        for body in ("workflow G\n    find product\n",
                     "workflow G\n    find product by input.sku\n"):
            with self.subTest(body=body):
                (node,) = repo_nodes(compile_doc(body))
                self.assertNotIn("cached", node)

    def test_refused_shapes(self):
        for line in ("find product cached by input.sku",
                     "find product cached cached", "find product bogus"):
            with self.subTest(line=line):
                with self.assertRaisesRegex(
                        LowerError,
                        "accepts either no trailing words, `by <ref>`, `cached`"):
                    compile_doc("workflow G\n    %s\n" % line)

    def test_cached_is_refused_on_update_delete_and_list(self):
        for line in ("update product cached", "delete product cached"):
            with self.subTest(line=line):
                with self.assertRaisesRegex(
                        LowerError,
                        "accepts either no trailing words or `by <ref>`, got"):
                    compile_doc("workflow G\n    %s\n" % line)
        with self.assertRaises(LowerError):
            compile_doc("workflow G\n    list product cached\n")

    def test_no_cache_budget_is_a_compile_error(self):
        with self.assertRaisesRegex(
                LowerError, "needs a `performance cache <duration>` budget"):
            compile_doc("workflow G\n    find product cached\n", budget=False)

    def test_budget_on_another_service_does_not_count(self):
        src = ("capability postgres\ncapability redis\n"
               "entity Product\n    field\n        id Text\n"
               "service Other\n    database\n        postgres\n"
               "    performance\n        cache 5m\n"
               "service Catalog\n    database\n        postgres\n%s"
               "workflow G\n    find product cached\n")
        with self.assertRaisesRegex(
                LowerError, "needs a `performance cache <duration>` budget"):
            lower(parse(src % ""), "m")
        doc = lower(parse(src % "    performance\n        cache 1m\n"),
                    "m").to_document()
        self.assertIs(repo_nodes(doc)[0]["cached"], True)

    def test_a_workflow_writing_what_it_reads_cached_is_refused(self):
        for write in ("set product.qty to product.qty - 1", "update product"):
            with self.subTest(write=write):
                with self.assertRaisesRegex(
                        LowerError, r"must be read without `cached` \(RFC-0062\)"):
                    compile_doc("workflow G\n    find product cached\n    %s\n"
                                % write)

    def test_create_as_beside_a_cached_read_is_allowed(self):
        doc = compile_doc("workflow G\n    find product cached\n"
                          "    create product as p2\n")
        self.assertEqual([n["operation"] for n in repo_nodes(doc)],
                         ["read", "create"])


class TestHitAndMiss(unittest.TestCase):

    def test_a_hit_skips_the_repository(self):
        interp = Interpreter(compile_doc(TWO_READS), repo_rows=ROW)
        result = interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(interp.repo.calls, [(PRODUCT, "read")])
        self.assertEqual((interp.cache.hits, interp.cache.misses), (1, 1))
        self.assertEqual(result["bindings"]["product"]["name"], "Widget")

    def test_a_miss_with_no_row_fails_and_caches_nothing(self):
        interp = Interpreter(compile_doc(TWO_READS), repo_rows={})
        result = interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual((result["status"], result["failure_kind"]),
                         ("failed", "not-found"))
        self.assertEqual(interp.cache.store, {})

    def test_by_cached_keys_by_the_lookup_value(self):
        rows = {PRODUCT: {"entity.product#S1": {"id": "p1", "sku": "S1", "name": "W"},
                          "entity.product#S2": {"id": "p2", "sku": "S2", "name": "V"}}}
        doc = compile_doc("workflow G\n    find product by input.sku cached\n")
        cache = FakeCache(Clock())
        calls = []
        for sku in ("S1", "S2", "S1"):
            interp = Interpreter(doc, repo_rows=rows, cache=cache)
            interp.run_workflow(WORKFLOW, {"id": "o1", "sku": sku})
            calls.append(len(interp.repo.calls))
        self.assertEqual(calls, [1, 1, 0])
        self.assertEqual(sorted(cache.store),
                         ["entity.product#S1", "entity.product#S2"])

    def test_a_miss_records_the_row_with_the_budget_ttl(self):
        ttls = []

        class Recording(FakeCache):
            def set(self, key, value, ttl_ms):
                ttls.append((key, ttl_ms))
                super().set(key, value, ttl_ms)
        cache = Recording(Clock())
        interp = Interpreter(compile_doc("workflow G\n    find product cached\n"),
                             repo_rows=ROW, cache=cache)
        interp.run_workflow(WORKFLOW, {"id": "p1"})
        # `performance cache 5m` (BUDGET) is 300000 ms.
        self.assertEqual(ttls, [("entity.product#p1", 300000)])
        value, expires_at = cache.store["entity.product#p1"]
        self.assertEqual(value["name"], "Widget")
        self.assertGreater(expires_at, interp.clock.now)

    def test_a_plain_read_makes_no_cache_call(self):
        interp = Interpreter(compile_doc("workflow G\n    find product\n"),
                             repo_rows=ROW)
        interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual((interp.cache.hits, interp.cache.misses), (0, 0))
        self.assertEqual(interp.cache.store, {})
        self.assertEqual(repo_spans(interp)[0].attrs, {"found": True})

    def test_a_registered_cache_driver_serves_the_second_identical_request(self):
        ep = importlib_metadata.EntryPoint(
            name="demo", value="tests.cache_spi_fixture:make_demo_cache",
            group="lnpl.caches")
        with mock.patch.object(drivers_module.importlib_metadata, "entry_points",
                               lambda **_kwargs: [ep]):
            cache = open_cache("demo:x")
        doc = compile_doc("workflow G\n    find product cached\n")
        first = Interpreter(doc, repo_rows=ROW, cache=cache)
        first.run_workflow(WORKFLOW, {"id": "p1"})
        second = Interpreter(doc, repo_rows=ROW, cache=cache)
        result = second.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual(first.repo.calls, [(PRODUCT, "read")])
        self.assertEqual(second.repo.calls, [])
        self.assertEqual(result["bindings"]["product"]["name"], "Widget")


class TestOutage(unittest.TestCase):

    def test_a_get_outage_falls_back_to_the_repository(self):
        class GetDown(FakeCache):
            def get(self, key):
                raise DriverError("down")
        interp = Interpreter(compile_doc(TWO_READS), repo_rows=ROW,
                             cache=GetDown(Clock()))
        result = interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(interp.repo.calls, [(PRODUCT, "read")] * 2)

    def test_a_set_outage_after_a_miss_does_not_fail_the_step(self):
        class SetDown(FakeCache):
            def set(self, key, value, ttl_ms):
                raise DriverError("down")
        interp = Interpreter(compile_doc(TWO_READS), repo_rows=ROW,
                             cache=SetDown(Clock()))
        result = interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(interp.repo.calls, [(PRODUCT, "read")] * 2)


class TestTraceAndMetrics(unittest.TestCase):

    def test_spans_and_metrics_record_miss_then_hit(self):
        interp = Interpreter(compile_doc(TWO_READS), repo_rows=ROW)
        interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual([s.attrs for s in repo_spans(interp)],
                         [{"cache_hit": False, "found": True},
                          {"cache_hit": True, "found": True}])
        self.assertEqual(
            [m for m in interp.trace.metrics if m[0].startswith("cache.")],
            [("cache.miss", {"step": "find product cached"}, 1),
             ("cache.hit", {"step": "find product cached"}, 1)])


class TestInvalidation(unittest.TestCase):

    def run_both(self, writer_body, writer_id):
        doc = compile_doc("workflow G\n    find product cached\n" + writer_body)
        cache = FakeCache(Clock())
        Interpreter(doc, repo_rows=ROW, cache=cache).run_workflow(
            WORKFLOW, {"id": "p1"})
        self.assertEqual(sorted(cache.store), ["entity.product#p1"])
        result = Interpreter(doc, repo_rows=ROW, cache=cache).run_workflow(
            writer_id, {"id": "p1"})
        self.assertEqual(result["status"], "completed")
        return cache

    def test_a_set_in_another_workflow_invalidates(self):
        cache = self.run_both("workflow U\n    find product\n"
                              "    set product.qty to product.qty - 1\n", "wf.u")
        self.assertEqual(cache.store, {})

    def test_a_delete_in_another_workflow_invalidates(self):
        cache = self.run_both("workflow D\n    delete product\n", "wf.d")
        self.assertEqual(cache.store, {})

    def test_a_document_without_cached_reads_makes_no_invalidate_call(self):
        calls = []

        class Spy(FakeCache):
            def invalidate(self, key):
                calls.append(key)
        doc = compile_doc("workflow D\n    delete product\n")
        Interpreter(doc, repo_rows=ROW, cache=Spy(Clock())).run_workflow(
            "wf.d", {"id": "p1"})
        self.assertEqual(calls, [])

    def test_a_rolled_back_run_discards_its_cache_writes(self):
        doc = compile_doc("workflow G\n    find product cached\n"
                          "    when product.qty > 0\n        fail out-of-stock\n")
        interp = Interpreter(doc, repo_rows=ROW)
        result = interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual((result["status"], result["failure_kind"]),
                         ("failed", "rejected"))
        self.assertEqual(interp.cache.misses, 1)
        self.assertEqual(interp.cache.store, {})

    def test_a_run_error_escaping_the_step_loop_discards_its_cache_writes(self):
        # The other rollback path of run_workflow: a RunError raised by the
        # step iterator itself (e.g. a guard it cannot evaluate) after the
        # cached read already ran and wrote the cache.
        real = interp_module._flatten_items

        def then_raise(*args, **kwargs):
            yield from real(*args, **kwargs)
            raise RunError("guard could not be evaluated")
        interp = Interpreter(compile_doc("workflow G\n    find product cached\n"),
                             repo_rows=ROW)
        with mock.patch.object(interp_module, "_flatten_items", then_raise):
            with self.assertRaises(RunError):
                interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual(interp.repo.calls, [(PRODUCT, "read")])
        self.assertEqual(interp.cache.misses, 1)
        self.assertEqual(interp.cache.store, {})

    def test_an_invalidate_outage_does_not_fail_the_write(self):
        class InvalidateDown(FakeCache):
            def invalidate(self, key):
                raise DriverError("down")
        doc = compile_doc("workflow G\n    find product cached\n"
                          "workflow D\n    delete product\n")
        cache = InvalidateDown(Clock())
        Interpreter(doc, repo_rows=ROW, cache=cache).run_workflow(
            WORKFLOW, {"id": "p1"})
        writer = Interpreter(doc, repo_rows=ROW, cache=cache)
        result = writer.run_workflow("wf.d", {"id": "p1"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(writer.repo.calls, [(PRODUCT, "delete")])
        # The key stays; its TTL bounds the staleness.
        self.assertEqual(sorted(cache.store), ["entity.product#p1"])

    def test_an_invalidate_outage_on_rollback_keeps_the_run_failed_not_raised(self):
        class InvalidateDown(FakeCache):
            def invalidate(self, key):
                raise DriverError("down")
        doc = compile_doc("workflow G\n    find product cached\n"
                          "    when product.qty > 0\n        fail out-of-stock\n")
        interp = Interpreter(doc, repo_rows=ROW, cache=InvalidateDown(Clock()))
        result = interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual((result["status"], result["failure_kind"]),
                         ("failed", "rejected"))

    def test_a_rollback_discards_only_the_current_runs_cache_writes(self):
        doc = compile_doc("workflow G\n    find product cached\n"
                          "workflow F\n    find product\n"
                          "    when product.qty > 0\n        fail out-of-stock\n")
        interp = Interpreter(doc, repo_rows=ROW)
        first = interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual(first["status"], "completed")
        second = interp.run_workflow("wf.f", {"id": "p1"})
        self.assertEqual(second["status"], "failed")
        # The completed first run's entry survives the second run's rollback.
        self.assertEqual(sorted(interp.cache.store), ["entity.product#p1"])



class TestInvalidateAfterCommit(unittest.TestCase):
    """Review C1: a write's read-through invalidation runs only after
    `repo.commit()` returned, so a concurrent `cached` reader cannot
    re-cache the pre-write row between the invalidate and the commit."""

    def run_writer(self, writer_body, writer_id):
        log = []

        class Repo(FakeRepository):
            def commit(self):
                log.append("commit")
                super().commit()

            def rollback(self):
                log.append("rollback")
                super().rollback()

        class Cache(FakeCache):
            def invalidate(self, key):
                log.append("invalidate " + key)
                super().invalidate(key)
        doc = compile_doc("workflow G\n    find product cached\n" + writer_body)
        cache = Cache(Clock())
        Interpreter(doc, repo_rows=ROW, cache=cache).run_workflow(
            WORKFLOW, {"id": "p1"})
        self.assertEqual(sorted(cache.store), ["entity.product#p1"])
        result = Interpreter(doc, repo_rows=ROW, cache=cache,
                             repository=Repo()).run_workflow(writer_id, {"id": "p1"})
        return result, log, cache

    def test_a_delete_invalidates_after_the_commit(self):
        result, log, cache = self.run_writer("workflow D\n    delete product\n",
                                             "wf.d")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(log, ["commit", "invalidate entity.product#p1"])
        self.assertEqual(cache.store, {})

    def test_a_set_invalidates_after_the_commit(self):
        result, log, cache = self.run_writer(
            "workflow U\n    find product\n"
            "    set product.qty to product.qty - 1\n", "wf.u")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(log, ["commit", "invalidate entity.product#p1"])
        self.assertEqual(cache.store, {})

    def test_a_rolled_back_write_invalidates_nothing(self):
        # The write never committed, so the cached row is still the stored one.
        result, log, cache = self.run_writer(
            "workflow D\n    find product\n    delete product\n"
            "    when product.qty > 0\n        fail out-of-stock\n", "wf.d")
        self.assertEqual((result["status"], result["failure_kind"]),
                         ("failed", "rejected"))
        self.assertEqual(log, ["rollback"])
        self.assertEqual(sorted(cache.store), ["entity.product#p1"])

    def test_a_failing_commit_invalidates_nothing(self):
        log = []

        class Repo(FakeRepository):
            def commit(self):
                log.append("commit")
                raise RunError("commit lost")

        class Cache(FakeCache):
            def invalidate(self, key):
                log.append("invalidate " + key)
        doc = compile_doc("workflow G\n    find product cached\n"
                          "workflow D\n    delete product\n")
        with self.assertRaisesRegex(RunError, "commit lost"):
            Interpreter(doc, repo_rows=ROW, cache=Cache(Clock()),
                        repository=Repo()).run_workflow("wf.d", {"id": "p1"})
        self.assertEqual(log, ["commit"])

    def test_an_uncommitted_runs_invalidation_does_not_reach_the_next_run(self):
        doc = compile_doc("workflow G\n    find product cached\n"
                          "workflow D\n    find product\n    delete product\n"
                          "    when product.qty > 0\n        fail out-of-stock\n")
        interp = Interpreter(doc, repo_rows=ROW)
        rolled_back = interp.run_workflow("wf.d", {"id": "p1"})
        self.assertEqual(rolled_back["status"], "failed")
        cached = interp.run_workflow(WORKFLOW, {"id": "p1"})
        self.assertEqual(cached["status"], "completed")
        # G's own commit must not flush D's rolled-back delete of p1.
        self.assertEqual(sorted(interp.cache.store), ["entity.product#p1"])

SPEC = HEAD % BUDGET + """workflow GetProduct
    find product cached
%s    spec
        given
            valid product
        when
            getproduct
        expect
            completed
            cache hit
            cache miss
"""


class TestSpecObservation(unittest.TestCase):

    def run_spec(self, second_read):
        decls = parse(SPEC % ("    find product cached\n" if second_read else ""))
        return run_manifest(extract(decls, "m"), lower(decls, "m").to_document())

    def test_two_reads_observe_a_miss_and_a_hit(self):
        passed, failed, lines = self.run_spec(True)
        self.assertEqual((passed, failed), (3, 0), lines)

    def test_one_read_cannot_claim_a_hit(self):
        passed, failed, lines = self.run_spec(False)
        self.assertEqual((passed, failed), (2, 1), lines)
        self.assertTrue(any("cache hit (cache hits=0)" in l for l in lines), lines)


if __name__ == "__main__":
    unittest.main()
