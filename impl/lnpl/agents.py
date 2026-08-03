"""Two agents doing the RFC-0006 Examples round trip (ROADMAP Phase 3).

The cycle RFC-0006 describes, and what each leg actually does here:

    Planner   receives an intent, decomposes it, and dispatches the work
    Coder     routes the step to the KB, loads the document, pins its version,
              and proposes the IR fragment that document tells it to produce
    Reviewer  approves, which is the only way a proposal reaches the document

The Coder is the interesting one: it does not decide *what* to emit from its own
knowledge. It asks the KB, and if the KB has nothing to say it **stops** rather
than inventing an Effect — the same rule the compiler's verb lexicon follows.
"""

import re

from .lower import derive_id
from .protocol import (CHILDREN_ALLOWED, REFERENCE_KEYS, ROLES, RpcError, Server,
                       attachments, moves, node_references, reference_only_edit)
from .spec import EXPECTATIONS, SPEC_VERSION

# Node kinds that may legitimately have no owner. RFC-0001 rule 2 allows only
# Declaration nodes to be entry (top-level) nodes; rule 5 exempts Constraint
# nodes, which are never owned via `children` and are reached through the
# `constraints` field instead. Everything else must have exactly one owner.
DECLARATION_KINDS = frozenset({"Entity", "Service", "Workflow", "Event", "Capability"})
CONSTRAINT_KINDS = frozenset({"Policy", "Security", "Performance"})
ENTRY_KINDS = DECLARATION_KINDS | CONSTRAINT_KINDS

# A10: provenance is a form, not just a non-empty string. `kb:<doc id>@<semver>`
# when the basis is a KB document, `ir:<node id>` when it is derived from the IR.
_SOURCE_FORM = re.compile(r"^(kb:[a-z0-9-]+@\d+\.\d+\.\d+|ir:[a-z][a-z0-9.]*)$")


def _ownership_cycle(merged):
    """One cycle in the `children` graph as a list of ids, or [] if acyclic.

    RFC-0001 rule 4. Checking only for a node that lists itself catches 1-cycles
    and nothing longer: two new nodes owning each other each have an owner, so
    every per-node check passes while the pair is unreachable from any entry node.
    """
    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(merged, white)
    for root in sorted(merged):
        if colour[root] != white:
            continue
        colour[root] = grey
        path = [root]
        stack = [(root, iter(merged[root].get("children", [])))]
        while stack:
            node_id, kids = stack[-1]
            descended = False
            for kid in kids:
                if kid not in merged:
                    continue              # rule 6 reports dangling separately
                if colour[kid] == grey:
                    return path[path.index(kid):] + [kid]
                if colour[kid] == white:
                    colour[kid] = grey
                    path.append(kid)
                    stack.append((kid, iter(merged[kid].get("children", []))))
                    descended = True
                    break
            if not descended:
                colour[node_id] = black
                stack.pop()
                path.pop()
    return []


def _refs_in(node, field):
    """The node ids `node` references through `field`. Empty when it has none."""
    if not node:
        return set()
    value = node.get(field)
    if isinstance(value, list):
        return {v for v in value if isinstance(v, str)}
    return {value} if isinstance(value, str) else set()


def _structure_fault(merged):
    """The first RFC-0001 structure-rule violation in a merged document, or None.

    Rules 2 (one owner, and only Declaration/Constraint nodes may be unowned),
    4 (acyclic ownership) and 6 (every reference resolves) are checked over the
    *whole* merged document, not just the proposed nodes — a proposal changes
    meaning by what it detaches as much as by what it adds.
    """
    dangling = sorted({ref for node in merged.values()
                       for ref in node_references(node) if ref not in merged})
    if dangling:
        return ("dangling: unresolved reference(s) %s — every owning and named "
                "reference must resolve in the same document (RFC-0001 rule 6)"
                % ", ".join(dangling))

    owners = {}
    contested = []
    for node in sorted(merged.values(), key=lambda n: n["id"]):
        for ref in node.get("children", []):
            if ref in owners:
                contested.append("%s (owned by %s and %s)" % (ref, owners[ref], node["id"]))
            else:
                owners[ref] = node["id"]
    if contested:
        return ("ownership: %s — a node may appear in at most one `children` list "
                "(RFC-0001 rule 2)" % ", ".join(sorted(contested)))

    orphans = sorted(n["id"] for n in merged.values()
                     if n["kind"] not in ENTRY_KINDS and n["id"] not in owners)
    if orphans:
        return ("orphan: nothing owns %s — only Declaration and Constraint nodes "
                "may be unowned (RFC-0001 rules 2, 5)" % ", ".join(orphans))

    cycle = _ownership_cycle(merged)
    if cycle:
        return ("cycle: ownership loops through %s — the `children` graph must be "
                "acyclic (RFC-0001 rule 4)" % " -> ".join(cycle))
    return None


