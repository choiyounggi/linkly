"""A minimal `EventPublisher` used only to prove the `lnpl.publishers`
entry-points discovery path works end-to-end (issue #191, RFC-0053) —
registration wiring, not broker correctness. `cache_spi_fixture.py` is the
`lnpl.caches` precedent this mirrors.

`make_demo_publisher` is the callable an entry-point's `value` names (the
shape `--target demo://...` needs): `EntryPoint(name="demo",
value="tests.publisher_spi_fixture:make_demo_publisher",
group="lnpl.publishers")`. Unlike a cache selector, the factory receives the
FULL `--target` string (a URL is for the driver's own `urlsplit`).
"""

from lnpl.drivers import DriverError, EventPublisher


class DemoEventPublisher(EventPublisher):
    """In-memory, records every confirmed publish in call order.
    `fail_ids` (set, mutable after construction) names CloudEvents
    envelope ids that must raise instead of succeeding -- the hook
    EventPublisherTCK needs to drive failure/restart/ordering cases
    without a real broker."""

    def __init__(self, target=None, fail_ids=frozenset()):
        self.target = target
        self.fail_ids = set(fail_ids)
        self.published = []
        self.closed = False

    def publish(self, envelope):
        if envelope["id"] in self.fail_ids:
            raise DriverError("simulated failure for %s" % envelope["id"])
        self.published.append(envelope["id"])

    def close(self):
        self.closed = True


def make_demo_publisher(target=None):
    return DemoEventPublisher(target)
