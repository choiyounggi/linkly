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

Of the three declarations added for that fix, **only the `performance` clause is
load-bearing** — removing it turns
`test_the_guarded_fixture_is_equivalent_with_its_guard_taken` red, and removing
either of the other two does not. `capability redis` and the `token Text` field
are kept for modelling coherence, matching how `examples/login.lnpl` declares a
capability for its own `cache user` and how a guard should reference a declared
field. They are documentation, not mechanism; do not cite them as the reason the
baseline is equivalent.

Mode B's missing enforcement is a real gap, not a fixture problem; it is pinned
separately by `TestModeBDoesNotEnforceTheCacheTtlContract` in `test_backend.py`
so that adding the budget here does not bury it.

Sources only. **No payloads** — a test's payload is what explains why it passes,
so it belongs in the test body where a reader can see it.

The `CHECKOUT_*` names below are the one exception to "sources", and they are
still the same rule: `examples/checkout.lnpl` is a *committed file*, so its one
home is that path — not a second copy of its text pasted here. They are paths so
that `test_golden.py` and the equivalence regression resolve the same file
instead of each deriving the repo root for itself. `SHORTEN_*` follows that same
rule for the refinement example and its three generated goldens, and
`LOGIN_SPEC`/`LOGIN_OPENAPI` and `CHECKOUT_SPEC`/`CHECKOUT_OPENAPI` follow it for
the `spec` and `openapi` halves of the other two quartets, which `test_golden.py`
regenerates and compares the same way.
"""

import os

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The first quartet's generated halves. Login's `.lnpl` and `.lir.json` stay as
# `test_golden.py` locals: the pair that already resolves them there passes, and
# moving it here would rewrite a working test for no gain.
LOGIN_SPEC = os.path.join(_REPO, "examples", "login.spec.json")
LOGIN_OPENAPI = os.path.join(_REPO, "examples", "login.openapi.json")

# The read-then-create example (issue #35) and its generated goldens.
CHECKOUT_LNPL = os.path.join(_REPO, "examples", "checkout.lnpl")
CHECKOUT_LIR = os.path.join(_REPO, "examples", "checkout.lir.json")
CHECKOUT_SPEC = os.path.join(_REPO, "examples", "checkout.spec.json")
CHECKOUT_OPENAPI = os.path.join(_REPO, "examples", "checkout.openapi.json")

# The refinement example (issue #31): `URL`/`Slug` instead of `Text`, and the
# three artifacts `lnpl compile` / `spec` / `openapi` generate from it.
SHORTEN_LNPL = os.path.join(_REPO, "examples", "shorten.lnpl")
SHORTEN_LIR = os.path.join(_REPO, "examples", "shorten.lir.json")
SHORTEN_SPEC = os.path.join(_REPO, "examples", "shorten.spec.json")
SHORTEN_OPENAPI = os.path.join(_REPO, "examples", "shorten.openapi.json")

# The guard example RFC-0008 §5.2 promised and the repo never had (issue #50,
# t4 F-8). Presence and Comparison `when` guards in one workflow, with the four
# committed artifacts every other example carries.
GUARDED_LNPL = os.path.join(_REPO, "examples", "guarded.lnpl")
GUARDED_LIR = os.path.join(_REPO, "examples", "guarded.lir.json")
GUARDED_SPEC = os.path.join(_REPO, "examples", "guarded.spec.json")
GUARDED_OPENAPI = os.path.join(_REPO, "examples", "guarded.openapi.json")

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


# RFC-0015's value expressions, in the shape issue #47's t1 could not write:
# a quantity-aware stock check, then the deduction. The two guards precede the
# assignment in source order because RFC-0015 refuses a guard that reads a value
# an earlier step assigned (mode B fixes condition fields at entry).
#
# `test_value_semantics.py` runs it through mode A and `test_backend.py` through
# the differential, so it lives here rather than in either of them.
VALUE_INVENTORY = """capability postgres

entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    read product
    when product.stock >= input.quantity
    create order
    when product.stock >= input.quantity
    set product.stock to product.stock - input.quantity
"""

# The range check t2 could only write as one bound, plus the equality that
# distinguishes a full refund from a partial one.
VALUE_PAYMENT = """capability postgres

entity Payment
    field
        id UUID
        amount Integer

entity Refund
    field
        id UUID
        amount Integer

service PaymentService
    policy
        timeout 5s

workflow Approve
    when input.amount > 0 and input.amount <= 10000
    create payment
"""

VALUE_REFUND = """capability postgres

entity Payment
    field
        id UUID
        amount Integer

entity Refund
    field
        id UUID
        amount Integer

service RefundService
    policy
        timeout 5s

workflow Refund
    read payment
    when payment.amount == input.amount
    create refund
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


# A workflow whose entity carries a `Password`-typed field, for the masking
# sweep that has to hold on every backend: swapping the repository driver must
# not change which values reach an output channel. The plain `label` field is
# the negative control — a channel where it is also missing was never captured,
# which would make the secret's absence vacuous.
SECRET_ACCOUNT = """capability postgres

entity Account
    field
        id UUID
        label Text
        cardSecret Password

service AccountService
    policy
        timeout 5s

workflow Fetch
    read account
"""
