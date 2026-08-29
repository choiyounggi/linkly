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

import re
import sys
from dataclasses import dataclass
from importlib import metadata as importlib_metadata

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
    "stored-row-shape-mismatch",    # #85  a read/find row is missing a declared field, or has the wrong type
    "rollback-escapes-network",     # #112 `policy rollback`'s service has a workflow step whose NetworkCall sits outside the transaction boundary
    "retry-on-non-idempotent",      # #109 `capability http` declares `method post`/`patch` together with `retry`
    "note-cap-exceeded",            # #111 a workflow has more than NOTE_CAP `note` annotations
    "event-consume-cycle",          # #118 `consume by` + that workflow's own `emit` reaches the event again
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
    # issue #119, D10: `warning`, not `info` — Task 03 gave `security role` a
    # real enforcement path, so an author who wrote `authorize` now HAS an
    # edit that removes this: drop the verb, add `security role <r>` to the
    # service instead. The RFC-0021 test ("does editing the program make this
    # go away?") answers yes now, where before Batch A it answered no.
    "authorization-not-verified": "warning",
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
    # #85: backfilling the stored row (adding the missing field, or fixing
    # its type) removes this — the data needs to change, not the program,
    # but it is still an edit that makes the diagnostic go away, so `warning`
    # (RFC-0021's data-side reading of the same question).
    "stored-row-shape-mismatch": "warning",
    # #112: RFC-0021's question, answered the same way as `unknown-verb` —
    # moving the `call`/`request` off the workflow that declares `policy
    # rollback`, or dropping the policy, removes this. The program is what
    # has to change, so `warning`, not `declared-not-enforced`'s `info`
    # (that code covers a fact the platform states about *itself*; this one
    # is about the *program's* shape).
    "rollback-escapes-network":  "warning",
    # #109: a retry on a non-idempotent method risks duplicating the call's
    # effect (a double charge, a double order) — dropping `retry`, switching
    # to an idempotent method, or pairing it with an idempotency key (#113)
    # each remove this, so `warning` (same test as `unknown-verb`).
    "retry-on-non-idempotent":   "warning",
    # #111: trimming `note`s below the cap removes this — same test as
    # `unknown-verb`; the workflow still compiles and runs either way.
    "note-cap-exceeded":         "warning",
    # #118, D3: a cycle is a *static signal* for a possible runtime infinite
    # dispatch loop, not proof of one — a guard inside the consuming workflow
    # may break it at run time, so the program is not necessarily wrong.
    # `warning`, not `info`: breaking the cycle (drop the `consume by`, or the
    # `emit`) is an edit the author can make, same test as `unknown-verb`.
    "event-consume-cycle":      "warning",
}


# RFC-0042 (issue #138): extensions register diagnostics under `<prefix>/<code>`,
# a namespace disjoint from `CODES` above — bare codes stay core-only forever,
# and `<prefix>/<code>` never enters `CODES`/`SEVERITY_OF` (the extension's own
# registration is that code's grade of record). `prefix` is the entry-point's
# own name; there is no separate prefix declaration.
DIAGNOSTICS_ENTRY_POINT_GROUP = "lnpl.diagnostics"

_EXTENSION_PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]{1,15}$")
RESERVED_EXTENSION_PREFIXES = ("lnpl", "core")

# RFC-0043 §검사 주체: the core's own synthesized `<entry-point>/<axis-code>`
# codes (issue #138/#140) reserve this *code* pattern statically, under any
# prefix — a `lnpl.diagnostics` extension may not register a code matching
# it, whether or not a driver by the same entry-point name actually reports
# anything this run. Static, not "does this driver report today", so load
# success never depends on which drivers happen to be installed.
_RESERVED_ENFORCEMENT_CODE_RE = re.compile(
    r"^(delivery|isolation|cache-scope|token-claims)(-.+)?$")


class ExtensionDiagnosticsError(Exception):
    """A `lnpl.diagnostics` entry-point registration violates RFC-0042 —
    raised at load time, before any diagnostic from it is ever emitted."""


