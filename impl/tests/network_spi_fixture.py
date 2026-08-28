"""A minimal `NetworkDriver` used only to prove the `lnpl.networks`
entry-points discovery path works end-to-end (issue #132) — registration
wiring, not backend correctness. `driver_spi_fixture.py` is the
`lnpl.drivers` precedent this mirrors.

`make_demo_network` is the callable an entry-point's `value` names (the
shape `--network demo:<arg>` needs): `EntryPoint(name="demo",
value="tests.network_spi_fixture:make_demo_network", group="lnpl.networks")`.
"""

from lnpl.drivers import NetworkDriver


class DemoNetworkDriver(NetworkDriver):
    """Deterministic, no I/O — just enough to prove the SPI reaches a real
    driver instance with the right arg, the same reasoning
    `driver_spi_fixture.py`'s module docstring gives for staying minimal."""

    def __init__(self, arg=None):
        self.arg = arg
        self.received = []

    def call(self, target, payload, timeout_ms, trace_headers=None,
             path_args=None):
        self.received.append(target)
        return 200, {"target": target}, {}

    def close(self):
        pass


def make_demo_network(arg=None):
    return DemoNetworkDriver(arg)
