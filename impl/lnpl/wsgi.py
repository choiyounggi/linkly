"""The WSGI callable that serves compiled LNPL workflows (issue #80).

This is the request-processing core that used to live entirely inside
`serve.py`'s `BaseHTTPRequestHandler` subclass: routing, the M1-M16
status-code mapping, JWT presence/verification, masking, GET single/list,
and SSE subscribe. It is re-expressed here against the standard `environ`/
`start_response` interface (PEP 3333) so any WSGI host — gunicorn behind
nginx in production, or the stdlib `wsgiref` dev server `serve.py` wraps —
serves the exact same code path. `serve.serve()` is a thin dev-server
wrapper around `make_wsgi_app()`; it does not re-implement any of this.

`build_app()` is the factory a WSGI host calls with no arguments —
`gunicorn "lnpl.wsgi:build_app()"` — so every argument it takes falls back
to an `LNPL_*` environment variable (issue #80, D1). The endpoint mapping
for outbound `NetworkCall`s reuses the `LNPL_ENDPOINT_<NAME>` contract
issue #101 already established; this module does not invent a second one.

The status-code mapping table (M1-M9 + the GET/SSE additions M10-M16) is
normative in docs/serving.md.
"""

import base64
import binascii
import hashlib
import http.client
import json
import os
import sys
import threading
import time
import urllib.parse
import uuid
from importlib import metadata as importlib_metadata

from .drivers import (DriverError, HmacTokenProvider, HttpNetworkDriver,
                      TokenError, _is_url_literal, audience_for_path,
                      open_repository)
from .diagnostics import format_lines, to_records
from .interp import (Interpreter, caller_view, mask_payload, open_clock,
                     refinement_index)
from .lexer import LexError
from .lower import LowerError, load_sources, lower
from .openapi import generate, _slug
from .parser import ParseError
from .repo_policy import default_rows, event_emissions, repository_calls, row_key
from .tracecontext import new_span_id, new_trace_id, parse_traceparent

# M4: refuse to buffer more than this before reading a byte. The Fake-backend
# dev server has no streaming consumer, so anything past 1 MiB is a mistake.
MAX_BODY_BYTES = 1 << 20

# issue #113, D10: how long a `(workflow_id, key)` claim survives before a
# repeat becomes a fresh miss instead of a replay/409. Unbounded retention
# would grow `lnpl_idempotency` forever; a client relying on idempotency
# past this window has already exceeded what Stripe's own contract
# promises (24h) and needs a new key anyway.
DEFAULT_IDEMPOTENCY_TTL_MS = 24 * 60 * 60 * 1000

# issue #99, D3: the cursor page-size ceiling. `limit` outside [1, MAX_LIMIT]
# is a 400 (`limit-invalid`), not a silent clamp — a client that asked for
# 1,000,000 rows gets a refusal that names the ceiling, not a page it never
# expected.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# issue #103, D5: constants an SSE stream's generator owns itself — a WSGI
# host has no separate reactor to bound an idle stream from outside, so the
# generator's own poll loop is what stops a slow/dead subscriber from
# pinning a worker forever. Module-level (read at call time, not captured at
# def time) so a test can shrink them for a fast, deterministic idle-timeout
# check without waiting out the production value — patch
# `lnpl.wsgi.SSE_POLL_INTERVAL_S`/`SSE_IDLE_TIMEOUT_S`, the module the loop
# actually reads from.
SSE_POLL_INTERVAL_S = 0.2
SSE_IDLE_TIMEOUT_S = 30.0

# issue #78: the closed table `--log-format` accepts. "text" (default) is the
# pre-existing silent behavior — no access log at all (D2, byte-identical).
# "json" emits one JSON Line per request to stderr, the same operational
# channel every other line here already uses.
LOG_FORMATS = ("text", "json")


def _etag_value(version):
    """`_version` -> the weak validator this server issues (issue #113,
    D12). Weak (`W/`), not strong: nothing here promises the masked JSON
    body a client reads back is byte-identical across every code path that
    can produce it, and a weak validator only claims semantic equivalence."""
    return 'W/"%d"' % version


def _parse_if_match(value):
    """The inverse of `_etag_value` -> the version an `If-Match` header
    claims, or `None` when the value is not this server's own ETag shape.
    `*` and multi-value `If-Match` lists (RFC 9110 §13.1.1) are not
    produced by this server's own GET, so neither is accepted here --
    a value this parser rejects is treated as malformed (D13's boundary),
    not silently matched or ignored.
    """
    text = value.strip()
    if text.startswith("W/"):
        text = text[2:]
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        return None
    digits = text[1:-1]
    if not digits.isdigit():
        return None
    return int(digits)


def open_log_format(spec):
    """`--log-format`'s value -> itself, validated; `ValueError` on a bad
    selector, naming the accepted set (mirrors `interp.open_clock`)."""
    if spec in LOG_FORMATS:
        return spec
    raise ValueError("unknown log format %r (accepted: %s)"
                     % (spec, ", ".join(LOG_FORMATS)))


class ExporterError(Exception):
    """The one error type a `TraceExporter` registration/load failure
    translates into (mirrors `DriverError`, drivers.py)."""


class TraceExporter:
    """issue #78: the adapter contract for exporting one completed request's
    Trace. `export(trace_dict)` receives exactly `interp.Trace.to_dict()`'s
    shape — `{"correlation_id", "span", "metrics", "logs"}` — already having
    passed through `mask_payload` wherever a value came from an entity field
    (no second masking rule, same as every other output channel here).
    """

    def export(self, trace_dict):
        raise NotImplementedError


class StderrJsonExporter(TraceExporter):
    """Built-in: one JSON line per exported trace, written to stderr."""

    def export(self, trace_dict):
        print(json.dumps(trace_dict, ensure_ascii=False), file=sys.stderr)


# issue #110, D7: the histogram boundaries `lnpl_workflow_duration_seconds`
# uses (seconds) — the widely-used Prometheus client default bucket set,
# reused rather than invented (out of scope: bucket tuning, per the brief).
_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75,
                    1.0, 2.5, 5.0, 7.5, 10.0)


def _label_value(value):
    """A Prometheus exposition-format label value: a double-quoted string
    with `\\`/`"`/newline escaped (the format's own escaping rules)."""
    escaped = (str(value).replace("\\", "\\\\")
              .replace('"', '\\"').replace("\n", "\\n"))
    return '"%s"' % escaped


