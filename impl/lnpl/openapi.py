"""IR -> OpenAPI 3.1 (RFC-0004 Architecture Optimizer, auto-generation).

CHARTER lists OpenAPI among the artifacts the platform generates rather than
hand-writes. The generator is deterministic and total: every fact in the output
traces to a node in the Semantic IR, and anything the IR does not state is left
out rather than invented.

Mapping (each row cites the IR that produces it):

    Workflow            -> one POST path  /<service-slug>/<workflow-slug>
    Entity.fields       -> the request schema, by semantic type
    Refinement          -> a named schema; fields of that type `$ref` it
    Password field      -> `format: password`, `writeOnly: true`
    Validation effect   -> which fields the request body requires
    Security jwt        -> a bearerAuth security scheme, applied per operation
    Performance response-> `x-response-slo-ms` on the operation
    Policy retry/timeout-> `x-retry` / `x-timeout-ms` on the operation
    Guard when          -> `x-conditional-steps` (the steps that may be skipped)
    Response(respond)   -> the 200 response's `content` schema, grouped by binding
    entity a workflow touches (issue #99, D1) -> one GET /<service-slug>/
                           <entity-slug>/{id} path, auto, no declaration needed
    Expose(expose list) -> one GET /<service-slug>/<entity-slug> path (issue #99,
                           D2 — opt-in only, no `expose` clause means no path)
    Event.subscribe     -> one GET /<service-slug>/events/<event-slug> path,
                           text/event-stream (issue #103 — opt-in only, and
                           only for a service whose own workflow `emit`s it,
                           same "reachable, not declared" rule D1 already uses)
"""

from .diagnostics import ENFORCEMENT
from .interp import _duration_ms
from .refinements import BASE_CATEGORY, facets_for_base
from .repo_policy import binding_name, event_emissions, repository_calls
from .types import SEMANTIC_TYPES

# Semantic type -> OpenAPI schema, projected from the one type registry
# (issue #24). Only the types RFC-0001 defines; an unknown type is an error, not
# a `{}` that silently accepts anything.
TYPE_SCHEMA = {name: spec["openapi"] for name, spec in SEMANTIC_TYPES.items()}

# Facet -> the JSON Schema keyword it projects to (RFC-0001 A.6.6). The names
# already agree; only the two numeric bounds are spelled differently.
FACET_KEYWORD = {"minLength": "minLength", "maxLength": "maxLength",
                 "pattern": "pattern", "min": "minimum", "max": "maximum",
                 "enum": "enum"}

# `Decimal` encodes as a string, and JSON Schema applies `minimum`/`maximum`
# and a numeric `enum` only to a number instance -- on a string schema
# `minimum: 1` accepts "-99" and a numeric `enum` is unsatisfiable. A.6.6
# defers this case to RFC-0004, so the facets ride the `x-` extension this file
# already uses for IR facts OpenAPI has no keyword for (`x-retry`, ...).
DECIMAL_FACET_KEYWORD = {"min": "x-min", "max": "x-max", "enum": "x-enum"}

# The Python types an `enum` member may take, keyed by the base's JSON Schema
# `type`. A.6.3 permits `enum` on the text and numeric categories and does not
# tie the member type to the base, so both directions of mismatch are
# constructible -- and each produces a schema no instance satisfies. `bool` is
# excluded everywhere: Python's bool subclasses int, and JSON `true` is not a
# number instance. `Decimal` is absent by design -- its base encodes as
# `string` while its members are legitimately numeric, and its facets ride
# `x-enum`, which the check below does not key on.
ENUM_MEMBER_TYPES = {"string": (str,), "integer": (int,), "number": (int, float)}

