"""LNPL -> Semantic IR lowering (RFC-0002 Appendix A).

Two rules decided here are the ones RFC-0002 A.4 left open:

R2 — node id derivation (A.4-7). One uniform rule:
    id = <kind prefix> "." <name split at PascalCase boundaries, lowercased,
                            joined by ".", with a trailing segment that merely
                            repeats the kind's own word removed>
  so `LoginService` as a Service becomes `svc.login`, while `UserCreated` as an
  Event keeps both segments (`created` is not the word "event") -> `event.user.created`.

R1 — Effect derivation (A.4-3). A step line's first token is a Verb (the grammar
  guarantees it), so deriving effects is a *lookup in a closed lexicon*, not
  inference. Authors keep declaring intent; the mapping stays deterministic.
  A verb outside the lexicon derives no Effect — silence, never a guess.
"""

import re

from .lexer import COMPARATORS, is_duration
from .refinements import (BASE_CATEGORY, FACET_NAMES, PRESETS, facets_for_base,
                          preset)

KIND_PREFIX = {
    "Entity": "entity",
    "Service": "svc",
    "Workflow": "wf",
    "Event": "event",
    "Capability": "cap",
    "Refinement": "refine",
    "Policy": "policy",
    "Security": "security",
    "Performance": "perf",
}

# The word each declaration kind "is" — a trailing name segment equal to it is
# redundant and gets stripped (R2).
KIND_WORD = {
    "Entity": "entity",
    "Service": "service",
    "Workflow": "workflow",
    "Event": "event",
    "Capability": "capability",
}

# Short slug per derived Effect kind, used as the last id segment (R2).
GUARD_SLUG = {"when": "when", "until": "until", "repeat": "repeat"}

EFFECT_SLUG = {
    "Validation": "check",
    "RepositoryCall": "repo",
    "CacheAccess": "cache",
    "NetworkCall": "net",
    "Transaction": "tx",
    "Authorization": "authz",
    "EventEmit": "emit",
    "BusinessRule": "rule",
}

# R1: the closed step-verb lexicon. verb -> (Effect kind, fixed fields)
VERB_LEXICON = {
    "validate": ("Validation", {}),
    "authenticate": ("RepositoryCall", {"operation": "read"}),
    "load": ("RepositoryCall", {"operation": "read"}),
    "find": ("RepositoryCall", {"operation": "read"}),
    "read": ("RepositoryCall", {"operation": "read"}),
    "create": ("RepositoryCall", {"operation": "create"}),
    "insert": ("RepositoryCall", {"operation": "create"}),
    "update": ("RepositoryCall", {"operation": "update"}),
    "delete": ("RepositoryCall", {"operation": "delete"}),
    "cache": ("CacheAccess", {"operation": "set"}),
    "invalidate": ("CacheAccess", {"operation": "invalidate"}),
    "call": ("NetworkCall", {}),
    "request": ("NetworkCall", {}),
    "emit": ("EventEmit", {}),
    "publish": ("EventEmit", {}),
    "authorize": ("Authorization", {}),
}

# Refinement surface forms (RFC-0002 §Full grammar).
PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")      # PascalName
NUMBER_RE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")    # Number
WORD_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")        # Word

POLICY_NAMES = ("retry", "rollback", "timeout", "parallel")
PERF_METRICS = ("response", "cache", "parallel", "prefetch", "batch")
VALUELESS_PERF = ("parallel", "prefetch", "batch")


class LowerError(Exception):
    """Raised when a declaration cannot be lowered to IR."""


def split_pascal(name):
    """`UserCreated` -> ['user', 'created']; `postgres` -> ['postgres']."""
    parts, cur = [], ""
    for ch in name:
        if ch.isupper() and cur:
            parts.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return [p.lower() for p in parts]


def derive_segments(name, kind):
    """R2 segment derivation, including the redundant-kind-word strip."""
    parts = split_pascal(name)
    word = KIND_WORD.get(kind)
    if word and len(parts) > 1 and parts[-1] == word:
        parts = parts[:-1]
    return parts


def derive_id(name, kind):
    """R2: full node id for a declaration."""
    if kind not in KIND_PREFIX:
        raise LowerError("no id prefix defined for kind %r" % kind)
    return ".".join([KIND_PREFIX[kind]] + derive_segments(name, kind))


