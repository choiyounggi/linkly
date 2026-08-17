"""LNPL parser — keyword-delimited blocks, no indentation semantics.

Produces a shallow declaration list (RFC-0002 §Declarations / §Clauses).
A top-level keyword closes the previous block; a clause keyword opens a
sub-section that closes at the next clause or top-level keyword.
"""

from .lexer import (KEYWORDS_CLAUSE, KEYWORDS_TOP, SCHEDULE_AT,
                    SCHEDULE_KEYWORD, tokenize)
from .condition import parse_condition, ConditionError

SERVICE_CLAUSES = ("goal", "policy", "security", "performance", "database")
ENTITY_CLAUSES = ("field",)

# The sections of a `spec` block, and the full set a `workflow` accepts.
# RFC-0002 §Full grammar: WorkflowDecl ::= 'workflow' PascalName EOL
# WorkflowItem* SpecClause? — steps, then an optional spec block, nothing else.
SPEC_SECTIONS = ("given", "when", "expect")
WORKFLOW_CLAUSES = ("spec",) + SPEC_SECTIONS

# Which declaration each misplaced clause belongs to, so the error can say where
# to move it instead of only what is wrong (issue #53, N-3). Every clause keyword
# outside `WORKFLOW_CLAUSES` has a row: without one, a workflow body that names a
# clause keyword parses, `cur_clause` latches, and every later line is absorbed
# into the clause list that `lower` only ever reads off a `service` — the clause
# and the rest of the body both vanish with rc=0.
CLAUSE_OWNER = dict.fromkeys(SERVICE_CLAUSES, "service")
CLAUSE_OWNER.update(dict.fromkeys(ENTITY_CLAUSES, "entity"))


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
        pending = decl.extra.get("_pending_guard")
        if pending is not None:
            # Without this, the assignment below would overwrite `pending` and the
            # first guard would leave the IR with no diagnostic (issue #45, t2 F-2).
            raise ParseError("line %d: `%s` follows the guard on line %d, but a guard "
                             "owns exactly one step or block; write the two "
                             "conditions as one guard joined by `and` (RFC-0015)"
                             % (line.lineno, head, pending["lineno"]))
        # A guard opens a fresh layout scope, so whatever the previous guard's
        # indentation implied stops applying here — but not before this line is
        # itself judged against it (a guard can be the misindented line).
        _check_guard_layout(decl, line)
        decl.extra["_pending_guard"] = {"mode": head,
                                        "arg": " ".join(line.tokens[1:]),
                                        "lineno": line.lineno,
                                        "indent": line.indent}
        return

    _attach(decl, {"item": "step", "line": line}, line)


def _check_guard_layout(decl, line):
    """Reject a line indented into a guard's block that the guard does not own.

    Blocks stay keyword-delimited (RFC-0002 §Block structure), so this column
    never *builds* structure — it can only contradict the structure already
    built. That contradiction is the sole signal separating issue #53's N-1
    (`repeat` over two indented steps) from an ordinary following step: the two
    are token-identical, and the parse that silently split them reported nothing.

    Tracking stops at the first line judged, so only the item directly following
    the guarded one is in scope.
    """
    visual = decl.extra.pop("_guard_visual", None)
    if visual is None or line.indent <= visual["column"]:
        return
    raise ParseError(
        "line %d: this line is indented as if it were inside the `%s` guard on "
        "line %d, but a guard owns exactly one step or block — so it runs "
        "outside the guard. Wrap the steps in a `pipeline` block and let the "
        "guard own that, or dedent this line to the guard's own column "
        "(RFC-0002 §Block structure)"
        % (line.lineno, visual["mode"], visual["lineno"]))


