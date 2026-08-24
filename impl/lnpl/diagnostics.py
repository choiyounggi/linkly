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

# The grade ladder, weakest first (#52). The tuple order *is* the ranking:
# `--strict=<level>` gates on everything from that index up, so reordering these
# reverses every threshold in the CLI. `error` is reserved — no code maps to it
# today, which `test_diagnostics_channel.py` pins so the next person to use it
# has to decide what `--strict=error` means.
SEVERITIES = ("info", "warning", "error")

# The closed set of diagnostic codes. A code is the only field a caller may
# branch on, so it is a contract: keep the spellings stable, and treat removing
# or renaming one as a breaking change.
CODES = (
    "unknown-verb",                 # #36  verb outside VERB_LEXICON -> no Effect
    "unknown-entity",               # #91  step object outside the declared entities
    "declared-not-enforced",        # #38  declared, and the runtime does nothing with it
    "declared-measured-only",       # #38  observed and reported, never blocks
    "authorization-not-verified",   # #38  Authorization Effect records, never checks
    "guard-skipped-steps",          # #44  a guard was false, so declared steps did not run
    "guard-orphaned-steps",         # RFC-0023  a guard owns one item; a later step touches the state it protected
    "validation-sample-derived",     # #55  mode B decided Validation from a sample payload
    "aggregation-orphaned-list",    # RFC-0025  sum/count reads a RowSet no earlier unguarded `list` fills
    "event-source-mismatch",        # #98  `emit` and its declared `on <Entity> <op>` step are not in the same guard scope
    "event-source-orphaned",        # #98  `emit` fires, but its declared `on <Entity> <op>` step never runs in this workflow
    "derived-never-assigned",       # #95  a `derived` field is `create`d, but no `set`/`format` in the workflow ever fills it
    "declared-not-bound",           # #101 a `call`/`request` target names no declared `capability http`
)

# code -> grade (#52). One question decides every row:
#
#   does editing the program make this diagnostic go away?
#
#   yes -> `warning`. The author probably did not mean this, and the fix is
#          theirs: drop the typo'd verb, or look at why a guard was false.
#   no  -> `info`. The program is correct and the platform is stating what it
#          does with it. No edit removes the line; only the platform changing
#          does. Reporting it is still the point (#38) — grading it `warning`
#          is what made `--strict` and a legitimate `on schedule` declaration
#          mutually exclusive (issue #52, qa/rerun r3 N-4).
#
# The grade lives here rather than at each `add()` call so it cannot be decided
# twice, differently, for the same fact.
SEVERITY_OF = {
    "unknown-verb":               "warning",
    "unknown-entity":             "warning",
    "declared-not-enforced":      "info",
    "declared-measured-only":     "info",
    "authorization-not-verified": "info",
    "guard-skipped-steps":        "warning",
    "guard-orphaned-steps":       "warning",
    # #55: no edit to the program removes this one. Mode B specialises at build
    # time, so its Validation outcome comes from a derived sample payload rather
    # than from anything the caller can pass — a statement about the channel, not
    # about the source.
    "validation-sample-derived":  "info",
    # RFC-0025 §4: adding a `list <entity>` before the aggregate removes this —
    # the program is what needs to change, so `warning` (same test as
    # `unknown-verb`, `guard-orphaned-steps`).
    "aggregation-orphaned-list":  "warning",
    # #98: moving the `emit` under the same guard scope as the `<op> <entity>`
    # step its source declares removes this — same test as `guard-orphaned-steps`.
    "event-source-mismatch":      "warning",
    # #98: no edit to the program removes this one short of adding the
    # `<op> <entity>` step or dropping the source/emit — a statement about the
    # source declaration being descriptive only, same logic as
    # `declared-not-enforced`.
    "event-source-orphaned":      "info",
    # #95: adding the missing `set`/`format` step removes this — same test as
    # `unknown-verb`, `aggregation-orphaned-list`.
    "derived-never-assigned":     "warning",
    # #101: a `capability http` declaration is optional — an undeclared
    # target still runs (method POST, no auth), so the program is correct as
    # written. Adding the declaration is a legitimate edit that removes this,
    # but it changes intent (opting into method/auth), not fixing a bug — the
    # same "the program is correct, the platform is stating what it does
    # with it" case `declared-not-enforced` already covers.
    "declared-not-bound":         "info",
}

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
    # Still nothing to compensate after #25. A real store now exists, but the
    # driver commits per operation and no workflow-wide transaction boundary
    # was introduced — adding the boundary without compensation logic would
    # make this row read `enforced` while a failed run left its earlier writes
    # in place.
    ("policy", "rollback"):
        (UNENFORCED, "Phase 1 has no Transaction boundary, so there is nothing "
                     "to compensate; the #25 drivers commit per operation"),
    ("policy", "parallel"):
        (UNENFORCED, "parsed, but the execution plan never reads it"),
    # Issue #25 gave `jwt` a real issue/verify path, and the status still reads
    # UNENFORCED because this diagnostic is emitted at COMPILE time, which does
    # not know which backend the program will run against. Naming the one path
    # that does enforce it is the honest form: a single global status would
    # make one of the two paths lie (the default run, and `serve` with a token
    # provider, do genuinely different things with the same declaration).
    ("security", "jwt"):
        (UNENFORCED, "the default path issues and verifies nothing; "
                     "`lnpl serve --jwt-secret-env NAME` verifies the bearer "
                     "token per request (docs/serving.md M3a, docs/backends.md)"),
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
    # RFC-0016. A schedule trigger is a real declaration with a real artifact —
    # it reaches the IR and the OpenAPI schedule metadata — and nothing fires
    # it. Saying that out loud is the whole difference between this and
    # `performance batch`, which t3 F-2 found parsing into silence.
    ("event", "schedule"):
        (UNENFORCED, "no scheduler runs it; the declaration reaches the IR and "
                     "the OpenAPI schedule metadata only — issue #26 (the "
                     "serving layer) owns the executor"),
}


