"""`lnpl relay --target`'s publisher SPI (issue #191, RFC-0053): a scheme
other than the built-in `http`/`https` is looked up in the `lnpl.publishers`
entry-points group — the same shape `test_cache_spi.py` proves for
`lnpl.caches` (issue #131).

Discovery (`importlib.metadata.entry_points(group=...)`) is monkeypatched to
a controlled, in-process set, same reasoning as `test_cache_spi.py`:
installing a second distribution just to prove group lookup works would need
a package this repo does not ship. `EntryPoint.load()` itself is never
mocked.
"""

import contextlib
import io
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import drivers as drivers_module
from lnpl.cli import _relay_drain_once_via_publisher
from lnpl.drivers import (PUBLISHERS, DriverError, EventPublisher,
                          PublishRejected, open_publisher)
from lnpl.testing import EventPublisherTCK

from tests.publisher_spi_fixture import DemoEventPublisher

GROUP = drivers_module.PUBLISHERS_ENTRY_POINT_GROUP


def entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=GROUP)


def registered(*entry_points):
    """A patcher for `drivers_module._publisher_entry_points`'s only
    external call — `importlib_metadata.entry_points(group=...)` —
    returning exactly `entry_points` regardless of what is installed."""
    return mock.patch.object(
        drivers_module.importlib_metadata, "entry_points",
        lambda **_kwargs: list(entry_points))


DEMO_ENTRY_POINT = entry_point(
    "demo", "tests.publisher_spi_fixture:make_demo_publisher")


class EventPublisherContractTest(unittest.TestCase):
    """Normal + boundary: `publish_batch`'s default loops in order and
    stops at the first raise -- the only concrete behavior the base
    contract itself provides."""

    def test_publish_batch_calls_publish_in_order(self):
        calls = []

        class _Recording(EventPublisher):
            def publish(self, envelope):
                calls.append(envelope["id"])

        _Recording().publish_batch([{"id": "e1"}, {"id": "e2"}])

        self.assertEqual(calls, ["e1", "e2"])

    def test_publish_batch_stops_at_the_first_raise(self):
        calls = []

        class _FailsOnSecond(EventPublisher):
            def publish(self, envelope):
                calls.append(envelope["id"])
                if envelope["id"] == "e1":
                    raise DriverError("boom")

        with self.assertRaises(DriverError):
            _FailsOnSecond().publish_batch(
                [{"id": "e1"}, {"id": "e2"}])

        self.assertEqual(calls, ["e1"])   # e2 never reached

    def test_publish_batch_of_nothing_publishes_nothing(self):
        calls = []

        class _Recording(EventPublisher):
            def publish(self, envelope):
                calls.append(envelope["id"])

        _Recording().publish_batch([])

        self.assertEqual(calls, [])

    def test_the_bare_contract_refuses_to_publish(self):
        with self.assertRaises(NotImplementedError):
            EventPublisher().publish({"id": "e1"})

    def test_a_permanent_rejection_is_a_driver_error(self):
        """`PublishRejected` must stay catchable as `DriverError` -- the
        relay's outer `except DriverError` is its one error type out."""
        self.assertTrue(issubclass(PublishRejected, DriverError))


class RegisteredSchemeTest(unittest.TestCase):
    """Normal: a fixture publisher registered under `lnpl.publishers` is
    caught by `--target demo://...` on registration alone."""

    def test_a_registered_scheme_is_caught_and_loads_the_driver(self):
        with registered(DEMO_ENTRY_POINT):
            driver = open_publisher("demo://broker:9092/topic")

        self.assertIsInstance(driver, DemoEventPublisher)

    def test_the_factory_receives_the_full_target_not_a_remainder(self):
        with registered(DEMO_ENTRY_POINT):
            driver = open_publisher("demo://broker:9092/topic")

        self.assertEqual(driver.target, "demo://broker:9092/topic")

    def test_the_scheme_match_is_case_insensitive(self):
        with registered(DEMO_ENTRY_POINT):
            driver = open_publisher("DEMO://broker/topic")

        self.assertIsInstance(driver, DemoEventPublisher)
        self.assertEqual(driver.target, "DEMO://broker/topic")

    def test_the_loaded_driver_behaves_like_a_publisher(self):
        with registered(DEMO_ENTRY_POINT):
            driver = open_publisher("demo://unused")

        driver.publish({"id": "outbox-1"})
        driver.close()

        self.assertEqual(driver.published, ["outbox-1"])
        self.assertTrue(driver.closed)