class Module:
    """Lowered module: a flat node table plus the emit order (RFC-0001 D17)."""

    def __init__(self, name):
        self.name = name
        self._nodes = {}
        self._order = []

    def add(self, node):
        nid = node["id"]
        if nid in self._nodes:
            raise LowerError("duplicate node id %r" % nid)
        self._nodes[nid] = node
        self._order.append(nid)
        return node

    def get(self, nid):
        return self._nodes.get(nid)

    def nodes(self):
        return [self._nodes[i] for i in self._order]

    def to_document(self, version="0.1"):
        return {"lir_version": version, "module": self.name, "nodes": self.nodes()}


def _node(kind, nid, **fields):
    node = {"kind": kind, "id": nid}
    node.update({k: v for k, v in fields.items() if v is not None})
    return node


def _parse_policy_line(tokens, lineno):
    head = tokens[0]
    if head not in POLICY_NAMES:
        raise LowerError("line %d: unknown policy %r (allowed: %s)"
                         % (lineno, head, ", ".join(POLICY_NAMES)))
    if head == "retry":
        if len(tokens) != 2 or not tokens[1].isdigit():
            raise LowerError("line %d: `retry` needs an integer" % lineno)
        return {"name": "retry", "value": int(tokens[1])}
    if head == "timeout":
        if len(tokens) != 2 or not is_duration(tokens[1]):
            raise LowerError("line %d: `timeout` needs a duration (e.g. 3s)" % lineno)
        return {"name": "timeout", "value": tokens[1]}
    if len(tokens) != 1:
        raise LowerError("line %d: `%s` takes no argument" % (lineno, head))
    return {"name": head}


def _parse_perf_line(tokens, lineno):
    metric = tokens[0]
    if metric not in PERF_METRICS:
        raise LowerError("line %d: unknown performance metric %r (allowed: %s)"
                         % (lineno, metric, ", ".join(PERF_METRICS)))
    if metric in VALUELESS_PERF:
        # A flag metric carries no value; `budgets[].value` is optional for exactly
        # this reason (schema revision 2026-07-31, formerly gap A.4-5).
        if len(tokens) != 1:
            raise LowerError("line %d: `%s` is a flag and takes no value"
                             % (lineno, metric))
        return {"metric": metric}
    if metric == "response":
        if len(tokens) != 3 or tokens[1] not in COMPARATORS:
            raise LowerError("line %d: `response` needs <comparator> <duration>" % lineno)
        return {"metric": "response", "value": tokens[1] + tokens[2]}
    if len(tokens) != 2:
        raise LowerError("line %d: `%s` needs one value" % (lineno, metric))
    return {"metric": metric, "value": tokens[1]}


def _parse_security_line(tokens, lineno):
    head = tokens[0]
    if head == "jwt":
        if len(tokens) != 1:
            raise LowerError("line %d: `jwt` takes no argument" % lineno)
        return "jwt"
    if head in ("role", "encrypt"):
        if len(tokens) != 2:
            raise LowerError("line %d: `%s` needs one argument" % (lineno, head))
        return head + " " + tokens[1]
    raise LowerError("line %d: unknown security mechanism %r "
                     "(allowed: jwt, role <r>, encrypt <field>)" % (lineno, head))


def _number(tok):
    """RFC-0002 `Number` -> int when it has no fraction, else float.

    `min 1` must stay `1`: the A.6.4 fragment for PositiveInteger writes an
    integer, and a float would serialize as 1.0 and stop matching it.
    """
    return float(tok) if "." in tok else int(tok)


def _enum_value(tok, lineno):
    """RFC-0002 `EnumValue ::= Word | Number`."""
    if NUMBER_RE.match(tok):
        return _number(tok)
    if WORD_RE.match(tok):
        return tok
    raise LowerError("line %d: %r is not a valid enum value (a Word or a Number)"
                     % (lineno, tok))


def _check_enum_member(value, base, lineno):
    """RFC-0011 A.6.3 — a member must be a value the base can actually hold.

    `Integer` is narrower than its category: `enum` enumerates the admissible
    values, so a member with a fractional part is dead. `min`/`max` are bounds
    and stay category-wide — `min 1.5` on an Integer still admits every int >= 2.
    """
    if BASE_CATEGORY[base] == "text":
        ok, form = isinstance(value, str), "a Word"
    elif base == "Integer":
        ok, form = isinstance(value, int), "a Number with no fractional part"
    else:                       # Decimal -- the only other base admitting enum
        ok, form = isinstance(value, (int, float)), "a Number"
    if not ok:
        raise LowerError("line %d: enum value %r cannot be a value of base %r "
                         "(allowed: %s — RFC-0011 A.6.3)"
                         % (lineno, value, base, form))


