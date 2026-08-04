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

DURATION_UNITS = ("ms", "s", "m")
COMPARATORS = ("<=", ">=", "<", ">")


class LexError(Exception):
    """Raised when a line cannot be tokenized."""


class Line:
    """One significant source line, indentation stripped."""

    __slots__ = ("lineno", "tokens", "raw")

    def __init__(self, lineno, tokens, raw):
        self.lineno = lineno
        self.tokens = tokens
        self.raw = raw

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
        body = _strip_comment(raw).strip()
        if not body:
            continue
        tokens = body.split()
        for t in tokens:
            if t in RESERVED:
                raise LexError(
                    "line %d: %r is reserved and must not be used "
                    "(RFC-0002 §Reserved Words)" % (i, t))
        lines.append(Line(i, tokens, raw))
    return lines


def is_duration(tok):
    for unit in ("ms", "s", "m"):
        if tok.endswith(unit) and tok[: -len(unit)].isdigit() and tok[: -len(unit)]:
            return True
    return False


def parse_duration_ms(tok):
    """`3s` -> 3000. Raises LexError on a non-duration token."""
    for unit, mult in (("ms", 1), ("s", 1000), ("m", 60000)):
        if tok.endswith(unit):
            head = tok[: -len(unit)]
            if head.isdigit() and head:
                return int(head) * mult
    raise LexError("not a duration: %r" % tok)