# How a facet composes onto a keyword the base already fixes. RFC-0001 A.6.2:
# a refinement NARROWS its base, so the answer is per keyword and directional --
# an upper bound narrows downward (intersect by taking the smaller), a lower
# bound narrows upward (take the larger). The facet is legal only when the
# intersection IS the facet; otherwise it widens the base, which is not a
# refinement and is refused. `pattern` is deliberately not in this table: two
# regexes have no intersection expressible as one `pattern`, so they compose as
# an `allOf` conjunction -- which can only remove instances, so a `pattern`
# never widens and has no refusal case (at the cost of not detecting two
# disjoint patterns). A keyword in neither place -- today only `enum`, which no
# base carries -- is refused rather than silently overwritten.
#
# The rule is about narrowing, not about which keyword the base happened to
# use, which is why it gives `Phone` (regex as a real `pattern`, types.py:48)
# and `UUID`/`Email`/`DateTime` (regex as a non-assertive `format`) the same
# answer where the old rule gave them opposite ones.
NARROWING = {"minLength": max, "minimum": max, "maxLength": min, "maximum": min}


class OpenApiError(Exception):
    """Raised when the IR states something this generator cannot express."""


def _slug(name):
    # Word boundary rule, identical to `lower.split_pascal`'s: a capital starts
    # a new word only when it is not inside a run of capitals, or is the last
    # capital of a run before a lowercase letter. Without the run test an
    # acronym explodes -- `APIKey` slugs to `a-p-i-key`. Keep this in step with
    # `lower.split_pascal`: both derive names for the same declarations, and a
    # disagreement puts a node id and its URL out of sync.
    out = []
    for i, ch in enumerate(name):
        if i and ch.isupper() and (not name[i - 1].isupper()
                                   or (i + 1 < len(name) and name[i + 1].islower())):
            out.append("-")
        out.append(ch.lower())
    return "".join(out)


def _refinement_schema(node):
    """A Refinement node -> its named schema: the base schema, strengthened."""
    base = node["base"]
    if base not in TYPE_SCHEMA or base not in BASE_CATEGORY:
        raise OpenApiError(
            "refinement %s: %r is not one of the 18 semantic types RFC-0001 "
            "A.6.2 allows as a base" % (node["name"], base))
    # Which facets the base's category admits (A.6.3). RFC-0001 A.7 puts this
    # invariant (ⓓ) outside what `schemas/lir.schema.json` checks, so a
    # schema-valid document can carry a facet the category forbids -- and
    # `generate` is a public entry point, not only the tail of `compile_source`.
    # Consulting the category rather than a per-base keyword table is what makes
    # the lookup below total: every facet a category admits has a projection for
    # every base in it (pinned by the test of that name in test_openapi.py).
    # Facet *values* are not checked here -- the IR schema types them
    # (`lir.schema.json:167-195`), so only a hand-built dict can carry a wrong
    # one, and that is a different invariant from ⓓ.
    allowed = facets_for_base(base)
    keywords = DECIMAL_FACET_KEYWORD if base == "Decimal" else FACET_KEYWORD
    schema = dict(TYPE_SCHEMA[base])
    for facet, value in node["facets"].items():
        if facet not in allowed:
            raise OpenApiError(
                "refinement %s: facet %r does not apply to base %s "
                "(RFC-0001 A.6.3)" % (node["name"], facet, base))
        keyword = keywords[facet]
        if keyword in schema and schema[keyword] != value:
            if keyword in NARROWING:
                if NARROWING[keyword](schema[keyword], value) != value:
                    raise OpenApiError(
                        "refinement %s cannot set %s to %r: base %s fixes it "
                        "at %r and %r widens it, but a refinement narrows its "
                        "base (RFC-0001 A.6.2)"
                        % (node["name"], keyword, value, base, schema[keyword],
                           value))
            elif keyword == "pattern":
                schema.setdefault("allOf", []).append({"pattern": value})
                continue
            else:
                raise OpenApiError(
                    "refinement %s cannot compose %s onto base %s: the "
                    "composition rule defines no intersection for that keyword"
                    % (node["name"], keyword, base))
        schema[keyword] = value
    _reject_uninhabited(node["name"], base, schema)
    return schema