class _AgentBase:
    """What every role shares: its name, the server, and a refusal path.

    The refusal path is the important part. A role that cannot decide must say so
    and cite the clause that owns the question — not fall back on a plausible
    guess. That is the same discipline the compiler's verb lexicon follows.
    """

    role = None

    def __init__(self, server):
        self.server = server

    def _meta(self, source):
        return {"origin": "agent:%s" % self.role, "source": source}

    def _refuse(self, task, reason, clause):
        """Close the task without proposing, recording why and under whose clause."""
        self.server.call("agent.report", task_id=task["task_id"], state="completed",
                         payload={"proposed": None, "reason": reason, "clause": clause})
        return {"proposal_id": None, "reason": reason, "clause": clause}

    def _pin_kb(self, query):
        """route -> load -> verify. Returns the document, or None if unrouted."""
        routed = self.server.call("kb.route", task_description=query)["doc_ids"]
        if not routed:
            return None
        doc = self.server.call("kb.load", doc_id=routed[0])["document"]
        self.server.call("kb.verify", doc_id=doc["id"], version=doc["version"])
        return doc


class Planner(_AgentBase):
    """Turns an intent into dispatched work. Proposes nothing (RFC-0006 role table)."""

    role = "Planner"

    def plan(self, intent, steps, deadline_ms=30000):
        """Dispatch one task per step; returns the task descriptors."""
        card = self.server.call("agent.card", role=self.role)
        if card["ir_access"]["propose"]:
            raise RpcError("internal", "Planner must not hold propose rights")
        tasks = []
        for i, step in enumerate(steps, start=1):
            task = self.server.call(
                "agent.dispatch", role="Coder",
                objective="implement step %r of %r" % (step, intent),
                deadline_ms=deadline_ms,
                idempotency_key="plan-%s-%d" % (_slug(intent), i))
            tasks.append({"task": task, "step": step})
        return tasks


class Coder(_AgentBase):
    """Routes a step to the KB, then proposes the IR the KB prescribes."""

    role = "Coder"

    def implement(self, task, step, deadline_ms=30000):
        """One leg of the cycle. Returns a record of what it did and why."""
        routed = self.server.call("kb.route", task_description=step)["doc_ids"]
        if not routed:
            # The KB has nothing for this step. Stopping is the correct outcome:
            # an agent that invents an Effect here is the synthesis route this
            # platform rejected.
            self.server.call("agent.report", task_id=task["task_id"],
                             state="completed",
                             payload={"step": step, "kb": [], "proposed": None,
                                      "reason": "no KB guidance; nothing proposed"})
            return {"step": step, "doc_id": None, "proposal_id": None}

        doc_id = routed[0]
        doc = self.server.call("kb.load", doc_id=doc_id)["document"]
        # Pin the version we reasoned against, so a later drift is detectable.
        self.server.call("kb.verify", doc_id=doc_id, version=doc["version"])

        fragment = self._fragment_for(step, doc)
        if fragment is None:
            self.server.call("agent.report", task_id=task["task_id"],
                             state="completed",
                             payload={"step": step, "kb": [doc_id], "proposed": None,
                                      "reason": "KB guidance carries no IR prescription"})
            return {"step": step, "doc_id": doc_id, "proposal_id": None}

        proposal = self.server.call(
            "ir.propose", role=self.role, ir_fragment=fragment,
            deadline_ms=deadline_ms,
            idempotency_key="coder-%s" % _slug(step))
        self.server.call("agent.report", task_id=task["task_id"],
                         state="input-required",
                         payload={"step": step, "kb": [doc_id],
                                  "proposed": proposal["proposal_id"],
                                  "awaiting": proposal["review_task_id"]})
        return {"step": step, "doc_id": doc_id,
                "proposal_id": proposal["proposal_id"],
                "review_task_id": proposal["review_task_id"],
                "kb_version": doc["version"]}

    # The mapping from KB guidance to an IR fragment. Deliberately tiny and
    # explicit: the Coder emits only what a document prescribes, and only kinds
    # its role may propose.
    def _fragment_for(self, step, doc):
        if doc["id"] != "security-jwt-issuance":
            return None
        # The jwt guidance prescribes an Authorization gate on *issuance*. Routing
        # is lexical, so it also matches steps that merely mention a token; the
        # prescription is narrowed by the step's verb, which the grammar guarantees
        # is the first token.
        if step.split()[0] != "generate":
            return None
        node = self._step_node_for(step)
        if node is None:
            return None
        authz_id = "%s.authz" % node["id"]
        # The Effect must be *owned* by its step, or it is unreachable in the flat
        # node table: propose the updated parent alongside the new child.
        parent = dict(node)
        parent["children"] = list(node.get("children", [])) + [authz_id]
        return {"module": self.server.doc["module"],
                "nodes": [parent,
                          {"kind": "Authorization",
                           "id": authz_id,
                           "requirement": "verified jwt",
                           "meta": self._meta("kb:%s@%s" % (doc["id"], doc["version"]))}]}

    def _step_node_for(self, step):
        for node in self.server.doc["nodes"]:
            if node["kind"] == "WorkflowStep" and node.get("name") == step:
                return node
        return None


