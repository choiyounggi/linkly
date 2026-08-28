"""Technology Compatibility Kits: `RepositoryDriver` (issue #75) and
`TokenProvider` (issue #119b), below.

`docs/backends.md` §5 has said since #25 that a real `postgres`/`redis`
binding is an external package's job, not the core's — no DB dependency
lands here. What the core owns instead is the *contract* those packages
must satisfy, and a runnable proof of it: the same idea as a JDBC TCK,
which ships with the JDBC spec so any vendor's driver can be checked
against one suite rather than each vendor asserting its own conformance.
`TokenProviderTCK` (issue #119b, D1/D5) applies the same idea to
`lnpl.tokens` SPI providers — see its own docstring below for the parts
specific to tokens (the foreign-issuer hook, the D6 assertion list).

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

`begin`/`commit`/`rollback` (issue #79, RFC-0032) mark a transaction boundary
spanning one workflow execution. RFC-0032 raised `policy rollback` to
**enforced**: one workflow execution is one implicit transaction, and a
failed run's writes must not survive it. This TCK asserts that directly —
`rollback` must discard both the row writes and the outbox registrations
made since the matching `begin`, and a second `begin` before the first is
closed must be refused. A driver that answers `rollback` with a no-op
(callable but inert) now fails these cases; it is no longer enough for the
three to be merely callable without raising.

The optimistic-version conflict (issue #92) is likewise not a required
capability of every driver — the base contract's `execute`/`persist` never
mention a version at all. A driver opts in by returning a read result that
carries an `observed_version` attribute (`SqliteRepositoryDriver`'s
`_VersionedRow` is the reference shape); this TCK detects that opt-in and
skips the conflict test for a driver that does not offer it, the same way a
JDBC TCK's optional-feature tests skip against a driver that reports the
feature unsupported.
"""

import base64
import json

