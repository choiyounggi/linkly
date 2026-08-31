"""`lnpl serve` — the built-in dev server for the request-processing core in
`lnpl.wsgi` (issue #26; restructured into a WSGI callable by issue #80).

The core — routing, the M1-M16 status-code mapping, JWT, masking, GET
single/list, and SSE subscribe — lives in `wsgi.py` as a PEP-3333 callable.
This module wraps that SAME callable with the stdlib `wsgiref.simple_server`
+ `socketserver.ThreadingMixIn`, so `lnpl serve` keeps its zero-dependency,
one-thread-per-request dev server unchanged in behavior; a production
deployment instead points a real WSGI host (gunicorn) at
`lnpl.wsgi:build_app()` and gets TLS termination and worker-process
management from that host + nginx instead of from this module. issue #148
narrowed the original D4 posture ("this module never gained a signal
handler for that") to those two specifically — TLS/worker-pool management
stays gunicorn+nginx's job (`examples/deploy/`), but SIGTERM graceful drain
(rejecting new requests, waiting for in-flight ones, then stopping) is now
this module's own, so `lnpl serve` itself behaves the same way under a
rolling deploy that a real WSGI host would.

The status-code mapping table (M1-M9) is normative in docs/serving.md, next
to the same table's GET/SSE rows (M10-M16, issues #99/#103).
"""

import signal
import socketserver
import sys
import threading
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

from .wsgi import (  # re-exported for backward compatibility — every name
    # below already had callers outside this module before issue #80.
    # _parse_limit/_TITLES are excluded from __all__ (private-looking names)
    # but test_serve_get.py/test_serve_backend.py import them directly from
    # this module, so they stay re-exported here despite looking unused.
    CursorError, DEFAULT_LIMIT, MAX_BODY_BYTES, MAX_LIMIT, ServeError,
    SSE_IDLE_TIMEOUT_S, SSE_POLL_INTERVAL_S, WsgiConfigError, _parse_limit,  # noqa: F401
    _TITLES, build_routes, decode_cursor, encode_cursor, make_wsgi_app,  # noqa: F401
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


def _install_sigterm_handler(app, server, grace_period_s):
    """issue #110, D11 + issue #148, D2: SIGTERM flips `/-/readyz` to 503
    (unchanged, still the ONLY thing the handler itself does — no I/O in
    signal context) AND starts a background drain: wait for `app`'s
    in-flight requests to reach 0, or `grace_period_s` seconds, whichever
    comes first, then stop the server. This is the one reversal of this
    module's former D4 posture ("this module never gained a signal handler
    for [draining/shutdown], that stays the WSGI host's job") — `lnpl serve`
    is still not the production path (gunicorn+nginx is, see the module
    docstring), but issue #148 asks the DEV server to also drain gracefully
    on its own, so tests exercising it don't need a real WSGI host.

    `server.shutdown()` must run on a thread OTHER than the one blocked in
    `serve_forever()` (stdlib requirement — same-thread would deadlock),
    which the drain thread already is.
    """
    def _drain_then_shutdown():
        drained = app.wait_for_drain(grace_period_s)
        print("lnpl serve: %s -- shutting down"
              % ("drain complete" if drained
                 else "grace period (%ss) exceeded with requests still "
                     "in flight" % grace_period_s),
              file=sys.stderr)
        server.shutdown()

    def _on_sigterm(signum, frame):
        # issue #150: `begin_shutdown()` sets the flag under `_inflight_cv`
        # (same lock `_admit()` checks it under) -- a bare attribute
        # assignment here raced the WSGI gate/increment. Still no I/O in
        # the handler itself, just the lock acquire.
        app.begin_shutdown()
        threading.Thread(target=_drain_then_shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _on_sigterm)


def serve(document, host="127.0.0.1", port=8080, repository_factory=None,
          token_provider=None, network=None, cache=None, clock=None,
          log_format="text", exporter=None, trust_incoming_trace=False,
          jwt_secret_env=None, metrics=False, idempotency_ttl_ms=None,
          capture_on_failure=False, rate_limit=None, grace_period_s=30.0):
    """A configured, not-yet-started server bound to `host:port`.

    Port 0 binds an ephemeral port (tests); the caller owns the lifecycle —
    `serve_forever()` to run, `shutdown()` + `server_close()` to stop.

    `repository_factory` is called once per request for a fresh capability
    store; omitted, each request gets the in-memory one. `token_provider`
    turns the M3 presence check into real verification (M3a); omitted, the
    header is only checked for presence, which is what shipped with #26.
    `network` (issue #101) is a `NetworkDriver` every request's Interpreter
    shares; omitted, each request gets its own FakeNetworkDriver. `cache`
    (issue #131) is a `CacheDriver` every request's Interpreter shares, the
    same one-instance-shared-across-requests shape `network` already has
    (a `CacheDriver` carries no per-request transaction state, unlike
    `repository`); omitted, each request gets its own FakeCache. `clock`
    (issue #80) is a `Clock` every request's Interpreter shares; omitted,
    each request gets its own virtual `Clock()` — the pre-#80 default.
    `log_format` (issue #78) is "text" (default, silent — the pre-#78
    behavior) or "json" (one JSON Line per request to stderr). `exporter`
    (issue #78) is a `TraceExporter` every completed workflow run's Trace is
    handed to; omitted, nothing is exported — independent of `log_format`.
    `capture_on_failure` (issue #111, D7) is off by default; on, a failed/
    500 run's canonical line (json log mode only) carries its masked input
    payload — a reproduction snapshot for exactly the runs that need one.
    `rate_limit` (issue #148, D1) is `None` by default (unlimited, the
    pre-#148 behavior); set, it is a single process-wide token bucket's
    rate == burst capacity, tokens/second. `grace_period_s` (issue #148, D2)
    bounds how long a SIGTERM's drain waits for in-flight requests before
    stopping the server anyway — default 30s, unused unless SIGTERM arrives.
    """
    kwargs = {}
    if idempotency_ttl_ms is not None:
        kwargs["idempotency_ttl_ms"] = idempotency_ttl_ms
    app = make_wsgi_app(document, repository_factory=repository_factory,
                        token_provider=token_provider, network=network,
                        cache=cache, clock=clock, log_format=log_format,
                        exporter=exporter,
                        trust_incoming_trace=trust_incoming_trace,
                        jwt_secret_env=jwt_secret_env, metrics=metrics,
                        capture_on_failure=capture_on_failure,
                        rate_limit=rate_limit,
                        **kwargs)
    server = _Server((host, port), _WSGIRequestHandler)
    server.set_app(app)
    _install_sigterm_handler(app, server, grace_period_s)
    return server
