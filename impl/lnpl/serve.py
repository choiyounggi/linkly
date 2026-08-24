"""`lnpl serve` — bind workflows to the OpenAPI paths over mode A (issue #26).

The server closes the last gap between "intent" and "a running HTTP service":
request body -> payload validation (the workflow's own Validation effect,
issue #48) -> mode A execution -> status-code mapping. The mapping table
(M1–M9) is normative in docs/serving.md; `map_result` implements the post-run
rows, the handler implements the pre-run rows.

Contract limits (docs/serving.md): schedule triggers (#49) and mode B are not
served. The capability backend and the token provider are the caller's to
supply (issue #25): with neither, this is the in-memory, presence-checked
server it has always been; with both, requests read a store that outlives them
and bearer tokens are actually verified.
"""

import base64
import binascii
import json
import sys
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .diagnostics import format_lines
from .drivers import DriverError, TokenError, audience_for_path
from .interp import Interpreter, mask_payload, refinement_index
from .openapi import generate, _slug
from .repo_policy import default_rows, repository_calls, row_key

# M4: refuse to buffer more than this before reading a byte. The Fake-backend
# dev server has no streaming consumer, so anything past 1 MiB is a mistake.
MAX_BODY_BYTES = 1 << 20

# issue #99, D3: the cursor page-size ceiling. `limit` outside [1, MAX_LIMIT]
# is a 400 (`limit-invalid`), not a silent clamp — a client that asked for
# 1,000,000 rows gets a refusal that names the ceiling, not a page it never
# expected.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class CursorError(Exception):
    """An `after` cursor could not be decoded, or does not fit this field."""


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


class ServeError(Exception):
    """The routing table and the generated OpenAPI contract disagree."""


