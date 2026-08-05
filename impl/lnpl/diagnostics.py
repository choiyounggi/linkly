"""Compiler and runtime diagnostics — the single channel (issues #36, #38).

Two symptoms, one failure mode: a verb outside `VERB_LEXICON` derived no Effect
and nobody was told (#36), and a `security jwt` / `policy rollback` declaration
was recorded and never enforced, also without a word (#38). The platform stayed
silent about what it could not do. Expressing those two facts in two different
ways would rebuild the problem one level up, so everything that reports "the
platform is not doing what this program says" passes through here.

Adding a diagnostic is therefore two steps and no new machinery: name it in
`CODES`, then `add(...)` it to the accumulator the producer already owns
(`Module.diagnostics` at compile time, `Interpreter.diagnostics` at run time).
Do not add a second record type, accumulator, or formatter.

What a diagnostic deliberately does NOT do:
  - it is not an IR node — `to_document()` is unchanged, so the golden
    `.lir.json` files stay byte-identical;
  - it is not a trace log — mode A/B equivalence covers log levels
    (docs/ROADMAP.md §Phase 2), and mode B cannot produce these;
  - it does not change an exit code — a descriptive step is a legitimate way to
    write LNPL (the golden `login.lnpl` uses three), so this reports, it does
    not reject.

Visibility is the whole contract. Actually enforcing the declarations below is
issue #25 and the roadmap, not this module.
"""

from dataclasses import dataclass

SEVERITIES = ("warning", "error")

# The closed set of diagnostic codes. A code is the only field a caller may
# branch on, so it is a contract: keep the spellings stable, and treat removing
# or renaming one as a breaking change.
CODES = (
    "unknown-verb",                 # #36  verb outside VERB_LEXICON -> no Effect
    "declared-not-enforced",        # #38  declared, and the runtime does nothing with it
    "declared-measured-only",       # #38  observed and reported, never blocks
    "authorization-not-verified",   # #38  Authorization Effect records, never checks
)

# How the runtime treats a declaration.
ENFORCED = "enforced"        # the declaration changes what execution does
MEASURED = "measured"        # execution observes and reports it, but never blocks
UNENFORCED = "unenforced"    # execution ignores it entirely
ENFORCEMENT_STATUSES = (ENFORCED, MEASURED, UNENFORCED)

# The declaration -> enforcement matrix. This is the canonical form; the table
# in `docs/ENFORCEMENT-MATRIX.md` is a human-readable copy of it, and
# `impl/tests/test_enforcement_matrix.py` fails when the two drift apart.
#
# Keyed by (clause, name) over the language's closed declaration sets:
# `lower.POLICY_NAMES`, `lower.SECURITY_MECHANISMS`, `lower.PERF_METRICS`.
ENFORCEMENT = {
    ("policy", "retry"):
        (ENFORCED, "run_workflow re-runs a failed step while its effects are idempotent"),
    ("policy", "timeout"):
        (ENFORCED, "a workflow deadline is computed, and exceeding it fails the run"),
    ("policy", "rollback"):
        (UNENFORCED, "Phase 1 has no Transaction boundary, so there is nothing to compensate"),
    ("policy", "parallel"):
        (UNENFORCED, "parsed, but the execution plan never reads it"),
    ("security", "jwt"):
        (UNENFORCED, "no token is issued or verified; the mechanism reaches the OpenAPI document only"),
    ("security", "role"):
        (UNENFORCED, "the role is never checked against anything"),
    ("security", "encrypt"):
        (UNENFORCED, "the field is not encrypted (Password masking is a separate, type-driven behaviour)"),
    ("performance", "response"):
        (MEASURED, "measured and reported per run, but an over-budget run is not blocked"),
    ("performance", "cache"):
        (ENFORCED, "owns the TTL budget every CacheAccess set is written with"),
    ("performance", "parallel"):
        (UNENFORCED, "parsed, but the execution plan never reads it"),
    ("performance", "prefetch"):
        (UNENFORCED, "parsed, but the execution plan never reads it"),
    ("performance", "batch"):
        (UNENFORCED, "parsed, but the execution plan never reads it"),
}


@dataclass(frozen=True)
class Diagnostic:
    """One thing the platform is not doing, and where.

    `code` is what callers branch on; `message` is for people and is never a
    stable interface. `subject` carries the same fact as the message in a form
    a test or a tool can compare — the verb, the declaration, the requirement —
    so nobody has to regex prose to find out what this is about.
    """

    code: str        # one of CODES
    severity: str    # one of SEVERITIES
    where: str       # the site: "line 31", or a node id such as "security.login"
    subject: str     # machine-readable subject: "generate" / "security jwt"
    message: str     # one human line; never branched on

    def __post_init__(self):
        if self.code not in CODES:
            raise ValueError("unknown diagnostic code: %r" % self.code)
        if self.severity not in SEVERITIES:
            raise ValueError("unknown severity: %r" % self.severity)


class Diagnostics:
    """An ordered accumulator of `Diagnostic`s — the channel every producer writes to.

    Order is insertion order, and nothing is deduplicated: two occurrences of
    the same unknown verb are two places to fix, and collapsing them would send
    the author back for a second round after fixing the first.
    """

    def __init__(self):
        self._items = []

    def add(self, code, severity, where, subject, message):
        """Record one diagnostic and return it."""
        diagnostic = Diagnostic(code=code, severity=severity, where=where,
                                subject=subject, message=message)
        self._items.append(diagnostic)
        return diagnostic

    def extend(self, diagnostics):
        """Append every diagnostic from another accumulator or any iterable."""
        self._items.extend(_records(diagnostics))

    def all(self):
        """Every diagnostic, in the order it was added (a copy)."""
        return list(self._items)

    def by_code(self, code):
        """Only the diagnostics carrying `code`, in order."""
        if code not in CODES:
            raise ValueError("unknown diagnostic code: %r" % code)
        return [d for d in self._items if d.code == code]

    def __len__(self):
        return len(self._items)

    def __bool__(self):
        return bool(self._items)

    def __iter__(self):
        return iter(self._items)


def _records(diagnostics):
    """Accept either a `Diagnostics` or a plain iterable of `Diagnostic`."""
    if isinstance(diagnostics, Diagnostics):
        return diagnostics.all()
    return list(diagnostics)


def format_lines(diagnostics):
    """Diagnostics -> the lines to show a person, summary last.

    The only formatter. Every command that shows diagnostics renders them from
    here, so `compile` and `run` cannot drift into two different reports of the
    same fact. No diagnostics means no output at all — not even a summary — so
    a clean module stays quiet.
    """
    records = _records(diagnostics)
    if not records:
        return []
    lines = ["%s: %s [%s] %s — %s" % (d.severity, d.code, d.where, d.subject,
                                      d.message)
             for d in records]
    warnings = sum(1 for d in records if d.severity == "warning")
    errors = sum(1 for d in records if d.severity == "error")
    lines.append("%d warning(s), %d error(s)" % (warnings, errors))
    return lines