def _attach(decl, item, line):
    """Place an item: inside an open block, under a pending guard, or at top level."""
    open_block = decl.extra.get("_open_block")
    if open_block is not None and item["item"] == "step":
        open_block["steps"].append(line)
        return
    guard = decl.extra.pop("_pending_guard", None)
    if guard is None:
        _check_guard_layout(decl, line)
    else:
        item = {"item": "guard", "guard": guard, "guarded": item}
        # Only a guarded item written *deeper* than its guard makes a following
        # deeper line misleading. At the guard's own column — the style
        # `examples/guarded.lnpl` uses — layout and structure already agree.
        if line.indent > guard["indent"]:
            decl.extra["_guard_visual"] = {"column": guard["indent"],
                                           "lineno": guard["lineno"],
                                           "mode": guard["mode"]}
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
                #               | 'on' 'schedule' Recurrence 'at' TimeOfDay Zone
                rest = line.tokens[2:]
                if rest[0] != "on":
                    raise ParseError(
                        "line %d: event source must be `on <Entity> "
                        "create|update|delete` or `on schedule <every> at "
                        "<HH:MM> <zone>`" % line.lineno)
                if len(rest) > 1 and rest[1] == SCHEDULE_KEYWORD:
                    # Shape only. Which recurrence, which clock time and which
                    # zone are admissible is a closed-set judgement, and this
                    # module has no diagnostics channel to name the allowed set
                    # in — `lower` owns that, as it does for policy and
                    # performance names.
                    if len(rest) != 6 or rest[3] != SCHEDULE_AT:
                        raise ParseError(
                            "line %d: a schedule source must be `on schedule "
                            "<every> at <HH:MM> <zone>` (for example: `on "
                            "schedule daily at 00:00 UTC`)" % line.lineno)
                    cur.extra["schedule"] = {"every": rest[2], "at": rest[4],
                                             "zone": rest[5]}
                    continue
                if len(rest) != 3:
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
            # A workflow had no allowlist, so a clause keyword meant for another
            # declaration latched `cur_clause` and swallowed the body silently
            # (issue #53, N-3). entity and service are checked just above; this
            # closes the one kind that was not.
            if cur.kind == "workflow" and head not in WORKFLOW_CLAUSES:
                owner = CLAUSE_OWNER[head]
                raise ParseError(
                    "line %d: `%s` is a `%s` clause and cannot appear in a "
                    "`workflow` body; move it to the owning `%s` declaration — "
                    "a workflow takes steps and an optional `spec` block "
                    "(RFC-0002 §Full grammar: WorkflowItem* SpecClause?)"
                    % (line.lineno, head, owner, owner))
            if (cur.kind == "workflow" and head in SPEC_SECTIONS
                    and not cur.extra.get("specs")):
                raise ParseError(
                    "line %d: `%s` belongs inside a `spec` block; open one with "
                    "`spec` before it (RFC-0002 §Full grammar: SpecClause)"
                    % (line.lineno, head))
            # Each `spec` keyword opens a NEW block (issue #46): its
            # given/when/expect sections live on the block, not in the shared
            # clause lists — sharing them is what silently merged blocks.
            if cur.kind == "workflow" and head == "spec":
                cur.extra.setdefault("specs", []).append(
                    {"given": [], "when": [], "expect": [],
                     "lineno": line.lineno, "_opened": set(),
                     "_indent": line.indent, "_section_indent": None})
            elif (cur.kind == "workflow" and head in ("given", "when", "expect")
                    and cur.extra.get("specs")):
                block = cur.extra["specs"][-1]
                if head in block["_opened"]:
                    raise ParseError(
                        "line %d: a second `%s` inside one spec block — "
                        "open a new `spec` block per scenario"
                        % (line.lineno, head))
                block["_opened"].add(head)
                block["_section_indent"] = line.indent
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
            # Exhaustive listing (issue #63), matching the compiler's existing
            # closed-set diagnostics (type errors, workflow id errors, spec
            # `given` errors) instead of guessing at the typo. `workflow` is
            # not listed here: line 300 above always consumes a workflow-body
            # content line as a step before this branch runs, so `workflow`
            # never reaches it.
            if cur.kind == "service":
                raise ParseError(
                    "line %d: content line %r outside any clause — a `service` "
                    "declaration opens: %s"
                    % (line.lineno, line.tokens, ", ".join(SERVICE_CLAUSES)))
            if cur.kind == "entity":
                raise ParseError(
                    "line %d: content line %r outside any clause — an `entity` "
                    "declaration opens: %s"
                    % (line.lineno, line.tokens, ", ".join(ENTITY_CLAUSES)))
            raise ParseError(
                "line %d: content line %r outside any clause — %s `%s` "
                "declaration takes no clause lines"
                % (line.lineno, line.tokens,
                   "an" if cur.kind == "event" else "a", cur.kind))

        if (cur.kind == "workflow" and cur_clause in SPEC_SECTIONS
                and cur.extra.get("specs")):
            block = cur.extra["specs"][-1]
            # A step written after the block was absorbed by whichever section
            # was open, so it never became a workflow item (issue #53, N-5).
            # Only the author's column separates it from a legitimate section
            # line, so the rule engages only where that column says something —
            # a spec written flat carries no signal and is left alone.
            section_indent = block["_section_indent"]
            if (section_indent is not None
                    and section_indent > block["_indent"]
                    and line.indent <= block["_indent"]):
                raise ParseError(
                    "line %d: a workflow step cannot follow the `spec` block "
                    "opened on line %d — a workflow's steps come before its "
                    "`spec` (RFC-0002 §Full grammar: WorkflowItem* SpecClause?); "
                    "move this line above the block"
                    % (line.lineno, block["lineno"]))
            block[cur_clause].append(line)
            continue
        cur.clauses[cur_clause].append(line)

    for d in decls:
        d.extra.pop("_guard_visual", None)     # scratch state, never lowered
        open_block = d.extra.pop("_open_block", None)
        if open_block is not None and open_block["type"] == "parallel":
            raise ParseError("declaration %s ends with an unclosed `parallel` block "
                             "(missing `merge`)" % d.name)
        if d.extra.pop("_pending_guard", None) is not None:
            raise ParseError("declaration %s ends with a guard that guards nothing"
                             % d.name)
        for block in d.extra.get("specs", []):
            block.pop("_opened", None)
            block.pop("_indent", None)
            block.pop("_section_indent", None)
    return decls
