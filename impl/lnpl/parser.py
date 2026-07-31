"""LNPL parser — keyword-delimited blocks, no indentation semantics.

Produces a shallow declaration list (RFC-0002 §Declarations / §Clauses).
A top-level keyword closes the previous block; a clause keyword opens a
sub-section that closes at the next clause or top-level keyword.
"""

from .lexer import KEYWORDS_CLAUSE, KEYWORDS_TOP, tokenize

SERVICE_CLAUSES = ("goal", "policy", "security", "performance", "database")


class ParseError(Exception):
    """Raised when the token stream violates the grammar."""


class Decl:
    """One top-level declaration with its clauses and body items."""

    __slots__ = ("kind", "name", "lineno", "clauses", "items", "extra")

    def __init__(self, kind, name, lineno):
        self.kind = kind          # entity | service | workflow | event | capability
        self.name = name
        self.lineno = lineno
        self.clauses = {}         # clause keyword -> [Line]
        self.items = []           # workflow body: [Line]
        self.extra = {}           # event source, capability version

    def __repr__(self):
        return "Decl(%s %s)" % (self.kind, self.name)


def _require_name(line):
    if len(line.tokens) < 2:
        raise ParseError("line %d: %r needs a name" % (line.lineno, line.head))
    return line.tokens[1]


def parse(source):
    """source text -> [Decl] in source order."""
    lines = tokenize(source)
    decls = []
    cur = None          # current Decl
    cur_clause = None   # current clause keyword, or None

    for line in lines:
        head = line.head

        if head in KEYWORDS_TOP:
            name = _require_name(line)
            cur = Decl(head, name, line.lineno)
            cur_clause = None
            decls.append(cur)

            if head == "event" and len(line.tokens) > 2:
                # EventSource ::= 'on' PascalName ('create'|'update'|'delete')
                rest = line.tokens[2:]
                if rest[0] != "on" or len(rest) != 3:
                    raise ParseError(
                        "line %d: event source must be `on <Entity> "
                        "create|update|delete`" % line.lineno)
                if rest[2] not in ("create", "update", "delete"):
                    raise ParseError(
                        "line %d: event trigger must be create|update|delete, got %r"
                        % (line.lineno, rest[2]))
                cur.extra["on"] = (rest[1], rest[2])
            elif head == "capability" and len(line.tokens) > 2:
                cur.extra["version"] = line.tokens[2]
            elif head != "event" and len(line.tokens) > 2:
                raise ParseError(
                    "line %d: unexpected trailing tokens after `%s %s`"
                    % (line.lineno, head, name))
            continue

        if cur is None:
            raise ParseError(
                "line %d: %r appears before any declaration" % (line.lineno, head))

        if head in KEYWORDS_CLAUSE and len(line.tokens) == 1:
            # A bare clause keyword opens a sub-section. `when`/`parallel` are
            # context-sensitive: inside a workflow body they are control words,
            # so only treat them as clauses where the declaration allows it.
            if cur.kind == "entity" and head != "field":
                raise ParseError(
                    "line %d: entity allows only the `field` clause, got %r"
                    % (line.lineno, head))
            if cur.kind == "service" and head not in SERVICE_CLAUSES:
                raise ParseError(
                    "line %d: service allows %s, got %r"
                    % (line.lineno, "/".join(SERVICE_CLAUSES), head))
            if cur.kind in ("event", "capability"):
                raise ParseError(
                    "line %d: %s takes no clauses" % (line.lineno, cur.kind))
            cur_clause = head
            cur.clauses.setdefault(head, [])
            continue

        if cur.kind == "workflow" and cur_clause is None:
            cur.items.append(line)
            continue

        if cur_clause is None:
            raise ParseError(
                "line %d: content line %r outside any clause" % (line.lineno, line.tokens))

        cur.clauses[cur_clause].append(line)

    return decls
