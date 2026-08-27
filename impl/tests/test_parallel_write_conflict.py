"""issue #108, D5/D9/D2-r1: `parallel` blocks reach the execution plan now, so
two things the parser used to let slide silently become real bugs the moment
steps race — this file pins the compile-time half.

D5: two steps inside one `parallel` block that both write (create/insert/
update/delete) the same entity is a `LowerError`, not a diagnostic — RFC-0012
binding is order-dependent, and a `parallel` block has no order, so which
write "wins" would be non-deterministic between runs. That is a correctness
bug the grammar cannot see (either step alone parses fine), so it is refused
at compile time rather than logged and shipped.

D9: `policy parallel` moves from `unenforced` to `enforced` in
`diagnostics.ENFORCEMENT` — a service that declares it no longer gets a
`declared-not-enforced` diagnostic.

D2-r1 (coordinator-ratified mid-implementation amendment): `policy parallel`
gains the same optional-integer-argument shape `retry`/`timeout` already
have — bare `parallel` still parses (cap falls back to the block's own step
count, at run time), `parallel <N>` sets an explicit cap.
"""

import unittest

from lnpl.diagnostics import ENFORCEMENT
from lnpl.lower import LowerError, lower
from lnpl.parser import parse

ENTITIES = """entity Product
    field
        id UUID
        stock Integer
entity Order
    field
        id UUID
        total Money
"""


def compile_module(source, name="t"):
    return lower(parse(source), name)


class TestSameEntityWriteConflictIsRefused(unittest.TestCase):
    def test_two_updates_to_the_same_entity_in_one_parallel_block_is_refused(self):
        # Normal case: the exact shape D5 exists for.
        source = ENTITIES + """workflow Restock
    find product
    parallel
    update product
    update product
    merge
"""
        lines = source.splitlines()
        first_line = lines.index("    update product") + 1
        second_line = first_line + 1
        with self.assertRaises(LowerError) as cm:
            compile_module(source)
        message = str(cm.exception)
        self.assertIn("Product", message)
        # Both offending lines are cited, not just the first.
        self.assertIn(str(first_line), message)
        self.assertIn(str(second_line), message)

    def test_create_and_update_racing_on_the_same_entity_is_also_refused(self):
        # The write family is create/insert/update/delete together, not just
        # matching verbs — a create racing an update is exactly as
        # non-deterministic as two updates.
        source = ENTITIES + """workflow Restock
    parallel
    create order
    update order
    merge
"""
        with self.assertRaises(LowerError) as cm:
            compile_module(source)
        self.assertIn("order", str(cm.exception))

    def test_read_and_write_on_the_same_entity_is_allowed(self):
        # Boundary: a reader alongside a writer races on nothing stored — only
        # writes are order-sensitive under RFC-0012.
        source = ENTITIES + """workflow Restock
    parallel
    find product
    update product
    merge
"""
        compile_module(source)   # must not raise

    def test_writes_to_different_entities_are_allowed(self):
        # Boundary: the conflict is per-entity, not per-block.
        source = ENTITIES + """workflow Restock
    parallel
    create order
    update product
    merge
"""
        compile_module(source)   # must not raise

    def test_a_lone_writer_in_the_block_is_allowed(self):
        # Boundary: one writer, no race, no matter how many other steps share
        # the block.
        source = ENTITIES + """workflow Restock
    parallel
    find product
    create order
    merge
"""
        compile_module(source)   # must not raise

    def test_two_writers_on_the_same_entity_outside_a_parallel_block_is_fine(self):
        # Boundary: sequential steps have a defined order (RFC-0012), so the
        # same two verbs back to back outside `parallel` is ordinary code.
        source = ENTITIES + """workflow Restock
    find product
    update product
    update product
"""
        compile_module(source)   # must not raise


class TestParallelPolicyTakesAnOptionalCap(unittest.TestCase):
    def test_bare_parallel_still_parses(self):
        # Normal case: pre-existing programs that declare the flag form keep
        # compiling unchanged.
        source = ENTITIES + """service ShopService
    policy
        parallel
workflow Restock
    find product
"""
        mod = compile_module(source)
        policy = [n for n in mod.to_document()["nodes"] if n["kind"] == "Policy"][0]
        self.assertEqual(policy["rules"], [{"name": "parallel"}])

    def test_parallel_with_an_integer_cap_parses(self):
        source = ENTITIES + """service ShopService
    policy
        parallel 3
workflow Restock
    find product
"""
        mod = compile_module(source)
        policy = [n for n in mod.to_document()["nodes"] if n["kind"] == "Policy"][0]
        self.assertEqual(policy["rules"], [{"name": "parallel", "value": 3}])

    def test_a_non_integer_cap_is_refused(self):
        # Error path: same arity discipline `retry` already enforces.
        source = ENTITIES + """service ShopService
    policy
        parallel three
workflow Restock
    find product
"""
        with self.assertRaises(LowerError) as cm:
            compile_module(source)
        self.assertIn("parallel", str(cm.exception))

    def test_a_zero_cap_is_refused(self):
        # Boundary: 0 workers can never run a block's steps at all — this is
        # not a smaller cap, it is a stuck one. `con["parallel_cap"] or
        # len(steps)` (interp.py) treats a falsy declared value as "no cap"
        # at all, so silently accepting 0 here would make the enforced cap
        # the OPPOSITE of what was declared. Refused at the source instead.
        source = ENTITIES + """service ShopService
    policy
        parallel 0
workflow Restock
    find product
"""
        with self.assertRaises(LowerError) as cm:
            compile_module(source)
        self.assertIn("parallel", str(cm.exception))

    def test_two_values_is_refused(self):
        # Boundary: exactly one optional argument, not more.
        source = ENTITIES + """service ShopService
    policy
        parallel 3 4
workflow Restock
    find product
"""
        with self.assertRaises(LowerError):
            compile_module(source)


class TestParallelPolicyIsNowEnforced(unittest.TestCase):
    def test_matrix_reports_policy_parallel_as_enforced(self):
        self.assertEqual(ENFORCEMENT[("policy", "parallel")][0], "enforced")

    def test_declaring_it_no_longer_reports_declared_not_enforced(self):
        source = ENTITIES + """service ShopService
    policy
        parallel 3
workflow Restock
    find product
"""
        mod = compile_module(source)
        diags = [d for d in mod.diagnostics.all() if d.code == "declared-not-enforced"]
        self.assertEqual([d.subject for d in diags], [])

    def test_performance_parallel_prefetch_batch_stay_unenforced(self):
        # Boundary: D9 promotes only `policy parallel`; the three
        # `performance` metrics stay unenforced (they are storage-access
        # patterns, not this issue's scope).
        for metric in ("parallel", "prefetch", "batch"):
            self.assertEqual(ENFORCEMENT[("performance", metric)][0], "unenforced")


if __name__ == "__main__":
    unittest.main()