class Reviewer(_AgentBase):
    """Approves or rejects — on its own criteria, not the caller's.

    `ir.propose` buys a two-stage approval, and that is worth exactly as much as
    the reviewer behind it. So `decide` defaults to *assessing*: the caller may
    still override, but has to say so, and the override is recorded.

    The five rejection criteria are the failures that would otherwise surface at
    apply time, moved to review time where a reviewer can explain them.
    """

    role = "Reviewer"

    def decide(self, review_task_id, proposal_id, approve=None, reason=""):
        if approve is None:
            ok, why = self._assess(proposal_id)
            approve, reason = ok, why or reason
        else:
            reason = "override: %s" % (reason or
                                       ("approved" if approve else "rejected"))
        payload = {"proposal_id": proposal_id,
                   "decision": "approved" if approve else "rejected",
                   "reason": reason}
        return self.server.call("agent.report", task_id=review_task_id,
                                payload=payload)

    def _source_resolves(self, source, existing):
        """Does this provenance string name something that actually exists?"""
        if source.startswith("kb:"):
            doc_id, _, version = source[3:].partition("@")
            return bool(self.server.kb.verify(doc_id, version))
        return source[3:] in existing

    def _assess(self, proposal_id):
        """Returns (approve, reason). Reason is `<code>: <why>` when rejecting."""
        proposal = self.server.proposals.get(proposal_id)
        if proposal is None:
            return False, "unknown: no such proposal %r" % proposal_id
        nodes = proposal["nodes"]
        existing = {n["id"]: n for n in self.server.doc["nodes"]}

        # RFC-0010. The server validated these at propose time, but this is a
        # second, independent gate — a proposal planted straight into
        # `server.proposals` never passed through the first one.
        intent = proposal.get("intent") or {}
        attach_map = attachments(intent)
        move_map = moves(intent)
        authored = {n["id"] for n in nodes} - set(existing)

        # Judge the declarations before the rights check consults them, so an
        # unauthored child or an illegal pairing says so instead of surfacing as a
        # generic `rights:` refusal.
        for parent, children in sorted(attach_map.items()):
            parent_kind = (next((n for n in nodes if n.get("id") == parent), None)
                           or existing.get(parent) or {}).get("kind")
            for child in sorted(children):
                if child not in authored:
                    return False, ("attach: %s was not authored by this proposal — "
                                   "a proposal may attach only a node it wrote "
                                   "(RFC-0010)" % child)
                child_kind = next((n.get("kind") for n in nodes
                                   if n.get("id") == child), None)
                if child_kind not in CHILDREN_ALLOWED.get(parent_kind, set()):
                    return False, ("attach: a %s may not own a %s (RFC-0001 노드 "
                                   "카탈로그; RFC-0004 §S2 V5): %s under %s"
                                   % (parent_kind, child_kind, child, parent))

        allowed = ROLES.get(proposal["role"], {}).get("propose", set())
        outside = []
        for node in nodes:
            if node.get("kind") in allowed:
                continue
            declared = attach_map.get(node.get("id"), set())
            if declared and reference_only_edit(node, existing.get(node.get("id")),
                                                declared):
                origin = (node.get("meta") or {}).get("origin") or ""
                if origin.startswith("agent:"):
                    continue
            outside.append(node.get("kind"))
        if outside:
            return False, ("rights: %s may not propose %s"
                           % (proposal["role"], ", ".join(sorted(set(outside)))))

        bad_source = []
        for node in nodes:
            if node["id"] in existing:
                continue          # a replacement of an existing node keeps its own
            source = (node.get("meta") or {}).get("source")
            if not source or not _SOURCE_FORM.match(source):
                bad_source.append("%s (%r)" % (node["id"], source))
                continue
            # A form that points at nothing is not a basis. Both the KB and the
            # document are in reach here, so matching the shape is not the answer
            # to "is this grounded?" — resolving it is.
            if not self._source_resolves(source, existing):
                bad_source.append("%s (%s resolves to nothing)" % (node["id"], source))
        if bad_source:
            return False, ("provenance: new node(s) need a meta.source that resolves "
                           "— `kb:<id>@<version>` naming a document at that exact "
                           "version, or `ir:<node id>` present in the document: %s"
                           % ", ".join(bad_source))

        # `ir.propose` adds or replaces. Since RFC-0010 it can also *move* a
        # reference, but only when the proposal declares it — an undeclared drop is
        # still a removal wearing an edit's clothes, and it changes runtime meaning,
        # because the interpreter reads `constraints` for retry, timeout, rollback
        # and the security mechanisms.
        declared_drops = {}
        for node in nodes:
            old = existing.get(node["id"])
            if old is None:
                continue
            if node.get("kind") != old.get("kind"):
                return False, ("kind: %s is a %s in the document and this would make "
                               "it a %s — `ir.propose` replaces a node, it does not "
                               "swap one out for another kind "
                               "(RFC-0010 §Methods/ir.propose)"
                               % (node["id"], old.get("kind"), node.get("kind")))
            # Per field, not across their union. `node_references` unions `children`
            # with the named fields, so a union comparison sees no change when a
            # reference merely *migrates* between them — and the interpreter reads
            # `constraints` for retry, timeout and rollback, so migrating a Policy
            # into `children` silently stops it applying. Measured: retry 2 became
            # retry 1 with a proposal that declared nothing at all.
            for field in sorted(REFERENCE_KEYS):
                gone = sorted(_refs_in(old, field) - _refs_in(node, field))
                for ref in gone:
                    if (node["id"], ref) not in move_map:
                        return False, (
                            "removal: replacing %s would drop %s from `%s` without "
                            "a declared move — `ir.propose` expresses a move by "
                            "declaring it in `intent`, and refuses an undeclared "
                            "removal (RFC-0010 §Methods/ir.propose)"
                            % (node["id"], ref, field))
                    declared_drops[(node["id"], ref)] = field

        # Merge into a copy — assessing must not change what it is assessing.
        merged = {nid: node for nid, node in existing.items()}
        for node in nodes:
            merged[node["id"]] = node

        # A declared move must land where it said, in the field it left. "References
        # it somewhere" is not enough: `node_references` unions `children` with the
        # named fields, so a Constraint declared as moved out of `constraints` could
        # be laundered into a `children` entry — emptying `constraints`, which the
        # interpreter reads for retry, timeout and rollback.
        for (from_id, node_id), to_id in sorted(move_map.items()):
            field = declared_drops.get((from_id, node_id))
            if field is None:
                return False, ("move: %s does not give up %s, so there is nothing "
                               "to move (RFC-0010)" % (from_id, node_id))
            if node_id not in _refs_in(merged.get(to_id), field):
                return False, ("move: %s must reference %s in `%s`, the field it "
                               "left (RFC-0010)" % (to_id, node_id, field))
            # And it must *newly* gain it. A destination that already referenced it
            # satisfies "references it" without any transfer happening, which turns
            # a declared move into a laundered removal — measured: a Policy dropped
            # from one Service and declared moved to another that already had it was
            # approved, and retry went from 2 to 1.
            if node_id in _refs_in(existing.get(to_id), field):
                return False, ("move: %s already referenced %s in `%s`, so nothing "
                               "was transferred — a declared move must land "
                               "somewhere new (RFC-0010)" % (to_id, node_id, field))
            # RFC-0010 also says a Constraint may only land in `constraints`. That
            # needs no separate branch: `field` is where the reference *left* from,
            # and a valid document only ever holds a Constraint in `constraints`
            # (RFC-0001 rule 5, enforced by `_structure_fault`'s orphan check), so
            # the same-field requirement above already implies it. A branch for it
            # was written and removed — no mutation could kill it, which is the
            # tell for an unreachable condition.

        fault = _structure_fault(merged)
        if fault:
            return False, fault

        if self.server.validate is not None:
            candidate = dict(self.server.doc)
            candidate["nodes"] = [merged[n["id"]] for n in self.server.doc["nodes"]]
            candidate["nodes"] += [n for n in nodes if n["id"] not in existing]
            try:
                self.server.validate(candidate)
            except Exception as exc:
                return False, "schema: merged document would be invalid (%s)" % exc

        return True, ("assessed: rights, resolved provenance, no removal, references, "
                      "ownership, acyclicity, schema all clear")



