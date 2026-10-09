"""A minimal `SecretProvider` used only to prove the `lnpl.secrets`
entry-points discovery path works end-to-end (issue #192) — registration
wiring, not vault correctness. `publisher_spi_fixture.py` is the
`lnpl.publishers` precedent this mirrors.

`make_demo_secret_provider` is the callable an entry-point's `value` names:
`EntryPoint(name="demo",
value="tests.secret_spi_fixture:make_demo_secret_provider",
group="lnpl.secrets")`. Like `lnpl.tokens`, the factory takes no arguments —
the `key` arrives per `get` call.

Every factory appends the instance it builds to `INSTANCES`, so a test that
went through `open_secret_provider` reaches the live object as
`INSTANCES[-1]` (clear the list in `setUp`). Every value here is synthetic
and carries the `FAKE-SECRET-192` marker, so a leak check can grep for it.
"""

from lnpl.drivers import DriverError, SecretProvider

DEMO_SECRET_K0 = b"FAKE-SECRET-192-k0-" + b"a" * 21
DEMO_SECRET_K1 = b"FAKE-SECRET-192-k1-" + b"b" * 21
DEMO_SECRET_K2 = b"FAKE-SECRET-192-k2-" + b"c" * 21

INSTANCES = []


class DemoSecretProvider(SecretProvider):
    """In-memory, stateful: `values` holds the current bytes per key,
    `previous` the value each key held before its last `rotate`. Setting
    `fail` (mutable after construction) makes `get`/`get_previous` raise
    `DriverError` until it is cleared; `raise_with` makes `get` raise that
    exception object instead (a driver that breaks the failure contract).
    `get_calls`/`close_calls` count calls, so a test can prove a re-read
    or a shutdown happened."""

    def __init__(self, values=None, raise_with=None):
        self.values = dict(values or {})
        self.previous = {}
        self.fail = False
        self.raise_with = raise_with
        self.get_calls = 0
        self.close_calls = 0

    def rotate(self, key, new_value):
        """Test-only: `new_value` becomes current, the old current becomes
        previous (only one previous is kept)."""
        if key in self.values:
            self.previous[key] = self.values[key]
        self.values[key] = new_value

    def get(self, key):
        self.get_calls += 1
        if self.raise_with is not None:
            raise self.raise_with
        self._check(key)
        return self.values[key]

    def get_previous(self, key):
        self._check(key)
        return self.previous.get(key)

    def close(self):
        self.close_calls += 1

    def _check(self, key):
        if self.fail:
            raise DriverError("demo secret provider is failing")
        if key not in self.values:
            raise DriverError("demo secret provider has no such key")


def make_demo_secret_provider():
    provider = DemoSecretProvider({"jwt": DEMO_SECRET_K0})
    INSTANCES.append(provider)
    return provider


def make_raising_secret_provider():
    provider = DemoSecretProvider(
        {"jwt": DEMO_SECRET_K0},
        raise_with=RuntimeError("demo backend error FAKE-SECRET-192-CAUSE-"
                                + "z" * 16))
    INSTANCES.append(provider)
    return provider


def make_short_secret_provider():
    provider = DemoSecretProvider({"jwt": b"FAKE-SECRET-192-short"})
    INSTANCES.append(provider)
    return provider


def make_broken_factory():
    raise RuntimeError("factory failed FAKE-SECRET-192-FACTORY")