def _parse_facet_line(tokens, lineno, allowed, base):
    """One FacetLine -> (name, value). RFC-0001 A.6.3 / RFC-0002 §Full grammar.

    The order of the checks is a contract the tests rely on: vocabulary, then
    applicability to the base's category, then arity, then value form. So
    `maxLength` on a Boolean fails as inapplicable, not as a bad number.
    """
    name = tokens[0]
    if name not in FACET_NAMES:
        raise LowerError("line %d: unknown facet %r (allowed: %s)"
                         % (lineno, name, ", ".join(FACET_NAMES)))
    if name not in allowed:
        raise LowerError(
            "line %d: facet %r does not apply to base %r (allowed: %s)"
            % (lineno, name, base,
               ", ".join(sorted(allowed)) or "none — this base admits no facets"))
    if name == "enum":
        if len(tokens) < 2:
            raise LowerError("line %d: `enum` needs at least one value" % lineno)
        values = [_enum_value(t, lineno) for t in tokens[1:]]
        for value in values:
            _check_enum_member(value, base, lineno)
        return name, values
    if len(tokens) != 2:
        raise LowerError("line %d: `%s` needs exactly one value" % (lineno, name))
    if name == "pattern":
        # A space or `#` inside the regex is removed by the lexer before we see
        # it, so compiling the value is what catches a truncation that breaks a
        # construct (`^a[b#c]$` -> `^a[b`). A truncation that still compiles
        # (`^a#b$` -> `^a`) survives — see test_KNOWN_LIMITATION_* in test_lower.
        try:
            re.compile(tokens[1])
        except re.error as exc:
            raise LowerError(
                "line %d: `pattern` is not a valid regex: %s (a space or `#` "
                "inside the regex is removed by the lexer — RFC-0002 §Full grammar)"
                % (lineno, exc))
        return name, tokens[1]
    if name in ("minLength", "maxLength"):
        if not tokens[1].isdigit():
            raise LowerError("line %d: `%s` needs a non-negative integer, got %r"
                             % (lineno, name, tokens[1]))
        return name, int(tokens[1])
    if not NUMBER_RE.match(tokens[1]):
        raise LowerError("line %d: `%s` needs a number, got %r"
                         % (lineno, name, tokens[1]))
    return name, _number(tokens[1])


def _refinement_node(name, base, facets):
    """A.6.2 — the one Refinement node shape.

    A user declaration and a built-in preset both come through here, so a preset
    serializes to exactly the node the user would have written (A.6.4: presets
    are not privileged).
    """
    return _node("Refinement", derive_id(name, "Refinement"),
                 name=name, base=base, facets=facets)


def _lower_refine(decl, taken):
    """One `refine` block -> a Refinement node. A.7 invariants b/c/d/e live here."""
    if not PASCAL_RE.match(decl.name):
        raise LowerError("line %d: refinement name %r must be PascalCase"
                         % (decl.lineno, decl.name))
    base = decl.extra["base"]
    if base not in BASE_CATEGORY:
        raise LowerError(
            "line %d: %r is not one of the 18 semantic types — a refinement's "
            "base cannot itself be a refinement (RFC-0001 A.6.2)"
            % (decl.lineno, base))
    if decl.name in taken:
        raise LowerError(
            "line %d: %r is already a semantic type, a built-in preset, an "
            "entity, or a refinement declared in this module "
            "(RFC-0001 A.6.2, RFC-0011 A.7)"
            % (decl.lineno, decl.name))
    allowed = facets_for_base(base)
    facets = {}
    for line in decl.items:
        name, value = _parse_facet_line(line.tokens, line.lineno, allowed, base)
        if name in facets:
            raise LowerError("line %d: facet %r is given twice" % (line.lineno, name))
        facets[name] = value
    if not facets:
        raise LowerError("refinement %s declares no facets" % decl.name)
    return _refinement_node(decl.name, base, facets)


def _resolve_type(name, refined_names, used_presets, lineno):
    """A.6.1 name resolution. Returns `name` unchanged — `fields[].type` holds a
    type name, never a node id.

    Order: the 18 base names, then this document's Refinements. A built-in preset
    a field names joins that second group and is recorded so it gets emitted
    (A.6.4 emit-on-use), which is what makes the document self-contained.
    """
    if name in BASE_CATEGORY or name in refined_names:
        return name
    if name in PRESETS:
        if name not in used_presets:
            used_presets.append(name)      # first-use order keeps output stable
        return name
    raise LowerError(
        "line %d: %r is not one of the 18 semantic types, a refinement declared "
        "in this module, or a built-in preset (RFC-0001 A.6.1)" % (lineno, name))