class Architect(_AgentBase):
    """Originates a program: intent + a declaration spec -> Declaration nodes.

    It does not invent fields or types. What the spec does not say, it refuses to
    say for you — the platform's whole claim is that the developer declares intent,
    not that an agent fills in the parts they left out.
    """

    role = "Architect"

    def design(self, task, spec, deadline_ms=30000):
        for key in ("entity", "service", "workflow"):
            if key not in (spec or {}):
                return self._refuse(task, "spec incomplete: missing %r" % key,
                                    "RFC-0006 §Roles (Architect: 입력 아티팩트)")
        doc = self._pin_kb("entity name field name node id derivation")
        if doc is None:
            return self._refuse(task, "no naming guidance in the knowledge base",
                                "RFC-0005 §Consumption Interface")

        source = "kb:%s@%s" % (doc["id"], doc["version"])
        ent, svc, wf = spec["entity"], spec["service"], spec["workflow"]
        entity_id = derive_id(ent["name"], "Entity")
        service_id = derive_id(svc["name"], "Service")
        workflow_id = derive_id(wf["name"], "Workflow")

        step_ids, nodes = [], []
        for i, step_name in enumerate(wf.get("steps", []), start=1):
            step_id = "%s.step.%d" % (workflow_id, i)
            step_ids.append(step_id)
            nodes.append({"kind": "WorkflowStep", "id": step_id,
                          "name": step_name, "meta": self._meta(source)})

        nodes = [
            {"kind": "Entity", "id": entity_id, "name": ent["name"],
             "fields": ent["fields"], "meta": self._meta(source)},
            {"kind": "Service", "id": service_id, "name": svc["name"],
             "children": [workflow_id], "meta": self._meta(source)},
            {"kind": "Workflow", "id": workflow_id, "name": wf["name"],
             "children": step_ids, "meta": self._meta(source)},
        ] + nodes

        proposal = self.server.call("ir.propose", role=self.role,
                                    ir_fragment={"module": self.server.doc["module"],
                                                 "nodes": nodes},
                                    deadline_ms=deadline_ms,
                                    idempotency_key="architect-%s" % _slug(wf["name"]))
        self.server.call("agent.report", task_id=task["task_id"],
                         state="input-required",
                         payload={"proposed": proposal["proposal_id"],
                                  "awaiting": proposal["review_task_id"]})
        return {"proposal_id": proposal["proposal_id"],
                "review_task_id": proposal["review_task_id"],
                "node_ids": [n["id"] for n in nodes]}