def _reject_uninhabited(name, base, schema):
    """Refuse a composition no instance can satisfy.

    RFC-0001 A.6.2: a refinement narrows its base. Narrowing to nothing is a
    mistake, not a type -- and nothing downstream catches it, because an
    uninhabited schema is still a structurally valid one (`check_schema` asks
    whether a schema is well-formed, not whether anything satisfies it).

    Deliberately narrow: this checks the ordered bound pairs and the `enum`,
    and nothing else. Full satisfiability -- does any `enum` member match the
    `pattern`, is a `pattern` inhabited, are two `pattern`s disjoint -- is a
    much larger problem and is NOT attempted here. That is a decision, not an
    oversight; the cases below are the ones a user actually hits.
    """
    for lo, hi in (("minLength", "maxLength"), ("minimum", "maximum"),
                   ("x-min", "x-max")):
        if lo in schema and hi in schema and schema[lo] > schema[hi]:
            raise OpenApiError("refinement %s is unsatisfiable: %s %r exceeds "
                               "%s %r" % (name, lo, schema[lo], hi, schema[hi]))
    if "enum" in schema:
        if not schema["enum"]:
            raise OpenApiError("refinement %s is unsatisfiable: an empty enum "
                               "admits no value (RFC-0001 A.6.3 requires at "
                               "least one member)" % name)
        want = ENUM_MEMBER_TYPES.get(schema.get("type"))
        if want is not None:
            bad = [m for m in schema["enum"]
                   if isinstance(m, bool) or not isinstance(m, want)]
            if bad:
                raise OpenApiError(
                    "refinement %s is unsatisfiable: enum member(s) %r cannot "
                    "be a %s, which is what base %s encodes as"
                    % (name, bad, schema["type"], base))


def generate(document, version="0.1.0"):
    """Semantic IR document -> an OpenAPI 3.1 dict."""
    nodes = {n["id"]: n for n in document["nodes"]}
    entities = [n for n in document["nodes"] if n["kind"] == "Entity"]
    services = [n for n in document["nodes"] if n["kind"] == "Service"]

    schemas, paths = {}, {}
    for node in document["nodes"]:
        if node["kind"] == "Refinement":
            schemas[node["name"]] = _refinement_schema(node)
    refined = set(schemas)
    for entity in entities:
        if entity["name"] in refined:
            raise OpenApiError(
                "name collision in components/schemas: %r is both an entity "
                "and a refinement" % entity["name"])
        schemas[entity["name"]] = _entity_schema(entity, refined)

    uses_bearer = False
    for service in services:
        con = _constraints(service, nodes)
        uses_bearer = uses_bearer or "jwt" in con["mechanisms"]
        svc_slug = _slug(service["name"])
        entity_ids = set()
        event_ids = set()
        for child_id in service.get("children", []):
            child = nodes[child_id]
            if child["kind"] == "Workflow":
                path = "/%s/%s" % (svc_slug, _slug(child["name"]))
                paths[path] = {"post": _operation(child, service, con, nodes,
                                                  entities, refined)}
                entity_ids.update(eid for eid, _op
                                  in repository_calls(document, child_id))
                event_ids.update(event_emissions(document, child_id))
            elif child["kind"] == "Expose":
                entity = nodes[child["entity"]]
                list_path = "/%s/%s" % (svc_slug, _slug(entity["name"]))
                paths.setdefault(list_path, {})["get"] = _get_list_operation(
                    service, entity, child["field"], con)
        for eid in sorted(entity_ids):
            entity = nodes[eid]
            single_path = "/%s/%s/{id}" % (svc_slug, _slug(entity["name"]))
            paths.setdefault(single_path, {})["get"] = _get_single_operation(
                service, entity, con)
        for eid in sorted(event_ids):
            event = nodes[eid]
            if not event.get("subscribe"):
                continue
            events_path = "/%s/events/%s" % (svc_slug, _slug(event["name"]))
            paths.setdefault(events_path, {})["get"] = _events_operation(
                service, event, con)

    spec = {
        "openapi": "3.1.0",
        "info": {"title": "%s API" % document["module"],
                 "version": version,
                 "description": "Generated from Semantic IR "
                                "(lir_version %s). Do not edit by hand."
                                % document["lir_version"]},
        "paths": paths,
        "components": {"schemas": schemas},
    }
    if uses_bearer:
        spec["components"]["securitySchemes"] = {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}

    # RFC-0016: schedule triggers ride a document-level extension rather than a
    # path. A schedule is not an HTTP operation, and inventing one would put an
    # endpoint in the contract that nothing serves. The key is omitted entirely
    # when no schedule is declared, so every document that predates RFC-0016
    # generates byte-identical output.
    #
    # `enforcement` is read from the matrix rather than written here, so the
    # document cannot claim a status the code does not hold.
    schedules = _schedules(document)
    if schedules:
        spec["x-lnpl-schedules"] = schedules
    return spec