def lower(decls, module_name):
    """[Decl] -> Module, emitting nodes in RFC-0001 canonical order."""
    mod = Module(module_name)

    by_kind = {"capability": [], "entity": [], "event": [], "service": [],
               "workflow": [], "refine": []}
    for d in decls:
        by_kind[d.kind].append(d)

    # ---- Refinements (RFC-0001 A.6). A declared block becomes a node whether or
    # not a field names it; the built-in presets are appended on use, below.
    # RFC-0011 A.7 (e): an entity and a refinement land in one
    # `components/schemas` name space, so a collision must fail here rather than
    # at generation time. `by_kind` is built above, so an entity declared later
    # in the file than the `refine` still takes its name.
    taken = set(BASE_CATEGORY) | set(PRESETS) | {d.name for d in by_kind["entity"]}
    refine_nodes = []
    refined_names = set()
    used_presets = []
    for d in by_kind["refine"]:
        refine_nodes.append(_lower_refine(d, taken))
        taken.add(d.name)
        refined_names.add(d.name)

    # Entity registry. A module may declare several entities; a step selects one
    # by naming it as its object (`load order`), which the grammar already gives us.
    # With a single entity the object may be omitted, as the golden scenario does.
    registry = {}
    for decl in by_kind["entity"]:
        fields = []
        for line in decl.clauses.get("field", []):
            if len(line.tokens) != 2:
                raise LowerError("line %d: field must be `<name> <Type>`" % line.lineno)
            fields.append({"name": line.tokens[0],
                           "type": _resolve_type(line.tokens[1], refined_names,
                                                 used_presets, line.lineno)})
        if not fields:
            raise LowerError("entity %s declares no fields" % decl.name)
        eid = derive_id(decl.name, "Entity")
        if eid in registry:
            raise LowerError("two entities derive the same id %r" % eid)
        registry[eid] = {"decl": decl, "id": eid, "name": decl.name, "fields": fields}

    cap_ids = [derive_id(d.name, "Capability") for d in by_kind["capability"]]
    cap_by_name = {d.name: derive_id(d.name, "Capability") for d in by_kind["capability"]}

    # ---- workflow ownership: nearest preceding service (RFC-0002 A.2 R2) ----
    owner_of = {}
    last_service = None
    for d in decls:
        if d.kind == "service":
            last_service = d
        elif d.kind == "workflow":
            owner_of[id(d)] = last_service

    # ---- Service nodes (+ their constraints, emitted later) ----
    service_nodes, constraint_nodes = [], []
    for d in by_kind["service"]:
        sid = derive_id(d.name, "Service")
        segs = derive_segments(d.name, "Service")
        constraints = []
        if "policy" in d.clauses:
            pid = ".".join([KIND_PREFIX["Policy"]] + segs)
            rules = [_parse_policy_line(l.tokens, l.lineno) for l in d.clauses["policy"]]
            constraint_nodes.append(_node("Policy", pid, rules=rules))
            constraints.append(pid)
        if "security" in d.clauses:
            secid = ".".join([KIND_PREFIX["Security"]] + segs)
            mechs = [_parse_security_line(l.tokens, l.lineno) for l in d.clauses["security"]]
            constraint_nodes.append(_node("Security", secid, mechanisms=mechs))
            constraints.append(secid)
        if "performance" in d.clauses:
            perfid = ".".join([KIND_PREFIX["Performance"]] + segs)
            budgets = [_parse_perf_line(l.tokens, l.lineno) for l in d.clauses["performance"]]
            constraint_nodes.append(_node("Performance", perfid, budgets=budgets))
            constraints.append(perfid)
        # Capability attribution (formerly the provisional R3). A service takes the
        # capabilities its own `database` clause names; with no such clause, a
        # single-service module attributes all of them, and a multi-service module
        # is a compile error rather than a guess.
        declared = []
        for line in d.clauses.get("database", []):
            if len(line.tokens) != 1:
                raise LowerError("line %d: a database line names one capability"
                                 % line.lineno)
            capname = line.tokens[0]
            if capname not in cap_by_name:
                raise LowerError("line %d: %r is not a declared capability "
                                 "(dangling reference — RFC-0001 structure rule 6)"
                                 % (line.lineno, capname))
            if cap_by_name[capname] not in declared:
                declared.append(cap_by_name[capname])
        if declared:
            requires = declared
        elif len(by_kind["service"]) == 1:
            requires = list(cap_ids)
        elif cap_ids:
            raise LowerError(
                "service %s declares no `database` clause, and this module has %d "
                "services — capability attribution would be a guess. Name the "
                "capabilities each service requires in its `database` clause."
                % (d.name, len(by_kind["service"])))
        else:
            requires = []

        # `goal` lines become BusinessRule nodes owned by this Service (RFC-0002
        # Appendix A.2: GoalLine -> BusinessRule). Until this existed the clause
        # parsed and then vanished — the worst kind of gap, a declaration that
        # silently does nothing.
        goal_nodes = []
        for n, line in enumerate(d.clauses.get("goal", []), start=1):
            statement = " ".join(line.tokens)
            goal_nodes.append(_node("BusinessRule", "%s.goal.%d" % (sid, n),
                                    name=statement, statement=statement))

        children = [g["id"] for g in goal_nodes]
        children += [derive_id(w.name, "Workflow")
                     for w in by_kind["workflow"] if owner_of.get(id(w)) is d]
        service_nodes.append(_node(
            "Service", sid, name=d.name,
            requires=requires or None,
            constraints=constraints or None,
            children=children or None))
        service_nodes.extend(goal_nodes)

    # A.6.4 emit-on-use: a preset a field named rides into this document as a
    # node, built by the same function a declaration uses. An unused preset is
    # not emitted.
    for name in used_presets:
        spec = preset(name)
        refine_nodes.append(_refinement_node(name, spec["base"], spec["facets"]))

    for n in refine_nodes:
        mod.add(n)

    for n in service_nodes:
        mod.add(n)

    for ent in registry.values():
        mod.add(_node("Entity", ent["id"], name=ent["name"], fields=ent["fields"]))

    for d in by_kind["event"]:
        eid = derive_id(d.name, "Event")
        source = None
        if "on" in d.extra:
            ent_name, trigger = d.extra["on"]
            ref = derive_id(ent_name, "Entity")
            if mod.get(ref) is None:
                raise LowerError("line %d: event source references undeclared entity %r "
                                 "(dangling reference — RFC-0001 structure rule 6)"
                                 % (d.lineno, ent_name))
            source = {"ref": ref, "on": trigger}
        mod.add(_node("Event", eid, name=d.name, source=source))

    # ---- Workflows: step nodes, guards, blocks + derived Effects (R1) ----
    for d in by_kind["workflow"]:
        wid = derive_id(d.name, "Workflow")
        ctx = _WfContext(wid, registry)
        top_ids = [ctx.plan(item) for item in d.items]
        mod.add(_node("Workflow", wid, name=d.name, children=top_ids or None))
        for node in ctx.emitted:
            mod.add(node)

    for n in constraint_nodes:
        mod.add(n)

    for d in by_kind["capability"]:
        mod.add(_node("Capability", derive_id(d.name, "Capability"),
                      name=d.name, version=d.extra.get("version")))

    return mod


