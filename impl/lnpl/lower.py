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

from .lexer import COMPARATORS, is_duration

KIND_PREFIX = {
    "Entity": "entity",
    "Service": "svc",
    "Workflow": "wf",
    "Event": "event",
    "Capability": "cap",
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


def lower(decls, module_name):
    """[Decl] -> Module, emitting nodes in RFC-0001 canonical order."""
    mod = Module(module_name)

    by_kind = {"capability": [], "entity": [], "event": [], "service": [], "workflow": []}
    for d in decls:
        by_kind[d.kind].append(d)

    entities = by_kind["entity"]
    if len(entities) > 1:
        raise LowerError(
            "Phase 1 lowers a single-entity module; found %d entities. "
            "Multi-entity scope resolution is unresolved (RFC-0002 A.4-8)." % len(entities))
    entity_decl = entities[0] if entities else None
    entity_id = derive_id(entity_decl.name, "Entity") if entity_decl else None
    entity_fields = []
    if entity_decl:
        for line in entity_decl.clauses.get("field", []):
            if len(line.tokens) != 2:
                raise LowerError("line %d: field must be `<name> <Type>`" % line.lineno)
            entity_fields.append({"name": line.tokens[0], "type": line.tokens[1]})
        if not entity_fields:
            raise LowerError("entity %s declares no fields" % entity_decl.name)

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

        children = [derive_id(w.name, "Workflow")
                    for w in by_kind["workflow"] if owner_of.get(id(w)) is d]
        service_nodes.append(_node(
            "Service", sid, name=d.name,
            requires=requires or None,
            constraints=constraints or None,
            children=children or None))

    for n in service_nodes:
        mod.add(n)

    if entity_decl:
        mod.add(_node("Entity", entity_id, name=entity_decl.name, fields=entity_fields))

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
        ctx = _WfContext(wid, entity_id, entity_fields)
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

    def __init__(self, wid, entity_id, entity_fields):
        self.wid = wid
        self.entity_id = entity_id
        self.entity_fields = entity_fields
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
        derived = _derive_effect(step_id, verb, obj, self.entity_id,
                                self.entity_fields, line.lineno)
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


def _derive_effect(step_id, verb, obj, entity_id, entity_fields, lineno):
    """R1: closed-lexicon lookup. Returns an Effect node dict, or None."""
    entry = VERB_LEXICON.get(verb)
    if entry is None:
        return None
    kind, fixed = entry
    eid = "%s.%s" % (step_id, EFFECT_SLUG[kind])

    if kind == "Validation":
        if entity_id is None:
            raise LowerError("line %d: `%s` needs an entity in scope" % (lineno, verb))
        field_names = [f["name"] for f in entity_fields]
        if obj and obj in field_names:
            ftype = next(f["type"] for f in entity_fields if f["name"] == obj)
            return _node(kind, eid, target="%s.%s" % (entity_id, obj), rule=ftype)
        # `input` (or no object) validates the workflow's input payload: every
        # declared field is checked by its semantic type's built-in rule.
        return _node(kind, eid, target=entity_id, rule="semantic-types")

    if kind == "RepositoryCall":
        if entity_id is None:
            raise LowerError("line %d: `%s` needs an entity in scope" % (lineno, verb))
        return _node(kind, eid, entity=entity_id, operation=fixed["operation"])

    if kind == "CacheAccess":
        base = obj or (entity_fields and entity_id.split(".")[-1]) or "value"
        return _node(kind, eid, key="%s:{id}" % base, operation=fixed["operation"])

    if kind == "NetworkCall":
        return _node(kind, eid, target=obj or "unspecified")

    if kind == "Authorization":
        return _node(kind, eid, requirement=obj or "unspecified")

    if kind == "EventEmit":
        raise LowerError(
            "line %d: `%s` derives an EventEmit, which must reference a declared "
            "event; surface notation for that reference is unresolved "
            "(RFC-0002 A.4-3)" % (lineno, verb))

    raise LowerError("line %d: no derivation defined for %s" % (lineno, kind))
