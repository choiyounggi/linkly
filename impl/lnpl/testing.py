"""`RepositoryDriver` Technology Compatibility Kit (issue #75).

`docs/backends.md` §5 has said since #25 that a real `postgres`/`redis`
binding is an external package's job, not the core's — no DB dependency
lands here. What the core owns instead is the *contract* those packages
must satisfy, and a runnable proof of it: the same idea as a JDBC TCK,
which ships with the JDBC spec so any vendor's driver can be checked
against one suite rather than each vendor asserting its own conformance.

Inherit `RepositoryDriverTCK` *and* `unittest.TestCase`, override
`make_driver()`, run the result as an ordinary test::

    import unittest
    from lnpl.testing import RepositoryDriverTCK

    class MyDriverTCKTest(RepositoryDriverTCK, unittest.TestCase):
        def make_driver(self):
            return MyRepositoryDriver(...)

`RepositoryDriverTCK` itself does NOT inherit `unittest.TestCase` — only a
mixin, combined with `TestCase` in the concrete subclass. A base that already
was `TestCase` would be collected and run on its own by `unittest discover`
wherever it is merely imported (its abstract `make_driver()` raising
`NotImplementedError` on every test) — the same reason a shared unittest test
base is conventionally written as a plain mixin, never as a `TestCase`
itself.

Every test method here operates on one driver instance at a time — no
`.lnpl` source, no `Interpreter` — because the contract this checks is the
driver's own (`RepositoryDriver`'s docstrings in `lnpl.drivers`), not how an
interpreter happens to call it. `make_driver()` is called once per test
method (`setUp`); call it again *within* a test that needs a second,
independent handle onto the same store (the version-conflict test below
does exactly this) — a driver author's `make_driver()` should open a new
connection to a fixed-for-this-test location, not a fresh store each call,
or that second call sees an empty store instead of the first handle's data.

`begin`/`commit`/`rollback` (issue #79, RFC-0032) default to a no-op on the
base `RepositoryDriver` — a driver with no transactional notion of its own
satisfies the contract by doing nothing in all three. This TCK checks only
that the three are callable in sequence without raising; it does not assert
that `rollback` discards writes, since the contract explicitly allows the
no-op answer.

The optimistic-version conflict (issue #92) is likewise not a required
capability of every driver — the base contract's `execute`/`persist` never
mention a version at all. A driver opts in by returning a read result that
carries an `observed_version` attribute (`SqliteRepositoryDriver`'s
`_VersionedRow` is the reference shape); this TCK detects that opt-in and
skips the conflict test for a driver that does not offer it, the same way a
JDBC TCK's optional-feature tests skip against a driver that reports the
feature unsupported.
"""

from lnpl.drivers import DriverError


