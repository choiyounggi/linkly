"""LNPL lexer — line-oriented tokenizer.

RFC-0002 §Lexical / §Block structure:
  - one declaration per line; indentation is NOT significant (stripped)
  - `#` starts a comment to end of line
  - blocks are delimited by keywords, never by indentation
"""

KEYWORDS_TOP = ("entity", "service", "workflow", "event", "capability", "refine")
KEYWORDS_CLAUSE = ("field", "goal", "policy", "security", "performance",
                   "database", "spec", "given", "when", "expect")
KEYWORDS_CONTROL = ("when", "repeat", "parallel", "until", "pipeline", "merge")
RESERVED = ("if", "for", "while", "switch")

# RFC-0016 widened this from `ms`/`s`/`m`. `h` and `d` are exact integer counts
# of milliseconds, so they add a table row and no semantics — unlike `w`/`mo`/`y`,
# whose lengths are not constant and which therefore stay out of the language.
#
# ONE table. The multiplier used to be spelled out at five call sites (`lexer`
# twice, `condition`, `interp`, `backend`); a unit added to only four of them
# parses here and then fails in whichever mode still held the short list, which
# is a mode divergence rather than an error the author can read.
DURATION_UNIT_MS = {"ms": 1, "s": 1000, "m": 60000,
                    "h": 3600000, "d": 86400000}

# i64 — the domain mode B compiles to. Defined here, in the module that imports
# nothing, so the duration table above can range-check without importing
# `condition` (which imports THIS module). `condition` re-exports both names, so
# every existing `from .condition import INT64_MAX` keeps working.
INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1

DURATION_UNITS = ("ms", "s", "m", "h", "d")

# Longest suffix first: `ms` must be tested before `s`, or `3ms` reads as `3m`
# followed by a stray `s`.
DURATION_SCAN = tuple(sorted(DURATION_UNIT_MS.items(), key=lambda kv: -len(kv[0])))

# Two-character comparators come first: a consumer that scans this table in order
# must see `<=` before `<`, or every `<=` reads as `<` followed by a stray `=`.
# RFC-0008 §1 fixed the six; RFC-0015 is what put `==`/`!=` in the generated
# reference, where their absence had left authors unable to tell which of the RFC
# and the reference was the implementation (t4 F-7).
COMPARATORS = ("<=", ">=", "==", "!=", "<", ">")

# RFC-0015 value expressions. `*` and `/` are deliberately absent: nothing in
# issue #47 needs them, and division would have to answer for rounding and for
# division by zero in two runtimes at once.
ARITH_OPS = ("+", "-")

# The one logical combinator. `or`/`not` are not in the language.
LOGICAL_OPS = ("and",)

# The assignment step, `set <reference> to <value>`.
ASSIGN_KEYWORDS = ("set", "to")

# The reserved namespace naming the run's input payload: `input.quantity`.
PAYLOAD_NAMESPACE = "input"

# RFC-0016 schedule triggers: `event DailyRollup on schedule daily at 00:00 UTC`.
#
# Each set is closed and deliberately small. `daily` is the only recurrence
# because it is the only one issue #49 asks for, and a cron expression is a
# language of its own rather than a word in this one. `UTC` is the only zone
# because an IANA name would have to be resolved against the build machine's tz
# database — which would make the set of accepted programs depend on the machine
# doing the accepting. Both are RFC-0016 §Open Questions.
SCHEDULE_KEYWORD = "schedule"
SCHEDULE_AT = "at"
SCHEDULE_RECURRENCES = ("daily",)
SCHEDULE_ZONES = ("UTC",)

# The closed set of event-source kinds that carry an enforcement status, i.e.
# the ones `diagnostics.ENFORCEMENT` speaks about. Entity sources (`on Order
# create`) are equally unenforced today, but giving them a row would start
# warning on every `event` declaration in every existing document — a behaviour
# change issue #49 does not ask for. RFC-0016 §Open Questions records it.
EVENT_TRIGGERS = ("schedule",)


class LexError(Exception):
    """Raised when a line cannot be tokenized."""


class Line:
    """One significant source line, indentation stripped from `tokens`.

    `indent` is the column the line starts at. It is recorded, never used to
    build structure: RFC-0002 keeps blocks keyword-delimited, so the same token
    sequence still parses the same way whatever the layout. `parser` reads the
    column only to reject a layout that contradicts the structure it parsed —
    a guard's second "indented" step, which is otherwise token-identical to an
    ordinary following step (issue #53, N-1).

    Required rather than defaulted: a `Line` built without a real column would
    silently disable that check, which is the failure shape this closes.
    """

    __slots__ = ("lineno", "tokens", "raw", "indent")

    def __init__(self, lineno, tokens, raw, indent):
        self.lineno = lineno
        self.tokens = tokens
        self.raw = raw
        self.indent = indent

    @property
    def head(self):
        return self.tokens[0] if self.tokens else None

    def __repr__(self):
        return "Line(%d, %r)" % (self.lineno, self.tokens)


def _strip_comment(text):
    idx = text.find("#")
    return text if idx < 0 else text[:idx]


def tokenize(source):
    """Split source into significant Lines.

    Blank lines and comment-only lines are dropped: they carry no meaning
    (RFC-0002 `BlankLine`/`Comment` produce no IR node).
    """
    lines = []
    for i, raw in enumerate(source.splitlines(), start=1):
        if "\t" in raw:
            raise LexError("line %d: tabs are forbidden (RFC-0002 §Block structure)" % i)
        body = _strip_comment(raw)
        text = body.strip()
        if not text:
            continue
        # Measured after the comment is removed, so `    # note` never counts as
        # a line and a trailing comment cannot shift the column.
        indent = len(body) - len(body.lstrip())
        tokens = text.split()
        for t in tokens:
            if t in RESERVED:
                raise LexError(
                    "line %d: %r is reserved and must not be used "
                    "(RFC-0002 §Reserved Words)" % (i, t))
        lines.append(Line(i, tokens, raw, indent))
    return lines


def is_duration(tok):
    for unit, _mult in DURATION_SCAN:
        if tok.endswith(unit) and tok[: -len(unit)].isdigit() and tok[: -len(unit)]:
            return True
    return False


def duration_ms_or_none(tok):
    """`3s` -> 3000; None when `tok` is not a duration.

    The one place the unit table is read. Callers that need an exception raise
    their own module's error, so a duration is spelled the same in the lexer,
    the condition parser, the interpreter and the backend.

    Raises OverflowError when the value does not fit the i64 domain both modes
    compile to (RFC-0015 §Value domain): Python integers are unbounded, so
    without this check `99999999999999999999d` would evaluate in mode A and
    truncate in mode B.
    """
    for unit, mult in DURATION_SCAN:
        if tok.endswith(unit):
            head = tok[: -len(unit)]
            if head.isdigit() and head:
                value = int(head) * mult
                if value > INT64_MAX:
                    raise OverflowError(
                        "duration %r is %d ms, past the 64-bit domain both "
                        "modes compile to" % (tok, value))
                return value
    return None


def parse_duration_ms(tok):
    """`3s` -> 3000. Raises LexError on a non-duration token."""
    try:
        value = duration_ms_or_none(tok)
    except OverflowError as e:
        raise LexError(str(e))
    if value is None:
        raise LexError("not a duration: %r" % tok)
    return value
