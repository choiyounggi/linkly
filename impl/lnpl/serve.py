"""`lnpl serve` — bind workflows to the OpenAPI paths over mode A (issue #26).

The server closes the last gap between "intent" and "a running HTTP service":
request body -> payload validation (the workflow's own Validation effect,
issue #48) -> mode A execution -> status-code mapping. The mapping table
(M1–M9) is normative in docs/serving.md; `map_result` implements the post-run
rows, the handler implements the pre-run rows.

Contract limits (docs/serving.md): mode A over the Fake capability backend
(#25 open); `Authorization` is presence-checked, not verified; schedule
triggers (#49) and mode B are not served.
"""

import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .diagnostics import format_lines
from .interp import Interpreter
from .openapi import generate, _slug
from .repo_policy import default_rows

# M4: refuse to buffer more than this before reading a byte. The Fake-backend
# dev server has no streaming consumer, so anything past 1 MiB is a mistake.
MAX_BODY_BYTES = 1 << 20


class ServeError(Exception):
    """The routing table and the generated OpenAPI contract disagree."""


def build_routes(document):
    """{path: {"workflow": node id, "auth": bool}} for every served workflow.

    The loop mirrors `openapi.generate` (service -> workflow children, same
    `_slug`), and the assertion at the end makes the mirror a guarantee: a path
    set that drifts from the published contract refuses to serve at startup
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
        for wf_id in service.get("children", []):
            wf = nodes[wf_id]
            if wf["kind"] != "Workflow":
                continue
            path = "/%s/%s" % (_slug(service["name"]), _slug(wf["name"]))
            routes[path] = {"workflow": wf_id, "auth": auth}
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
    "body-too-large": "request body too large",
    "body-unreadable": "request body is not a JSON object",
    "deadline-exceeded": "workflow deadline exceeded",
    "validation-failed": "payload validation failed",
    "workflow-failed": "workflow execution failed",
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

    def __init__(self, address, document, routes):
        super().__init__(address, _Handler)
        self.document = document
        self.routes = routes


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

    do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = _reject_non_post

    def do_POST(self):
        route = self.server.routes.get(self.path)
        if route is None:                                          # M1
            self._send(404, problem(404, "not-found",
                                    "no OpenAPI path %r" % self.path))
            return
        if route["auth"] and self.headers.get("Authorization") is None:  # M3
            # Presence-checked only: verifying the bearer token is #25's
            # contract, not this server's (docs/serving.md).
            self._send(401, problem(401, "auth-missing",
                                    "the service declares `security jwt`; "
                                    "send an Authorization header"))
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

    def _run(self, workflow_id, payload):
        doc = self.server.document
        correlation_id = "req-%s" % uuid.uuid4().hex[:12]
        interp = Interpreter(doc, repo_rows=default_rows(doc, workflow_id, payload),
                             correlation_id=correlation_id)
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


def serve(document, host="127.0.0.1", port=8080):
    """A configured, not-yet-started server bound to `host:port`.

    Port 0 binds an ephemeral port (tests); the caller owns the lifecycle —
    `serve_forever()` to run, `shutdown()` + `server_close()` to stop.
    """
    return _Server((host, port), document, build_routes(document))