class _WfContext:
    """Turns one workflow body into nodes, numbering ids as it goes."""

    def __init__(self, wid, registry):
        self.wid = wid
        self.registry = registry
        self.emitted = []
        self._step_n = 0
        self._guard_n = 0
        self._block_n = {"parallel": 0, "pipeline": 0}

    def plan(self, item):
        """Emit the nodes for one body item; returns the id the parent should own."""
        if item["item"] == "step":
            return self._step(item["line"])
        if item["item"] == "block":
            return self._block(item["block"])
        if item["item"] == "guard":
            return self._guard(item["guard"], item["guarded"])
        raise LowerError("unknown body item %r" % item["item"])

    def _next_step_id(self):
        self._step_n += 1
        return "%s.step.%d" % (self.wid, self._step_n)

    def _step(self, line):
        step_id = self._next_step_id()
        verb = line.tokens[0]
        obj = line.tokens[1] if len(line.tokens) > 1 else None
        derived = _derive_effect(step_id, verb, obj, self.registry, line.lineno)
        self.emitted.append(_node("WorkflowStep", step_id,
                                  name=" ".join(line.tokens),
                                  children=[derived["id"]] if derived else None))
        if derived:
            self.emitted.append(derived)
        return step_id

    def _block(self, block):
        kind = "Concurrency" if block["type"] == "parallel" else "Pipeline"
        self._block_n[block["type"]] += 1
        slug = "%s.%d" % (block["type"], self._block_n[block["type"]])
        node_id = "%s.%s" % (self.wid, slug)
        child_ids = [self._step(line) for line in block["steps"]]
        if not child_ids:
            raise LowerError("line %d: `%s` block has no steps"
                             % (block["lineno"], block["type"]))
        if kind == "Concurrency":
            self.emitted.append(_node(kind, node_id, mode="parallel",
                                      children=child_ids))
        else:
            # RFC-0001 requires Pipeline.name; the grammar makes the name optional,
            # so an unnamed pipeline gets a derived one (formerly gap A.4-4).
            name = block["name"] or slug
            self.emitted.append(_node(kind, node_id, name=name, children=child_ids))
        return node_id

    def _guard(self, guard, guarded):
        self._guard_n += 1
        node_id = "%s.guard.%d" % (self.wid, self._guard_n)
        inner_id = self.plan(guarded)
        fields = {"mode": guard["mode"]}
        if guard["mode"] == "repeat":
            fields["count"] = int(guard["arg"])
        else:
            fields["condition"] = guard["arg"]
        self.emitted.append(_node("Guard", node_id, children=[inner_id], **fields))
        return node_id