class MetricsRegistry:
    """issue #110, D7/D9/D10: the process-level RED registry `--metrics`
    exposes at `/-/metrics`.

    D9: lives ALONGSIDE `Trace.metrics`, not instead of it. That array is
    the per-request `--trace-exporter` (#78) contract and is neither read
    from nor written to here — this registry is populated by reading a
    COMPLETED request's already-computed `result` (`_respond`), so removing
    `--trace-exporter` support later could never affect this registry, and
    vice versa.

    D10: `wsgi` is one thread per request (`_Server(ThreadingMixIn, ...)`,
    serve.py), so every update goes through `_lock` — an unprotected `+=`
    here would lose updates under concurrent requests.

    D7's three: `lnpl_workflow_runs_total{service,workflow,status}`
    (counter), `lnpl_workflow_duration_seconds{service,workflow}`
    (histogram), `lnpl_step_failures_total{service,workflow,step,kind}`
    (counter) — every label already inside `Trace.metric`'s own allowlist
    (D7: no new label axis).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._runs_total = {}            # (service, workflow, status) -> int
        self._step_failures_total = {}   # (service, workflow, step, kind) -> int
        # Cumulative bucket counts (Prometheus convention: bucket[i] counts
        # every observation <= its bound, so rendering needs no further
        # summation) + running sum/count for `_sum`/`_count`.
        self._duration_buckets = {}      # (service, workflow) -> [int, ...]
        self._duration_sum = {}          # (service, workflow) -> float
        self._duration_count = {}        # (service, workflow) -> int

    def record_run(self, service, workflow, status, duration_s):
        key = (service, workflow, status)
        dkey = (service, workflow)
        with self._lock:
            self._runs_total[key] = self._runs_total.get(key, 0) + 1
            buckets = self._duration_buckets.setdefault(
                dkey, [0] * len(_DURATION_BUCKETS))
            for i, bound in enumerate(_DURATION_BUCKETS):
                if duration_s <= bound:
                    buckets[i] += 1
            self._duration_sum[dkey] = self._duration_sum.get(dkey, 0.0) + duration_s
            self._duration_count[dkey] = self._duration_count.get(dkey, 0) + 1

    def record_step_failure(self, service, workflow, step, kind):
        key = (service, workflow, step, kind)
        with self._lock:
            self._step_failures_total[key] = self._step_failures_total.get(key, 0) + 1

    def render(self):
        """-> Prometheus text exposition format (D7's RED 3). A stable sort
        over every series so the same registry state always renders the
        same text — a scraper (and a test) can parse this, not just count
        lines."""
        with self._lock:
            runs = dict(self._runs_total)
            failures = dict(self._step_failures_total)
            buckets = {k: list(v) for k, v in self._duration_buckets.items()}
            sums = dict(self._duration_sum)
            counts = dict(self._duration_count)
        lines = [
            "# HELP lnpl_workflow_runs_total Total workflow runs, by outcome.",
            "# TYPE lnpl_workflow_runs_total counter",
        ]
        for service, workflow, status in sorted(runs):
            lines.append(
                "lnpl_workflow_runs_total{service=%s,workflow=%s,status=%s} %d"
                % (_label_value(service), _label_value(workflow),
                   _label_value(status), runs[(service, workflow, status)]))
        lines += [
            "# HELP lnpl_workflow_duration_seconds Workflow run duration, in seconds.",
            "# TYPE lnpl_workflow_duration_seconds histogram",
        ]
        for service, workflow in sorted(buckets):
            dkey = (service, workflow)
            bucket_counts = buckets[dkey]
            for i, bound in enumerate(_DURATION_BUCKETS):
                lines.append(
                    "lnpl_workflow_duration_seconds_bucket{service=%s,workflow=%s,le=%s} %d"
                    % (_label_value(service), _label_value(workflow),
                       _label_value(repr(bound)), bucket_counts[i]))
            lines.append(
                'lnpl_workflow_duration_seconds_bucket{service=%s,workflow=%s,le="+Inf"} %d'
                % (_label_value(service), _label_value(workflow), counts[dkey]))
            lines.append(
                "lnpl_workflow_duration_seconds_sum{service=%s,workflow=%s} %s"
                % (_label_value(service), _label_value(workflow), repr(sums[dkey])))
            lines.append(
                "lnpl_workflow_duration_seconds_count{service=%s,workflow=%s} %d"
                % (_label_value(service), _label_value(workflow), counts[dkey]))
        lines += [
            "# HELP lnpl_step_failures_total Total step failures, by classification.",
            "# TYPE lnpl_step_failures_total counter",
        ]
        for service, workflow, step, kind in sorted(failures):
            lines.append(
                "lnpl_step_failures_total{service=%s,workflow=%s,step=%s,kind=%s} %d"
                % (_label_value(service), _label_value(workflow), _label_value(step),
                   _label_value(kind), failures[(service, workflow, step, kind)]))
        return "\n".join(lines) + "\n"


# issue #78: the entry-points group an external package registers a
# TraceExporter factory under — `_driver_entry_points()`'s shape (t75,
# drivers.py) mirrored for exporters. Built-in `stderr-json` is matched
# before this group is ever consulted, so a registered entry-point can never
# shadow it.
EXPORTERS = ("stderr-json",)
EXPORTERS_ENTRY_POINT_GROUP = "lnpl.exporters"


def _exporter_entry_points():
    try:
        return importlib_metadata.entry_points(group=EXPORTERS_ENTRY_POINT_GROUP)
    except TypeError:
        return importlib_metadata.entry_points().get(
            EXPORTERS_ENTRY_POINT_GROUP, [])


def _registered_exporter_names():
    return sorted(ep.name for ep in _exporter_entry_points())


def open_exporter(spec):
    """`--trace-exporter`'s value -> a `TraceExporter`, or `None` for the
    default (no exporting). Beyond the built-in `stderr-json`, `spec` is
    looked up in the `lnpl.exporters` entry-points group (issue #78, mirrors
    `open_repository`'s `lnpl.drivers` lookup, issue #75) — an external
    package registers `name = "module:factory"`.
    """
    if spec is None:
        return None
    if spec == "stderr-json":
        return StderrJsonExporter()
    for entry_point in _exporter_entry_points():
        if entry_point.name == spec:
            try:
                factory = entry_point.load()
            except Exception as exc:
                raise ExporterError(
                    "trace exporter %r registered via entry-point %r failed "
                    "to load: %s" % (spec, entry_point.value, exc)) from exc
            return factory()
    raise ValueError(
        "unknown trace exporter %r (built-in: %s; registered entry-points: %s)"
        % (spec, ", ".join(EXPORTERS),
           ", ".join(_registered_exporter_names()) or "none"))


class CursorError(Exception):
    """An `after` cursor could not be decoded, or does not fit this field."""


class ServeError(Exception):
    """The routing table and the generated OpenAPI contract disagree, or
    (issue #81) a schedule trigger's event-to-workflow linkage is
    ambiguous — both are startup-time refusals, never a guess."""


class WsgiConfigError(Exception):
    """`build_app()` could not resolve a valid configuration from its
    arguments/environment — raised before any request is ever served, the
    same "failed launch, not a failed request" posture `cli.cmd_serve`
    already established for the CLI path (issue #80, D6)."""


def _entity_view(document, entity_node):
    """`entity_node` as the masking chokepoint's observability view — each
    field carries its resolved 18-type `base`, so a `Password` refinement is
    still masked (mirrors `Interpreter._entity_view`; GET has no Interpreter
    instance to borrow one from, since it never runs a workflow — issue #99).
    """
    refinements = refinement_index(document)
    fields = [dict(f, base=refinements.get(f.get("type"), {})
                   .get("base", f.get("type")))
             for f in entity_node.get("fields", [])]
    return dict(entity_node, fields=fields)


def _input_digest(masked_payload):
    """issue #111, D6: a stable fingerprint over the MASKED payload — "is
    this the same input?", not the input itself. Sorted keys, no whitespace,
    UTF-8: an RFC 8785-style canonical JSON, the minimal approximation this
    channel needs (a full canonical-JSON implementation is not RFC 8785's
    number formatting or Unicode-normalization rules, both moot here since
    `payload` is already-parsed JSON with no float/Unicode edge the request
    body did not already carry)."""
    canonical = json.dumps(masked_payload, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _effect_counts(result):
    """issue #111, D6: `result["steps"][].effects` (already `Annotation`-
    filtered, issue #111 D5) tallied by kind — `{"RepositoryCall": 3,
    "NetworkCall": 1, ...}` — the canonical line's `effects` field."""
    counts = {}
    for step in result.get("steps", []):
        for kind in step.get("effects", []):
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def encode_cursor(value, key):
    """(sort value, row_key) -> an opaque cursor token (issue #99, D3)."""
    raw = json.dumps({"v": value, "k": key}, ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(token):
    """cursor token -> (sort value, row_key). Raises `CursorError` on
    anything undecodable — bad base64, bad JSON, the wrong shape. A cursor
    that decodes cleanly but names a since-deleted row is NOT an error here:
    keyset comparison (`paginate`) resumes "as of that point" without ever
    needing the row to still exist (D3)."""
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise CursorError("cursor is not valid base64/JSON") from exc
    if not isinstance(data, dict) or "v" not in data or "k" not in data:
        raise CursorError("cursor is missing the expected v/k shape")
    return data["v"], data["k"]


def paginate(rows, field, entity_id, after, limit):
    """`rows` already ordered by `(field, row_key)` ascending (the exact
    contract `RepositoryDriver.query_sorted` promises) -> `(page, next)`.

    `after` is a decoded `(value, row_key)` pair, or `None` for the first
    page. Raises `CursorError` when `after`'s value cannot be compared
    against this field (a forged cross-type cursor — D3's "위조 커서 400").
    `next` is `None` on the last page, an opaque cursor token otherwise.
    """
    if after is not None:
        try:
            rows = [r for r in rows
                   if (r.get(field), row_key(entity_id, r)) > after]
        except TypeError as exc:
            raise CursorError(
                "cursor does not match this field's type") from exc
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        next_cursor = encode_cursor(last.get(field), row_key(entity_id, last))
    return page, next_cursor


def _parse_limit(raw):
    """query string `limit` -> a page size in `[1, MAX_LIMIT]`.

    `None` (the param was absent) -> `DEFAULT_LIMIT`. Raises `ValueError` for
    anything else outside the closed range — never a silent clamp (D3).
    """
    if raw is None:
        return DEFAULT_LIMIT
    if not raw.isdigit() or not (1 <= int(raw) <= MAX_LIMIT):
        raise ValueError(
            "limit must be an integer between 1 and %d" % MAX_LIMIT)
    return int(raw)


def _required_role(mechanisms):
    """The `<r>` in this service's `security role <r>`, or `None` (issue
    #119, D5) — `_parse_security_line` stores it as the plain string
    `"role <r>"`, the same shape `"jwt"` already is."""
    for mech in mechanisms:
        if mech.startswith("role "):
            return mech[len("role "):]
    return None


def build_routes(document):
    """{path: {"kind": ..., "auth": bool, "role": str|None, ...}} for every
    served path.

    Three kinds (issue #99 adds the last two to the original workflow-only
    table):

      "workflow"     POST /<svc>/<workflow-slug>            {"workflow": id}
      "get-single"   GET  /<svc>/<entity-slug>/{id}          {"entity": id}
      "get-list"     GET  /<svc>/<entity-slug>               {"entity", "field"}
      "sse-subscribe" GET  /<svc>/events/<event-slug>         {"event": id}

    "get-single" is automatic for every entity a service's workflows touch
    (D1 — "entities bound to the service", derived the same way
    `repo_policy.seeded_entities` already derives "entities this workflow
    reads": from the RepositoryCall effects the document's own graph
    already carries, not a new declaration). "get-list" exists only where
    `expose list <Entity> by <field>` declared it (D2 — default un-exposed).
    "sse-subscribe" (issue #103) follows the SAME structural rule as
    "get-single": a service owns the events its own workflows actually
    `emit` (`repo_policy.event_emissions`, the `EventEmit` twin of
    `repository_calls`) — and among those, only the ones the event
    declaration itself opted into via `subscribe` (default un-exposed, same
    posture as D2).

    The loop mirrors `openapi.generate` (same `_slug`, same per-kind walk),
    and the assertion at the end makes the mirror a guarantee: a path set
    that drifts from the published contract refuses to serve at startup
    rather than 404-ing at request time.
    """
    nodes = {n["id"]: n for n in document["nodes"]}
    routes = {}
    for service in document["nodes"]:
        if service["kind"] != "Service":
            continue
        auth = False
        role = None
        for cid in service.get("constraints", []):
            node = nodes.get(cid)
            if node is not None and node["kind"] == "Security":
                mechanisms = node.get("mechanisms", [])
                auth = "jwt" in mechanisms
                role = _required_role(mechanisms)
        svc_slug = _slug(service["name"])
        entity_ids = set()
        event_ids = set()
        for cid in service.get("children", []):
            child = nodes[cid]
            if child["kind"] == "Workflow":
                path = "/%s/%s" % (svc_slug, _slug(child["name"]))
                routes[path] = {"kind": "workflow", "workflow": cid, "auth": auth,
                               "role": role}
                entity_ids.update(eid for eid, _op in repository_calls(document, cid))
                event_ids.update(event_emissions(document, cid))
            elif child["kind"] == "Expose":
                entity = nodes[child["entity"]]
                list_path = "/%s/%s" % (svc_slug, _slug(entity["name"]))
                routes[list_path] = {"kind": "get-list", "entity": child["entity"],
                                     "field": child["field"], "auth": auth,
                                     "role": role}
        for eid in entity_ids:
            entity = nodes[eid]
            single_path = "/%s/%s/{id}" % (svc_slug, _slug(entity["name"]))
            routes[single_path] = {"kind": "get-single", "entity": eid, "auth": auth,
                                   "role": role}
        for eid in event_ids:
            event = nodes[eid]
            if not event.get("subscribe"):
                continue
            events_path = "/%s/events/%s" % (svc_slug, _slug(event["name"]))
            routes[events_path] = {"kind": "sse-subscribe", "event": eid, "auth": auth,
                                   "role": role}
    contract = set(generate(document)["paths"])
    if set(routes) != contract:
        raise ServeError("served paths %r do not match the OpenAPI contract %r"
                         % (sorted(routes), sorted(contract)))
    return routes


def _schedule_events(document):
    """Every schedule-sourced Event node, in document order — the same
    `"every" in source` filter `openapi._schedules` already uses to tell a
    schedule source from an entity source."""
    return [n for n in document["nodes"] if n["kind"] == "Event"
           and n.get("source") and "every" in n["source"]]


def resolve_schedule_triggers(document, events=None):
    """schedule Event id -> (workflow id, owning Service node) (issue #81, D1).

    An Event carries no owner in the IR — `lower.py`'s `owner_of` computes
    "nearest preceding `service` declaration" (RFC-0002 A.2 R2) for a
    Workflow only. This applies that SAME rule to a schedule Event, post-hoc
    over the compiled document's `line` fields, rather than duplicating it
    inside `lower.py` (out of this task's scope): the nearest `Service`
    whose own `line` does not exceed the event's.

    Exactly one Workflow child of that service is required. Zero (no
    preceding service, or one with no workflow) or two-or-more is refused
    with `ServeError` rather than guessed — the brief's fail-closed
    alternative to inventing a second, undeclared link between an event and
    a workflow.

    `events` restricts resolution to a subset (default: every schedule event
    in the document) — `cli.cmd_trigger` uses this to fail only on the one
    schedule it was asked to run, not on an unrelated ambiguous schedule
    elsewhere in the same module.
    """
    services = sorted((n for n in document["nodes"] if n["kind"] == "Service"),
                      key=lambda n: n["line"])
    nodes = {n["id"]: n for n in document["nodes"]}
    triggers = {}
    for event in (events if events is not None else _schedule_events(document)):
        owner = None
        for service in services:
            if service["line"] <= event["line"]:
                owner = service
            else:
                break
        if owner is None:
            raise ServeError(
                "schedule event %r (line %d) precedes every `service` "
                "declaration in this module — no service owns it, so no "
                "workflow can be chosen without guessing (issue #81, D1)"
                % (event["name"], event["line"]))
        candidates = [cid for cid in owner.get("children", [])
                     if nodes[cid]["kind"] == "Workflow"]
        if len(candidates) != 1:
            raise ServeError(
                "schedule event %r (line %d) is owned by service %r, which "
                "declares %d workflow(s) — exactly one is required to pick "
                "a trigger target without guessing (issue #81, D1)"
                % (event["name"], event["line"], owner["name"], len(candidates)))
        triggers[event["id"]] = (candidates[0], owner)
    return triggers


def build_schedule_routes(document, triggers=None):
    """`/-/schedules/<event-slug>` -> the SAME `"workflow"` route shape
    `build_routes` already produces (issue #81, D1) — so `_do_post`/`_run`/
    `_respond`/`map_result`/`_check_auth`/the JSON access log (t78) all run
    UNMODIFIED for a trigger request: an external scheduler and an
    OpenAPI-declared workflow POST share the identical execution, response,
    and observation path. `auth` is looked up the same way `build_routes`
    already looks it up for that same service's own workflow routes (a
    `security jwt` service refuses an unauthenticated trigger exactly like
    it refuses an unauthenticated workflow call — no new auth invented).

    Kept OUT of `build_routes`'s own dict/assertion on purpose: RFC-0016
    keeps a schedule off `paths` (`x-lnpl-schedules` is metadata, not an
    operation), so merging these in before `build_routes`'s
    `set(routes) == contract` check would break that assertion for every
    document with a schedule declaration.
    """
    if triggers is None:
        triggers = resolve_schedule_triggers(document)
    nodes = {n["id"]: n for n in document["nodes"]}
    routes = {}
    for eid, (wid, service) in triggers.items():
        event = nodes[eid]
        auth = False
        role = None
        for cid in service.get("constraints", []):
            node = nodes.get(cid)
            if node is not None and node["kind"] == "Security":
                mechanisms = node.get("mechanisms", [])
                auth = "jwt" in mechanisms
                role = _required_role(mechanisms)
        path = "/-/schedules/%s" % _slug(event["name"])
        # issue #119: mirrors `auth` above — a `security role` service's
        # trigger route is not a side door around its own role requirement.
        routes[path] = {"kind": "workflow", "workflow": wid, "auth": auth,
                        "role": role}
    return routes


def build_ops_routes(document):
    """`/-/healthz`/`/-/readyz` (issue #110, D1) — the SAME out-of-band
    pattern `build_schedule_routes` established: merged into `routes` via
    `update()` AFTER `build_routes`'s own `set(routes) == contract`
    assertion, so an ops path can never trip that assertion for any
    document (`document` itself is unused here, kept only so every route
    builder `make_wsgi_app` calls shares one call shape).

    `"auth": False, "role": None` on both, unconditionally — not derived
    from any service's own `security` declaration (D2). A kubelet's
    liveness/readiness probe never carries a bearer token; gating either
    path on auth would leave every pod permanently unready.
    """
    return {
        "/-/healthz": {"kind": "ops-health", "auth": False, "role": None},
        "/-/readyz": {"kind": "ops-ready", "auth": False, "role": None},
    }


def build_metrics_route(document):
    """`/-/metrics` (issue #110, D1/D6) — same out-of-band merge pattern as
    `build_ops_routes`, kept as its OWN builder rather than folded into it:
    `make_wsgi_app` only calls this one when `--metrics` is on, so off, the
    route is never created at all and the path 404s exactly like any other
    undeclared path — no special-cased "metrics disabled" response.
    """
    return {"/-/metrics": {"kind": "ops-metrics", "auth": False, "role": None}}


def _workflow_service_names(document):
    """workflow node id -> the owning service's declared `name` (issue
    #110, D7's `service` label) — the SAME parent/child walk `build_routes`
    already does to build that workflow's own route path, reused here only
    for the label value, not a route."""
    nodes = {n["id"]: n for n in document["nodes"]}
    names = {}
    for node in document["nodes"]:
        if node["kind"] != "Service":
            continue
        for cid in node.get("children", []):
            if nodes[cid]["kind"] == "Workflow":
                names[cid] = node["name"]
    return names


# The post-run mapping rows, in decision order. M6 is decided before M7: a
# deadline that lands on a validation step ("deadline exhausted before step
# 'validate input'") is a timeout, not a payload rejection. issue #128: M6
# reads the typed `failure_kind` interp.py's two deadline sites both set,
# same as M8a's conflict check below — not a match against
# `failure_reason`'s wording, which is free to reword without breaking this.
def map_result(result):
    """`run_workflow` result -> (http status, error code or None)."""
    if result["status"] == "completed":
        return 200, None                                  # M9 — skipped[] rides the body
    if result.get("failure_kind") == "deadline":
        return 504, "deadline-exceeded"                   # M6
    failed = result["failed_step"]
    for entry in result["steps"]:
        if entry["step"] == failed and "Validation" in entry.get("effects", ()):
            return 400, "validation-failed"               # M7
    if result.get("failure_kind") == "conflict":
        return 409, "conflict"                            # M8a
    return 500, "workflow-failed"                         # M8


_TITLES = {
    "not-found": "no such path",
    "method-not-allowed": "method not allowed",
    "auth-missing": "authorization required",
    "auth-invalid": "authorization token rejected",
    "forbidden": "the caller's role does not permit this",
    "conflict": "the request conflicts with the current state of the target resource",
    "idempotency-in-progress": "a request with this Idempotency-Key is already running",
    "precondition-failed": "the If-Match version no longer matches the stored row",
    "precondition-invalid": "the If-Match header value is not a recognized ETag",
    "body-too-large": "request body too large",
    "body-unreadable": "request body is not a JSON object",
    "deadline-exceeded": "workflow deadline exceeded",
    "validation-failed": "payload validation failed",
    "workflow-failed": "workflow execution failed",
    "cursor-invalid": "the `after` cursor could not be used",
    "limit-invalid": "the `limit` query parameter is out of range",
    "read-failed": "repository read failed",
    "not-ready": "the server is not ready to receive traffic",
}


def problem(status, code, detail, **extras):
    """The one RFC 9457 problem+json shape every error response uses.

    `code` is the stable string clients branch on (never the message); extras
    carry the run observables (`correlation_id`, `failed_step`, `skipped`) when
    a run happened.
    """
    body = {"title": _TITLES[code], "status": status, "code": code,
            "detail": detail}
    body.update(extras)
    return body


def _status_line(status):
    return "%d %s" % (status, http.client.responses.get(status, ""))


def _json_response(start_response, status, body, content_type="application/problem+json",
                   headers=()):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    header_list = [("Content-Type", content_type),
                   ("Content-Length", str(len(payload)))]
    header_list.extend(headers)
    start_response(_status_line(status), header_list)
    return [payload]


class LnplWsgiApp:
    """A PEP-3333 callable bound to one compiled document + routing table.

    Shares construction with the embedded dev server: `serve.serve()` builds
    one of these via `make_wsgi_app()` and wraps it in `wsgiref`, so the
    routing/auth/mapping/SSE logic below is the ONLY implementation — there
    is no second copy for the socket path to drift from.
    """

    def __init__(self, document, routes, repository_factory=None,
                 token_provider=None, network=None, clock=None,
                 log_format="text", exporter=None, trust_incoming_trace=False,
                 jwt_secret_env=None, metrics_registry=None,
                 idempotency_ttl_ms=DEFAULT_IDEMPOTENCY_TTL_MS,
                 capture_on_failure=False):
        self.document = document
        self.nodes = {n["id"]: n for n in document["nodes"]}
        self.routes = routes
        # issue #110, D7: workflow node id -> owning service name, computed
        # once (not per-request) for the metrics labels `_respond` records.
        self._workflow_service_names = _workflow_service_names(document)
        # A factory, not a driver: each request opens its own store and closes
        # it, so a connection is never shared across threads/workers. The
        # provider is the opposite — one immutable object, safe to read from
        # every request.
        self.repository_factory = repository_factory
        self.token_provider = token_provider
        # issue #101: `HttpNetworkDriver` opens/closes its own connection per
        # `call()`, so one instance is safe to share across every request's
        # Interpreter, the same as `token_provider`. `None` means "the
        # Interpreter builds its own FakeNetworkDriver" (RFC-0027 §1 default).
        self.network = network
        # issue #80: `None` keeps the pre-existing default — the Interpreter
        # builds its own virtual `Clock()` — byte-identical to before this
        # issue for every caller that does not pass one.
        self.clock = clock
        # issue #78: "text" (default) is the pre-existing silent behavior —
        # `__call__` takes the exact original code path, unchanged.
        self.log_format = log_format
        # issue #78: `None` (default) means no TraceExporter configured —
        # independent of `log_format`, so a caller can export traces while
        # staying on the default text access-log (or vice versa).
        self.exporter = exporter
        # issue #107, D7: off by default. Off means an inbound `traceparent`
        # is never adopted as this request's trace-id — a fresh one is
        # always minted, and the inbound value is recorded only as a link.
        # Naively inheriting a client-supplied sampled flag opens a
        # denial-of-monitoring surface (W3C Trace Context, security
        # considerations); this flag is the "configured trusted source"
        # gate security-input-validation-at-trust-boundaries calls for.
        self.trust_incoming_trace = trust_incoming_trace
        # issue #110, D4 check 3: the NAME of the env var `--jwt-secret-env`
        # named, not its value — `_readyz_broken` re-reads `os.environ` at
        # request time, independent of `cli.cmd_serve`'s own startup-time
        # validation, so a variable removed from a still-running process's
        # environment is caught by the next readiness probe rather than
        # never observed again. `None` (default) means the flag was not
        # given — nothing to check.
        self.jwt_secret_env = jwt_secret_env
        # issue #110, D6/D9: `None` (default, `--metrics` off) means
        # `/-/metrics` was never even added to `routes` — off is a plain
        # 404, not a "disabled" response this attribute would gate. Set,
        # it is the process-level `MetricsRegistry` `_respond` records
        # into and `_metrics` renders from.
        self.metrics = metrics_registry
        # issue #110, D11: process-level, set only by a SIGTERM handler
        # (serve.py) that does no I/O in the handler itself. `/-/readyz`
        # reads this and nothing else decides it; `/-/healthz` never reads
        # it (liveness must stay 200 through a graceful shutdown).
        self.shutting_down = False
        # issue #113, D10/D11: how long a claimed `Idempotency-Key` survives
        # (`SqliteRepositoryDriver.idempotency_begin`). `None` factory means
        # the `fake` backend -- it reseeds an empty store every request, so
        # no claim could ever outlive the request that made it (D11); warn
        # once at startup rather than staying silently inert.
        self.idempotency_ttl_ms = idempotency_ttl_ms
        # issue #111, D7: off by default. On, `_respond` adds the masked
        # input payload to `log_sink` only for a run that ends failed/500 —
        # a successful run never carries its payload into the canonical
        # line, so turning this on does not make every request's log line
        # dominate on cost the way an unconditional payload would.
        self.capture_on_failure = capture_on_failure
        if repository_factory is None:
            print(
                "lnpl serve: Idempotency-Key support is disabled -- the "
                "`fake` backend seeds a fresh in-memory store per request, "
                "so there is nowhere to durably record a claim (issue "
                "#113, D11). Use --backend sqlite:<path> to enable it.",
                file=sys.stderr)

    def _resolve_trace_context(self, environ):
        """issue #107: decide this request's `(trace_id, span_id, link,
        tracestate, flags)` from an inbound `traceparent`/`tracestate`
        header pair.

        Never raises and never fails the request (D2) — a malformed or
        untrusted `traceparent` just means a freshly minted trace-id, not a
        rejection. `span_id` is always freshly generated: a received
        `parent-id` names the caller's span, never ours (W3C §3.4).

        D6/r1-F1: `flags` (trace-flags, e.g. the sampled bit) is propagated
        verbatim ONLY when we actually adopt the inbound trace (trust on and
        parsed). Every other case starts a trace-id of our own minting, so
        the sampling decision is ours too — "01" (sampled), never inherited.
        Naively inheriting an untrusted/unparsed value here would let an
        unrelated caller's flags apply to a trace-id we generated.
        """
        raw = environ.get("HTTP_TRACEPARENT")
        parsed = parse_traceparent(raw)

        # D5, W3C MUST: tracestate is parsed/forwarded only alongside a
        # successfully parsed traceparent; otherwise it is discarded, not
        # merely ignored.
        tracestate = environ.get("HTTP_TRACESTATE") if parsed is not None else None

        if parsed is None:
            return new_trace_id(), new_span_id(), None, tracestate, "01"

        if not self.trust_incoming_trace:
            link = {"trace_id": parsed["trace_id"], "parent_id": parsed["parent_id"]}
            return new_trace_id(), new_span_id(), link, tracestate, "01"

        return parsed["trace_id"], new_span_id(), None, tracestate, parsed["flags"]

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET")
        path_info = environ.get("PATH_INFO", "")
        query = environ.get("QUERY_STRING", "")
        raw_path = path_info + ("?" + query if query else "")
        if self.log_format == "json":
            return self._call_with_json_log(environ, start_response, method,
                                            path_info, query, raw_path)
        if method == "POST":
            return self._do_post(environ, start_response, path_info, raw_path)
        if method == "GET":
            return self._do_get(environ, start_response, path_info, query, raw_path)
        return self._reject_non_post(start_response, path_info, raw_path)

    def _call_with_json_log(self, environ, start_response, method, path_info,
                            query, raw_path):
        """issue #78, D1: one JSON Line per request to stderr. `log_sink` is an
        out-parameter `_respond` fills in for a POST/workflow run (the only
        request kind with a `correlation_id`/diagnostics/skipped[] to report);
        every other request kind logs with those fields at their defaults.
        SSE is a generator, not a materialized body — its line is emitted at
        stream end (`_log_sse_then`), not at connection open, so `duration_ms`
        reflects the stream's actual lifetime.

        issue #123, D1: `trace_id`/`span_id` are resolved exactly once here,
        for every method — this is the one place all four route kinds pass
        through in JSON log mode. `log_sink` starts seeded with the pair
        (instead of `{}`) so GET/SSE, which never reach `_respond`, still
        report them; the POST/workflow path forwards this same resolution
        into `_respond` as `trace_ctx` so it never resolves a second, and
        possibly different, one (D1's own overwrite risk).
        """
        start_t = time.monotonic()
        correlation_id = "req-%s" % uuid.uuid4().hex[:12]
        trace_ctx = self._resolve_trace_context(environ)
        trace_id, span_id = trace_ctx[:2]
        log_sink = {"trace_id": trace_id, "span_id": span_id}
        captured = {}

        def capture_start_response(status_line, headers, exc_info=None):
            captured["status"] = int(status_line.split(" ", 1)[0])
            return start_response(status_line, headers, exc_info)

        # issue #111, D8: Stripe's `ensure`-block guarantee, extended to the
        # non-SSE path. `_respond` already turns a `run_workflow` escape into
        # a 500 response (never re-raising), so the gap this closes is
        # earlier/wider: anything that raises before a body is even decided
        # — `_do_post`/`_do_get`/`_reject_non_post` themselves, or routing/
        # auth/body-parsing inside them — used to skip `_emit_request_log`
        # entirely, the one non-SSE path with no `finally`. `logged` tracks
        # whether either normal branch below already emitted (directly, or
        # by handing off to `_log_sse_then`'s OWN try/finally) so this
        # `finally` fires exactly once per request, never twice.
        logged = False
        try:
            if method == "POST":
                body = self._do_post(environ, capture_start_response, path_info,
                                     raw_path, log_sink=log_sink, trace_ctx=trace_ctx)
            elif method == "GET":
                body = self._do_get(environ, capture_start_response, path_info,
                                   query, raw_path)
            else:
                body = self._reject_non_post(capture_start_response, path_info, raw_path)

            if not isinstance(body, list):
                # The SSE generator: log once the stream actually ends.
                logged = True
                return self._log_sse_then(body, method, path_info, correlation_id,
                                          start_t, captured, log_sink)
            self._emit_request_log(method, path_info, correlation_id, start_t,
                                   captured, log_sink)
            logged = True
            return body
        finally:
            if not logged:
                self._emit_request_log(method, path_info, correlation_id,
                                       start_t, captured, log_sink)

    def _emit_request_log(self, method, path, correlation_id, start_t,
                          captured, log_sink):
        line = {
            "correlation_id": log_sink.get("correlation_id") or correlation_id,
            "method": method,
            "path": path,
            "workflow": log_sink.get("workflow"),
            "status": captured.get("status"),
            "duration_ms": round((time.monotonic() - start_t) * 1000, 3),
            "skipped": log_sink.get("skipped", []),
            "diagnostics": log_sink.get("diagnostics", []),
        }
        # issue #107, D3 / issue #123, D1: trace_id/span_id sit alongside
        # correlation_id, not in place of it. `_call_with_json_log` seeds
        # `log_sink` with both keys for every route kind, so `None` only
        # happens if `_resolve_trace_context` itself ever returned one --
        # it doesn't (D1's own tuple is never partial) -- and the omission
        # here is defensive, not the pre-#123 GET/SSE golden-line byte
        # invariance that used to rely on it.
        trace_id = log_sink.get("trace_id")
        if trace_id is not None:
            line["trace_id"] = trace_id
        span_id = log_sink.get("span_id")
        if span_id is not None:
            line["span_id"] = span_id
        # issue #111, D6: `notes`/`effects`/`input_digest` widen the
        # canonical line the same way `trace_id`/`span_id` did (#107/#123)
        # — appended only when present, so a payload-less route (GET, or a
        # request that never reached `_respond`) omits them rather than
        # carrying an empty/null placeholder.
        notes = log_sink.get("notes")
        if notes:
            line["notes"] = notes
        effects = log_sink.get("effects")
        if effects:
            line["effects"] = effects
        input_digest = log_sink.get("input_digest")
        if input_digest is not None:
            line["input_digest"] = input_digest
        # issue #111, D7: `--capture-on-failure` — set on `log_sink` only
        # when the flag is on AND this run ended failed/500 (`_respond`
        # decides which); a successful run's line never carries this key.
        captured_input = log_sink.get("input")
        if captured_input is not None:
            line["input"] = captured_input
        print(json.dumps(line, ensure_ascii=False), file=sys.stderr)

    def _log_sse_then(self, generator, method, path, correlation_id, start_t,
                      captured, log_sink):
        try:
            for chunk in generator:
                yield chunk
        finally:
            self._emit_request_log(method, path, correlation_id, start_t,
                                   captured, log_sink)

    def _reject_non_post(self, start_response, path_info, raw_path):
        if raw_path in self.routes:                                # M2
            return _json_response(start_response, 405,
                                  problem(405, "method-not-allowed",
                                         "only POST is served at %s" % path_info),
                                  headers=(("Allow", "POST"),))
        return _json_response(start_response, 404,                  # M1
                              problem(404, "not-found",
                                     "no OpenAPI path %r" % raw_path))

    def _check_auth(self, environ, start_response, route, path_info):
        """`(claims, None)` when this route's auth requirement is satisfied;
        `(None, response)` otherwise, where `response` is the already-built
        401 WSGI response. issue #99, D5: GET reuses this SAME check a POST
        workflow route already used — no new judgment invented for the read
        surface.

        issue #119: a two-tuple, not a single value doubling as both claims
        and failure signal — `claims` can legitimately be `{}` (a verified
        token that carries no extra claims), and an empty dict is falsy, so
        collapsing "auth passed with no claims" and "auth failed" onto one
        `None`-checked return would read a rejected token as a pass. Failure
        is always the second slot; callers branch on that, never on whether
        `claims` is truthy.
        """
        if not route["auth"]:
            return None, None
        header = environ.get("HTTP_AUTHORIZATION")
        if header is None:                                          # M3
            return None, _json_response(start_response, 401,
                                  problem(401, "auth-missing",
                                         "the service declares `security jwt`; "
                                         "send an Authorization header"))
        if self.token_provider is not None:                          # M3a
            claims, response = self._token_accepted(
                start_response, header, path_info)
            if response is not None:
                return None, response
            response = self._role_accepted(start_response, route, claims)   # M3b
            if response is not None:
                return None, response
            return claims, None
        return None, None

    def _role_accepted(self, start_response, route, claims):
        """`None` when this route's `security role` requirement (if any) is
        satisfied by the verified token's role; otherwise the 403 response
        (issue #119, D5/D8/D9 — M3b, ordered strictly after M3a: a request
        never gets here without a token that already verified).

        D5 (deny by default): no role claim, or a role claim that does not
        exactly match, are the SAME outcome — 403. `caller_view` already
        collapses "absent"/"ambiguous" to `None` (D3); comparing against
        `None` here would let a required role of `None` (impossible — a
        route only reaches this with `route["role"]` truthy) accidentally
        pass a caller with no role, so the `required` guard above is what
        makes that unreachable, not a coincidence of the comparison.

        D8: the response body does not say which role was required — a 403
        page is exactly the reconnaissance surface `problem`'s existing
        401 case (`auth-invalid`) already declines to feed. The specifics go
        to stderr against a correlation id, the same shape `_token_accepted`
        already uses for M3a.
        """
        required = route.get("role")
        if not required:
            return None
        actual = caller_view(claims)
        actual_role = actual["role"] if actual is not None else None
        if actual_role == required:
            return None
        correlation_id = "req-%s" % uuid.uuid4().hex[:12]
        print("serve: role rejected (correlation_id=%s): required %r, got %r"
              % (correlation_id, required, actual_role), file=sys.stderr)
        return _json_response(start_response, 403,
                              problem(403, "forbidden",
                                     "the caller's role does not satisfy this "
                                     "service's `security role` requirement",
                                     correlation_id=correlation_id))

    def _token_accepted(self, start_response, header, path_info):
        """`(claims, None)` when the bearer token passes; `(None, response)`
        when it doesn't — see `_check_auth` for why this is a tuple.

        The response says only that the token was rejected. Which check failed
        — signature, audience, expiry — is exactly the feedback someone tuning
        a forgery wants, so it goes to the server's stderr against a
        correlation id instead, where the operator can still find it.
        """
        scheme, _, token = header.partition(" ")
        correlation_id = "req-%s" % uuid.uuid4().hex[:12]
        detail = None
        claims = None
        if scheme.lower() != "bearer" or not token.strip():
            detail = "authorization scheme is not Bearer"
        else:
            try:
                claims = self.token_provider.verify(
                    token.strip(), audience_for_path(path_info))
            except (TokenError, ValueError) as exc:
                detail = str(exc)
        if detail is None:
            return claims, None
        print("serve: token rejected (correlation_id=%s): %s"
              % (correlation_id, detail), file=sys.stderr)
        return None, _json_response(start_response, 401,
                              problem(401, "auth-invalid",
                                     "the bearer token was not accepted",
                                     correlation_id=correlation_id))

    def _do_post(self, environ, start_response, path_info, raw_path,
                log_sink=None, trace_ctx=None):
        route = self.routes.get(raw_path)                            # M1
        if route is None:
            return _json_response(start_response, 404,
                                  problem(404, "not-found",
                                         "no OpenAPI path %r" % raw_path))
        if route.get("kind") != "workflow":                           # M2
            return _json_response(start_response, 405,
                                  problem(405, "method-not-allowed",
                                         "only GET is served at %s" % raw_path),
                                  headers=(("Allow", "GET"),))
        claims, auth_result = self._check_auth(environ, start_response, route, path_info)
        if auth_result is not None:
            return auth_result
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            length = 0
        if length > MAX_BODY_BYTES:                                   # M4
            return _json_response(start_response, 413,
                                  problem(413, "body-too-large",
                                         "request body exceeds %d bytes"
                                         % MAX_BODY_BYTES))
        raw = environ["wsgi.input"].read(length) if length > 0 else b""
        if raw:
            try:
                payload = json.loads(raw)
            except ValueError:                                       # M5
                return _json_response(start_response, 400,
                                      problem(400, "body-unreadable",
                                             "request body is not valid JSON"))
            if not isinstance(payload, dict):                        # M5
                return _json_response(start_response, 400,
                                      problem(400, "body-unreadable",
                                             "request body must be a JSON object"))
        else:
            # No special case for an empty body: it runs as {} and a workflow
            # with a Validation effect rejects it through M7.
            payload = {}
        # issue #113, D8/D9: absent by default -- a request with no header
        # takes the exact pre-#113 path through `_run`/`_respond` (D9
        # regression: byte-identical when no key is sent).
        idempotency_key = environ.get("HTTP_IDEMPOTENCY_KEY")
        # issue #113, D13: absent by default -- current behavior unchanged
        # when no client sends it.
        if_match = environ.get("HTTP_IF_MATCH")
        return self._run(environ, start_response, route["workflow"], payload,
                         claims=claims, log_sink=log_sink, trace_ctx=trace_ctx,
                         idempotency_key=idempotency_key, if_match=if_match)

    def _do_get(self, environ, start_response, path_info, query, raw_path):
        """issue #99: single-row GET (auto, D1) and list GET (opt-in via
        `expose`, D2). A 3-segment path with a non-empty last segment is
        tried as a single-row template first (`/<svc>/<entity>/{id}`); a
        2-segment path is looked up directly (workflow POST-only paths and
        list GET paths share that shape, `build_routes`' "kind" tells them
        apart, same as `_do_post` already does for its own paths).
        """
        segments = path_info.split("/")
        if len(segments) == 4 and segments[3]:
            template = "/%s/%s/{id}" % (segments[1], segments[2])
            route = self.routes.get(template)
            if route is not None and route.get("kind") == "get-single":
                _, auth_result = self._check_auth(environ, start_response, route, path_info)
                if auth_result is not None:
                    return auth_result
                return self._get_single(start_response, route, segments[3])
            # issue #103: `/<svc>/events/<slug>` is ALSO a 4-segment path
            # (`["", svc, "events", slug]`), so it reaches here whenever no
            # single-row template matched — the single-row attempt above is
            # tried first and unchanged, this is a fallback, not a rewrite.
            events_route = self.routes.get(path_info)
            if events_route is not None and events_route.get("kind") == "sse-subscribe":
                _, auth_result = self._check_auth(environ, start_response, events_route, path_info)
                if auth_result is not None:
                    return auth_result
                return self._subscribe(environ, start_response, events_route)
            return _json_response(start_response, 404,                # M1
                                  problem(404, "not-found",
                                         "no OpenAPI path %r" % raw_path))
        route = self.routes.get(path_info)
        if route is not None and route.get("kind") == "get-list":
            _, auth_result = self._check_auth(environ, start_response, route, path_info)
            if auth_result is not None:
                return auth_result
            return self._get_list(start_response, route, query)
        if route is not None and route.get("kind") in (
                "ops-health", "ops-ready", "ops-metrics"):
            _, auth_result = self._check_auth(environ, start_response, route, path_info)
            if auth_result is not None:
                return auth_result
            if route["kind"] == "ops-health":
                return self._healthz(start_response)
            if route["kind"] == "ops-ready":
                return self._readyz(start_response)
            return self._metrics(start_response)
        if route is not None:                                        # M2
            return _json_response(start_response, 405,
                                  problem(405, "method-not-allowed",
                                         "only POST is served at %s" % raw_path),
                                  headers=(("Allow", "POST"),))
        return _json_response(start_response, 404,                    # M1
                              problem(404, "not-found",
                                     "no OpenAPI path %r" % raw_path))

    def _get_single(self, start_response, route, id_value):
        entity_id = route["entity"]
        factory = self.repository_factory
        repository = factory() if factory is not None else None
        if repository is None:
            # No backend configured: nothing has ever been persisted, so
            # every id is legitimately absent (module docstring: "the
            # in-memory, presence-checked server it has always been").
            return _json_response(start_response, 404,
                                  problem(404, "not-found", "no such row"))
        correlation_id = "req-%s" % uuid.uuid4().hex[:12]
        try:
            row = repository.execute(entity_id, "read",
                                     row_key(entity_id, {"id": id_value}))
        except DriverError as exc:
            print("serve: internal error (correlation_id=%s): %s"
                  % (correlation_id, exc), file=sys.stderr)
            return _json_response(start_response, 500,
                                  problem(500, "read-failed", "internal server error",
                                         correlation_id=correlation_id))
        finally:
            repository.close()
        if row is None:
            return _json_response(start_response, 404,
                                  problem(404, "not-found", "no such row"))
        entity_node = self.nodes[entity_id]
        masked = mask_payload(row, _entity_view(self.document, entity_node))
        # issue #113, D12: opt-in on the SAME `observed_version` attribute
        # `persist()`'s conditional write already reads (drivers.py) --
        # `FakeRepository` never sets it, so the `fake` backend never
        # issues an ETag (nothing to condition a later If-Match on).
        version = getattr(row, "observed_version", None)
        headers = () if version is None else (("ETag", _etag_value(version)),)
        return _json_response(start_response, 200, masked,
                              content_type="application/json", headers=headers)

    def _get_list(self, start_response, route, query):
        entity_id, field = route["entity"], route["field"]
        params = urllib.parse.parse_qs(query, keep_blank_values=True)
        try:
            limit = _parse_limit(params.get("limit", [None])[0])
        except ValueError as exc:
            return _json_response(start_response, 400,
                                  problem(400, "limit-invalid", str(exc)))
        after = None
        after_raw = params.get("after", [None])[0]
        if after_raw is not None:
            try:
                after = decode_cursor(after_raw)
            except CursorError as exc:
                return _json_response(start_response, 400,
                                      problem(400, "cursor-invalid", str(exc)))
        factory = self.repository_factory
        rows = []
        if factory is not None:
            repository = factory()
            correlation_id = "req-%s" % uuid.uuid4().hex[:12]
            try:
                rows = repository.query_sorted(entity_id, field)
            except DriverError as exc:
                print("serve: internal error (correlation_id=%s): %s"
                      % (correlation_id, exc), file=sys.stderr)
                return _json_response(start_response, 500,
                                      problem(500, "read-failed", "internal server error",
                                             correlation_id=correlation_id))
            finally:
                repository.close()
        try:
            page, next_cursor = paginate(rows, field, entity_id, after, limit)
        except CursorError as exc:
            return _json_response(start_response, 400,
                                  problem(400, "cursor-invalid", str(exc)))
        entity_node = self.nodes[entity_id]
        view = _entity_view(self.document, entity_node)
        items = [mask_payload(r, view) for r in page]
        return _json_response(start_response, 200,
                              {"items": items, "next": next_cursor},
                              content_type="application/json")

    def _healthz(self, start_response):
        """issue #110, D3: liveness. The process is running and this
        document loaded — nothing else. No repository, no network: a
        liveness probe that touches a backend turns a transient outage into
        a pod-restart storm that cannot fix the backend and only adds
        downtime (the search-cited failure mode D3 exists to avoid)."""
        return _json_response(start_response, 200, {"status": "ok"},
                              content_type="application/json")

    def _readyz(self, start_response):
        """issue #110, D4/D5/D11: readiness. Shutdown (D11) is checked
        first and short-circuits the rest — a server told to drain has
        nothing left worth probing. Otherwise the closed list of four
        (`_readyz_broken`). 503 + problem+json naming every broken check:
        unlike 401/403 this is operator-facing, not attacker-facing, so
        D5 does not withhold the specifics the way M3a/M3b do.
        """
        if self.shutting_down:
            return _json_response(start_response, 503,
                                  problem(503, "not-ready",
                                         "the server received SIGTERM and is "
                                         "shutting down",
                                         checks=["shutting-down"]))
        broken = self._readyz_broken()
        if broken:
            return _json_response(start_response, 503,
                                  problem(503, "not-ready",
                                         "readiness check(s) failed: %s"
                                         % ", ".join(broken),
                                         checks=broken))
        return _json_response(start_response, 200, {"status": "ok"},
                              content_type="application/json")

    def _readyz_broken(self):
        """issue #110, D4's closed list of four, by name — extending this
        list is a decision (D4 says so explicitly), not a one-line patch:

          1. routing<->OpenAPI contract  — `build_routes` already asserted
             this at construction time (`ServeError` otherwise); this
             object exists only because it passed, so there is nothing left
             to check here.
          2. persistent backend reachable — acquire and release one
             connection.
          3. `--jwt-secret-env`'s named variable is still present.
          4. `--network http`'s logical-name endpoint mapping is resolved
             — like (1), `_resolve_network` already asserted this at
             construction time (`WsgiConfigError` otherwise).

        Returns the broken ones' names, in the order above; empty means
        ready.
        """
        broken = []
        if self.repository_factory is not None:
            try:
                repository = self.repository_factory()
            except DriverError:
                broken.append("repository")
            else:
                repository.close()
        if self.jwt_secret_env and not os.environ.get(self.jwt_secret_env):
            broken.append("jwt-secret-env")
        return broken

    def _metrics(self, start_response):
        """issue #110, D6/D7: only reachable when `--metrics` is on — the
        route itself does not exist otherwise (`make_wsgi_app` never merges
        in `build_metrics_route`'s dict), so off is a plain 404 upstream of
        this method, not a branch inside it. Prometheus text exposition
        format, rendered from the process-level registry (D9) — no
        auth (D2), same as healthz/readyz."""
        payload = self.metrics.render().encode("utf-8")
        headers = [("Content-Type", "text/plain; version=0.0.4; charset=utf-8"),
                  ("Content-Length", str(len(payload)))]
        start_response(_status_line(200), headers)
        return [payload]

    def _last_event_id(self, environ, start_response):
        """`Last-Event-ID` header -> the outbox seq to resume after (issue
        #103, D3), as an `int`. Absent -> 0 (from the start). A forged/
        non-integer value builds the 400 response and returns it instead —
        the same "위조 커서 400" judgment `decode_cursor`/`paginate` already
        make for `after` (D3's own basis: pagination-contract.md), reusing
        `cursor-invalid` rather than inventing a second error code for what
        is the same shape of mistake. Callers tell the two apart with
        `isinstance(result, int)`.
        """
        header = environ.get("HTTP_LAST_EVENT_ID")
        if header is None:
            return 0
        if not header.isdigit():
            return _json_response(start_response, 400,
                                  problem(400, "cursor-invalid",
                                         "Last-Event-ID must be a non-negative "
                                         "integer outbox seq"))
        return int(header)

    def _subscribe(self, environ, start_response, route):
        """issue #103: tail `lnpl_outbox` for one event as SSE frames —
        `id:` is the outbox seq (t102's monotonic delivery cursor, not
        `emission_id`), `data:` is the payload exactly as EventEmit already
        masked it (D4 — no second masking path). The generator polls
        `read_outbox` at `SSE_POLL_INTERVAL_S`; a connection idle past
        `SSE_IDLE_TIMEOUT_S` (no rows AND no client read to service) ends the
        generator on its own (D5) — the WSGI iterable is otherwise held open
        for as long as the client stays connected. Each `yield` is written
        and flushed to the client immediately by the WSGI host (stdlib
        `wsgiref`'s `ServerHandler.write` flushes per chunk; gunicorn workers
        do the same), which is what makes this a real-time push and not a
        buffered response.
        """
        after_seq = self._last_event_id(environ, start_response)
        if not isinstance(after_seq, int):
            return after_seq                                # 400 already built
        event_id = route["event"]
        start_response(_status_line(200),
                       [("Content-Type", "text/event-stream"),
                        ("Cache-Control", "no-cache")])
        return self._sse_frames(event_id, after_seq)

    def _sse_frames(self, event_id, after_seq):
        factory = self.repository_factory
        repository = factory() if factory is not None else None
        try:
            idle_s = 0.0
            while idle_s < SSE_IDLE_TIMEOUT_S:
                # `lnpl_outbox.event` is `EventEmit.event` verbatim — the
                # derived node id (`_event_ref`), not the declared name — so
                # this reads by `event_id`, matching what `record_emission`
                # actually wrote (interp.py: `emission["event"] = event_ref`).
                rows = (repository.read_outbox(event_id, after_seq)
                        if repository is not None else [])
                if not rows:
                    time.sleep(SSE_POLL_INTERVAL_S)
                    idle_s += SSE_POLL_INTERVAL_S
                    continue
                idle_s = 0.0
                for row in rows:
                    frame = "id: %d\ndata: %s\n\n" % (
                        row["seq"],
                        json.dumps(row["payload"], ensure_ascii=False))
                    yield frame.encode("utf-8")
                    after_seq = row["seq"]
        except (BrokenPipeError, ConnectionResetError, DriverError):
            # A client that walked away, or a store fault mid-stream: this
            # connection has nothing left to serve either way — end the
            # generator quietly, the response line is already on the wire.
            pass
        finally:
            if repository is not None:
                repository.close()

    def _run(self, environ, start_response, workflow_id, payload, claims=None,
            log_sink=None, trace_ctx=None, idempotency_key=None, if_match=None):
        doc = self.document
        correlation_id = "req-%s" % uuid.uuid4().hex[:12]
        factory = self.repository_factory
        repository = factory() if factory is not None else None
        try:
            return self._respond(environ, start_response, doc, workflow_id, payload,
                                 correlation_id, repository, claims=claims,
                                 log_sink=log_sink, trace_ctx=trace_ctx,
                                 idempotency_key=idempotency_key,
                                 if_match=if_match)
        finally:
            # A request that fails must still release its store, or the leak
            # is one connection per failed request.
            if repository is not None:
                repository.close()

    def _check_if_match(self, doc, workflow_id, payload, repository, if_match,
                        correlation_id):
        """`None` when the request may proceed; otherwise `(status, body)`
        for the 400/412 response to send instead of running the workflow
        (issue #113, D13).

        Conditions against the FIRST entity the workflow reads
        (`repo_policy.repository_calls`, declared order) -- the workflow
        endpoint has no single targeted resource the way a REST PUT/PATCH
        does, so the row a prior GET's ETag came from is the one this
        checks. A workflow with no `read` step, or a driver/row with no
        `observed_version` (D12's same opt-in), has nothing to condition
        on -- skipped, not enforced, matching D12's "no version, no ETag"
        the other direction.
        """
        claimed_version = _parse_if_match(if_match)
        if claimed_version is None:
            return 400, problem(400, "precondition-invalid",
                                "If-Match %r is not a recognized ETag" % if_match,
                                correlation_id=correlation_id)
        if repository is None:
            return None
        reads = [entity for entity, op in repository_calls(doc, workflow_id)
                if op == "read"]
        if not reads:
            return None
        entity_id = reads[0]
        try:
            row = repository.execute(entity_id, "read",
                                     row_key(entity_id, payload))
        except DriverError:
            # Let the workflow's own read surface this the normal way
            # (M8/M14) instead of a second, earlier translation of it.
            return None
        observed = getattr(row, "observed_version", None) if row is not None else None
        if observed is None:
            return None
        if observed != claimed_version:
            return 412, problem(412, "precondition-failed",
                                "the row has changed since If-Match's version "
                                "was read", correlation_id=correlation_id)
        return None

    def _respond(self, environ, start_response, doc, workflow_id, payload,
                correlation_id, repository, claims=None, log_sink=None,
                trace_ctx=None, idempotency_key=None, if_match=None):
        # issue #113, D8/D9/D11: opt-in on the repository object, the same
        # `getattr` idiom D12's ETag opt-in uses -- covers "no backend at
        # all" (fake -> `repository is None`) and "a backend that never
        # implemented it" in one check, no special-casing either.
        claim = (idempotency_key is not None and repository is not None
                and hasattr(repository, "idempotency_begin"))
        if claim:
            now_ms = int(time.time() * 1000)
            claim_status, stored = repository.idempotency_begin(
                workflow_id, idempotency_key, now_ms, self.idempotency_ttl_ms)
            if claim_status == "in-progress":                       # D8
                return _json_response(
                    start_response, 409,
                    problem(409, "idempotency-in-progress",
                           "a request with this Idempotency-Key is already running",
                           correlation_id=correlation_id))
            if claim_status == "done":                              # D7: replay
                http_status, body = stored
                content_type = ("application/json" if http_status == 200
                                else "application/problem+json")
                return _json_response(start_response, http_status, body,
                                      content_type=content_type)
            # claim_status == "started": this call just claimed the key --
            # run the workflow below and finalize its outcome before returning.
        if if_match is not None:
            precondition = self._check_if_match(doc, workflow_id, payload,
                                                repository, if_match, correlation_id)
            if precondition is not None:
                precondition_status, precondition_body = precondition
                if claim:
                    # A precondition failure is as deterministic an outcome
                    # as any workflow result -- the same stale If-Match
                    # against the same key should keep replaying it, not
                    # get stuck at `in-progress` until the TTL clears it.
                    repository.idempotency_finish(workflow_id, idempotency_key,
                                                  precondition_status, precondition_body)
                return _json_response(start_response, precondition_status,
                                      precondition_body)
        interp = Interpreter(doc, clock=self.clock,
                             repo_rows=default_rows(doc, workflow_id, payload),
                             correlation_id=correlation_id, repository=repository,
                             network=self.network, claims=claims)
        # issue #111, D6: computed once, reused for the canonical line's
        # `input_digest` on both the escape path below and the normal
        # completion path — the same masking chokepoint the workflow-start
        # trace log already uses (`Interpreter._entity_node`), so this is a
        # third call site of an EXISTING rule, not a second one (issue #43).
        masked_payload = mask_payload(payload, interp._entity_node())
        input_digest = _input_digest(masked_payload)
        # issue #107: resolved exactly once per request, right where the
        # Trace this request will use is built — trace_id/span_id/trace_link
        # are a runtime-decided identity, D3's correlation_id stays separate
        # and untouched alongside them on the same record.
        #
        # issue #123, D1 (r1): `trace_ctx` arrives pre-resolved from
        # `_call_with_json_log` for the JSON-log path -- resolving again
        # here would mint a second, different `span_id` (fresh every call)
        # and let this Trace disagree with the canonical line already
        # seeded from the first resolution. Text-log mode never goes
        # through `_call_with_json_log` at all, so it falls back to
        # resolving its own here, exactly as before this task.
        if trace_ctx is None:
            trace_ctx = self._resolve_trace_context(environ)
        trace_id, span_id, trace_link, tracestate, flags = trace_ctx
        interp.trace.trace_id = trace_id
        interp.trace.span_id = span_id
        interp.trace.trace_link = trace_link
        interp.trace.tracestate = tracestate
        interp.trace.flags = flags
        try:
            result = interp.run_workflow(workflow_id, payload)
        except Exception:
            # run_workflow reports expected failures in `result`; an escape is
            # a server fault. The body stays generic (no internals) — the
            # correlation id is the handle to the stderr log.
            #
            # issue #113: a claim made above is deliberately left
            # `in-progress` on this path -- an escaped exception means the
            # workflow's own fate (did it commit, roll back, or crash mid-
            # write?) is genuinely unknown, so recording ANY definite
            # outcome here would risk replaying a wrong one. The claim
            # self-heals via the TTL (D10); see docs/serving.md.
            import traceback
            print("serve: internal error (correlation_id=%s)" % correlation_id,
                  file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            if log_sink is not None:                                 # issue #78
                log_sink.update(correlation_id=correlation_id, workflow=workflow_id,
                                skipped=[], diagnostics=to_records(interp.diagnostics),
                                trace_id=interp.trace.trace_id, span_id=interp.trace.span_id,
                                input_digest=input_digest)
                if self.capture_on_failure:                          # issue #111, D7
                    log_sink["input"] = masked_payload
            if self.exporter is not None:                            # issue #78, D3
                self.exporter.export(interp.trace.to_dict())
            return _json_response(start_response, 500,
                                  problem(500, "workflow-failed",
                                         "internal server error",
                                         correlation_id=correlation_id))
        for line in format_lines(interp.diagnostics):
            print(line, file=sys.stderr)
        status, code = map_result(result)
        if self.metrics is not None:                                  # issue #110, D7/D9
            service_name = self._workflow_service_names.get(workflow_id, "")
            wf_name = self.nodes[workflow_id]["name"]
            self.metrics.record_run(service_name, wf_name, result["status"],
                                    result["duration_ms"] / 1000.0)
            if result["status"] != "completed" and result.get("failed_step"):
                self.metrics.record_step_failure(service_name, wf_name,
                                                 result["failed_step"], code)
        if log_sink is not None:                                     # issue #78
            log_sink.update(correlation_id=result["correlation_id"],
                            workflow=workflow_id, skipped=result["skipped"],
                            diagnostics=to_records(interp.diagnostics),
                            trace_id=interp.trace.trace_id, span_id=interp.trace.span_id,
                            input_digest=input_digest, notes=result.get("notes", []),
                            effects=_effect_counts(result))
            if self.capture_on_failure and result["status"] != "completed":  # D7
                log_sink["input"] = masked_payload
        if self.exporter is not None:                                 # issue #78, D3
            self.exporter.export(interp.trace.to_dict())
        if status == 200:                                            # M9
            body = result
            content_type = "application/json"
        else:
            body = problem(status, code, result["failure_reason"],
                          correlation_id=result["correlation_id"],
                          failed_step=result["failed_step"],
                          skipped=result["skipped"])                # M6/M7/M8
            content_type = "application/problem+json"
        if claim:
            # issue #113, D7/r1: a SEPARATE statement, after `run_workflow`
            # returned and its own transaction already closed -- see
            # `idempotency_finish`'s docstring for why this can never be
            # inside that boundary. Runs for a completed AND a failed run
            # alike: Stripe replays "the resulting status code and body...
            # regardless of whether it succeeds or fails."
            repository.idempotency_finish(workflow_id, idempotency_key, status, body)
        return _json_response(start_response, status, body, content_type=content_type)


def make_wsgi_app(document, repository_factory=None, token_provider=None,
                  network=None, clock=None, log_format="text", exporter=None,
                  trust_incoming_trace=False, jwt_secret_env=None, metrics=False,
                  idempotency_ttl_ms=DEFAULT_IDEMPOTENCY_TTL_MS,
                  capture_on_failure=False):
    """An already-compiled `document` -> a WSGI callable.

    This is the single constructor both `build_app()` (env-var driven, for a
    production WSGI host) and `serve.serve()` (the embedded dev server) call
    — the two entry points can never drift apart because they build the same
    object the same way (issue #80, D2).

    issue #81, D1: the schedule-trigger routes are merged in AFTER
    `build_routes`'s own OpenAPI-contract assertion, so they can never make
    that assertion fail — see `build_schedule_routes`.

    issue #119, D6: a `security role` declared with no `token_provider`
    configured is presence-checking dressed up as RBAC — the role can never
    be read off a token that is never verified, so every request to that
    route would either 401 (if `security jwt` also applies) or silently
    carry no role and 403 forever. Refusing at construction, before any
    request is served, is the same "failed launch, not a failed request"
    posture `WsgiConfigError` already exists for.
    """
    routes = build_routes(document)
    routes.update(build_schedule_routes(document))
    # issue #110, D1: same reason schedule routes are merged in AFTER the
    # contract assertion, not before — `/-/healthz`/`/-/readyz` are not an
    # OpenAPI operation, so folding them into `build_routes`'s own dict
    # would fail `set(routes) == contract` for every document.
    routes.update(build_ops_routes(document))
    # issue #110, D6: `/-/metrics` is only ever created when `--metrics` is
    # on — off, this call never happens, so the path is undeclared and
    # 404s the same way any other undeclared path does.
    if metrics:
        routes.update(build_metrics_route(document))
    if token_provider is None:
        gated = sorted({path for path, route in routes.items() if route.get("role")})
        if gated:
            raise WsgiConfigError(
                "%d route(s) declare `security role` but no token_provider "
                "is configured — a role can never be read off a token that "
                "is never verified: %s. Configure `--jwt-secret-env` (or "
                "pass token_provider=... directly)" % (len(gated), gated[0]))
    return LnplWsgiApp(document, routes,
                       repository_factory=repository_factory,
                       token_provider=token_provider, network=network,
                       clock=clock, log_format=log_format, exporter=exporter,
                       trust_incoming_trace=trust_incoming_trace,
                       jwt_secret_env=jwt_secret_env,
                       metrics_registry=MetricsRegistry() if metrics else None,
                       idempotency_ttl_ms=idempotency_ttl_ms,
                       capture_on_failure=capture_on_failure)


# --------------------------------------------------------------------------
# build_app() — the env-var-driven factory a WSGI host calls directly
# --------------------------------------------------------------------------

def _module_name(paths):
    """RFC-0031: one file -> its basename; one directory -> the directory's
    basename; several explicit files -> the first one's basename. A verbatim
    copy of `cli.py`'s own `_module_name` — `cli.py` imports `serve.py`,
    which wraps this module, so importing `cli.py` from here would cycle;
    the three lines are cheaper to keep in sync than the import is to break.
    """
    if len(paths) == 1 and os.path.isdir(paths[0]):
        return os.path.basename(os.path.normpath(paths[0]))
    return os.path.splitext(os.path.basename(paths[0]))[0]


def _network_targets(document):
    """Every `NetworkCall.target` in `document` that is a logical name, not
    a URL literal, deduplicated in first-appearance order (issue #101 D3) —
    the set that needs an endpoint mapping."""
    seen = []
    for n in document["nodes"]:
        if n["kind"] != "NetworkCall":
            continue
        target = n["target"]
        if target not in seen and not _is_url_literal(target):
            seen.append(target)
    return seen


def _http_capabilities(document):
    """name -> {"method", "auth"} for every declared `capability http` node
    (issue #101) — `method` is present only on those, so it doubles as the
    filter for "is this Capability node an http one"."""
    return {n["name"]: {"method": n["method"], "auth": n.get("auth")}
            for n in document["nodes"] if n["kind"] == "Capability" and "method" in n}


def _resolve_network(document, endpoints):
    """`endpoints` (an explicit {name: url} override) + the
    `LNPL_ENDPOINT_<NAME>` environment contract (issue #101, t101 — reused
    verbatim, not reinvented) -> an `HttpNetworkDriver`, or `None` when
    `document` makes no logical-name `NetworkCall` (the pre-#101 default:
    the Interpreter builds its own `FakeNetworkDriver`).

    Raises `WsgiConfigError` for a target with neither an `endpoints` entry
    nor the matching environment variable, or a declared `capability http
    ... auth ... from <ENV>` whose named variable is unset — the same
    startup-time judgment `cli._open_endpoints` already makes for the CLI
    path, so a misconfigured deployment fails at `build_app()` rather than
    on the first request that needs the network.
    """
    targets = _network_targets(document)
    if not targets:
        return None
    caps = _http_capabilities(document)
    given = dict(endpoints or {})
    resolved_endpoints = {}
    resolved_caps = {}
    for name in targets:
        url = given.get(name)
        if url is None:
            url = os.environ.get("LNPL_ENDPOINT_%s" % name.upper())
        if url is None:
            raise WsgiConfigError(
                "network target %r has no `endpoints` entry or "
                "LNPL_ENDPOINT_%s environment variable" % (name, name.upper()))
        resolved_endpoints[name] = url
        cap = caps.get(name)
        if cap is None:
            # declared-not-bound: a legitimate, undeclared logical name still
            # gets a route — method POST, no auth, the pre-#101 default.
            resolved_caps[name] = {"method": "POST", "headers": {}}
            continue
        headers = {}
        auth = cap.get("auth")
        if auth is not None:
            value = os.environ.get(auth["env"])
            if value is None:
                raise WsgiConfigError(
                    "%s is not set in the environment (capability http %s "
                    "declares `auth %s from %s`)"
                    % (auth["env"], name, auth["kind"], auth["env"]))
            if auth["kind"] == "bearer":
                headers["Authorization"] = "Bearer %s" % value
            else:
                headers[auth["header"]] = value
        resolved_caps[name] = {"method": cap["method"].upper(), "headers": headers}
    return HttpNetworkDriver(endpoints=resolved_endpoints, capabilities=resolved_caps)


def build_app(sources=None, backend=None, jwt_secret_env=None, clock=None,
              endpoints=None, log_format=None, trace_exporter=None,
              idempotency_ttl_s=None):
    """A ready WSGI callable, for a host that calls a zero-argument factory
    — `gunicorn "lnpl.wsgi:build_app()"` (issue #80, D1).

    Every argument omitted falls back to its environment variable:

      sources        LNPL_SOURCE          `os.pathsep`-joined paths, or one
                                           directory (t77 `load_sources`)
      backend        LNPL_BACKEND         "fake" (default) or "sqlite:<path>"
      jwt_secret_env LNPL_JWT_SECRET_ENV  name of the var holding the HMAC
                                           signing secret; unset -> presence-
                                           checked, not verified (M3, not M3a)
      clock          LNPL_CLOCK           "virtual" (default) or "real"
      endpoints      (no single env var — each `NetworkCall` target reads
                     `LNPL_ENDPOINT_<NAME>`, t101's existing contract)
      log_format     LNPL_LOG_FORMAT      "text" (default, silent) or "json"
                                           (issue #78)
      trace_exporter LNPL_TRACE_EXPORTER  built-in `stderr-json`, an
                                           `lnpl.exporters` entry-point name,
                                           or unset (default: no exporting)
      idempotency_ttl_s LNPL_IDEMPOTENCY_TTL_S  seconds an `Idempotency-Key`
                                           claim is honored before a repeat
                                           becomes a fresh miss (issue #113,
                                           D10); default 86400 (24h)

    A `sources`/`backend`/`jwt_secret_env`/`clock`/`log_format`/
    `trace_exporter`/network target that cannot be resolved raises
    `WsgiConfigError` before any request is served — a failed launch, not a
    failed first request.
    """
    if sources is None:
        raw = os.environ.get("LNPL_SOURCE")
        if not raw:
            raise WsgiConfigError(
                "LNPL_SOURCE is not set and no `sources` was given")
        sources = raw.split(os.pathsep)
    elif isinstance(sources, str):
        sources = [sources]
    else:
        sources = list(sources)
    try:
        decls = load_sources(sources)
        document = lower(decls, _module_name(sources)).to_document()
    except (OSError, LowerError, ParseError, LexError) as exc:
        raise WsgiConfigError("LNPL_SOURCE %r: %s" % (sources, exc)) from exc

    if backend is None:
        backend = os.environ.get("LNPL_BACKEND", "fake")
    repository_factory = None
    if backend != "fake":
        try:
            probe = open_repository(backend)
        except (ValueError, DriverError) as exc:
            raise WsgiConfigError("LNPL_BACKEND %r: %s" % (backend, exc)) from exc
        probe.close()
        repository_factory = lambda spec=backend: open_repository(spec)

    if jwt_secret_env is None:
        jwt_secret_env = os.environ.get("LNPL_JWT_SECRET_ENV")
    token_provider = None
    if jwt_secret_env:
        secret = os.environ.get(jwt_secret_env)
        if not secret:
            raise WsgiConfigError(
                "%s is not set in the environment" % jwt_secret_env)
        try:
            token_provider = HmacTokenProvider(secret)
        except TokenError as exc:
            raise WsgiConfigError(
                "%s (from %s)" % (exc, jwt_secret_env)) from exc

    clock_spec = clock if clock is not None else os.environ.get("LNPL_CLOCK", "virtual")
    try:
        clock_obj = open_clock(clock_spec)
    except ValueError as exc:
        raise WsgiConfigError(str(exc)) from exc

    network = _resolve_network(document, endpoints)

    log_format = log_format if log_format is not None else os.environ.get(
        "LNPL_LOG_FORMAT", "text")
    try:
        log_format = open_log_format(log_format)
    except ValueError as exc:
        raise WsgiConfigError(str(exc)) from exc

    trace_exporter = trace_exporter if trace_exporter is not None else \
        os.environ.get("LNPL_TRACE_EXPORTER")
    try:
        exporter = open_exporter(trace_exporter)
    except (ValueError, ExporterError) as exc:
        raise WsgiConfigError(str(exc)) from exc

    if idempotency_ttl_s is None:
        idempotency_ttl_s = os.environ.get("LNPL_IDEMPOTENCY_TTL_S")
    try:
        idempotency_ttl_ms = (DEFAULT_IDEMPOTENCY_TTL_MS
                              if idempotency_ttl_s is None
                              else int(idempotency_ttl_s) * 1000)
    except ValueError as exc:
        raise WsgiConfigError(
            "LNPL_IDEMPOTENCY_TTL_S %r is not an integer number of seconds"
            % idempotency_ttl_s) from exc

    return make_wsgi_app(document, repository_factory=repository_factory,
                         token_provider=token_provider, network=network,
                         clock=clock_obj, log_format=log_format,
                         exporter=exporter,
                         idempotency_ttl_ms=idempotency_ttl_ms)
