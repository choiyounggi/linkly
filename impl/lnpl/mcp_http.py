"""MCP Streamable HTTP transport (spec 2025-06-18) for the stdio server's handle().

One endpoint, `/mcp`: POST carries one JSON-RPC message and gets a JSON
response (202 with no body for notifications); DELETE ends a session. No SSE
stream is offered — GET answers 405, which the spec allows. A Bearer token
from `LNPL_MCP_TOKEN` is required (no token, no start), the server binds
127.0.0.1 unless told otherwise, and browsers are unsupported (no CORS; a
non-loopback Origin gets 403). Every tools/call runs in a fresh child
process bounded in time, memory and result size, so a runaway workflow can
never stall the server. Standard library only.
"""

import argparse
import collections
import hmac
import http.server
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse

from lnpl import mcp_server

ENDPOINT = "/mcp"
TOKEN_ENV = "LNPL_MCP_TOKEN"
MIN_TOKEN_BYTES = 32            # mirrors drivers.MIN_SECRET_BYTES
MAX_BODY_BYTES = 1 << 20        # same value as wsgi.MAX_BODY_BYTES
MAX_SESSIONS = 64
REQUEST_TIMEOUT_S = 30.0        # per socket read
TOOL_TIMEOUT_S = 10.0           # wall clock per tools/call
MAX_RESULT_BYTES = 1 << 22      # 4 MiB per tools/call response
CHILD_MEMORY_BYTES = 1 << 29    # 512 MiB peak RSS per tool child
MAX_TOOL_CALLS = 4              # concurrent tool children
LOOPBACK_ORIGIN_HOSTS = ("localhost", "127.0.0.1", "::1")
WWW_AUTHENTICATE = 'Bearer realm="lnpl-mcp"'
DEFAULT_PORT = 8765

CHILD_MEMORY_EXIT = 86          # exit status of a child stopped by its memory watchdog
MEMORY_POLL_S = 0.05
_CHILD_CODE = ("import json, sys; env = json.loads(sys.stdin.buffer.read()); "
               "sys.path[:0] = env['sys_path']; "
               "from lnpl.mcp_http import _child_main; sys.exit(_child_main(env))")


def check_token(token):
    """None when `token` may guard the listener, else why not (never echoes it)."""
    if not token:
        return "LNPL_MCP_TOKEN is not set; the HTTP transport refuses to start without a token"
    if any(not ("\x21" <= ch <= "\x7e") for ch in token):
        return "LNPL_MCP_TOKEN must be visible ASCII with no whitespace"
    if len(token.encode("utf-8")) < MIN_TOKEN_BYTES:
        return "LNPL_MCP_TOKEN must be at least 32 bytes"
    return None


def origin_allowed(origin):
    """DNS-rebinding guard: only an exact loopback `http://host[:port]`."""
    try:
        parts = urllib.parse.urlsplit(origin)
        parts.port                      # raises ValueError on a non-numeric port
    except ValueError:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    if parts.path or parts.query or parts.fragment:
        return False
    return parts.scheme == "http" and parts.hostname in LOOPBACK_ORIGIN_HOSTS


def _tool_error(mid, text):
    return mcp_server._ok(mid, {"content": [{"type": "text", "text": text}], "isError": True})


def _encode(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _child_env(environ):
    """The child's environment: everything except the bearer token."""
    return {key: value for key, value in environ.items() if key != TOKEN_ENV}


def _parse_child_output(stdout, returncode, mid=None):
    if returncode == 0:
        try:
            obj = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            obj = None
        if isinstance(obj, dict):
            return obj
    return mcp_server._error(mid, mcp_server.INTERNAL_ERROR, "internal error")


def _guarded_handle(message):
    """handle() with sys.stdout pointed at stderr, so nothing a tool prints
    can corrupt the child's one-JSON-object stdout."""
    saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        return mcp_server.handle(message, allow_paths=False)
    except Exception:
        traceback.print_exc()
        return mcp_server._error(message.get("id"), mcp_server.INTERNAL_ERROR, "internal error")
    finally:
        sys.stdout = saved


def _memory_watchdog(resource, limit):
    unit = 1 if sys.platform == "darwin" else 1024   # ru_maxrss: bytes on macOS, KiB on Linux
    while True:
        time.sleep(MEMORY_POLL_S)
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unit > limit:
            os._exit(CHILD_MEMORY_EXIT)


def _child_response(env):
    """Runs ONLY inside the tool child (it sets rlimits on its own process)."""
    mid = (env.get("message") or {}).get("id")
    try:
        import resource
    except ImportError:
        return _encode(_tool_error(mid, "tool calls are disabled on this platform: the resource "
                                        "module is unavailable, so the HTTP transport cannot "
                                        "bound their memory"))
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (env["cpu_seconds"], env["cpu_seconds"] + 1))
    except (ValueError, OSError):
        pass                                      # backstop only; the parent's kill is the time bound
    threading.Thread(target=_memory_watchdog, args=(resource, env["memory_bytes"]),
                     daemon=True).start()
    data = _encode(_guarded_handle(env["message"]))
    if len(data) > env["max_result_bytes"]:
        data = _encode(_tool_error(mid, "tool result is %d bytes; the HTTP transport limit is %d bytes"
                                        % (len(data), env["max_result_bytes"])))
    return data


