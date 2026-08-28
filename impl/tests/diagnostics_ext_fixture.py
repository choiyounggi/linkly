"""Fixture `lnpl.diagnostics` extensions (RFC-0042, issue #138) —
`driver_spi_fixture.py`/`token_spi_fixture.py`'s pattern: this repo is the
only consumer of its own group, so entry-points are constructed in-process
against these functions rather than installing a second package.

Every function here is the `register()` an entry-point's `value` names —
called with no arguments, returning `{"codes": {...}, "check": callable}`
(RFC-0042's Reference-level Spec). The entry-point's own *name* is the
prefix; none of these functions choose or carry a prefix themselves.
"""

CALLS = []  # test_extension_diagnostics.py inspects this to prove `check`'s args


def register_kafka():
    """Well-formed: one `info` code, `check` returns exactly that one
    diagnostic with a real `line` number (mirrors RFC-0042 §Examples)."""
    def check(document, config):
        CALLS.append((document, config))
        return [{"code": "at-least-once", "where": "emit userCreated",
                 "subject": "emit userCreated",
                 "message": "the installed kafka outbox relay guarantees "
                             "at-least-once delivery only", "line": 12}]
    return {"codes": {"at-least-once": {
                "severity": "info",
                "description": "outbox relay is at-least-once only"}},
            "check": check}


def register_error_severity():
    """Invalid: declares `error`, which RFC-0042 reserves — rejected at
    load time, `check` is never called."""
    return {"codes": {"boom": {"severity": "error", "description": "x"}},
            "check": lambda document, config: []}


def register_partial_unknown_code():
    """Registers one code (`known`) but `check` emits a second, unregistered
    one (`unknown`) alongside it — the execution-time filter case (D6):
    only the unregistered diagnostic is dropped, not the whole extension."""
    return {"codes": {"known": {"severity": "warning", "description": "x"}},
            "check": lambda document, config: [
                {"code": "known", "where": "w", "subject": "s",
                 "message": "m", "line": 1},
                {"code": "unknown", "where": "w", "subject": "s",
                 "message": "m", "line": 1}]}


def register_empty():
    """Boundary: an extension that registers no codes and emits nothing."""
    return {"codes": {}, "check": lambda document, config: []}
