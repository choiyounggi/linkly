"""Clock contract: virtual (default) vs real bindings.

RFC-0003 §Execution Model (Clock, RFC-0029 Updates), issue #100. The default
virtual binding must stay byte-identical to what shipped before this issue;
`--clock real` is a new, separately-selected binding that ties `CacheAccess`
TTL judgment to actual wall-clock elapsed time.
"""

import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lnpl.cli import main
from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import Clock, FakeCache, RealClock, open_clock

from tests.test_runtime import PAYLOAD, SOURCE, build


class OpenClockSelectorTest(unittest.TestCase):
    """`open_clock` mirrors `open_repository`/`open_network`'s closed table."""

    def test_virtual_returns_none_for_the_byte_identical_default(self):
        self.assertIsNone(open_clock("virtual"))

    def test_real_returns_a_real_clock_instance(self):
        self.assertIsInstance(open_clock("real"), RealClock)

    def test_an_unknown_selector_is_rejected_naming_the_accepted_set(self):
        with self.assertRaises(ValueError) as ctx:
            open_clock("atomic")
        message = str(ctx.exception)
        self.assertIn("atomic", message)
        self.assertIn("virtual", message)
        self.assertIn("real", message)


class RealClockTest(unittest.TestCase):
    """`RealClock.now` reflects actual elapsed wall-clock time."""

    def test_now_advances_with_real_time_without_calling_advance(self):
        clock = RealClock()
        first = clock.now
        time.sleep(0.02)
        second = clock.now
        # 20ms slept; a generous floor absorbs scheduling jitter without
        # losing the point — `now` moved on its own, no `advance()` called.
        self.assertGreaterEqual(second - first, 15)

    def test_advance_is_a_no_op(self):
        clock = RealClock()
        before = clock.now
        returned = clock.advance(5000)
        # Nowhere near the 5000ms argument: advance() does not fast-forward
        # a real clock the way it fast-forwards the virtual one.
        self.assertLess(returned - before, 100)


class FakeCacheTtlBoundaryTest(unittest.TestCase):
    """Integer-ms virtual clock: exact-boundary TTL judgment. The clock's
    counter is an int (never a float), so the boundary is asserted exactly —
    no tolerance needed (testing-quality-injected-clock-duration-assertions
    rule 4)."""

    def test_entry_is_live_one_ms_before_the_boundary(self):
        clock = Clock(step_cost_ms=0)
        cache = FakeCache(clock)
        cache.set("k", "v", ttl_ms=100)
        clock.now = 99
        self.assertEqual(cache.get("k"), "v")

    def test_entry_is_expired_exactly_at_the_boundary(self):
        clock = Clock(step_cost_ms=0)
        cache = FakeCache(clock)
        cache.set("k", "v", ttl_ms=100)
        clock.now = 100
        self.assertIsNone(cache.get("k"))


class RealClockCacheExpiryIntegrationTest(unittest.TestCase):
    """DoD (issue #100): `--clock real` + a persistent (sqlite) repository —
    `CacheAccess` TTL expires by actual wall-clock elapsed time, not the
    deterministic virtual counter.

    Built at the Interpreter/driver level rather than through `lnpl serve`:
    `serve.py` is out of this task's scope (owned by other tasks), and it
    already builds a fresh Interpreter — and so a fresh cache — per request,
    so no single request could observe a TTL crossing a real sleep anyway.
    What this proves is the primitive a persistent cache driver needs: TTL
    survives real elapsed time on one long-lived cache instance paired with
    a persistent (sqlite) repository, which is exactly the "redis binding"
    gap `docs/backends.md` §5 records.
    """

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.db = os.path.join(box.name, "store.db")

    def test_ttl_expires_after_real_elapsed_time_under_a_sqlite_repository(self):
        repository = SqliteRepositoryDriver(self.db)
        self.addCleanup(repository.close)
        interp = build(repository=repository, clock=RealClock())

        interp.cache.set("user:1", {"id": "1"}, ttl_ms=50)
        self.assertEqual(interp.cache.get("user:1"), {"id": "1"})

        time.sleep(0.1)  # 100ms real sleep, well past the 50ms TTL

        self.assertIsNone(interp.cache.get("user:1"))


class ClockCliSelectorTest(unittest.TestCase):
    """`--clock` on `run`, mirroring `--backend`/`--network`'s CLI shape
    (`test_cli_backend.py::RunBackendTest`)."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.source = os.path.join(self.dir, "login.lnpl")
        with open(self.source, "w", encoding="utf-8") as fh:
            fh.write(SOURCE)
        self.payload = os.path.join(self.dir, "payload.json")
        with open(self.payload, "w", encoding="utf-8") as fh:
            json.dump(PAYLOAD, fh)

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_the_default_run_is_unchanged_by_the_new_flag(self):
        """`--clock virtual` stated explicitly must equal the flag omitted —
        the byte-identical-default regression this task's DoD requires."""
        implicit = self._run(["run", self.source, "--payload", self.payload,
                              "--json"])
        explicit = self._run(["run", self.source, "--payload", self.payload,
                              "--json", "--clock", "virtual"])

        self.assertEqual(implicit[0], 0)
        self.assertEqual(explicit[0], 0)
        self.assertEqual(implicit[1], explicit[1])   # byte-identical stdout

    def test_an_unknown_clock_is_an_operator_error(self):
        rc, out, err = self._run(["run", self.source, "--clock", "atomic"])

        self.assertEqual(rc, 2)
        self.assertEqual(out, "")            # a rejected run emits no result
        self.assertIn("atomic", err)
        self.assertIn("virtual", err)
        self.assertIn("real", err)

    def test_clock_real_is_accepted_and_runs(self):
        rc, out, _ = self._run(["run", self.source, "--payload", self.payload,
                                "--json", "--clock", "real"])

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["result"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
