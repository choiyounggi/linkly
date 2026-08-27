"""Issue #109 — `NetworkDriverTCK` run against both `NetworkDriver`
implementations. Structural parity is the point: the same declaration
(method/retry/breaker) must be graded identically whether the target is
`FakeNetworkDriver`'s in-memory script or `HttpNetworkDriver`'s real socket.

The last class is a negative control (`testing/quality/harness-reverse-
controls`, mirrored from `test_driver_contract.py`'s `RollbackTCKDiscriminatesTest`):
proof the TCK actually discriminates, by running one of its own cases
against a driver that deliberately ignores `retry`.
"""

import unittest

from lnpl.drivers import DriverError, FakeNetworkDriver, HttpNetworkDriver
from lnpl.testing import NETWORK_TCK_TARGET, NetworkDriverTCK

from tests.test_network_driver import (_ServerTestCase, _make_handler,
                                       _make_scripted_handler)


class FakeNetworkDriverTCKTest(NetworkDriverTCK, unittest.TestCase):

    def make_driver(self, target, capabilities, script):
        return FakeNetworkDriver(stubs={target: list(script)},
                                 capabilities={target: capabilities},
                                 sleep=lambda seconds: None)

    # `FakeNetworkDriver` performs no real I/O — `make_slow_driver`'s default
    # (`None`) stands, so the timeout test skips for this driver kind.


class HttpNetworkDriverTCKTest(NetworkDriverTCK, _ServerTestCase):

    def make_driver(self, target, capabilities, script):
        url = self.start(_make_scripted_handler(list(script)))
        driver = HttpNetworkDriver(endpoints={target: url},
                                   capabilities={target: capabilities},
                                   sleep=lambda seconds: None)
        return driver

    def make_slow_driver(self, target, capabilities, delay_s):
        url = self.start(_make_handler(status=200, body={}, delay_s=delay_s))
        return HttpNetworkDriver(endpoints={target: url},
                                 capabilities={target: capabilities},
                                 sleep=lambda seconds: None)


class _IgnoresRetryDriver(FakeNetworkDriver):
    """Negative control: a driver that always makes exactly one attempt,
    `retry` declaration or not — the exact shape issue #109's D2 forbids.
    `NetworkDriverTCK`'s retry-recovery case must fail against this driver;
    if it did not, the TCK would be checking nothing about retry at all."""

    def call(self, target, payload, timeout_ms, trace_headers=None,
             path_args=None):
        stub = self.stubs.get(target, (200, {}))
        item = stub[0] if isinstance(stub, list) else stub
        self.received.append({"target": target, "payload": payload,
                              "trace_headers": dict(trace_headers or {}),
                              "path": None})
        return item if len(item) == 3 else (*item, {})


def _run_one_tck_case(driver_factory, case_name):
    class _OneCase(NetworkDriverTCK, unittest.TestCase):
        def make_driver(self, target, capabilities, script):
            return driver_factory(target, capabilities, script)

    result = unittest.TestResult()
    _OneCase(case_name).run(result)
    return result


class RetryTCKDiscriminatesTest(unittest.TestCase):

    def test_the_retry_recovery_case_fails_against_a_driver_that_never_retries(self):
        def factory(target, capabilities, script):
            return _IgnoresRetryDriver(stubs={target: list(script)},
                                       capabilities={target: capabilities})

        result = _run_one_tck_case(
            factory, "test_retry_recovers_across_a_failing_then_succeeding_sequence")

        self.assertFalse(result.wasSuccessful())

    def test_the_no_retry_declared_case_still_passes_against_it(self):
        """Sanity: the negative-control driver is not simply broken outright
        — it correctly handles the *other* half of the contract (no
        declaration -> one attempt), so the failure above is specifically
        about retry, not about the fixture being unusable."""
        def factory(target, capabilities, script):
            return _IgnoresRetryDriver(stubs={target: list(script)},
                                       capabilities={target: capabilities})

        result = _run_one_tck_case(
            factory, "test_no_retry_declared_makes_exactly_one_attempt")

        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)


if __name__ == "__main__":
    unittest.main()
