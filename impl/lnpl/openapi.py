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
"""

from .interp import _duration_ms
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


class OpenApiError(Exception):
    """Raised when the IR states something this generator cannot express."""


def _slug(name):
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i:
            out.append("-")
        out.append(ch.lower())
    return "".join(out)


def _refinement_schema(node):
    """A Refinement node -> its named schema: the base schema, strengthened."""
    base = node["base"]
    keywords = DECIMAL_FACET_KEYWORD if base == "Decimal" else FACET_KEYWORD
    schema = dict(TYPE_SCHEMA[base])
    for facet, value in node["facets"].items():
        keyword = keywords[facet]
        if keyword in schema and schema[keyword] != value:
            raise OpenApiError(
                "refinement %s cannot set %s to %r: base %s already fixes it "
                "at %r, and a refinement strengthens its base rather than "
                "replacing it" % (node["name"], keyword, value, base,
                                  schema[keyword]))
        schema[keyword] = value
    return schema


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
        for wf_id in service.get("children", []):
            wf = nodes[wf_id]
            if wf["kind"] != "Workflow":
                continue
            path = "/%s/%s" % (_slug(service["name"]), _slug(wf["name"]))
            paths[path] = {"post": _operation(wf, service, con, nodes, entities)}

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
    return spec


def _entity_schema(entity, refined):
    props, required = {}, []
    for field in entity.get("fields", []):
        tname = field["type"]
        if tname in refined:
            # 3.1 honours keywords beside a `$ref`, but the IR states nothing
            # about the field beyond its type, so the reference stands alone.
            props[field["name"]] = {"$ref": "#/components/schemas/%s" % tname}
            if field.get("required", True):
                required.append(field["name"])
            continue
        if tname not in TYPE_SCHEMA:
            raise OpenApiError("no OpenAPI mapping for semantic type %r "
                               "(field %s.%s)" % (tname, entity["name"], field["name"]))
        props[field["name"]] = dict(TYPE_SCHEMA[tname])
        if field.get("required", True):
            required.append(field["name"])
    schema = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


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


def _operation(wf, service, con, nodes, entities):
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

    op = {
        "operationId": "%s_%s" % (_slug(service["name"]).replace("-", "_"),
                                  _slug(wf["name"]).replace("-", "_")),
        "summary": "%s workflow" % wf["name"],
        "description": "Steps: %s" % " -> ".join(s["name"] for s in steps),
        "responses": {
            "200": {"description": "the workflow completed"},
            "400": {"description": "validation failed"},
            "504": {"description": "the workflow deadline was exceeded"},
        },
    }
    if request_entity is not None:
        op["requestBody"] = {
            "required": True,
            "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/%s" % request_entity["name"]}}},
        }
    if "jwt" in con["mechanisms"]:
        op["security"] = [{"bearerAuth": []}]
        op["responses"]["401"] = {"description": "authentication failed"}
    if con["response_slo_ms"] is not None:
        op["x-response-slo-ms"] = con["response_slo_ms"]
    if con["retry"] is not None:
        op["x-retry"] = con["retry"]
    if con["timeout_ms"] is not None:
        op["x-timeout-ms"] = con["timeout_ms"]
    if conditional:
        op["x-conditional-steps"] = conditional
    return op