def _derive_effect(step_id, verb, obj, registry, lineno):
    """R1: closed-lexicon lookup. Returns an Effect node dict, or None."""
    entry = VERB_LEXICON.get(verb)
    if entry is None:
        return None
    kind, fixed = entry
    eid = "%s.%s" % (step_id, EFFECT_SLUG[kind])

    if kind == "Validation":
        ent = _resolve_entity(registry, obj, verb, lineno)
        field_names = [f["name"] for f in ent["fields"]]
        if obj and obj in field_names:
            ftype = next(f["type"] for f in ent["fields"] if f["name"] == obj)
            return _node(kind, eid, target="%s.%s" % (ent["id"], obj), rule=ftype)
        # `input` (or no object) validates the workflow's input payload: every
        # declared field is checked by its semantic type's built-in rule.
        return _node(kind, eid, target=ent["id"], rule="semantic-types")

    if kind == "RepositoryCall":
        ent = _resolve_entity(registry, obj, verb, lineno)
        return _node(kind, eid, entity=ent["id"], operation=fixed["operation"])

    if kind == "CacheAccess":
        base = obj
        if base is None:
            ent = _resolve_entity(registry, None, verb, lineno)
            base = ent["id"].split(".")[-1]
        return _node(kind, eid, key="%s:{id}" % base, operation=fixed["operation"])

    if kind == "NetworkCall":
        return _node(kind, eid, target=obj or "unspecified")

    if kind == "Authorization":
        return _node(kind, eid, requirement=obj or "unspecified")

    if kind == "EventEmit":
        # `emit <Event>`: the object names a declared event. Without one there is
        # nothing to reference, and RFC-0001 makes `event` required on EventEmit.
        if obj is None:
            raise LowerError(
                "line %d: `%s` needs the event to emit as its object "
                "(e.g. `emit userCreated`)" % (lineno, verb))
        return _node(kind, eid, event=_event_ref(obj, lineno))

    raise LowerError("line %d: no derivation defined for %s" % (lineno, kind))


def _resolve_entity(registry, obj, verb, lineno):
    """Pick the entity a step operates on.

    The object names it when there is a choice; with exactly one entity declared
    the object may be omitted. Ambiguity is an error that lists the candidates —
    picking one would make the program's meaning depend on declaration order.
    """
    if not registry:
        raise LowerError("line %d: `%s` needs an entity in scope, and the module "
                         "declares none" % (lineno, verb))
    if obj:
        for ent in registry.values():
            if obj == ent["id"].split(".", 1)[1].replace(".", "") \
               or obj == "".join(split_pascal(ent["name"])):
                return ent
            if obj in [f["name"] for f in ent["fields"]]:
                return ent
    if len(registry) == 1:
        return next(iter(registry.values()))
    raise LowerError(
        "line %d: `%s %s` does not say which entity it means, and this module "
        "declares %d (%s). Name the entity as the step's object."
        % (lineno, verb, obj or "", len(registry),
           ", ".join(sorted(e["name"] for e in registry.values()))))


def _event_ref(obj, lineno):
    """`userCreated` -> `event.user.created` (the R2 id rule, applied to an event)."""
    pascal = obj[0].upper() + obj[1:] if obj else obj
    if not re.match(r"^[A-Za-z][A-Za-z0-9]*$", obj or ""):
        raise LowerError("line %d: %r is not a valid event name" % (lineno, obj))
    return derive_id(pascal, "Event")