def _extension_entry_points():
    """Every entry-point registered under `lnpl.diagnostics`, across the
    stdlib API's version split `drivers._driver_entry_points()` also
    handles: 3.10+ takes `group=` as a select filter; 3.9's `entry_points()`
    takes no arguments and returns a `{group: [EntryPoint, ...]}` mapping
    instead (`pyproject.toml`'s declared floor is 3.9)."""
    try:
        return importlib_metadata.entry_points(group=DIAGNOSTICS_ENTRY_POINT_GROUP)
    except TypeError:
        return importlib_metadata.entry_points().get(
            DIAGNOSTICS_ENTRY_POINT_GROUP, [])


def load_extensions():
    """Load and validate every registered `lnpl.diagnostics` extension,
    returning `{prefix: {"codes": {"<code>": {"severity", "description"}},
    "check": callable(document, config) -> list[dict]}}`.

    Load-time validation (RFC-0042 Reference-level Spec) — every violation
    raises `ExtensionDiagnosticsError` before compilation proceeds, never a
    partial, half-loaded registry:

    - the prefix (the entry-point's own name) must match
      `^[a-z][a-z0-9-]{1,15}$`;
    - `lnpl`/`core` are reserved and may not be used as a prefix;
    - one prefix has one owner — a second registration under an
      already-seen prefix is refused;
    - an extension declaring `error` severity for any code is refused —
      extensions may declare `info`/`warning` only;
    - a code matching `^(delivery|isolation|cache-scope|token-claims)
      (-.+)?$` is refused under any prefix — reserved for the core's own
      RFC-0043 driver-enforcement bridge (`capabilities.
      enforcement_diagnostic_records`), statically, regardless of whether
      any driver by that entry-point name actually reports anything this
      run.

    Not cached: called fresh each time (the `lnpl.drivers`/`lnpl.tokens`
    precedent), so a test can swap `importlib_metadata.entry_points` between
    calls without a stale registry surviving it.
    """
    registry = {}
    for ep in _extension_entry_points():
        prefix = ep.name
        if not _EXTENSION_PREFIX_RE.match(prefix):
            raise ExtensionDiagnosticsError(
                "extension prefix %r (entry-point %r) does not match %s "
                "(RFC-0042); registered so far: %s"
                % (prefix, ep.value, _EXTENSION_PREFIX_RE.pattern,
                   ", ".join(sorted(registry)) or "none"))
        if prefix in RESERVED_EXTENSION_PREFIXES:
            raise ExtensionDiagnosticsError(
                "extension prefix %r (entry-point %r) is reserved for the "
                "core (RFC-0042); reserved prefixes: %s"
                % (prefix, ep.value, ", ".join(RESERVED_EXTENSION_PREFIXES)))
        if prefix in registry:
            raise ExtensionDiagnosticsError(
                "prefix %r (entry-point %r) is already owned by another "
                "extension registered under the same name — one prefix, "
                "one owner (RFC-0042); registered so far: %s"
                % (prefix, ep.value, ", ".join(sorted(registry))))
        try:
            register = ep.load()
        except Exception as exc:
            raise ExtensionDiagnosticsError(
                "extension %r (entry-point %r) failed to load: %s"
                % (prefix, ep.value, exc)) from exc
        result = register()
        codes = result["codes"]
        for code, meta in codes.items():
            if _RESERVED_ENFORCEMENT_CODE_RE.match(code):
                raise ExtensionDiagnosticsError(
                    "extension %r registered diagnostic %r, which matches "
                    "the reserved enforcement-code pattern %s — no "
                    "`lnpl.diagnostics` extension may register a code the "
                    "core's own driver-enforcement bridge owns, under any "
                    "prefix (RFC-0043); registered so far: %s"
                    % (prefix, "%s/%s" % (prefix, code),
                       _RESERVED_ENFORCEMENT_CODE_RE.pattern,
                       ", ".join(sorted(registry)) or "none"))
            severity = meta.get("severity")
            if severity not in ("info", "warning"):
                raise ExtensionDiagnosticsError(
                    "extension %r registered diagnostic %r with severity "
                    "%r — extensions may declare 'info' or 'warning' only "
                    "(RFC-0042); registered so far: %s"
                    % (prefix, "%s/%s" % (prefix, code), severity,
                       ", ".join(sorted(registry)) or "none"))
        registry[prefix] = {"codes": codes, "check": result["check"]}
    return registry


