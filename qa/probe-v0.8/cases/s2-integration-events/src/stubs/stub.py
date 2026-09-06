"""s2-integration-events stub server — stdlib only. See requirements/s2.md B1..B7."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

_state = {"b3_calls": 0}


def _log(log_path, method, path, status, body_len):
    ts = datetime.now(timezone.utc).isoformat()
    with open(log_path, "a") as f:
        f.write(f"{ts} {method} {path} {status} {body_len}\n")


def make_handler(mode, log_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _reply(self, status, body_obj):
            body = json.dumps(body_obj).encode() if body_obj is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)
            _log(log_path, self.command, self.path, status, len(body))

        def do_GET(self):
            if not self.path.startswith("/fx"):
                self._reply(404, {"error": "not found"})
                return
            if mode == "b1":
                self._reply(200, {"rate": 1350.5})
            elif mode == "b2":
                self._reply(500, {"error": "fx unavailable"})
            elif mode == "b3":
                _state["b3_calls"] += 1
                if _state["b3_calls"] <= 2:
                    self._reply(500, {"error": "fx unavailable"})
                else:
                    self._reply(200, {"rate": 1350.5})
            elif mode == "b4":
                time.sleep(3)
                self._reply(200, {"rate": 1350.5})
            elif mode == "b5":
                self._reply(200, {"rate": "abc"})
            else:
                self._reply(404, {"error": "unexpected mode for GET"})

        def do_POST(self):
            if not self.path.startswith("/hook"):
                self._reply(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length:
                self.rfile.read(length)
            if mode == "hook-ok":
                self._reply(200, {"ok": True})
            elif mode == "b7":
                self._reply(500, {"error": "hook unavailable"})
            else:
                self._reply(404, {"error": "unexpected mode for POST"})

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True,
                     choices=["b1", "b2", "b3", "b4", "b5", "hook-ok", "b7"])
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--log", required=True)
    args = ap.parse_args()

    server = HTTPServer(("127.0.0.1", args.port), make_handler(args.mode, args.log))
    actual_port = server.server_address[1]
    print(f"PORT={actual_port}", flush=True)
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