from lnpl.drivers import DriverError, TokenError


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

    # -- query with predicate/order/limit (issue #116, D5/D6/D10) -----------
    #
    # Optional, the same way the optimistic-version conflict above is: a
    # driver opts in by setting `supports_predicate = True` (`RepositoryDriver`'s
    # own docstring); one that has not is never called this way by
    # `interp.Interpreter` (it falls back to a plain `query(entity_id)`,
    # filtered in Python instead), so there is nothing here for it to satisfy.

    def _skip_unless_predicate_supported(self):
        if not getattr(self.driver, "supports_predicate", False):
            self.skipTest(
                "driver does not declare supports_predicate — "
                "query()'s predicate/order/limit are never pushed down to it")

    def test_query_without_predicate_order_or_limit_is_the_pre_116_call(self):
        """The regression case every driver must keep true regardless of
        `supports_predicate`: three `None`s behaves exactly like the old
        one-argument `query(entity_id)`."""
        self.driver.seed({"widget": {"w1": {"id": "w1", "n": 1}}})

        self.assertEqual(
            self.driver.query("widget", predicate=None, order=None, limit=None),
            self.driver.query("widget"))

    def test_predicate_filters_rows(self):
        self._skip_unless_predicate_supported()
        self.driver.seed({"widget": {
            "w1": {"id": "w1", "n": 1}, "w2": {"id": "w2", "n": 2},
        }})

        rows = self.driver.query("widget", predicate=[("n", ">", 1)])

        self.assertEqual([row["id"] for row in rows], ["w2"])

    def test_predicate_matching_no_row_is_an_empty_list(self):
        self._skip_unless_predicate_supported()
        self.driver.seed({"widget": {"w1": {"id": "w1", "n": 1}}})

        self.assertEqual(
            self.driver.query("widget", predicate=[("n", ">", 100)]), [])

    def test_predicate_conjunction_requires_every_term(self):
        self._skip_unless_predicate_supported()
        self.driver.seed({"widget": {
            "w1": {"id": "w1", "n": 5}, "w2": {"id": "w2", "n": 15},
            "w3": {"id": "w3", "n": 25},
        }})

        rows = self.driver.query(
            "widget", predicate=[("n", ">", 10), ("n", "<", 20)])

        self.assertEqual([row["id"] for row in rows], ["w2"])

    def test_predicate_equality_on_a_text_value(self):
        """D2's motivating case: equality pushed down for a non-numeric
        field, not just Integer/DateTime."""
        self._skip_unless_predicate_supported()
        self.driver.seed({"widget": {
            "w1": {"id": "w1", "status": "open"},
            "w2": {"id": "w2", "status": "closed"},
        }})

        rows = self.driver.query("widget", predicate=[("status", "==", "open")])

        self.assertEqual([row["id"] for row in rows], ["w1"])

    def test_order_ascending_and_descending(self):
        self._skip_unless_predicate_supported()
        self.driver.seed({"widget": {
            "w1": {"id": "w1", "n": 30}, "w2": {"id": "w2", "n": 10},
            "w3": {"id": "w3", "n": 20},
        }})

        asc = self.driver.query("widget", order=("n", False))
        desc = self.driver.query("widget", order=("n", True))

        self.assertEqual([row["id"] for row in asc], ["w2", "w3", "w1"])
        self.assertEqual([row["id"] for row in desc], ["w1", "w3", "w2"])

    def test_limit_caps_the_result(self):
        self._skip_unless_predicate_supported()
        self.driver.seed({"widget": {
            "w1": {"id": "w1", "n": 1}, "w2": {"id": "w2", "n": 2},
            "w3": {"id": "w3", "n": 3},
        }})

        rows = self.driver.query("widget", order=("n", False), limit=2)

        self.assertEqual([row["id"] for row in rows], ["w1", "w2"])

    def test_predicate_order_and_limit_compose(self):
        self._skip_unless_predicate_supported()
        self.driver.seed({"widget": {
            "w1": {"id": "w1", "n": 5}, "w2": {"id": "w2", "n": 30},
            "w3": {"id": "w3", "n": 20}, "w4": {"id": "w4", "n": 10},
        }})

        rows = self.driver.query("widget", predicate=[("n", ">", 5)],
                                 order=("n", True), limit=2)

        self.assertEqual([row["id"] for row in rows], ["w2", "w3"])

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

    def test_rollback_discards_writes_made_inside_the_transaction(self):
        self.driver.begin()
        self.driver.execute("widget", "create", "w-tx-rollback")

        self.driver.rollback()

        self.assertIsNone(
            self.driver.execute("widget", "read", "w-tx-rollback"))

    def test_rollback_discards_the_outbox_registration_made_with_it(self):
        self.driver.begin()
        self.driver.execute("widget", "create", "w-tx-outbox")
        self.driver.record_emission({
            "emission_id": "tx-outbox-1",
            "event": "widget.created",
            "payload": {"id": "w-tx-outbox"},
        })
        if self.driver.read_outbox("widget.created") == []:
            self.skipTest(
                "driver does not implement the outbox (record_emission "
                "left nothing to read back)")
        # reached here => there really was something for rollback to undo

        self.driver.rollback()

        self.assertIsNone(
            self.driver.execute("widget", "read", "w-tx-outbox"))
        self.assertEqual(self.driver.read_outbox("widget.created"), [])

    def test_a_nested_begin_is_refused(self):
        self.driver.begin()

        with self.assertRaises(DriverError):
            self.driver.begin()

        self.driver.rollback()

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


class CacheDriverTCK:
    """Mix into a `unittest.TestCase` subclass, override `make_cache()` and
    `advance(ms)` — see `CacheDriver`'s docstring (`lnpl.drivers`) for what
    every implementation must agree on regardless of how it judges TTL
    (clock comparison vs. the store's own native expiry).

    `advance(ms)` moves time forward for TTL purposes: a fake driver ticks
    its own injected clock, a real store waits (`time.sleep`) — the same
    per-driver hook shape `RepositoryDriverTCK.make_driver()` uses for the
    thing each driver must supply itself.
    """

    def make_cache(self):
        raise NotImplementedError(
            "CacheDriverTCK subclasses must override make_cache() to "
            "return a fresh CacheDriver")

    def advance(self, ms):
        raise NotImplementedError(
            "CacheDriverTCK subclasses must override advance(ms) to move "
            "this driver's notion of time forward by ms")

    def setUp(self):
        self.cache = self.make_cache()
        self.addCleanup(self.cache.close)

    def test_a_set_value_is_then_gettable(self):
        self.cache.set("k1", {"n": 1}, ttl_ms=60_000)

        self.assertEqual(self.cache.get("k1"), {"n": 1})

    def test_an_absent_key_returns_none_not_an_exception(self):
        self.assertIsNone(self.cache.get("no-such-key"))

    def test_ttl_expiry_returns_none_after_advancing_past_it(self):
        self.cache.set("k2", "v", ttl_ms=10)

        self.advance(20)

        self.assertIsNone(self.cache.get("k2"))

    def test_ttl_ms_zero_expires_immediately(self):
        self.cache.set("k3", "v", ttl_ms=0)

        self.assertIsNone(self.cache.get("k3"))

    def test_an_empty_value_round_trips(self):
        self.cache.set("k4", "", ttl_ms=60_000)

        self.assertEqual(self.cache.get("k4"), "")

    def test_overwriting_the_same_key_replaces_the_value(self):
        self.cache.set("k5", "first", ttl_ms=60_000)
        self.cache.set("k5", "second", ttl_ms=60_000)

        self.assertEqual(self.cache.get("k5"), "second")

    def test_invalidate_removes_the_key(self):
        self.cache.set("k6", "v", ttl_ms=60_000)

        self.cache.invalidate("k6")

        self.assertIsNone(self.cache.get("k6"))