class SecurityAuditor(_AgentBase):
    """One rule, decidable from the IR alone.

    A workflow that reads an entity carrying a `Password` field, on a service with
    no Security constraint, gets a `jwt` requirement proposed. Anything else is
    *not a finding* — and an auditor that reports non-findings trains people to
    ignore it.
    """

    role = "SecurityAuditor"

    def audit(self, task, deadline_ms=30000):
        nodes = {n["id"]: n for n in self.server.doc["nodes"]}
        secret_entities = {
            n["id"] for n in nodes.values()
            if n["kind"] == "Entity"
            and any(f.get("type") == "Password" for f in n.get("fields", []))}
        if not secret_entities:
            return self._clean(task, "no entity carries a Password field")

        reading_steps = {n["id"]: n for n in nodes.values()
                         if n["kind"] == "RepositoryCall"
                         and n.get("operation") == "read"
                         and n.get("entity") in secret_entities}
        if not reading_steps:
            return self._clean(task, "no workflow reads an entity with a Password field")

        owners = {c: n for n in nodes.values() for c in n.get("children", [])}
        findings = []
        for effect_id in reading_steps:
            step = owners.get(effect_id)
            wf = owners.get(step["id"]) if step else None
            svc = owners.get(wf["id"]) if wf else None
            if svc is None or svc["kind"] != "Service":
                continue
            has_security = any(nodes.get(c, {}).get("kind") == "Security"
                               for c in svc.get("constraints", []))
            if not has_security:
                findings.append(svc)
        if not findings:
            return self._clean(task, "every affected service already declares Security")

        doc = self._pin_kb("generate token jwt security")
        if doc is None:
            return self._refuse(task, "no security guidance in the knowledge base",
                                "RFC-0005 §Consumption Interface")
        source = "kb:%s@%s" % (doc["id"], doc["version"])

        svc = findings[0]
        segs = svc["id"].split(".", 1)[1]
        sec_id = "security.%s" % segs
        # The Constraint is all this role may propose. Attaching it to the service
        # means replacing a Service node, which is a Declaration — outside
        # SecurityAuditor's rights (RFC-0006 §Roles). So the finding names the
        # attachment an Architect-level proposal still has to make; proposing the
        # Service anyway would be the role reaching past its own contract.
        fragment = {"module": self.server.doc["module"], "nodes": [
            {"kind": "Security", "id": sec_id, "mechanisms": ["jwt"],
             "meta": self._meta(source)}]}
        proposal = self.server.call("ir.propose", role=self.role, ir_fragment=fragment,
                                    deadline_ms=deadline_ms,
                                    idempotency_key="audit-%s" % sec_id)
        self.server.call("agent.report", task_id=task["task_id"],
                         state="input-required",
                         payload={"proposed": proposal["proposal_id"],
                                  "finding": "service %s reads secrets without a "
                                             "Security constraint" % svc["id"],
                                  "attachment_required": {
                                      "node": svc["id"], "field": "constraints",
                                      "add": sec_id,
                                      "why": "SecurityAuditor may not propose "
                                             "Declaration nodes (RFC-0006 §Roles)"}})
        return {"proposal_id": proposal["proposal_id"],
                "review_task_id": proposal["review_task_id"],
                "service_id": svc["id"], "constraint_id": sec_id,
                "attachment_required": True}

    def _clean(self, task, reason):
        """No violation is not a refusal — it is a clean audit."""
        self.server.call("agent.report", task_id=task["task_id"], state="completed",
                         payload={"proposed": None, "finding": None, "reason": reason})
        return {"proposal_id": None, "reason": reason}