@dataclass(frozen=True)
class Diagnostic:
    """One thing the platform is not doing, and where.

    `code` is what callers branch on; `message` is for people and is never a
    stable interface. `subject` carries the same fact as the message in a form
    a test or a tool can compare — the verb, the declaration, the requirement —
    so nobody has to regex prose to find out what this is about.

    `severity` is derived, not stored: it reads `SEVERITY_OF[code]`, so there is
    no argument through which a producer could grade the same code two ways.

    `line` (RFC-0024) is the 1-based source line the diagnostic is about, when
    the producer has one in hand — the IR node's own optional `line` field for a
    compile-time producer, or a node lookup for a runtime one. `None` when no
    node the diagnostic is about carries a line (e.g. it predates RFC-0024's
    lowering coverage), in which case rendering falls back to the pre-RFC-0024
    form.

    `suggestion` (RFC-0026) is a close match a producer found for an unrecognized
    name — e.g. `unknown-verb`'s nearest `VERB_LEXICON` entry — or `None` when it
    found none. The key is always present on a record so a consumer can rely on
    it existing without branching on the producer's code.
    """

    code: str        # one of CODES
    where: str       # the site: "line 31", or a node id such as "security.login"
    subject: str     # machine-readable subject: "generate" / "security jwt"
    message: str     # one human line; never branched on
    line: int = None  # 1-based source line, or None (RFC-0024)
    suggestion: str = None  # a close VERB_LEXICON match, or None (RFC-0026)

    def __post_init__(self):
        if self.code not in CODES:
            raise ValueError("unknown diagnostic code: %r" % self.code)

    @property
    def severity(self):
        """One of SEVERITIES, decided by the code alone (#52)."""
        return SEVERITY_OF[self.code]


class Diagnostics:
    """An ordered accumulator of `Diagnostic`s — the channel every producer writes to.

    Order is insertion order, and nothing is deduplicated: two occurrences of
    the same unknown verb are two places to fix, and collapsing them would send
    the author back for a second round after fixing the first.
    """

    def __init__(self):
        self._items = []

    def add(self, *, code, where, subject, message, line=None, suggestion=None):
        """Record one diagnostic and return it.

        Keyword-only: `severity` used to sit second, so a stale positional call
        would bind a grade string into `where` and store it without complaint.
        The bare `*` makes every such call fail where it is written.

        `line` (RFC-0024) is optional and defaults to `None` — a producer that
        has no source line for its subject (or predates RFC-0024) does not have
        to invent one.

        `suggestion` (RFC-0026) is optional and defaults to `None` — a producer
        with no close match to offer (or that predates RFC-0026) does not have
        to invent one.
        """
        diagnostic = Diagnostic(code=code, where=where, subject=subject,
                                message=message, line=line, suggestion=suggestion)
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


def to_records(diagnostics):
    """Diagnostics -> plain dicts, for a caller that reads JSON not prose (#52).

    Not a second formatter: `format_lines` still owns the only human rendering,
    and this owns none — it hands over the record's own fields so a consumer can
    branch on `code` and `severity` instead of regexing a `message` that was
    never a stable interface (r3 F-8).

    `severity` is spelled out because it is a derived property, so
    `dataclasses.asdict` would silently drop it — and dropping the grade is
    exactly what would make this channel useless for a graded CI gate.
    """
    return [{"code": d.code, "severity": d.severity, "where": d.where,
             "subject": d.subject, "message": d.message, "line": d.line,
             "suggestion": d.suggestion}
            for d in _records(diagnostics)]


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
    lines = [
        ("%s: %s [%s] (line %d) %s — %s" % (d.severity, d.code, d.where,
                                            d.line, d.subject, d.message)
         if d.line is not None else
         "%s: %s [%s] %s — %s" % (d.severity, d.code, d.where, d.subject,
                                  d.message))
        for d in records
    ]
    infos = sum(1 for d in records if d.severity == "info")
    warnings = sum(1 for d in records if d.severity == "warning")
    errors = sum(1 for d in records if d.severity == "error")
    lines.append("%d info, %d warning(s), %d error(s)" % (infos, warnings, errors))
    return lines