class RepositoryDriverTCK:
    """Mix into a `unittest.TestCase` subclass, override `make_driver()` —
    see the module docstring for the usage example and what each test does
    and does not assume about the driver under test."""

    def make_driver(self):
        raise NotImplementedError(
            "RepositoryDriverTCK subclasses must override make_driver() "
            "to return a fresh RepositoryDriver")

    def setUp(self):
        self.driver = self.make_driver()
        self.addCleanup(self.driver.close)

    # -- seed / read -----------------------------------------------------

    def test_a_seeded_row_is_readable(self):
        self.driver.seed({"widget": {"w1": {"id": "w1", "n": 1}}})

        row = self.driver.execute("widget", "read", "w1")

        self.assertEqual(row["id"], "w1")
        self.assertEqual(row["n"], 1)

    def test_seed_inserts_only_where_absent(self):
        self.driver.seed({"widget": {"w1": {"id": "w1", "n": 1}}})

        self.driver.seed({"widget": {"w1": {"id": "w1", "n": 999}}})

        self.assertEqual(self.driver.execute("widget", "read", "w1")["n"], 1)

    def test_reading_an_absent_row_returns_none(self):
        self.assertIsNone(self.driver.execute("widget", "read", "no-such-row"))

    # -- create / update / delete -----------------------------------------

    def test_a_created_row_is_then_readable(self):
        result = self.driver.execute("widget", "create", "w2")

        self.assertEqual(result, {"affected": 1})
        self.assertIsNotNone(self.driver.execute("widget", "read", "w2"))

    def test_a_duplicate_create_raises_a_driver_error(self):
        self.driver.execute("widget", "create", "w3")

        with self.assertRaises(DriverError):
            self.driver.execute("widget", "create", "w3")

    def test_update_reports_the_row_as_affected(self):
        self.driver.execute("widget", "create", "w4")

        result = self.driver.execute("widget", "update", "w4")

        self.assertEqual(result["affected"], 1)

    def test_delete_removes_the_row(self):
        self.driver.execute("widget", "create", "w5")

        self.driver.execute("widget", "delete", "w5")

        self.assertIsNone(self.driver.execute("widget", "read", "w5"))

    # -- query -------------------------------------------------------------

    def test_query_of_an_untouched_entity_is_an_empty_list_not_none(self):
        self.assertEqual(self.driver.query("no-such-entity"), [])

    def test_query_returns_every_seeded_row(self):
        self.driver.seed({"widget": {"w1": {"id": "w1"}}})

        self.assertEqual(self.driver.query("widget"), [{"id": "w1"}])

    def test_query_orders_by_row_key_ascending_regardless_of_insertion_order(self):
        # Inserted 2, 0, 1 — row_key ascending is "0", "1", "2". A driver
        # that just returned insertion order would pass every other case
        # here and still disagree with this one (RFC-0025 §7).
        self.driver.seed({"widget": {
            "2": {"id": "2"}, "0": {"id": "0"}, "1": {"id": "1"},
        }})

        rows = self.driver.query("widget")

        self.assertEqual([row["id"] for row in rows], ["0", "1", "2"])

    # -- persist -------------------------------------------------------------

    def test_persist_flushes_a_row_mutated_after_read(self):
        self.driver.seed({"widget": {"w1": {"id": "w1", "n": 1}}})
        row = self.driver.execute("widget", "read", "w1")

        row["n"] = 2
        self.driver.persist("widget", "w1", row)

        self.assertEqual(self.driver.execute("widget", "read", "w1")["n"], 2)

    # -- transactions (issue #79) -------------------------------------------

    def test_begin_commit_is_callable_in_sequence(self):
        self.driver.begin()
        self.driver.execute("widget", "create", "w-tx-commit")
        self.driver.commit()

        self.assertIsNotNone(
            self.driver.execute("widget", "read", "w-tx-commit"))

    def test_begin_rollback_is_callable_in_sequence(self):
        self.driver.begin()
        self.driver.execute("widget", "create", "w-tx-rollback")
        self.driver.rollback()  # no visibility assertion — see module docstring

    # -- optimistic version conflict (issue #92) ----------------------------

    def test_a_stale_read_conflicts_when_the_driver_supports_optimistic_versions(self):
        self.driver.seed({"widget": {"w-v1": {"id": "w-v1", "n": 0}}})
        first_read = self.driver.execute("widget", "read", "w-v1")
        if not hasattr(first_read, "observed_version"):
            self.skipTest(
                "driver does not opt into optimistic version conflicts "
                "(no observed_version on a read result)")

        # A second, independent handle onto the same store writes first —
        # the deterministic form of the "another run persisted between this
        # run's read and its write" race (issue #92).
        second_driver = self.make_driver()
        self.addCleanup(second_driver.close)
        stolen = second_driver.execute("widget", "read", "w-v1")
        stolen["n"] = 1
        second_driver.persist("widget", "w-v1", stolen)

        first_read["n"] = first_read["n"] + 1
        with self.assertRaises(DriverError) as caught:
            self.driver.persist("widget", "w-v1", first_read)
        self.assertIn("conflict", str(caught.exception))
        # The write that landed first is what a re-read sees — the stale
        # attempt above never reached the row.
        self.assertEqual(
            self.driver.execute("widget", "read", "w-v1")["n"], 1)