def extension_diagnostic_records(document):
    """Run every registered `lnpl.diagnostics` extension's `check` against
    `document` — the compiled IR only, no source text or file path (RFC-0042
    D7) — and return the list of 6-key records (`<prefix>/<code>`, the
    extension's own registered severity) to merge into a caller's
    diagnostics, followed by the core's own RFC-0043 driver-enforcement
    bridge records for the same document.

    The one shared definition behind `lnpl compile`, `wsgi.build_app`, and
    the MCP `lnpl_compile` tool (issue #140, docs/backends.md §11) — all
    three read the same records for the same document. RFC-0043 (issue
    #138/#140 follow-up) rides the same shared layer rather than its own:
    `capabilities.enforcement_diagnostic_records` is called last, via a
    lazy (in-function) import — `capabilities.py` already imports this
    module at top level, so a top-level import here would be circular.

    Loading and validating the registry (`load_extensions`) is load-time —
    any violation raises `ExtensionDiagnosticsError`, which the caller
    handles as a hard failure. Once loaded, a `check` diagnostic whose code
    its own extension never registered is an execution-time problem, not a
    load-time one (RFC-0042 D6): that one diagnostic is dropped and warned
    about on stderr, but the rest of that extension's diagnostics — and
    every other extension — still make it through.
    """
    registry = load_extensions()
    records = []
    for prefix, entry in registry.items():
        codes = entry["codes"]
        for raw in entry["check"](document, {}):
            bare = raw["code"]
            if bare not in codes:
                print("warning: extension %r emitted diagnostic %r, which "
                      "it did not register — dropping (RFC-0042)"
                      % (prefix, bare), file=sys.stderr)
                continue
            records.append({
                "code": "%s/%s" % (prefix, bare),
                "severity": codes[bare]["severity"],
                "where": raw["where"],
                "subject": raw["subject"],
                "message": raw["message"],
                "line": raw.get("line"),
            })
    from lnpl import capabilities as _capabilities
    records.extend(_capabilities.enforcement_diagnostic_records(document))
    return records