def _schedules(document):
    """The declared schedule triggers, in node order, as OpenAPI metadata."""
    out = []
    for node in document["nodes"]:
        if node.get("kind") != "Event":
            continue
        source = node.get("source") or {}
        if "every" not in source:
            continue                       # an entity source, not a schedule
        out.append({"event": node["id"],
                    "every": source["every"],
                    "at": source["at"],
                    "zone": source["zone"],
                    "enforcement": ENFORCEMENT[("event", "schedule")][0]})
    return out


def _entity_schema(entity, refined):
    props, required = {}, []
    for field in entity.get("fields", []):
        tname = field["type"]
        if tname in refined:
            # 3.1 honours keywords beside a `$ref`, but the IR states nothing
            # about the field beyond its type, so the reference stands alone.
            props[field["name"]] = {"$ref": "#/components/schemas/%s" % tname}
        elif tname not in TYPE_SCHEMA:
            raise OpenApiError("no OpenAPI mapping for semantic type %r "
                               "(field %s.%s)" % (tname, entity["name"], field["name"]))
        else:
            props[field["name"]] = dict(TYPE_SCHEMA[tname])
        if field.get("derived"):
            # issue #95: server-computed — never required of a request, and
            # marked the way `Password`/`writeOnly` already marks the mirror
            # case, so request and response keep sharing this one schema
            # ($ref) rather than splitting into two.
            props[field["name"]]["readOnly"] = True
            continue
        if field.get("required", True):
            required.append(field["name"])
    schema = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def _required_role(mechanisms):
    """The `<r>` in this service's `security role <r>`, or `None` (issue
    #119, D5/D12) — mirrors `wsgi._required_role`; kept local rather than
    imported across modules for a two-line lookup over an already-parsed
    list `wsgi.py` never hands this module."""
    for mech in mechanisms:
        if mech.startswith("role "):
            return mech[len("role "):]
    return None


def _apply_role(op, con):
    """D12: role requirements ride the `x-lnpl-roles` extension, not an
    OAuth2 scope — a scope is something the CLIENT requests and the server
    grants a subset of; `security role <r>` is a fixed server-side
    requirement the client cannot negotiate, so modelling it as a scope
    would have the contract assert something false."""
    required_role = _required_role(con["mechanisms"])
    if required_role is not None:
        op["x-lnpl-roles"] = [required_role]
        op["responses"]["403"] = {
            "description": "the caller's verified role does not satisfy "
                           "this service's `security role` requirement"}


def _constraints(service, nodes):
    out = {"mechanisms": [], "retry": None, "timeout_ms": None,
           "response_slo_ms": None}
    for cid in service.get("constraints", []):
        node = nodes.get(cid)
        if node is None:
            raise OpenApiError("dangling constraint reference %r" % cid)
        if node["kind"] == "Security":
            out["mechanisms"] = list(node.get("mechanisms", []))
        elif node["kind"] == "Policy":
            for rule in node.get("rules", []):
                if rule["name"] == "retry":
                    out["retry"] = rule["value"]
                elif rule["name"] == "timeout":
                    out["timeout_ms"] = _duration_ms(rule["value"])
        elif node["kind"] == "Performance":
            for b in node.get("budgets", []):
                if b["metric"] == "response":
                    out["response_slo_ms"] = _duration_ms(
                        str(b["value"]).lstrip("<>="))
    return out


def _walk_steps(nodes, ids, conditional=None):
    """Yield WorkflowStep nodes, recording which ones sit under a `when` guard."""
    for nid in ids:
        node = nodes[nid]
        if node["kind"] == "WorkflowStep":
            yield node
        elif node["kind"] in ("Concurrency", "Pipeline"):
            for inner in _walk_steps(nodes, node.get("children", []), conditional):
                yield inner
        elif node["kind"] == "Guard":
            for inner in _walk_steps(nodes, node.get("children", []), conditional):
                if node["mode"] == "when" and conditional is not None:
                    conditional.append(inner["name"])
                yield inner


