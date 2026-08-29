"""Fixture drivers for RFC-0043's `lnpl_enforcement` self-report SPI (issue
#138/#140). `test_enforcement_reporting.py` and `test_mcp_server.py` register
these classes directly as entry-point values (`module:ClassName`) — a class
is itself the "factory" `docs/backends.md` §8 requires (`ClassName(arg)`
calls `__init__`, same as a wrapping `make_driver(arg)` function would), and
`RFC-0043 §신고 SPI` reads `lnpl_enforcement` off whatever `ep.load()`
returns — here, the class itself, where the attribute is set directly. Each
class accepts an optional `arg` for the same reason `driver_spi_fixture.py`'s
`DemoRepositoryDriver` does (constructor shape parity), even though these
tests never instantiate one — only `ep.load()` (import, no call) is ever
exercised.
"""

from lnpl.drivers import CacheDriver, RepositoryDriver, TokenProvider


class IsolationReportingDriver(RepositoryDriver):
    """Reports `isolation` only — RFC-0043 §Examples' postgres case."""

    lnpl_enforcement = {"isolation": "read-committed"}

    def __init__(self, arg=None):
        self.arg = arg


class DeliveryReportingDriver(RepositoryDriver):
    """Reports `delivery` only — RFC-0043 §Examples' kafka-outbox-adjacent
    case (registered under `lnpl.drivers`/repository, same as any other
    `RepositoryDriver`, even though it models an event relay — RFC-0043
    §매칭 규칙: the entry-point's group, not its conceptual role, is what
    ties it to a slot)."""

    lnpl_enforcement = {"delivery": "at-least-once"}

    def __init__(self, arg=None):
        self.arg = arg


class CacheScopeReportingDriver(CacheDriver):
    """Reports `cache_scope` only."""

    lnpl_enforcement = {"cache_scope": "process-local"}

    def __init__(self, arg=None):
        self.arg = arg


class TokenClaimsReportingDriver(TokenProvider):
    """Reports `token_claims` only (`list[str]`)."""

    lnpl_enforcement = {"token_claims": ["sub", "aud", "exp"]}

    def __init__(self, arg=None):
        self.arg = arg


class UnknownKeyDriver(RepositoryDriver):
    """One valid axis (`delivery`) alongside one the core does not know —
    the unknown key must be dropped, not the whole report (RFC-0043 §신고
    SPI forward-compat)."""

    lnpl_enforcement = {"delivery": "exactly-once", "made_up_axis": "whatever"}

    def __init__(self, arg=None):
        self.arg = arg


class OutOfVocabularyDriver(RepositoryDriver):
    """A known axis with a value outside the closed vocabulary — the whole
    axis entry is dropped (plan D2); nothing else is reported, so this
    driver contributes no diagnostic at all."""

    lnpl_enforcement = {"delivery": "maybe-once"}

    def __init__(self, arg=None):
        self.arg = arg


class NonListClaimsDriver(TokenProvider):
    """`token_claims` given a scalar instead of a `list[str]` — dropped
    (plan D2), same treatment as an out-of-vocabulary scalar value."""

    lnpl_enforcement = {"token_claims": "sub"}

    def __init__(self, arg=None):
        self.arg = arg


class NoReportDriver(RepositoryDriver):
    """No `lnpl_enforcement` attribute at all — "no report", same as every
    built-in driver (`fake`/`sqlite`)."""

    def __init__(self, arg=None):
        self.arg = arg
