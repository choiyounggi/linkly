"""`lnpl serve` — the built-in dev server for the request-processing core in
`lnpl.wsgi` (issue #26; restructured into a WSGI callable by issue #80).

The core — routing, the M1-M16 status-code mapping, JWT, masking, GET
single/list, and SSE subscribe — lives in `wsgi.py` as a PEP-3333 callable.
This module wraps that SAME callable with the stdlib `wsgiref.simple_server`
+ `socketserver.ThreadingMixIn`, so `lnpl serve` keeps its zero-dependency,
one-thread-per-request dev server unchanged in behavior; a production
deployment instead points a real WSGI host (gunicorn) at
`lnpl.wsgi:build_app()` and gets TLS termination, graceful shutdown, and
worker management from that host + nginx instead of from this module (D4 —
this module never gained a signal handler for that).

The status-code mapping table (M1-M9) is normative in docs/serving.md, next
to the same table's GET/SSE rows (M10-M16, issues #99/#103).
"""

import socketserver
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

from .wsgi import (  # re-exported for backward compatibility — every name
    # below already had callers outside this module before issue #80.
    CursorError, DEFAULT_LIMIT, MAX_BODY_BYTES, MAX_LIMIT, ServeError,
    SSE_IDLE_TIMEOUT_S, SSE_POLL_INTERVAL_S, WsgiConfigError, _parse_limit,
    _TITLES, build_routes, decode_cursor, encode_cursor, make_wsgi_app,
    map_result, paginate, problem,
)

__all__ = [
    "CursorError", "DEFAULT_LIMIT", "MAX_BODY_BYTES", "MAX_LIMIT",
    "ServeError", "SSE_IDLE_TIMEOUT_S", "SSE_POLL_INTERVAL_S",
    "WsgiConfigError", "build_routes", "decode_cursor", "encode_cursor",
    "map_result", "paginate", "problem", "serve",
]


class _WSGIRequestHandler(WSGIRequestHandler):

    # The default per-request access line goes to stderr and would drown the
    # per-run diagnostics, which are the output that carries meaning here
    # (unchanged from issue #26).
    def log_message(self, format, *args):
        pass


class _Server(socketserver.ThreadingMixIn, WSGIServer):
    """One thread per request; workers share only read-only state (the WSGI
    app's compiled document and routing table), so requests need no lock —
    each run gets its own Interpreter and its own repository rows. Mirrors
    `http.server.ThreadingHTTPServer`'s own `ThreadingMixIn` + `daemon_threads`
    pairing, with `WSGIServer` standing in for `HTTPServer`."""

    daemon_threads = True


def serve(document, host="127.0.0.1", port=8080, repository_factory=None,
          token_provider=None, network=None, clock=None, log_format="text",
          exporter=None, trust_incoming_trace=False,
          idempotency_ttl_ms=None):
    """A configured, not-yet-started server bound to `host:port`.

    Port 0 binds an ephemeral port (tests); the caller owns the lifecycle —
    `serve_forever()` to run, `shutdown()` + `server_close()` to stop.

    `repository_factory` is called once per request for a fresh capability
    store; omitted, each request gets the in-memory one. `token_provider`
    turns the M3 presence check into real verification (M3a); omitted, the
    header is only checked for presence, which is what shipped with #26.
    `network` (issue #101) is a `NetworkDriver` every request's Interpreter
    shares; omitted, each request gets its own FakeNetworkDriver. `clock`
    (issue #80) is a `Clock` every request's Interpreter shares; omitted,
    each request gets its own virtual `Clock()` — the pre-#80 default.
    `log_format` (issue #78) is "text" (default, silent — the pre-#78
    behavior) or "json" (one JSON Line per request to stderr). `exporter`
    (issue #78) is a `TraceExporter` every completed workflow run's Trace is
    handed to; omitted, nothing is exported — independent of `log_format`.
    """
    kwargs = {}
    if idempotency_ttl_ms is not None:
        kwargs["idempotency_ttl_ms"] = idempotency_ttl_ms
    app = make_wsgi_app(document, repository_factory=repository_factory,
                        token_provider=token_provider, network=network,
                        clock=clock, log_format=log_format, exporter=exporter,
                        trust_incoming_trace=trust_incoming_trace, **kwargs)
    server = _Server((host, port), _WSGIRequestHandler)
    server.set_app(app)
    return server
