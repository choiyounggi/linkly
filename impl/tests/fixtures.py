"""Workflow sources shared by the test suite.

Two reasons this module exists.

**One home per source.** `GUARDED` was defined verbatim in both
`test_backend.py` and `test_lnpl_dialect.py`, and the `until` source in
`test_until_mode_equivalence.py`. Editing one copy silently drifts from the
other, which is exactly what the `GUARDED` change below would have done.

**`GUARDED` needs a cache budget.** `cache user` lowers to a `CacheAccess set`,
and RFC-0003 requires every cache key to carry a TTL. Mode A enforces that by
raising `RunError`; mode B does not enforce it at all. Without a
`performance / cache 5m` clause the two modes therefore disagree *before any
test does anything* — `FAIL 2/4 policy outcome — A=failed B=completed`. Three
`TestDivergenceIsDetected` cases were asserting `assertFalse(ok)` against that
standing divergence rather than against the fault each of them names, so their
own monkeypatches could be removed without the tests noticing.

Mode B's missing enforcement is a real gap, not a fixture problem; it is pinned
separately by `TestModeBDoesNotEnforceTheCacheTtlContract` in `test_backend.py`
so that adding the budget here does not bury it.

Sources only. **No payloads** — a test's payload is what explains why it passes,
so it belongs in the test body where a reader can see it.
"""

GUARDED = """
capability postgres
capability redis
entity User
    field
        id UUID
        email Email
        token Text
service S
    performance
        cache 5m
workflow W
    load user
    when token missing
    cache user
"""


def guarded_source(guard):
    """`GUARDED` with its guard line replaced — e.g. `guarded_source("repeat 3")`.

    Substitutes the whole indented line, so callers never manage indentation.
    """
    return GUARDED.replace("    when token missing", "    " + guard)


# The `until` workflow, kept free of cache effects so its equivalence turns only
# on the loop condition. `test_until_mode_equivalence.py` pins it at counter
# 0/9/10/100; the two `until` mismatch cases in `test_backend.py` use it because
# `GUARDED` has no `until` at all — which is what made their patches no-ops.
UNTIL_COUNTER = """capability postgres

entity Workflow
    field
        id UUID
        counter Integer
        doneAt DateTime

service S
    policy
        timeout 5s

workflow W
    step Start
    until counter >= 10
    step Loop
    step End
"""