NETWORK_TCK_TARGET = "TckTarget"


class NetworkDriverTCK:
    """`NetworkDriver` Technology Compatibility Kit (issue #109) — the
    `RepositoryDriverTCK` idiom applied to `capability http`'s resilience
    contract: methods, retry, breaker, response headers, timeout, checked
    once against both `FakeNetworkDriver` and `HttpNetworkDriver` so neither
    can quietly drift from what the other does with the same declaration.

    Mix into a `unittest.TestCase` subclass, override `make_driver()` (and
    `make_slow_driver()` if this driver kind can time out — see below)::

        import unittest
        from lnpl.testing import NetworkDriverTCK

        class MyDriverTCKTest(NetworkDriverTCK, unittest.TestCase):
            def make_driver(self, target, capabilities, script):
                return MyNetworkDriver(...)

    Unlike `RepositoryDriverTCK`'s zero-argument `make_driver()`, this one
    takes the scenario itself: `target` (always `NETWORK_TCK_TARGET`),
    `capabilities` (this target's resolved capabilities entry — `method`
    plus, per test, `retry`/`breaker`), and `script` — a list of `(status,
    body)`/`(status, body, headers)` tuples, one per transport ATTEMPT, in
    order, holding on the last once exhausted (`FakeNetworkDriver`'s own
    list-stub convention). `NetworkDriver`'s two implementations are not
    symmetric in what holds their state: `FakeNetworkDriver` takes the
    script as a constructor dict, while `HttpNetworkDriver`'s "script" is a
    real server the subclass must stand up — passing the scenario in lets
    each subclass answer only the question it alone can (how THIS driver
    kind gets told to answer this way), the same reason
    `SqliteDriverTCKTest.make_driver()` opens a real file `RepositoryDriverTCK`
    never mentions.

    Every test constructs `sleep`/`rand` such that a scripted retry never
    actually waits — `make_driver()` implementations should thread through a
    no-op `sleep` (both drivers accept one) so the TCK stays fast regardless
    of the `backoff_ms` a scenario declares.

    `make_slow_driver(target, capabilities, delay_s)` is optional — return
    `None` (the default) for a driver kind that performs no real I/O and so
    cannot time out (`FakeNetworkDriver`); the timeout test then skips, the
    same "opt-in capability" shape `RepositoryDriverTCK`'s optimistic-version
    test uses (`hasattr(first_read, "observed_version")`) for a capability
    only some drivers offer.
    """

    def make_driver(self, target, capabilities, script):
        raise NotImplementedError(
            "NetworkDriverTCK subclasses must override make_driver(target, "
            "capabilities, script) to return a fresh NetworkDriver wired to "
            "answer `target` with `script`, one entry per attempt")

    def make_slow_driver(self, target, capabilities, delay_s):
        return None

    # -- methods -----------------------------------------------------------

    def test_get_reaches_the_wire_and_returns_the_scripted_response(self):
        driver = self.make_driver(NETWORK_TCK_TARGET, {"method": "GET"},
                                  [(200, {"ok": True})])
        self.addCleanup(driver.close)

        status, body, _headers = driver.call(NETWORK_TCK_TARGET, {}, 2000)

        self.assertEqual((status, body), (200, {"ok": True}))

    def test_put_patch_delete_each_reach_the_wire(self):
        for method in ("PUT", "PATCH", "DELETE"):
            driver = self.make_driver(NETWORK_TCK_TARGET, {"method": method},
                                      [(200, {})])
            self.addCleanup(driver.close)

            status, _body, _headers = driver.call(NETWORK_TCK_TARGET,
                                                   {"x": 1}, 2000)

            self.assertEqual(status, 200)

    # -- retry (issue #109, D1/D2) ------------------------------------------

    def test_no_retry_declared_makes_exactly_one_attempt(self):
        """The declared-not-bound default: a target the capability's `retry`
        clause never mentions gets exactly one attempt, even against a
        retryable status — the pre-#109, RFC-0027 behaviour."""
        driver = self.make_driver(NETWORK_TCK_TARGET, {"method": "POST"},
                                  [(500, {}), (200, {"should": "not reach"})])
        self.addCleanup(driver.close)

        status, body, _headers = driver.call(NETWORK_TCK_TARGET, {}, 2000)

        self.assertEqual((status, body), (500, {}))

    def test_retry_recovers_across_a_failing_then_succeeding_sequence(self):
        driver = self.make_driver(
            NETWORK_TCK_TARGET,
            {"method": "POST",
             "retry": {"count": 2, "backoff_ms": 1, "jitter": False}},
            [(500, {}), (200, {"ok": True})])
        self.addCleanup(driver.close)

        status, body, _headers = driver.call(NETWORK_TCK_TARGET, {}, 2000)

        self.assertEqual((status, body), (200, {"ok": True}))

    def test_a_non_retryable_4xx_is_not_retried_even_with_retry_declared(self):
        driver = self.make_driver(
            NETWORK_TCK_TARGET,
            {"method": "POST",
             "retry": {"count": 3, "backoff_ms": 1, "jitter": False}},
            [(404, {}), (200, {"should": "not reach"})])
        self.addCleanup(driver.close)

        status, body, _headers = driver.call(NETWORK_TCK_TARGET, {}, 2000)

        self.assertEqual((status, body), (404, {}))

    # -- breaker (issue #109, D5) --------------------------------------------

    def test_breaker_opens_after_the_threshold_and_rejects_without_a_response(self):
        driver = self.make_driver(
            NETWORK_TCK_TARGET,
            {"method": "POST", "breaker": {"threshold": 2, "window_ms": 60_000}},
            [(500, {})])
        self.addCleanup(driver.close)

        first = driver.call(NETWORK_TCK_TARGET, {}, 2000)
        second = driver.call(NETWORK_TCK_TARGET, {}, 2000)

        self.assertEqual(first[0], 500)
        self.assertEqual(second[0], 500)
        with self.assertRaises(DriverError) as caught:
            driver.call(NETWORK_TCK_TARGET, {}, 2000)
        self.assertIn("breaker-open", str(caught.exception))

    def test_no_breaker_declared_never_rejects_on_its_own(self):
        driver = self.make_driver(NETWORK_TCK_TARGET, {"method": "POST"},
                                  [(500, {})])
        self.addCleanup(driver.close)

        for _ in range(5):
            status, _body, _headers = driver.call(NETWORK_TCK_TARGET, {}, 2000)
            self.assertEqual(status, 500)

    # -- response headers (issue #109, D7) -----------------------------------

    def test_response_headers_reach_the_caller_lower_cased(self):
        driver = self.make_driver(
            NETWORK_TCK_TARGET, {"method": "GET"},
            [(200, {}, {"x-request-id": "abc123"})])
        self.addCleanup(driver.close)

        _status, _body, headers = driver.call(NETWORK_TCK_TARGET, {}, 2000)

        self.assertEqual(headers.get("x-request-id"), "abc123")

    def test_headers_still_bind_for_a_non_2xx_response(self):
        """The status/body/headers triple binds in full even when the
        status is not 2xx (RFC-0027 §1: a response was received, that is a
        value, not a fault) — `test_response_headers_reach_the_caller_
        lower_cased` above only pins this for a 200, so a driver that
        special-cased headers to 2xx responses only would pass that test
        and still be wrong."""
        driver = self.make_driver(
            NETWORK_TCK_TARGET, {"method": "GET"},
            [(500, {"error": "boom"}, {"retry-after": "5"})])
        self.addCleanup(driver.close)

        status, body, headers = driver.call(NETWORK_TCK_TARGET, {}, 2000)

        self.assertEqual(status, 500)
        self.assertEqual(body, {"error": "boom"})
        self.assertEqual(headers.get("retry-after"), "5")

    # -- response body -------------------------------------------------------

    def test_an_empty_response_body_round_trips(self):
        """A body of `{}` is a value (RFC-0027 §1's "empty RowSet is a valid
        binding" idea, applied to a response body) — it must reach the
        caller as `{}`, not `None` or a driver-side default substitution."""
        driver = self.make_driver(NETWORK_TCK_TARGET, {"method": "GET"},
                                  [(200, {})])
        self.addCleanup(driver.close)

        _status, body, _headers = driver.call(NETWORK_TCK_TARGET, {}, 2000)

        self.assertEqual(body, {})

    # -- timeout (opt-in — see make_slow_driver's docstring note above) -----

    def test_a_response_slower_than_the_timeout_raises_driver_error(self):
        driver = self.make_slow_driver(NETWORK_TCK_TARGET, {"method": "GET"},
                                       delay_s=1.0)
        if driver is None:
            self.skipTest("this driver kind performs no real I/O and so "
                          "cannot time out")
        self.addCleanup(driver.close)

        with self.assertRaises(DriverError):
            driver.call(NETWORK_TCK_TARGET, {}, timeout_ms=50)