def _response_schema(steps, nodes, entities, refined):
    """issue #96, D6: the `respond`-declared FieldMask -> a 200 response
    schema, grouped by binding the same way `interp`'s `result["response"]`
    groups its values (`{"<binding>": {"<field>": ...}}`) — the two shapes
    must agree, or the OpenAPI contract would describe a body the server
    never sends. Returns None when the workflow declares no `respond`, so a
    document without one generates byte-identical output (D4).
    """
    refs = None
    for step in steps:
        for child_id in step.get("children", []):
            effect = nodes[child_id]
            if effect["kind"] == "Response":
                refs = effect["refs"]
    if refs is None:
        return None

    by_binding = {binding_name(e): e for e in entities}
    grouped, order = {}, []
    for ref in refs:
        binding, _, field_name = ref.partition(".")
        entity = by_binding[binding]
        field = next(f for f in entity["fields"] if f["name"] == field_name)
        tname = field["type"]
        if tname in refined:
            field_schema = {"$ref": "#/components/schemas/%s" % tname}
        else:
            field_schema = dict(TYPE_SCHEMA[tname])
        if field.get("derived"):
            # issue #95: server-computed — the response schema marks it
            # read-only the same way `_entity_schema` already does.
            field_schema["readOnly"] = True
        if binding not in grouped:
            grouped[binding] = {}
            order.append(binding)
        grouped[binding][field_name] = field_schema

    properties = {binding: {"type": "object", "properties": grouped[binding],
                            "required": list(grouped[binding]),
                            "additionalProperties": False}
                 for binding in order}
    return {"type": "object", "properties": properties, "required": order,
           "additionalProperties": False}


def _operation(wf, service, con, nodes, entities, refined):
    conditional = []
    steps = list(_walk_steps(nodes, wf.get("children", []), conditional))

    request_entity = None
    for step in steps:
        for child_id in step.get("children", []):
            effect = nodes[child_id]
            if effect["kind"] == "Validation":
                target = effect["target"]
                entity_id = ".".join(target.split(".")[:2])
                request_entity = next((e for e in entities if e["id"] == entity_id), None)

    response_schema = _response_schema(steps, nodes, entities, refined)

    op = {
        "operationId": "%s_%s" % (_slug(service["name"]).replace("-", "_"),
                                  _slug(wf["name"]).replace("-", "_")),
        "summary": "%s workflow" % wf["name"],
        "description": "Steps: %s" % " -> ".join(s["name"] for s in steps),
        "responses": {
            "200": {"description": "the workflow completed"},
            "400": {"description": "validation failed"},
            "409": {"description": "a repository create conflicted with an existing row (conflict), or another request with the same Idempotency-Key is still running (idempotency-in-progress) -- issue #113"},
            "412": {"description": "If-Match no longer matches the current version of the entity this workflow reads -- issue #113"},
            "504": {"description": "the workflow deadline was exceeded"},
        },
        "parameters": [
            {"name": "Idempotency-Key", "in": "header", "required": False,
             "schema": {"type": "string"},
             "description": "replay this workflow's prior response for the same key instead of running it again"},
            {"name": "If-Match", "in": "header", "required": False,
             "schema": {"type": "string"},
             "description": "the ETag a prior GET of the entity this workflow reads returned; 412 on mismatch"},
        ],
    }
    if response_schema is not None:
        op["responses"]["200"]["content"] = {
            "application/json": {"schema": response_schema}}
    if request_entity is not None:
        op["requestBody"] = {
            "required": True,
            "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/%s" % request_entity["name"]}}},
        }
    if "jwt" in con["mechanisms"]:
        op["security"] = [{"bearerAuth": []}]
        op["responses"]["401"] = {"description": "authentication failed"}
    _apply_role(op, con)
    if con["response_slo_ms"] is not None:
        op["x-response-slo-ms"] = con["response_slo_ms"]
    if con["retry"] is not None:
        op["x-retry"] = con["retry"]
    if con["timeout_ms"] is not None:
        op["x-timeout-ms"] = con["timeout_ms"]
    if conditional:
        op["x-conditional-steps"] = conditional
    return op