def build_routes(document):
    """{path: {"kind": ..., "auth": bool, ...}} for every served path.

    Three kinds (issue #99 adds the last two to the original workflow-only
    table):

      "workflow"   POST /<svc>/<workflow-slug>            {"workflow": id}
      "get-single" GET  /<svc>/<entity-slug>/{id}          {"entity": id}
      "get-list"   GET  /<svc>/<entity-slug>               {"entity", "field"}

    "get-single" is automatic for every entity a service's workflows touch
    (D1 — "entities bound to the service", derived the same way
    `repo_policy.seeded_entities` already derives "entities this workflow
    reads": from the RepositoryCall effects the document's own graph
    already carries, not a new declaration). "get-list" exists only where
    `expose list <Entity> by <field>` declared it (D2 — default un-exposed).

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
        for cid in service.get("constraints", []):
            node = nodes.get(cid)
            if node is not None and node["kind"] == "Security":
                auth = "jwt" in node.get("mechanisms", [])
        svc_slug = _slug(service["name"])
        entity_ids = set()
        for cid in service.get("children", []):
            child = nodes[cid]
            if child["kind"] == "Workflow":
                path = "/%s/%s" % (svc_slug, _slug(child["name"]))
                routes[path] = {"kind": "workflow", "workflow": cid, "auth": auth}
                entity_ids.update(eid for eid, _op in repository_calls(document, cid))
            elif child["kind"] == "Expose":
                entity = nodes[child["entity"]]
                list_path = "/%s/%s" % (svc_slug, _slug(entity["name"]))
                routes[list_path] = {"kind": "get-list", "entity": child["entity"],
                                     "field": child["field"], "auth": auth}
        for eid in entity_ids:
            entity = nodes[eid]
            single_path = "/%s/%s/{id}" % (svc_slug, _slug(entity["name"]))
            routes[single_path] = {"kind": "get-single", "entity": eid, "auth": auth}
    contract = set(generate(document)["paths"])
    if set(routes) != contract:
        raise ServeError("served paths %r do not match the OpenAPI contract %r"
                         % (sorted(routes), sorted(contract)))
    return routes


# The post-run mapping rows, in decision order. M6 is decided before M7: a
# deadline that lands on a validation step ("deadline exhausted before step
# 'validate input'") is a timeout, not a payload rejection. The prefix is
# pinned to interp.py's two message forms ("deadline exceeded after step %r",
# "deadline exhausted before step %r") — the result carries no typed failure
# class, and the runner contract is consume-only here.
def map_result(result):
    """`run_workflow` result -> (http status, error code or None)."""
    if result["status"] == "completed":
        return 200, None                                  # M9 — skipped[] rides the body
    if (result["failure_reason"] or "").startswith("deadline"):
        return 504, "deadline-exceeded"                   # M6
    failed = result["failed_step"]
    for entry in result["steps"]:
        if entry["step"] == failed and "Validation" in entry.get("effects", ()):
            return 400, "validation-failed"               # M7
    return 500, "workflow-failed"                         # M8


_TITLES = {
    "not-found": "no such path",
    "method-not-allowed": "method not allowed",
    "auth-missing": "authorization required",
    "auth-invalid": "authorization token rejected",
    "body-too-large": "request body too large",
    "body-unreadable": "request body is not a JSON object",
    "deadline-exceeded": "workflow deadline exceeded",
    "validation-failed": "payload validation failed",
    "workflow-failed": "workflow execution failed",
    "cursor-invalid": "the `after` cursor could not be used",
    "limit-invalid": "the `limit` query parameter is out of range",
    "read-failed": "repository read failed",
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


class _Server(ThreadingHTTPServer):
    """One thread per request; workers share only read-only state (the compiled
    document and the routing table), so requests need no lock — each run gets
    its own Interpreter and its own repository rows."""

    daemon_threads = True

    def __init__(self, address, document, routes, repository_factory=None,
                 token_provider=None, network=None):
        super().__init__(address, _Handler)
        self.document = document
        self.nodes = {n["id"]: n for n in document["nodes"]}
        self.routes = routes
        # A factory, not a driver: each request opens its own store and closes
        # it, so a connection is never shared across threads. The provider is
        # the opposite — one immutable object, safe to read from every thread.
        self.repository_factory = repository_factory
        self.token_provider = token_provider
        # issue #101: `HttpNetworkDriver` opens/closes its own connection per
        # `call()`, so one instance is safe to share across every request's
        # Interpreter, the same as `token_provider`. `None` means "the
        # Interpreter builds its own FakeNetworkDriver" (RFC-0027 §1
        # default) — serve had no outbound network path before this.
        self.network = network


class _Handler(BaseHTTPRequestHandler):

    # The default per-request access line goes to stderr and would drown the
    # per-run diagnostics, which are the output that carries meaning here.
    def log_message(self, format, *args):
        pass

    def _send(self, status, body, content_type="application/problem+json",
              headers=()):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def _reject_non_post(self):
        if self.path in self.server.routes:                        # M2
            self._send(405, problem(405, "method-not-allowed",
                                    "only POST is served at %s" % self.path),
                       headers=(("Allow", "POST"),))
        else:                                                      # M1
            self._send(404, problem(404, "not-found",
                                    "no OpenAPI path %r" % self.path))

    do_PUT = do_DELETE = do_PATCH = do_HEAD = _reject_non_post

    def _check_auth(self, route):
        """True when this route's auth requirement is satisfied; otherwise
        sends 401 (M3/M3a) and returns False. issue #99, D5: GET reuses this
        SAME check a POST workflow route already used — no new judgment
        invented for the read surface."""
        if not route["auth"]:
            return True
        header = self.headers.get("Authorization")
        if header is None:                                         # M3
            self._send(401, problem(401, "auth-missing",
                                    "the service declares `security jwt`; "
                                    "send an Authorization header"))
            return False
        if self.server.token_provider is not None:                 # M3a
            return self._token_accepted(header)
        return True

    def do_POST(self):
        route = self.server.routes.get(self.path)
        if route is None:                                          # M1
            self._send(404, problem(404, "not-found",
                                    "no OpenAPI path %r" % self.path))
            return
        if route.get("kind") != "workflow":                        # M2
            self._send(405, problem(405, "method-not-allowed",
                                    "only GET is served at %s" % self.path),
                       headers=(("Allow", "GET"),))
            return
        if not self._check_auth(route):
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:                                # M4
            self._send(413, problem(413, "body-too-large",
                                    "request body exceeds %d bytes"
                                    % MAX_BODY_BYTES))
            return
        raw = self.rfile.read(length) if length > 0 else b""
        if raw:
            try:
                payload = json.loads(raw)
            except ValueError:                                     # M5
                self._send(400, problem(400, "body-unreadable",
                                        "request body is not valid JSON"))
                return
            if not isinstance(payload, dict):                      # M5
                self._send(400, problem(400, "body-unreadable",
                                        "request body must be a JSON object"))
                return
        else:
            # No special case for an empty body: it runs as {} and a workflow
            # with a Validation effect rejects it through M7.
            payload = {}
        self._run(route["workflow"], payload)

    def do_GET(self):
        """issue #99: single-row GET (auto, D1) and list GET (opt-in via
        `expose`, D2). A 3-segment path with a non-empty last segment is
        tried as a single-row template first (`/<svc>/<entity>/{id}`); a
        2-segment path is looked up directly (workflow POST-only paths and
        list GET paths share that shape, `build_routes`' "kind" tells them
        apart, same as `do_POST` already does for its own paths).
        """
        path_only, _, query = self.path.partition("?")
        segments = path_only.split("/")
        if len(segments) == 4 and segments[3]:
            template = "/%s/%s/{id}" % (segments[1], segments[2])
            route = self.server.routes.get(template)
            if route is not None and route.get("kind") == "get-single":
                if not self._check_auth(route):
                    return
                self._get_single(route, segments[3])
                return
            self._send(404, problem(404, "not-found",             # M1
                                    "no OpenAPI path %r" % self.path))
            return
        route = self.server.routes.get(path_only)
        if route is not None and route.get("kind") == "get-list":
            if not self._check_auth(route):
                return
            self._get_list(route, query)
            return
        if route is not None:                                    # M2
            self._send(405, problem(405, "method-not-allowed",
                                    "only POST is served at %s" % self.path),
                       headers=(("Allow", "POST"),))
            return
        self._send(404, problem(404, "not-found",                 # M1
                                "no OpenAPI path %r" % self.path))

    def _get_single(self, route, id_value):
        entity_id = route["entity"]
        factory = self.server.repository_factory
        repository = factory() if factory is not None else None
        if repository is None:
            # No backend configured: nothing has ever been persisted, so
            # every id is legitimately absent (module docstring: "the
            # in-memory, presence-checked server it has always been").
            self._send(404, problem(404, "not-found", "no such row"))
            return
        correlation_id = "req-%s" % uuid.uuid4().hex[:12]
        try:
            row = repository.execute(entity_id, "read",
                                     row_key(entity_id, {"id": id_value}))
        except DriverError as exc:
            print("serve: internal error (correlation_id=%s): %s"
                  % (correlation_id, exc), file=sys.stderr)
            self._send(500, problem(500, "read-failed", "internal server error",
                                    correlation_id=correlation_id))
            return
        finally:
            repository.close()
        if row is None:
            self._send(404, problem(404, "not-found", "no such row"))
            return
        entity_node = self.server.nodes[entity_id]
        masked = mask_payload(row, _entity_view(self.server.document, entity_node))
        self._send(200, masked, content_type="application/json")

    def _get_list(self, route, query):
        entity_id, field = route["entity"], route["field"]
        params = urllib.parse.parse_qs(query, keep_blank_values=True)
        try:
            limit = _parse_limit(params.get("limit", [None])[0])
        except ValueError as exc:
            self._send(400, problem(400, "limit-invalid", str(exc)))
            return
        after = None
        after_raw = params.get("after", [None])[0]
        if after_raw is not None:
            try:
                after = decode_cursor(after_raw)
            except CursorError as exc:
                self._send(400, problem(400, "cursor-invalid", str(exc)))
                return
        factory = self.server.repository_factory
        rows = []
        if factory is not None:
            repository = factory()
            correlation_id = "req-%s" % uuid.uuid4().hex[:12]
            try:
                rows = repository.query_sorted(entity_id, field)
            except DriverError as exc:
                print("serve: internal error (correlation_id=%s): %s"
                      % (correlation_id, exc), file=sys.stderr)
                self._send(500, problem(500, "read-failed", "internal server error",
                                        correlation_id=correlation_id))
                return
            finally:
                repository.close()
        try:
            page, next_cursor = paginate(rows, field, entity_id, after, limit)
        except CursorError as exc:
            self._send(400, problem(400, "cursor-invalid", str(exc)))
            return
        entity_node = self.server.nodes[entity_id]
        view = _entity_view(self.server.document, entity_node)
        items = [mask_payload(r, view) for r in page]
        self._send(200, {"items": items, "next": next_cursor},
                  content_type="application/json")

    def _token_accepted(self, header):
        """True when the bearer token passes; otherwise sends 401 and False.

        The response says only that the token was rejected. Which check failed
        — signature, audience, expiry — is exactly the feedback someone tuning
        a forgery wants, so it goes to the server's stderr against a
        correlation id instead, where the operator can still find it.
        """
        scheme, _, token = header.partition(" ")
        correlation_id = "req-%s" % uuid.uuid4().hex[:12]
        detail = None
        if scheme.lower() != "bearer" or not token.strip():
            detail = "authorization scheme is not Bearer"
        else:
            try:
                self.server.token_provider.verify(
                    token.strip(), audience_for_path(self.path))
            except (TokenError, ValueError) as exc:
                detail = str(exc)
        if detail is None:
            return True
        print("serve: token rejected (correlation_id=%s): %s"
              % (correlation_id, detail), file=sys.stderr)
        self._send(401, problem(401, "auth-invalid",
                                "the bearer token was not accepted",
                                correlation_id=correlation_id))
        return False

    def _run(self, workflow_id, payload):
        doc = self.server.document
        correlation_id = "req-%s" % uuid.uuid4().hex[:12]
        factory = self.server.repository_factory
        repository = factory() if factory is not None else None
        try:
            self._respond(doc, workflow_id, payload, correlation_id, repository)
        finally:
            # `finally`: a request that fails must still release its store, or
            # the leak is one connection per failed request.
            if repository is not None:
                repository.close()

    def _respond(self, doc, workflow_id, payload, correlation_id, repository):
        interp = Interpreter(doc, repo_rows=default_rows(doc, workflow_id, payload),
                             correlation_id=correlation_id, repository=repository,
                             network=self.server.network)
        try:
            result = interp.run_workflow(workflow_id, payload)
        except Exception:
            # run_workflow reports expected failures in `result`; an escape is
            # a server fault. The body stays generic (no internals) — the
            # correlation id is the handle to the stderr log.
            import traceback
            print("serve: internal error (correlation_id=%s)" % correlation_id,
                  file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            self._send(500, problem(500, "workflow-failed",
                                    "internal server error",
                                    correlation_id=correlation_id))
            return
        for line in format_lines(interp.diagnostics):
            print(line, file=sys.stderr)
        status, code = map_result(result)
        if status == 200:                                          # M9
            self._send(200, result, content_type="application/json")
            return
        self._send(status, problem(status, code, result["failure_reason"],
                                   correlation_id=result["correlation_id"],
                                   failed_step=result["failed_step"],
                                   skipped=result["skipped"]))     # M6/M7/M8


def serve(document, host="127.0.0.1", port=8080, repository_factory=None,
          token_provider=None, network=None):
    """A configured, not-yet-started server bound to `host:port`.

    Port 0 binds an ephemeral port (tests); the caller owns the lifecycle —
    `serve_forever()` to run, `shutdown()` + `server_close()` to stop.

    `repository_factory` is called once per request for a fresh capability
    store; omitted, each request gets the in-memory one. `token_provider`
    turns the M3 presence check into real verification (M3a); omitted, the
    header is only checked for presence, which is what shipped with #26.
    `network` (issue #101) is a `NetworkDriver` every request's Interpreter
    shares; omitted, each request gets its own FakeNetworkDriver.
    """
    return _Server((host, port), document, build_routes(document),
                   repository_factory=repository_factory,
                   token_provider=token_provider, network=network)