class UnregisteredSchemeTest(unittest.TestCase):
    """Error: a scheme neither built in nor registered is rejected, and the
    message names both closed-table halves so a typo is diagnosable —
    without ever echoing the target itself (it may carry userinfo)."""

    def test_names_the_scheme_and_the_built_in_set(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_publisher("nope://broker/x")

        message = str(caught.exception)
        self.assertIn("'nope'", message)
        for name in PUBLISHERS:
            self.assertIn(name, message)

    def test_names_the_registered_entry_point_scheme(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_publisher("nope://broker/x")

        self.assertIn("demo", str(caught.exception))

    def test_zero_registered_entry_points_says_none_rather_than_an_empty_list(self):
        with registered():
            with self.assertRaises(ValueError) as caught:
                open_publisher("nope://broker/x")

        self.assertIn("registered: none", str(caught.exception))

    def test_the_message_never_echoes_userinfo(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_publisher("nope://user:s3cr3t@host/x")

        message = str(caught.exception)
        self.assertNotIn("s3cr3t", message)
        self.assertNotIn("user:", message)

    def test_a_target_without_any_scheme_is_rejected_not_posted(self):
        """Boundary: an empty string has no scheme at all -- rejected as an
        unknown scheme, never routed to the http(s) path."""
        with registered():
            with self.assertRaises(ValueError) as caught:
                open_publisher("")

        self.assertIn("unknown publisher scheme ''", str(caught.exception))


class EntryPointLoadFailureTest(unittest.TestCase):
    """Error: a registered scheme whose entry-point fails to import is a
    driver fault (`DriverError`), not a traceback out of `open_publisher`."""

    def test_an_import_failure_becomes_a_driver_error(self):
        broken = entry_point(
            "broken", "tests.no_such_fixture_module_xyz:make_publisher")

        with registered(broken):
            with self.assertRaises(DriverError) as caught:
                open_publisher("broken://user:s3cr3t@host/x")

        self.assertIn("broken", str(caught.exception))
        self.assertNotIn("s3cr3t", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, ImportError)


class BuiltinShadowingTest(unittest.TestCase):
    """Boundary: http/https return None (the relay's own byte-identical
    urllib path), and a package registering either name can never shadow
    them — the built-in check runs before entry-points are consulted."""

    def test_open_publisher_returns_none_for_http_and_https(self):
        self.assertIsNone(open_publisher("http://x"))
        self.assertIsNone(open_publisher("https://x"))

    def test_an_upper_case_http_scheme_is_still_the_builtin(self):
        self.assertIsNone(open_publisher("HTTPS://x"))

    def test_a_same_named_entry_point_never_shadows_builtin_http(self):
        for name in PUBLISHERS:
            shadow = entry_point(
                name, "tests.publisher_spi_fixture:make_demo_publisher")
            with self.subTest(scheme=name), registered(shadow):
                self.assertIsNone(open_publisher("%s://x" % name))


class _RecordingOutbox:
    """Two outbox methods the glue calls, recording every ack call."""

    def __init__(self, rows):
        self.rows = rows
        self.ack_calls = []

    def drain_outbox(self):
        return [dict(r) for r in self.rows]

    def ack_outbox(self, seqs):
        self.ack_calls.append(list(seqs))


EVENT_NAMES = {"event.order.placed": "OrderPlaced"}


def _drain(repository, publisher):
    """-> (acked, stderr) for one `_relay_drain_once_via_publisher` call."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        acked = _relay_drain_once_via_publisher(
            repository, EVENT_NAMES, "orders", publisher)
    return acked, err.getvalue()


class DrainViaPublisherTest(unittest.TestCase):
    """The production glue's own branches, beyond what the TCK drives:
    the envelope it hands the publisher, the permanent-rejection
    dead-letter bucket, the unknown-event skip, and an empty outbox."""

    def test_the_envelope_is_the_cloudevents_shape_the_http_path_posts(self):
        seen = []

        class _Recording(EventPublisher):
            def publish(self, envelope):
                seen.append(envelope)

        repo = _RecordingOutbox([{"seq": 7, "event": "event.order.placed",
                                  "payload": {"amount": 5}}])

        acked, _err = _drain(repo, _Recording())

        self.assertEqual(acked, 1)
        self.assertEqual(seen, [{"specversion": "1.0", "id": "outbox-7",
                                 "source": "orders", "type": "OrderPlaced",
                                 "data": {"amount": 5}}])
        self.assertEqual(repo.ack_calls, [[7]])

    def test_a_permanent_rejection_is_acked_and_dead_lettered(self):
        class _Rejects(EventPublisher):
            def publish(self, envelope):
                raise PublishRejected("schema mismatch")

        repo = _RecordingOutbox([{"seq": 3, "event": "event.order.placed",
                                  "payload": {}}])

        acked, err = _drain(repo, _Rejects())

        self.assertEqual(acked, 1)
        self.assertEqual(repo.ack_calls, [[3]])
        self.assertIn("dead-letter", err)
        self.assertIn("seq=3", err)
        self.assertIn("schema mismatch", err)

    def test_a_transient_failure_is_left_unacked_and_reported(self):
        repo = _RecordingOutbox([{"seq": 4, "event": "event.order.placed",
                                  "payload": {}}])

        acked, err = _drain(repo, DemoEventPublisher(fail_ids={"outbox-4"}))

        self.assertEqual(acked, 0)
        self.assertEqual(repo.ack_calls, [])
        self.assertIn("seq=4", err)
        self.assertIn("left un-acked", err)

    def test_one_failure_does_not_stop_later_rows(self):
        repo = _RecordingOutbox([
            {"seq": 1, "event": "event.order.placed", "payload": {}},
            {"seq": 2, "event": "event.order.placed", "payload": {}}])
        publisher = DemoEventPublisher(fail_ids={"outbox-1"})

        acked, _err = _drain(repo, publisher)

        self.assertEqual(acked, 1)
        self.assertEqual(publisher.published, ["outbox-2"])
        self.assertEqual(repo.ack_calls, [[2]])

    def test_an_undeclared_event_id_is_skipped_and_left_unacked(self):
        repo = _RecordingOutbox([{"seq": 5, "event": "event.not.declared",
                                  "payload": {}}])
        publisher = DemoEventPublisher()

        acked, err = _drain(repo, publisher)

        self.assertEqual(acked, 0)
        self.assertEqual(publisher.published, [])
        self.assertEqual(repo.ack_calls, [])
        self.assertIn("event.not.declared", err)

    def test_an_empty_outbox_acks_nothing(self):
        repo = _RecordingOutbox([])

        acked, err = _drain(repo, DemoEventPublisher())

        self.assertEqual(acked, 0)
        self.assertEqual(repo.ack_calls, [])
        self.assertEqual(err, "")


class DemoPublisherPassesTheTCKTest(EventPublisherTCK, unittest.TestCase):
    """A publisher the core module did not construct still has to pass the
    same contract the relay relies on."""

    def make_publisher(self, fail_ids=frozenset()):
        return DemoEventPublisher(fail_ids=fail_ids)


def _run_one_tck_case(case_name):
    class _OneCase(EventPublisherTCK, unittest.TestCase):
        def make_publisher(self, fail_ids=frozenset()):
            return DemoEventPublisher(fail_ids=fail_ids)

    result = unittest.TestResult()
    _OneCase(case_name).run(result)
    return result


def _ack_before_publish_glue(repository, event_names, source, publisher):
    """Negative control: acks first, publishes second -- a crash
    between the two loses the event forever even though the row is
    marked delivered."""
    acked = []
    for emission in repository.drain_outbox():
        name = event_names.get(emission["event"])
        envelope = {"id": "outbox-%d" % emission["seq"], "type": name,
                    "source": source, "data": emission["payload"]}
        acked.append(emission["seq"])
        try:
            publisher.publish(envelope)
        except DriverError:
            pass
    if acked:
        repository.ack_outbox(acked)
    return len(acked)


def _drop_on_error_glue(repository, event_names, source, publisher):
    """Negative control: swallows a publish failure and acks anyway --
    a failed publish is silently dropped instead of retried."""
    acked = []
    for emission in repository.drain_outbox():
        name = event_names.get(emission["event"])
        envelope = {"id": "outbox-%d" % emission["seq"], "type": name,
                    "source": source, "data": emission["payload"]}
        try:
            publisher.publish(envelope)
        except DriverError:
            pass
        acked.append(emission["seq"])
    if acked:
        repository.ack_outbox(acked)
    return len(acked)


class EventPublisherTCKDiscriminatesTest(unittest.TestCase):
    """`harness-reverse-controls`: before trusting that the failure
    case catches a broken glue, prove it does -- against the real
    glue (pass) and two deliberately-broken ones (fail). `DRAIN_ONCE`
    is a `staticmethod` bound to the real function object at class-
    definition time, so the ONLY way to substitute a broken glue for
    one TCK run is to patch the class attribute itself
    (`mock.patch.object(EventPublisherTCK, "DRAIN_ONCE", ...)`) --
    patching the module-level name `lnpl.testing._relay_drain_once_via_publisher`
    has no effect on an already-bound staticmethod."""

    CASE = "test_failure_leaves_the_row_unacked"

    def test_the_case_passes_against_the_real_glue(self):
        result = _run_one_tck_case(self.CASE)

        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures) + len(result.errors), 0)

    def test_the_case_fails_against_an_ack_before_publish_glue(self):
        with mock.patch.object(EventPublisherTCK, "DRAIN_ONCE",
                               staticmethod(_ack_before_publish_glue)):
            result = _run_one_tck_case(self.CASE)

        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures) + len(result.errors), 1)

    def test_the_case_fails_against_a_drop_on_error_glue(self):
        with mock.patch.object(EventPublisherTCK, "DRAIN_ONCE",
                               staticmethod(_drop_on_error_glue)):
            result = _run_one_tck_case(self.CASE)

        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures) + len(result.errors), 1)


if __name__ == "__main__":
    unittest.main()