def _child_main(env):
    real_out = sys.stdout.buffer
    real_out.write(_child_response(env))
    real_out.flush()
    return 0


class McpHttpServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, token, *, max_sessions=MAX_SESSIONS,
                 request_timeout=REQUEST_TIMEOUT_S, tool_timeout=TOOL_TIMEOUT_S,
                 max_result_bytes=MAX_RESULT_BYTES, child_memory_bytes=CHILD_MEMORY_BYTES,
                 max_tool_calls=MAX_TOOL_CALLS):
        error = check_token(token)
        if error:
            raise ValueError(error)
        self.token_bytes = token.encode("ascii")
        self.sessions = collections.OrderedDict()
        self.lock = threading.Lock()                # guards self.sessions only
        self.max_sessions = max_sessions
        self.request_timeout = request_timeout
        self.tool_timeout = tool_timeout
        self.max_result_bytes = max_result_bytes
        self.child_memory_bytes = child_memory_bytes
        self.max_tool_calls = max_tool_calls
        self.tool_slots = threading.BoundedSemaphore(max_tool_calls)
        super().__init__(server_address, McpRequestHandler)

    def new_session(self):
        sid = secrets.token_hex(16)
        with self.lock:
            self.sessions[sid] = True
            while len(self.sessions) > self.max_sessions:
                self.sessions.popitem(last=False)
        return sid

    def has_session(self, sid):
        with self.lock:
            return sid in self.sessions

    def end_session(self, sid):
        with self.lock:
            return self.sessions.pop(sid, None) is not None

    def dispatch(self, message):
        """One JSON-RPC message -> response dict or None. A tools/call with an
        id runs in a child process (run_tool_call); a tools/call notification
        (id null) reaches handle(), which returns None (202). Everything else
        runs in the request thread and takes no lock: it reads only module
        constants."""
        try:
            if message.get("method") == "tools/call" and message.get("id") is not None:
                return self.run_tool_call(message)
            return mcp_server.handle(message, allow_paths=False)
        except Exception:
            traceback.print_exc()
            return mcp_server._error(message.get("id"), mcp_server.INTERNAL_ERROR, "internal error")

    def run_tool_call(self, message):
        mid = message.get("id")
        if not self.tool_slots.acquire(blocking=False):
            return _tool_error(mid, "server busy: %d tool calls are already running; retry later"
                                    % self.max_tool_calls)
        try:
            envelope = _encode({"sys_path": [os.path.abspath(p) for p in sys.path],
                                "message": message,
                                "max_result_bytes": self.max_result_bytes,
                                "memory_bytes": self.child_memory_bytes,
                                "cpu_seconds": int(self.tool_timeout) + 1})
            proc = subprocess.Popen([sys.executable, "-I", "-c", _CHILD_CODE],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    env=_child_env(os.environ))
            try:
                stdout, _ = proc.communicate(envelope, timeout=self.tool_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return _tool_error(mid, "tool call stopped: it ran longer than the %g s limit of "
                                        "the HTTP transport" % self.tool_timeout)
            if proc.returncode == CHILD_MEMORY_EXIT:
                return _tool_error(mid, "tool call stopped: it used more than the %d MiB memory "
                                        "limit of the HTTP transport" % (self.child_memory_bytes >> 20))
            return _parse_child_output(stdout, proc.returncode, mid)
        finally:
            self.tool_slots.release()


def make_server(host, port, token, **options):
    return McpHttpServer((host, port), token, **options)


class McpRequestHandler(http.server.BaseHTTPRequestHandler):
    # protocol_version stays HTTP/1.0: every response closes its connection,
    # so an unread request body can never be parsed as a next request.

    def setup(self):
        self.timeout = self.server.request_timeout
        super().setup()

    def version_string(self):
        return "lnpl-mcp"

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, format, *args):
        return                          # the stdlib line would echo the raw request line

    def log_request(self, code="-", size="-"):
        sys.stderr.write("lnpl-mcp: %s %s %s\n" % (
            getattr(self, "command", None) or "-",
            urllib.parse.urlsplit(getattr(self, "path", "") or "").path, code))
        sys.stderr.flush()

    def _send_json(self, status, body, extra_headers=()):
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        for name, value in extra_headers:
            self.send_header(name, value)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data and self.command != "HEAD":
            self.wfile.write(data)

    def _send_error_json(self, status, code, message, extra_headers=()):
        self._send_json(status, mcp_server._error(None, code, message), extra_headers)

    def _authorized(self):
        header = self.headers.get("Authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer":
            return False
        return hmac.compare_digest(presented.encode("latin-1", "replace"), self.server.token_bytes)

    def _prelude(self):
        """Origin (403) -> path (404) -> auth (401) -> protocol header (400).
        True to continue; False when a response was already sent."""
        origin = self.headers.get("Origin")
        if origin is not None and not origin_allowed(origin):
            self._send_error_json(403, mcp_server.INVALID_REQUEST, "origin not allowed")
            return False
        if urllib.parse.urlsplit(self.path).path != ENDPOINT:
            self._send_error_json(404, mcp_server.INVALID_REQUEST, "not found")
            return False
        if not self._authorized():
            self._send_error_json(401, mcp_server.INVALID_REQUEST, "unauthorized",
                                  [("WWW-Authenticate", WWW_AUTHENTICATE)])
            return False
        version = self.headers.get("MCP-Protocol-Version")
        if version is not None and version not in mcp_server.SUPPORTED_PROTOCOL_VERSIONS:
            self._send_error_json(400, mcp_server.INVALID_REQUEST, "unsupported MCP-Protocol-Version")
            return False
        return True

    def _method_not_allowed(self):
        if self._prelude():
            self._send_error_json(405, mcp_server.INVALID_REQUEST, "method not allowed",
                                  [("Allow", "POST, DELETE")])

    do_GET = do_PUT = do_PATCH = do_OPTIONS = do_HEAD = _method_not_allowed

    def _read_message(self):
        """The request's one JSON-RPC object, or None after an error response.
        Nothing is read from the body before every header check has passed."""
        if self.headers.get("Transfer-Encoding") is not None:
            self._send_error_json(411, mcp_server.INVALID_REQUEST,
                                  "Transfer-Encoding is not supported; send Content-Length")
            return None
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_error_json(415, mcp_server.INVALID_REQUEST,
                                  "Content-Type must be application/json")
            return None
        raw = self.headers.get("Content-Length") or ""
        # ASCII digits only: int() would also take "+5", " 5" and "1_0".
        length = int(raw) if raw.isascii() and raw.isdigit() else -1
        if length < 0:
            self._send_error_json(411, mcp_server.INVALID_REQUEST, "Content-Length required")
            return None
        if length > MAX_BODY_BYTES:
            self._send_error_json(413, mcp_server.INVALID_REQUEST, "request body too large")
            return None
        data = self.rfile.read(length)
        try:
            message = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            self._send_error_json(400, mcp_server.PARSE_ERROR, "invalid JSON")
            return None
        if not isinstance(message, dict):
            self._send_error_json(400, mcp_server.INVALID_REQUEST,
                                  "a JSON-RPC message must be a single object")
            return None
        return message

    def do_POST(self):
        if not self._prelude():
            return
        message = self._read_message()
        if message is None:
            return
        if "method" not in message and ("result" in message or "error" in message):
            self._send_json(202, None)          # a client response; we send no requests
            return
        is_initialize = message.get("method") == "initialize"
        if not is_initialize:
            sid = self.headers.get("Mcp-Session-Id")
            if sid is None:
                self._send_error_json(400, mcp_server.INVALID_REQUEST, "missing Mcp-Session-Id header")
                return
            if not self.server.has_session(sid):
                self._send_error_json(404, mcp_server.INVALID_REQUEST, "unknown or terminated session")
                return
        response = self.server.dispatch(message)
        if response is None:
            self._send_json(202, None)
            return
        headers = []
        if is_initialize and "result" in response:
            headers.append(("Mcp-Session-Id", self.server.new_session()))
        self._send_json(200, response, headers)

    def do_DELETE(self):
        if not self._prelude():
            return
        sid = self.headers.get("Mcp-Session-Id")
        if sid is None:
            self._send_error_json(400, mcp_server.INVALID_REQUEST, "missing Mcp-Session-Id header")
            return
        if not self.server.end_session(sid):
            self._send_error_json(404, mcp_server.INVALID_REQUEST, "unknown or terminated session")
            return
        self._send_json(204, None)


def main(argv=None, environ=None):
    """`python -m lnpl.mcp_http`. rc 0 after Ctrl-C, 2 on a refused start."""
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(
        prog="python -m lnpl.mcp_http",
        description="Serve the lnpl MCP tools over Streamable HTTP at /mcp. "
                    "Requires LNPL_MCP_TOKEN (32+ visible-ASCII bytes).")
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to bind (default 127.0.0.1; anything else exposes the "
                             "server beyond this machine)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="TCP port (default %d; 0 picks a free port)" % DEFAULT_PORT)
    args = parser.parse_args(argv)
    token = environ.get(TOKEN_ENV)
    error = check_token(token)
    if error:
        print("lnpl-mcp: %s" % error, file=sys.stderr)
        return 2
    try:
        server = make_server(args.host, args.port, token)
    except OSError as exc:
        print("lnpl-mcp: cannot listen on %s:%d: %s" % (args.host, args.port, exc.strerror or exc),
              file=sys.stderr)
        return 2
    print("lnpl-mcp: http listening on %s:%d" % (args.host, server.server_address[1]),
          file=sys.stderr, flush=True)
    if args.host not in ("127.0.0.1", "localhost"):
        print("lnpl-mcp: warning: %s is not loopback; put TLS and rate limiting in front of "
              "this server" % args.host, file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