def _b64u_json(obj):
    """A compact-JWS header/claims segment: JSON, then unpadded base64url —
    the same encoding `HmacTokenProvider._sign`'s callers use, reproduced here
    so `TokenProviderTCK` can forge a segment without importing anything
    HMAC-specific (the forged segments below are never signed with a key)."""
    return base64.urlsafe_b64encode(
        json.dumps(obj).encode("utf-8")).rstrip(b"=").decode("ascii")


class TokenProviderTCK:
    """`TokenProvider` Technology Compatibility Kit (issue #119b).

    Same idiom as `RepositoryDriverTCK` above: a pure mixin, never inherit
    `unittest.TestCase` directly here — combine the two in the concrete
    subclass, override `make_provider()` and `make_foreign_issuer_provider()`::

        import unittest
        from lnpl.testing import TokenProviderTCK

        class MyProviderTCKTest(TokenProviderTCK, unittest.TestCase):
            def make_provider(self):
                return MyTokenProvider(...)

            def make_foreign_issuer_provider(self):
                return MyTokenProvider(..., issuer="somebody-else")

    `make_provider()` returns the instance under test: `self.provider.verify`
    is what every case below calls. `make_foreign_issuer_provider()` returns
    a second, otherwise-equivalent instance (same signing key/material) that
    issues genuinely-signed tokens under a DIFFERENT `iss` — the only way to
    exercise "a foreign issuer is rejected" (D6 item 4) without the TCK
    forging a signature it cannot produce for an unknown algorithm; every
    other forged-token case here corrupts bytes or reuses a claims segment
    verbatim, which needs no key at all.

    D6's closed list of seven assertions (issue #119b): (1) a valid token
    verifies and returns its claims, (2) a forged signature is rejected, (3)
    `alg: none` is rejected, (4) a foreign issuer is rejected, (5) an
    audience mismatch is rejected, (6) an expired token is rejected, (7) an
    algorithm outside the provider's allowlist is rejected. Items 3 and 7 are
    the ones the module docstring on `drivers.py`'s `ACCEPTED_ALGS` names
    directly: letting a token pick its own algorithm is what `alg: none` and
    the RS256-public-key-as-HMAC-secret confusion both exploit, so a
    conformant provider must never let the token's own header decide which
    key or algorithm verifies it.

    `issue()`'s `ttl_ms` is assumed to honor negative values as "already
    expired" (`HmacTokenProvider` does; `test_token_provider.py`'s
    `test_a_zero_lifetime_token_expires_at_once...` pins the zero case) — the
    expired-token case here relies on that rather than sleeping or forging a
    past `exp` by hand, which would need the same unavailable-signature
    workaround the alg cases below avoid.

    issue #115's lesson governs how this TCK earns trust: it is only
    published alongside a positive control (`HmacTokenProviderTCKTest`,
    `impl/tests/test_token_contract.py`) AND a negative control
    (`_NoSignatureCheckProvider` in the same file, run through the forged-
    signature case alone and asserted to FAIL it) — a TCK nobody has shown
    can fail has unmeasured discriminating power.
    """

    AUDIENCE = "tck-audience"
    SUBJECT = "tck-subject"

    def make_provider(self):
        raise NotImplementedError(
            "TokenProviderTCK subclasses must override make_provider() to "
            "return a fresh TokenProvider that verifies its own tokens")

    def make_foreign_issuer_provider(self):
        raise NotImplementedError(
            "TokenProviderTCK subclasses must override "
            "make_foreign_issuer_provider() to return a second TokenProvider "
            "built from the same signing material as make_provider(), "
            "configured with a different issuer")

    def setUp(self):
        self.provider = self.make_provider()

    # -- D6 (1): a valid token verifies and returns its claims --------------

    def test_a_valid_token_verifies_and_returns_its_claims(self):
        token = self.provider.issue(self.SUBJECT, self.AUDIENCE)

        claims = self.provider.verify(token, self.AUDIENCE)

        self.assertEqual(claims["sub"], self.SUBJECT)
        self.assertEqual(claims["aud"], self.AUDIENCE)

    # -- D6 (2): a forged signature is rejected ------------------------------

    def test_a_forged_signature_is_rejected(self):
        token = self.provider.issue(self.SUBJECT, self.AUDIENCE)
        header, claims, signature = token.split(".")
        flipped = ("A" if signature[:1] != "A" else "B") + signature[1:]

        with self.assertRaises(TokenError):
            self.provider.verify(".".join([header, claims, flipped]),
                                 self.AUDIENCE)

    # -- D6 (3): `alg: none` is rejected --------------------------------------

    def test_alg_none_is_rejected(self):
        """The attack the allowlist exists for: no algorithm, no signature —
        an attacker asking the verifier to trust the claims outright."""
        token = self.provider.issue(self.SUBJECT, self.AUDIENCE)
        _, claims, _ = token.split(".")
        forged = "%s.%s." % (_b64u_json({"alg": "none", "typ": "JWT"}), claims)

        with self.assertRaises(TokenError):
            self.provider.verify(forged, self.AUDIENCE)

    # -- D6 (4): a foreign issuer is rejected --------------------------------

    def test_a_foreign_issuer_is_rejected(self):
        foreign = self.make_foreign_issuer_provider()
        token = foreign.issue(self.SUBJECT, self.AUDIENCE)

        with self.assertRaises(TokenError):
            self.provider.verify(token, self.AUDIENCE)

    # -- D6 (5): an audience mismatch is rejected ----------------------------

    def test_an_audience_mismatch_is_rejected(self):
        token = self.provider.issue(self.SUBJECT, self.AUDIENCE)

        with self.assertRaises(TokenError):
            self.provider.verify(token, self.AUDIENCE + "-someone-else")

    # -- D6 (6): an expired token is rejected --------------------------------

    def test_an_expired_token_is_rejected(self):
        token = self.provider.issue(self.SUBJECT, self.AUDIENCE,
                                    ttl_ms=-3600 * 1000)

        with self.assertRaises(TokenError):
            self.provider.verify(token, self.AUDIENCE)

    # -- D6 (7): an algorithm outside the allowlist is rejected --------------

    def test_an_algorithm_outside_the_allowlist_is_rejected(self):
        """The RS256-public-key-as-HMAC-secret confusion and every other
        alg-substitution attack live here: the token names an algorithm the
        provider never agreed to accept."""
        token = self.provider.issue(self.SUBJECT, self.AUDIENCE)
        _, claims, _ = token.split(".")
        forged = "%s.%s." % (
            _b64u_json({"alg": "XX9999-not-a-real-algorithm", "typ": "JWT"}),
            claims)

        with self.assertRaises(TokenError):
            self.provider.verify(forged, self.AUDIENCE)

    # -- boundary: a malformed token is rejected, not a crash ----------------

    def test_a_non_compact_jws_string_is_rejected_not_crashed(self):
        with self.assertRaises(TokenError):
            self.provider.verify("not-a-token", self.AUDIENCE)

    def test_an_empty_token_is_rejected_not_crashed(self):
        with self.assertRaises(TokenError):
            self.provider.verify("", self.AUDIENCE)
