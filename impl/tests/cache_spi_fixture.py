"""A minimal `CacheDriver` used only to prove the `lnpl.caches` entry-points
discovery path works end-to-end (issue #131) — registration wiring, not
backend correctness. `driver_spi_fixture.py` is the `lnpl.drivers` precedent
this mirrors.

`make_demo_cache` is the callable an entry-point's `value` names (the shape
`--cache demo:<arg>` needs): `EntryPoint(name="demo",
value="tests.cache_spi_fixture:make_demo_cache", group="lnpl.caches")`.
TTL here is judged by comparison against this fixture's own tiny counter, not
`interp.Clock` — keeping this fixture driver-only, without importing `interp`
(out of scope here, see `driver_spi_fixture.py`'s module docstring for why the
TCK stays driver-only, same reasoning).
"""

from lnpl.drivers import CacheDriver


class DemoCacheDriver(CacheDriver):
    """In-memory, keyed the same way `interp.FakeCache` is — just without
    importing `interp`. `advance(ms)` is a fixture-only hook `CacheDriverTCK`
    calls to move this driver's own counter forward for TTL tests."""

    def __init__(self, arg=None):
        self.arg = arg
        self.store = {}   # key -> (value, expires_at)
        self.now = 0

    def advance(self, ms):
        self.now += ms

    def get(self, key):
        entry = self.store.get(key)
        if entry is None or entry[1] <= self.now:
            return None
        return entry[0]

    def set(self, key, value, ttl_ms):
        self.store[key] = (value, self.now + ttl_ms)

    def invalidate(self, key):
        self.store.pop(key, None)

    def close(self):
        pass


def make_demo_cache(arg=None):
    return DemoCacheDriver(arg)
