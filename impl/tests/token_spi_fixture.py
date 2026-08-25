"""A minimal `TokenProvider` used only to prove the `lnpl.tokens`
entry-points discovery path works end-to-end (issue #119b, Task 03) —
registration wiring, not a real signature algorithm. `driver_spi_fixture.py`
is the `lnpl.drivers` precedent this mirrors.

Unlike `open_repository`'s `factory(arg)`, a token provider factory takes no
arguments (`open_token_provider`'s docstring explains why: key material and
verification config are the SPI implementer's own concern, not a CLI string).
This fixture is still HMAC underneath — real RS256/ES256 is `cryptography`'s
job (D1), out of this repo entirely — but it proves `TokenProviderTCK`
against something the core module did not construct, which is the point:
an entry-point-loaded provider must be able to pass the same TCK the
built-in one does.
"""

from lnpl.drivers import HmacTokenProvider

DEMO_SECRET = "fedcba9876543210fedcba9876543210"


class DemoTokenProvider(HmacTokenProvider):
    """A stand-in "external" provider — a distinct class so identity checks
    (`isinstance`) can tell it apart from the built-in, even though its
    verification logic is inherited unchanged."""


def make_demo_token_provider():
    return DemoTokenProvider(DEMO_SECRET)
