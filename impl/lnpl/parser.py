"""LNPL parser — keyword-delimited blocks, no indentation semantics.

Produces a shallow declaration list (RFC-0002 §Declarations / §Clauses).
A top-level keyword closes the previous block; a clause keyword opens a
sub-section that closes at the next clause or top-level keyword.
"""

from .lexer import KEYWORDS_CLAUSE, KEYWORDS_TOP, tokenize
from .condition import parse_condition, ConditionError

SERVICE_CLAUSES = ("goal", "policy", "security", "performance", "database")


class ParseError(Exception):
    """Raised when the token stream violates the grammar."""


class Decl:
    """One top-level declaration with its clauses and body items."""

    __slots__ = ("kind", "name", "lineno", "clauses", "items", "extra")

    def __init__(self, kind, name, lineno):
        self.kind = kind          # entity | service | workflow | event | capability | refine
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


def _append_workflow_item(decl, line):
    """Build the workflow body as a list of items.

    An item is either a plain step line, a guard (which owns the item that
    follows it), or a block (`parallel` ... `merge`, `pipeline` ...). Blocks are
    closed by their own keyword, never by indentation (RFC-0002 §Block structure).
    """
    head = line.head
    open_block = decl.extra.get("_open_block")

    if head == "merge":
        if open_block is None or open_block["type"] != "parallel":
            raise ParseError("line %d: `merge` closes a `parallel` block, but none is open"
                             % line.lineno)
        decl.extra.pop("_open_block")
        return

    if head in ("parallel", "pipeline"):
        # `parallel` waits for `merge`; `pipeline` closes at the next keyword, so a
        # new block only conflicts with an open `parallel`.
        if open_block is not None and open_block["type"] == "parallel":
            raise ParseError("line %d: `%s` cannot nest inside `parallel` "
                             "(nesting depth is capped at 2 — RFC-0002 §Block structure)"
                             % (line.lineno, head))
        if head == "pipeline" and len(line.tokens) > 2:
            raise ParseError("line %d: `pipeline` takes at most one name" % line.lineno)
        if head == "parallel" and len(line.tokens) > 1:
            raise ParseError("line %d: `parallel` takes no name" % line.lineno)
        decl.extra.pop("_open_block", None)      # an open pipeline ends here
        block = {"type": head, "lineno": line.lineno, "steps": [],
                 "name": line.tokens[1] if len(line.tokens) > 1 else None}
        _attach(decl, {"item": "block", "block": block}, line)
        decl.extra["_open_block"] = block
        return

    if head in ("when", "until", "repeat"):
        if len(line.tokens) < 2:
            raise ParseError("line %d: `%s` needs %s"
                             % (line.lineno, head,
                                "a count" if head == "repeat" else "a condition"))
        if head == "repeat" and not line.tokens[1].isdigit():
            raise ParseError("line %d: `repeat` needs an integer count" % line.lineno)
        # RFC-0008: validate condition syntax at parse time
        if head in ("when", "until"):
            cond_str = " ".join(line.tokens[1:])
            try:
                parse_condition(cond_str)  # validate; raise ConditionError if invalid
            except ConditionError as e:
                raise ParseError("line %d: invalid condition: %s" % (line.lineno, e))
        if open_block is not None and open_block["type"] == "parallel":
            raise ParseError("line %d: a guard cannot appear inside a `parallel` block "
                             "(close it with `merge` first)" % line.lineno)
        decl.extra.pop("_open_block", None)      # an open pipeline ends here
        decl.extra["_pending_guard"] = {"mode": head,
                                        "arg": " ".join(line.tokens[1:]),
                                        "lineno": line.lineno}
        return

    _attach(decl, {"item": "step", "line": line}, line)


def _attach(decl, item, line):
    """Place an item: inside an open block, under a pending guard, or at top level."""
    open_block = decl.extra.get("_open_block")
    if open_block is not None and item["item"] == "step":
        open_block["steps"].append(line)
        return
    guard = decl.extra.pop("_pending_guard", None)
    if guard is not None:
        item = {"item": "guard", "guard": guard, "guarded": item}
    decl.items.append(item)


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
            elif head == "refine":
                # RefineDecl ::= 'refine' PascalName 'of' BaseTypeName EOL FacetLine+
                rest = line.tokens[2:]
                if len(rest) != 2 or rest[0] != "of":
                    raise ParseError(
                        "line %d: refinement must be `refine <Name> of <BaseType>`"
                        % line.lineno)
                cur.extra["base"] = rest[1]
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
            if cur.kind in ("event", "capability", "refine"):
                raise ParseError(
                    "line %d: %s takes no clauses" % (line.lineno, cur.kind))
            cur_clause = head
            cur.clauses.setdefault(head, [])
            continue

        if cur.kind == "workflow" and cur_clause is None:
            _append_workflow_item(cur, line)
            continue

        if cur.kind == "refine" and cur_clause is None:
            # FacetLine+ sits directly under the declaration: `refine` has no
            # clause keyword (RFC-0002 §Full grammar). Values are checked when
            # lowering, where the base decides which facets apply.
            cur.items.append(line)
            continue

        if cur_clause is None:
            raise ParseError(
                "line %d: content line %r outside any clause" % (line.lineno, line.tokens))

        cur.clauses[cur_clause].append(line)

    for d in decls:
        open_block = d.extra.pop("_open_block", None)
        if open_block is not None and open_block["type"] == "parallel":
            raise ParseError("declaration %s ends with an unclosed `parallel` block "
                             "(missing `merge`)" % d.name)
        if d.extra.pop("_pending_guard", None) is not None:
            raise ParseError("declaration %s ends with a guard that guards nothing"
                             % d.name)
    return decls
