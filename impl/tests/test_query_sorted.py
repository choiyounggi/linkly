"""Issue #99, D7 — `RepositoryDriver.query_sorted`: the read-only surface
`expose list` pages over. Both backends must agree on order — sqlite pushes
sort to SQL via a parameterized `json_extract` path (never SQL text), the
Fake sorts the same `(field value, row_key)` pair in memory — because a
cursor built from one backend's page must mean the same thing under either
`--backend` (mirrors `query`'s own row_key-order contract, RFC-0025 §7).
"""

import os
import tempfile
import unittest

from lnpl.drivers import DriverError, SqliteRepositoryDriver
from lnpl.interp import FakeRepository

ENTITY = "entity.order"

ROWS = {
    ENTITY: {
        "entity.order#a": {"id": "a", "placedAt": "2026-01-03T00:00:00Z"},
        "entity.order#b": {"id": "b", "placedAt": "2026-01-01T00:00:00Z"},
        "entity.order#c": {"id": "c", "placedAt": "2026-01-02T00:00:00Z"},
    }
}

# Two rows share the same sort value — row_key must break the tie.
TIED_ROWS = {
    ENTITY: {
        "entity.order#z": {"id": "z", "placedAt": "2026-01-01T00:00:00Z"},
        "entity.order#a": {"id": "a", "placedAt": "2026-01-01T00:00:00Z"},
    }
}


def _sqlite_driver():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    driver = SqliteRepositoryDriver(tmp.name)
    driver.seed(ROWS)
    return driver, tmp.name


class QuerySortedParityTest(unittest.TestCase):
    """Normal case: both backends return rows ordered by the sort field."""

    def test_fake_orders_by_field_ascending(self):
        repo = FakeRepository(ROWS)
        ids = [r["id"] for r in repo.query_sorted(ENTITY, "placedAt")]
        self.assertEqual(["b", "c", "a"], ids)

    def test_sqlite_orders_by_field_ascending(self):
        driver, path = _sqlite_driver()
        try:
            ids = [r["id"] for r in driver.query_sorted(ENTITY, "placedAt")]
            self.assertEqual(["b", "c", "a"], ids)
        finally:
            driver.close()
            os.unlink(path)

    def test_both_backends_agree_on_tiebreak_order(self):
        # Boundary: equal sort values -> row_key (`entity.order#a` <
        # `entity.order#z`) decides, and both backends must pick the same one.
        fake_ids = [r["id"] for r in
                   FakeRepository(TIED_ROWS).query_sorted(ENTITY, "placedAt")]
        self.assertEqual(["a", "z"], fake_ids)

        driver = SqliteRepositoryDriver(
            tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
        try:
            driver.seed(TIED_ROWS)
            sqlite_ids = [r["id"] for r in driver.query_sorted(ENTITY, "placedAt")]
            self.assertEqual(fake_ids, sqlite_ids)
        finally:
            path = driver.path
            driver.close()
            os.unlink(path)


class QuerySortedBoundaryTest(unittest.TestCase):
    def test_empty_entity_yields_empty_list_never_none(self):
        repo = FakeRepository({})
        self.assertEqual([], repo.query_sorted(ENTITY, "placedAt"))

    def test_sqlite_empty_entity_yields_empty_list_never_none(self):
        driver, path = _sqlite_driver()
        try:
            self.assertEqual([], driver.query_sorted("entity.nothing", "placedAt"))
        finally:
            driver.close()
            os.unlink(path)


class QuerySortedErrorTest(unittest.TestCase):
    def test_sqlite_error_surfaces_as_driver_error(self):
        # Close the underlying connection directly (not through
        # `driver.close()`, which also clears `self._conn` to None and would
        # raise AttributeError instead) so `execute` hits a real sqlite3
        # failure — `DriverError` is the one error type this module lets out
        # (module docstring: "ONE ERROR TYPE OUT").
        driver, path = _sqlite_driver()
        try:
            driver._conn.close()
            with self.assertRaises(DriverError) as caught:
                driver.query_sorted(ENTITY, "placedAt")
            self.assertIn(ENTITY, str(caught.exception))
        finally:
            driver._conn = None
            os.unlink(path)



# RFC-0053 §9: rows lacking the sort field (or holding null) sort last.
MISSING_ROWS = {
    ENTITY: {
        "entity.order#a": {"id": "a", "placedAt": "2026-01-03T00:00:00Z"},
        "entity.order#b": {"id": "b"},
        "entity.order#c": {"id": "c", "placedAt": "2026-01-01T00:00:00Z"},
        "entity.order#d": {"id": "d", "placedAt": None},
    }
}


def _store_dir(test):
    """A per-test sqlite directory under `.claude/tmp`, removed on teardown."""
    import shutil
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    path = tempfile.mkdtemp(prefix="lnpl-t208b-", dir=base)
    test.addCleanup(shutil.rmtree, path, True)
    return path


class QuerySortedMissingFieldTest(unittest.TestCase):

    def sqlite(self, rows=MISSING_ROWS):
        driver = SqliteRepositoryDriver(os.path.join(_store_dir(self), "s.db"))
        self.addCleanup(driver.close)
        driver.seed(rows)
        return driver

    def test_fake_query_sorted_missing_field_sorts_last(self):
        ids = [r["id"] for r in FakeRepository(MISSING_ROWS).query_sorted(ENTITY, "placedAt")]
        self.assertEqual(["c", "a", "b", "d"], ids)

    def test_sqlite_query_sorted_missing_field_sorts_last(self):
        ids = [r["id"] for r in self.sqlite().query_sorted(ENTITY, "placedAt")]
        self.assertEqual(["c", "a", "b", "d"], ids)

    def test_sqlite_query_order_missing_field_sorts_last_desc(self):
        ids = [r["id"] for r in self.sqlite().query(ENTITY, order=("placedAt", True))]
        self.assertEqual(["a", "c", "b", "d"], ids)

    def test_sqlite_query_order_missing_field_sorts_last_asc(self):
        ids = [r["id"] for r in self.sqlite().query(ENTITY, order=("placedAt", False))]
        self.assertEqual(["c", "a", "b", "d"], ids)

    def test_fake_and_sqlite_agree_on_order_with_missing_rows(self):
        fake = FakeRepository(MISSING_ROWS)
        driver = self.sqlite()
        for desc in (False, True):
            with self.subTest(desc=desc):
                self.assertEqual(
                    [r["id"] for r in fake.query(ENTITY, order=("placedAt", desc))],
                    [r["id"] for r in driver.query(ENTITY, order=("placedAt", desc))])
        self.assertEqual([r["id"] for r in fake.query_sorted(ENTITY, "placedAt")],
                         [r["id"] for r in driver.query_sorted(ENTITY, "placedAt")])

    def test_sqlite_predicate_with_order_still_filters(self):
        # Regression: the doubled order parameter does not shift the
        # predicate's own bound parameters.
        ids = [r["id"] for r in self.sqlite().query(
            ENTITY, predicate=[("id", "!=", "a")], order=("placedAt", True), limit=2)]
        self.assertEqual(["c", "b"], ids)


if __name__ == "__main__":
    unittest.main()