def _get_single_operation(service, entity, con):
    """issue #99, D1/D6: single-row GET, auto for any entity a service's
    workflows touch. The 200 body IS the entity schema — already `readOnly`-
    correct via `_entity_schema` (issue #95) — so no field-by-field builder
    is needed the way `_response_schema` needed one for `respond`'s partial
    FieldMask.
    """
    op = {
        "operationId": "%s_get_%s" % (_slug(service["name"]).replace("-", "_"),
                                      _slug(entity["name"]).replace("-", "_")),
        "summary": "get one %s" % entity["name"],
        "parameters": [{"name": "id", "in": "path", "required": True,
                        "schema": {"type": "string"}}],
        "responses": {
            "200": {"description": "the row, masked",
                    "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/%s"
                                          % entity["name"]}}},
                    "headers": {
                        "ETag": {"schema": {"type": "string"},
                                "description": "weak validator (W/\"<version>\"); "
                                               "absent on a backend with no "
                                               "row versioning -- issue #113, D12"}}},
            "404": {"description": "no such row"},
        },
    }
    if "jwt" in con["mechanisms"]:
        op["security"] = [{"bearerAuth": []}]
        op["responses"]["401"] = {"description": "authentication failed"}
    _apply_role(op, con)
    return op


def _get_list_operation(service, entity, field, con):
    """issue #99, D2/D3/D6: the opt-in cursor-paginated list GET. The 200
    envelope (`items`/`next`) mirrors exactly what `serve.py`'s `_get_list`
    sends — same discipline `_response_schema` follows for `respond`: the
    OpenAPI contract must describe the body the server actually returns.
    """
    op = {
        "operationId": "%s_list_%s" % (_slug(service["name"]).replace("-", "_"),
                                       _slug(entity["name"]).replace("-", "_")),
        "summary": "list %s by %s" % (entity["name"], field),
        "parameters": [
            {"name": "after", "in": "query", "required": False,
             "schema": {"type": "string"},
             "description": "opaque cursor from a previous page's `next`"},
            {"name": "limit", "in": "query", "required": False,
             "schema": {"type": "integer"}},
        ],
        "responses": {
            "200": {"description": "a page, ordered by %s ascending" % field,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "items": {"type": "array",
                                     "items": {"$ref": "#/components/schemas/%s"
                                               % entity["name"]}},
                            "next": {"type": ["string", "null"]},
                        },
                        "required": ["items", "next"],
                        "additionalProperties": False,
                    }}}},
            "400": {"description": "malformed `after` cursor or `limit`"},
        },
    }
    if "jwt" in con["mechanisms"]:
        op["security"] = [{"bearerAuth": []}]
        op["responses"]["401"] = {"description": "authentication failed"}
    _apply_role(op, con)
    return op


def _events_operation(service, event, con):
    """issue #103, D2/D3/D4: the opt-in SSE subscribe surface. The body is an
    open-ended sequence of `id:`/`data:` frames, not one JSON document, so
    `text/event-stream` replaces `_get_list_operation`'s JSON schema — there
    is no OpenAPI/JSON-Schema vocabulary for an SSE frame sequence.
    """
    op = {
        "operationId": "%s_subscribe_%s" % (_slug(service["name"]).replace("-", "_"),
                                            _slug(event["name"]).replace("-", "_")),
        "summary": "subscribe to %s" % event["name"],
        "parameters": [
            {"name": "Last-Event-ID", "in": "header", "required": False,
             "schema": {"type": "string"},
             "description": "resume after this outbox seq, no loss (D3)"},
        ],
        "responses": {
            "200": {"description": "an SSE stream of masked emissions, "
                                   "id: is the outbox seq",
                    "content": {"text/event-stream": {"schema": {"type": "string"}}}},
            "400": {"description": "Last-Event-ID is not a valid seq"},
        },
    }
    if "jwt" in con["mechanisms"]:
        op["security"] = [{"bearerAuth": []}]
        op["responses"]["401"] = {"description": "authentication failed"}
    _apply_role(op, con)
    return op