class PerformanceAnalyzer(_AgentBase):
    """Proposes a response budget from measurements — and only from measurements."""

    role = "PerformanceAnalyzer"

    def analyze(self, task, workflow_id, measurements, deadline_ms=30000):
        if not measurements:
            return self._refuse(task, "no measurements to derive a budget from",
                                "RFC-0006 §Roles (PerformanceAnalyzer: 입력 아티팩트)")
        nodes = {n["id"]: n for n in self.server.doc["nodes"]}
        owners = {c: n for n in nodes.values() for c in n.get("children", [])}
        svc = owners.get(workflow_id)
        if svc is None or svc["kind"] != "Service":
            return self._refuse(task, "workflow %r has no owning service" % workflow_id,
                                "RFC-0001 §구조 규칙 (소유 유일)")
        for cid in svc.get("constraints", []):
            node = nodes.get(cid, {})
            if node.get("kind") == "Performance" and any(
                    b.get("metric") == "response" for b in node.get("budgets", [])):
                self.server.call("agent.report", task_id=task["task_id"],
                                 state="completed",
                                 payload={"proposed": None,
                                          "reason": "a response budget is already "
                                                    "declared; not overwriting it"})
                return {"proposal_id": None, "reason": "budget already declared"}

        try:
            durations = [m["duration_ms"] for m in measurements]
        except (KeyError, TypeError):
            return self._refuse(task, "a measurement has no duration_ms",
                                "RFC-0006 §Roles (PerformanceAnalyzer: 입력 아티팩트)")
        if any(not isinstance(d, int) or isinstance(d, bool) or d <= 0
               for d in durations):
            return self._refuse(
                task, "measurements must be positive integer durations, got %r"
                      % durations,
                "RFC-0003 §Policy Enforcement (response는 계측 대상)")
        observed = max(durations)
        # Round up to 10ms. The max, not a percentile: with a handful of samples a
        # percentile is either the max or a less safe number pretending to be data.
        budget = ((observed + 9) // 10) * 10
        segs = svc["id"].split(".", 1)[1]
        perf_id = "perf.%s" % segs
        # Same rights boundary as SecurityAuditor: the Constraint is proposable,
        # the Service replacement that would reference it is not.
        fragment = {"module": self.server.doc["module"], "nodes": [
            {"kind": "Performance", "id": perf_id,
             "budgets": [{"metric": "response", "value": "<%dms" % budget}],
             "meta": self._meta("ir:%s" % workflow_id)}]}
        proposal = self.server.call("ir.propose", role=self.role, ir_fragment=fragment,
                                    deadline_ms=deadline_ms,
                                    idempotency_key="perf-%s" % perf_id)
        self.server.call("agent.report", task_id=task["task_id"],
                         state="input-required",
                         payload={"proposed": proposal["proposal_id"],
                                  "observed_max_ms": observed, "budget_ms": budget,
                                  "attachment_required": {
                                      "node": svc["id"], "field": "constraints",
                                      "add": perf_id,
                                      "why": "PerformanceAnalyzer may not propose "
                                             "Declaration nodes (RFC-0006 §Roles)"}})
        return {"proposal_id": proposal["proposal_id"],
                "review_task_id": proposal["review_task_id"],
                "observed_max_ms": observed, "budget_ms": budget,
                "constraint_id": perf_id, "attachment_required": True}


class Tester(_AgentBase):
    """Derives spec cases from the Constraint nodes — and proposes no IR at all.

    `spec` is a test artifact, not part of the program's meaning (RFC-0002 A.4-2).
    Tester holds Behavior propose rights and deliberately does not use them:
    emitting a node here would reverse a decision the suite already made.
    """

    role = "Tester"

    def derive(self, task, workflow_id, deadline_ms=30000):
        nodes = {n["id"]: n for n in self.server.doc["nodes"]}
        wf = nodes.get(workflow_id)
        if wf is None or wf["kind"] != "Workflow":
            return self._refuse(task, "no such workflow %r" % workflow_id,
                                "RFC-0001 §노드 카탈로그 (Workflow)")
        owners = {c: n for n in nodes.values() for c in n.get("children", [])}
        svc = owners.get(workflow_id)
        constraints = [nodes[c] for c in (svc or {}).get("constraints", [])
                       if c in nodes]

        step_count = sum(1 for c in wf.get("children", [])
                         if nodes.get(c, {}).get("kind") == "WorkflowStep")
        happy = {"name": "%s happy path" % wf["name"], "workflow": workflow_id,
                 "given": ["valid account"], "when": ["run"],
                 "expect": ["completed", "steps %d" % step_count]}
        cases = [happy]

        retry_n = None
        for node in constraints:
            if node["kind"] == "Policy":
                for rule in node.get("rules", []):
                    if rule["name"] == "retry":
                        retry_n = int(rule["value"])
            elif node["kind"] == "Performance":
                for budget in node.get("budgets", []):
                    if budget["metric"] == "response":
                        happy["expect"].append("slo met")
                    elif budget["metric"] == "cache":
                        happy["expect"].append("cache written")

        if retry_n is not None:
            cases.append({"name": "%s exhausts its retries" % wf["name"],
                          "workflow": workflow_id,
                          "given": ["empty repository"], "when": ["run"],
                          "expect": ["failed", "attempts %d" % (retry_n + 1)]})

        unknown = [e.split()[0] for case in cases for e in case["expect"]
                   if e.split()[0] not in EXPECTATIONS]
        if unknown:
            return self._refuse(task,
                                "derived an expectation the runner cannot evaluate: %s"
                                % ", ".join(sorted(set(unknown))),
                                "RFC-0002 부록 A.4-② (spec은 테스트 아티팩트)")

        manifest = {"spec_version": SPEC_VERSION,
                    "module": self.server.doc["module"], "cases": cases}
        self.server.call("agent.report", task_id=task["task_id"], state="completed",
                         payload={"proposed": None, "manifest": manifest})
        return manifest


class RefactoringAgent(_AgentBase):
    """Splits a step that owns more than one repository access — and nothing else.

    The KB prescribes exactly one restructuring (`patterns-repository-call`): *"한
    step에 한 저장소 접근. 두 접근이 필요하면 두 step이다. step은 재시도·span의
    단위이므로 접근을 묶으면 재시도가 둘을 함께 반복한다."* That last clause is the
    reason, and it is also the honest limit of what this transform preserves:

    **effect order survives; retry grouping does not.** A moved access stops being
    retried together with the one it left. That is the *point* of the prescription,
    not a defect — but RFC-0006's role table says this role "의미를 보존하며 구조를
    바꾼다", and only half of that is true here. RFC-0010 §Examples records it.

    Two deliberate limits:

    - **Only a step owned by a `Workflow` or a `Pipeline`.** Under a `Concurrency`
      owner the new step would become a parallel branch, which mode A is
      single-threaded enough never to reveal; under a `Guard` it would leave two
      guarded items where RFC-0001 allows exactly one. Both refuse.
    - **Direct children only.** A `RepositoryCall` nested inside a `Transaction`
      does not count, so a step with one direct and one nested access is not
      reported. That under-detects the KB rule rather than answering it wrongly.

    Anything it cannot ground, it declines — the same discipline as
    `Coder._fragment_for` returning `None` instead of inventing an Effect.
    """

    role = "RefactoringAgent"

    KB_DOC = "patterns-repository-call"
    SPLITTABLE_OWNERS = ("Workflow", "Pipeline")

    def _violations(self, doc):
        """`(owner_id, step, [extra call ids])` for each step to split."""
        nodes = {n["id"]: n for n in doc["nodes"]}
        owners = {c: n for n in doc["nodes"] for c in n.get("children", [])}
        found = []
        for node in doc["nodes"]:
            if node.get("kind") != "WorkflowStep":
                continue
            calls = [c for c in node.get("children", [])
                     if nodes.get(c, {}).get("kind") == "RepositoryCall"]
            if len(calls) < 2:
                continue
            owner = owners.get(node["id"])
            if owner is None or owner.get("kind") not in self.SPLITTABLE_OWNERS:
                continue
            found.append((owner["id"], node, calls[1:]))
        return found

    def _new_step(self, doc, owner_id, call_id, taken):
        """A step owning `call_id` alone, or None when its name cannot be derived."""
        nodes = {n["id"]: n for n in doc["nodes"]}
        call = nodes[call_id]
        entity = nodes.get(call.get("entity"))
        operation = call.get("operation")
        # Refuse rather than invent, and refuse rather than raise: an entity whose
        # `name` is whitespace, a number, or absent used to reach `.split()[0]` and
        # come out as an IndexError instead of a declined task.
        if not entity or not isinstance(entity.get("name"), str):
            return None
        parts = entity["name"].split()
        if not parts or not isinstance(operation, str) or not operation:
            return None
        # `query` is not in the KB's verb dictionary (authenticate/load/find/read →
        # read, create/insert, update, delete), and `find` is the entry that maps to
        # the same operation — so a name built from `query` would not round-trip
        # through the dictionary that document owns.
        verb = "find" if operation == "query" else operation
        name = "%s %s" % (verb, parts[0].lower())
        n = 1
        while "%s.split.%d" % (owner_id, n) in nodes or \
                "%s.split.%d" % (owner_id, n) in taken:
            n += 1
        new_id = "%s.split.%d" % (owner_id, n)
        taken.add(new_id)
        return {"kind": "WorkflowStep", "id": new_id, "name": name,
                "children": [call_id],
                "meta": self._meta("kb:%s@%s" % (self.KB_DOC, self._kb_version()))}

    def _kb_version(self):
        """Through the protocol, and pinned — as Architect and Coder do it.

        Reading `server.kb` directly skips the version pin, leaves the KB access out
        of the transcript, and lets a missing document escape as a raw KbError
        instead of a structured error.
        """
        doc = self.server.call("kb.load", doc_id=self.KB_DOC)["document"]
        version = doc["version"]
        if not self.server.call("kb.verify", doc_id=self.KB_DOC, version=version):
            raise RpcError("kb_version_conflict",
                           "%s@%s no longer verifies" % (self.KB_DOC, version))
        return version

    def _split(self, doc, owner_id, step, extra_call_ids):
        """`(nodes, intent)` for one step's split, or `(None, None)`."""
        nodes = {n["id"]: n for n in doc["nodes"]}
        taken = set()
        new_steps = []
        for call_id in extra_call_ids:
            made = self._new_step(doc, owner_id, call_id, taken)
            if made is None:
                return None, None
            new_steps.append(made)

        original = dict(step)
        original["children"] = [c for c in step.get("children", [])
                                if c not in extra_call_ids]

        owner = dict(nodes[owner_id])
        children = list(owner.get("children", []))
        at = children.index(step["id"]) + 1
        # Immediately after the original, not appended: `children` order is
        # execution order (RFC-0001 Workflow row), so the tail is a different
        # program.
        owner["children"] = (children[:at] + [s["id"] for s in new_steps]
                             + children[at:])
        # `origin` only. This node already has its own provenance, and rewriting
        # `meta.source` under cover of an attachment is what the gate refuses.
        owner["meta"] = dict(owner.get("meta") or {},
                             origin="agent:%s" % self.role)

        intent = {
            "attach": [{"parent": owner_id, "child": s["id"]} for s in new_steps],
            "move": [{"node": s["children"][0], "from": step["id"], "to": s["id"]}
                     for s in new_steps],
        }
        return [owner, original] + new_steps, intent

    def propose(self, task, deadline_ms=30000):
        """Propose the first split this document needs, or refuse."""
        doc = self.server.doc
        violations = self._violations(doc)
        if not violations:
            return self._refuse(
                task, "no step owns more than one repository access",
                "kb:%s (한 step에 한 저장소 접근)" % self.KB_DOC)

        owner_id, step, extra = violations[0]
        nodes, intent = self._split(doc, owner_id, step, extra)
        if nodes is None:
            return self._refuse(
                task, "cannot derive a step name for every moved access",
                "RFC-0001 §노드 카탈로그 (WorkflowStep.name은 동사구)")

        fragment = {"lir_version": doc["lir_version"], "module": doc["module"],
                    "nodes": nodes}
        proposal = self.server.call("ir.propose", role=self.role,
                                    ir_fragment=fragment, intent=intent,
                                    deadline_ms=deadline_ms,
                                    idempotency_key="refactor-%s" % step["id"])
        self.server.call("agent.report", task_id=task["task_id"],
                         state="input-required",
                         payload={"proposed": proposal["proposal_id"],
                                  "split": step["id"],
                                  "moved": [m["node"] for m in intent["move"]]})
        return proposal


class ReleaseAgent(_AgentBase):
    """Read-only. Summarises what would ship, and never turns a failure into a pass."""

    role = "ReleaseAgent"

    def summarize(self, task, verification=None, deadline_ms=30000):
        overview = self.server.call("ir.get")
        nodes = {n["id"]: n for n in self.server.doc["nodes"]}
        by_kind = {}
        for node in nodes.values():
            by_kind[node["kind"]] = by_kind.get(node["kind"], 0) + 1

        ready, blockers = True, []
        if not verification:
            # `None` and `{}` are the same thing here: no evidence. An empty map is
            # the more dangerous of the two, because it looks like a result.
            ready = False
            blockers.append("no verification result was supplied")
        elif not isinstance(verification, dict):
            # `True`, "all green", [("t", True)] — a caller saying "it passed" in a
            # shape this cannot audit per check. Refusing beats iterating something
            # that happens to be iterable and calling the result readiness.
            ready = False
            blockers.append("verification must be a map of check name -> True, got %s"
                            % type(verification).__name__)
            verification = {}
        else:
            # Sorted by repr, not by key: mixed key types (1 and "a") make `sorted`
            # raise, and a crash while auditing evidence is not an audit.
            for name, ok in sorted(verification.items(), key=lambda kv: repr(kv[0])):
                if ok is not True:
                    # Only literal True counts. A truthy marker like "FAILED" would
                    # otherwise be read as a pass.
                    ready = False
                    blockers.append("verification %r is %r, not a pass" % (name, ok))

        summary = {"module": overview["module"],
                   "lir_version": overview["lir_version"],
                   "node_count": len(overview["node_ids"]),
                   "by_kind": by_kind,
                   "capabilities": sorted(n["name"] for n in nodes.values()
                                          if n["kind"] == "Capability"),
                   "verification": verification,
                   "ready": ready, "blockers": blockers}
        self.server.call("agent.report", task_id=task["task_id"], state="completed",
                         payload={"proposed": None, "summary": summary})
        return summary


def run_cycle(document, knowledge_base, intent, steps, schema_validator=None):
    """The full RFC-0006 Examples cycle. Returns (server, transcript)."""
    server = Server(document, knowledge_base, schema_validator=schema_validator)
    planner, coder, reviewer = Planner(server), Coder(server), Reviewer(server)

    transcript = []
    for item in planner.plan(intent, steps):
        record = coder.implement(item["task"], item["step"])
        transcript.append(record)
        if record["proposal_id"]:
            # No `approve=` argument: the Reviewer judges. Passing True here made
            # the one end-to-end path the README advertises the single path that
            # never exercised the judgment, which is the rubber stamp this work
            # was meant to remove.
            approved = reviewer.decide(record["review_task_id"],
                                       record["proposal_id"])
            record["review_state"] = approved["state"]
            record["applied"] = approved["result"]["applied_nodes"]
    return server, transcript


def _slug(text):
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower())