def severity_of(code):
    """Grade for any diagnostic code, bare or `<prefix>/<code>` (RFC-0042).

    A bare code (no `/`) resolves through `SEVERITY_OF`, unchanged — `CODES`
    stays the closed, core-only table it always was. A `<prefix>/<code>`
    code resolves through whatever is currently registered under
    `lnpl.diagnostics`: the extension's own registration is that code's
    grade of record, since it never enters `CODES`/`SEVERITY_OF`.
    """
    if "/" not in code:
        return SEVERITY_OF[code]
    prefix, _, bare = code.partition("/")
    return load_extensions()[prefix]["codes"][bare]["severity"]


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
    # issue #79, RFC-0032: `run_workflow` now opens one transaction per
    # execution and rolls it back on any failure, so there is something to
    # compensate again. The boundary is the whole execution, not a
    # declared `Transaction` node (Phase 1 still has no syntax for one) —
    # RFC-0032 narrows RFC-0003's Transaction-node contract to that scope
    # for as long as the language has no other way to open one.
    ("policy", "rollback"):
        (ENFORCED, "run_workflow opens a transaction before its first step "
                   "and rolls it back on any failure, discarding every "
                   "write (and outbox registration) that run made"),
    # issue #108, RFC-0041: `run_workflow` now runs a `parallel` block's steps
    # on a block-scoped `ThreadPoolExecutor`, fail-fast, capped at the
    # declared value (or the block's own step count with no explicit cap).
    ("policy", "parallel"):
        (ENFORCED, "run_workflow executes a `parallel` block's steps "
                   "concurrently, cancels the rest on the first failure, and "
                   "caps concurrency at the declared value"),
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
    # issue #119, D6/D9: unlike `jwt` above, `role` has no live weak path to
    # name — a `security role` declaration that serves at all is checked,
    # because D6 refuses to even start `serve` without a token_provider
    # configured (`WsgiConfigError` -> rc 2). What is left once launch
    # succeeds is a single behaviour, not two paths to pick the weaker of.
    ("security", "role"):
        (ENFORCED, "every route the declaring service owns requires the "
                   "verified token's role to exactly match `<r>`; mismatch "
                   "or absence is 403 `forbidden` (docs/serving.md M3b)"),
    ("performance", "response"):
        (MEASURED, "measured and reported per run, but an over-budget run is not blocked"),
    ("performance", "cache"):
        (ENFORCED, "owns the TTL budget every CacheAccess set is written with"),
    # issue #108 D9: `policy parallel` (above) is what governs concurrent
    # *execution* now; these three stay UNENFORCED because they are storage-
    # access patterns (how a RepositoryCall is issued/batched), not execution
    # order — that meaning waits on query predicates (issue #116's
    # neighbourhood), out of this issue's scope.
    ("performance", "parallel"):
        (UNENFORCED, "parsed, but the execution plan never reads it"),
    ("performance", "prefetch"):
        (UNENFORCED, "parsed, but the execution plan never reads it"),
    ("performance", "batch"):
        (UNENFORCED, "parsed, but the execution plan never reads it"),
    # RFC-0016 + issue #81. A schedule trigger is a real declaration with a
    # real artifact — it reaches the IR and the OpenAPI schedule metadata —
    # and still stays UNENFORCED for the same reason `security jwt` does
    # (`TestPathDependentEnforcement` in test_enforcement_matrix.py): this
    # diagnostic is emitted at COMPILE time, which cannot know whether an
    # operator ever configured an external scheduler to call the trigger
    # surface issue #81 built. The default (compile, then do nothing else)
    # still runs no workflow; naming the path that does is what keeps the
    # status honest instead of a promise the default cannot keep.
    ("event", "schedule"):
        (UNENFORCED, "by default nothing calls it; `lnpl trigger --schedule "
                     "NAME` and `POST /-/schedules/<slug>` (`lnpl serve`) "
                     "run the linked workflow on demand, but only when an "
                     "external scheduler (cron/systemd — see `lnpl "
                     "schedules`) is configured to call one of them "
                     "(issue #81)"),
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


def format_lines_from_records(records):
    """Plain dict records (code/severity/where/subject/message/line) -> the
    lines to show a person, summary last. The record-shaped twin of
    `format_lines`, for a caller that has already merged core diagnostics
    (via `to_records`) with extension diagnostics (RFC-0042, issue #138) —
    the latter are never `Diagnostic` instances, so they only exist in this
    dict shape. `format_lines` itself delegates here so there stays one
    rendering rule.
    """
    if not records:
        return []
    lines = [
        ("%s: %s [%s] (line %d) %s — %s" % (r["severity"], r["code"], r["where"],
                                            r["line"], r["subject"], r["message"])
         if r["line"] is not None else
         "%s: %s [%s] %s — %s" % (r["severity"], r["code"], r["where"],
                                  r["subject"], r["message"]))
        for r in records
    ]
    infos = sum(1 for r in records if r["severity"] == "info")
    warnings = sum(1 for r in records if r["severity"] == "warning")
    errors = sum(1 for r in records if r["severity"] == "error")
    lines.append("%d info, %d warning(s), %d error(s)" % (infos, warnings, errors))
    return lines


def format_lines(diagnostics):
    """Diagnostics -> the lines to show a person, summary last.

    The only formatter. Every command that shows diagnostics renders them from
    here, so `compile` and `run` cannot drift into two different reports of the
    same fact. No diagnostics means no output at all — not even a summary — so
    a clean module stays quiet.
    """
    return format_lines_from_records(to_records(diagnostics))
