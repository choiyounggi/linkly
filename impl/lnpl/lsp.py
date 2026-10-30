"""`lnpl lsp` — a stdio Language Server Protocol 3.17 server (issue #254).

Editors spawn this process and exchange JSON-RPC 2.0 messages framed by
`Content-Length` headers over binary stdin/stdout (LSP base protocol). That is
a different framing from `mcp_server`'s one-JSON-object-per-line protocol, so
the two share no transport code.

Every open document is compiled (`parse` -> `lower` -> RFC-0042 extension
diagnostics) and the result is pushed as `textDocument/publishDiagnostics`. The
`unknown-verb` did-you-mean `suggestion` (RFC-0026) is offered as a quickfix
`textDocument/codeAction`, and `textDocument/hover` on a workflow step's verb
links the RFC section that defines it.

Stdlib only. The server never writes to the user's files: a code action is a
`WorkspaceEdit` the client applies. stdout carries protocol frames and nothing
else; tracebacks go to stderr.
"""

import json
import os
import re
import sys
import traceback
from urllib.parse import unquote, urlparse

from lnpl import __version__
from lnpl.diagnostics import ExtensionDiagnosticsError, extension_diagnostic_records
from lnpl.lexer import LexError
from lnpl.lower import VERB_LEXICON, LowerError, lower
from lnpl.parser import ParseError, parse

# JSON-RPC 2.0 / LSP 3.17 ErrorCodes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_NOT_INITIALIZED = -32002

# Compiler severity -> LSP DiagnosticSeverity (Error 1, Warning 2, Information 3).
_SEVERITY = {"error": 1, "warning": 2, "info": 3}

# LSP line terminators (3.17 "Text Documents": \n, \r\n, \r). str.splitlines()
# also breaks on \f, \v, \x85,   ..., which the client does not count.
_LSP_BREAK = re.compile(r"\r\n|\r|\n")

_READ_CHUNK = 65536

RFC_BASE_URL = "https://github.com/choiyounggi/linkly/blob/main/rfcs/"

_APPENDIX_A = ("0067-syntax-v2.md", "### 부록 A: Lowering 매핑")
# verb -> (RFC file, heading line verbatim). test_lsp pins the keys to
# VERB_LEXICON and each heading to a line of an Accepted RFC.
VERB_RFC = {
    "set": ("0051-money-arithmetic-in-set-and-guards.md",
            "# RFC-0051: `set`·가드의 Money 산술 — 같은 통화 부분집합"),
    "validate": ("0053-optional-field-modifier.md",
                 "### 3. 입력 경계 — `validate`와 `null`"),
    "list": ("0077-list-where-predicate-v2.md",
             "### 1. `list` 표면 문법 — RFC-0025 §1 갱신 (치환 후 최종 텍스트) (D1)"),
    "create": ("0030-create-result-binding-and-payload-seed.md",
               "# RFC-0030: `create` 결과 바인딩과 payload 시드"),
    "insert": ("0030-create-result-binding-and-payload-seed.md",
               "### 1. 문법 — RFC-0027 §2 표기 재사용, `create`/`insert`로 확장 (D1)"),
    "authorize": ("0035-authorization-enforcement-deferred-scope.md",
                  "### D2. `authorize` 동사의 (a)/(b) 판단 기준"),
    "respond": ("0059-respond-aggregate-and-list-terms.md",
                "# RFC-0059: `respond`의 이름 붙인 집계 항과 목록 항"),
    "note": ("0039-note-verb-and-canonical-line.md",
             "# RFC-0039: `note` 동사와 canonical log line 확장"),
    "fail": ("0056-fail-business-rejection.md",
             "# RFC-0056: `fail` 동사 — 저자가 선언하는 업무 거절"),
    "authenticate": _APPENDIX_A, "load": _APPENDIX_A, "find": _APPENDIX_A,
    "read": _APPENDIX_A, "update": _APPENDIX_A, "delete": _APPENDIX_A,
    "cache": _APPENDIX_A, "invalidate": _APPENDIX_A, "call": _APPENDIX_A,
    "request": _APPENDIX_A, "emit": _APPENDIX_A, "publish": _APPENDIX_A,
    "format": _APPENDIX_A,
}


class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class _InvalidParams(_RpcError):
    def __init__(self, message):
        super().__init__(INVALID_PARAMS, message)


def _read_message(stdin):
    """One frame body (bytes), or None at EOF / on a broken header block."""
    length = None
    while True:
        line = stdin.readline()
        if line == b"":
            return None
        if line.endswith(b"\r\n"):
            line = line[:-2]
        elif line.endswith(b"\n"):
            line = line[:-1]
        if line == b"":
            break
        if b":" not in line:
            return None
        name, value = line.split(b":", 1)
        if name.strip().lower() == b"content-length":
            length = value.strip()
    if length is None or not (length.isascii() and length.isdigit()):
        return None
    try:
        remaining = int(length)
    except ValueError:  # beyond int()'s 4300-digit limit
        return None
    # Read in bounded chunks: a BufferedReader preallocates n bytes for one
    # read(n), so a huge declared length would be a MemoryError before EOF.
    chunks = []
    while remaining > 0:
        chunk = stdin.read(min(remaining, _READ_CHUNK))
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_message(stdout, obj):
    try:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate from the client (echoed `method`, `id`, document
        # text) has no UTF-8 form; ASCII-escaped JSON carries it as \udXXX.
        body = json.dumps(obj).encode("ascii")
    stdout.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    stdout.flush()


# ---- positions --------------------------------------------------------------

def _utf16_len(s):
    return len(s.encode("utf-16-le")) // 2


def _lsp_position(text, offset):
    prefix = text[:offset]
    breaks = list(_LSP_BREAK.finditer(prefix))
    start = breaks[-1].end() if breaks else 0
    return {"line": len(breaks), "character": _utf16_len(prefix[start:])}


def _zero_range():
    return {"start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0}}


def _line_span(text, lineno, subject):
    """LSP range of `subject` on compiler line `lineno` (1-based, splitlines
    numbering), else of the line's non-blank body, else the zero range."""
    parts = text.splitlines(keepends=True)
    if (not isinstance(lineno, int) or isinstance(lineno, bool)
            or lineno < 1 or lineno > len(parts)):
        return _zero_range()
    base = sum(len(p) for p in parts[:lineno - 1])
    stripped = parts[lineno - 1].splitlines()
    content = stripped[0] if stripped else ""
    body = content.split("#", 1)[0]
    if not body.strip():
        return _zero_range()
    span = None
    for m in re.finditer(r"\S+", body):
        if m.group() == subject:
            span = (m.start(), m.end())
            break
    if span is None:
        span = (len(body) - len(body.lstrip()), len(body.rstrip()))
    return {"start": _lsp_position(text, base + span[0]),
            "end": _lsp_position(text, base + span[1])}


def _module_name(uri):
    name = os.path.basename(unquote(urlparse(uri).path))
    if name.endswith(".lnpl"):
        name = name[:-len(".lnpl")]
    return name or "lsp"


# ---- compile ----------------------------------------------------------------

def _compile(text, uri):
    """LSP Diagnostic dicts for one document. A compile failure is an expected
    outcome here — one `compile-error` diagnostic, never an exception."""
    def make(code, severity, message, rng, subject=None, suggestion=None,
             line=None):
        return {"range": rng, "severity": severity, "code": code,
                "source": "lnpl", "message": message,
                "data": {"subject": subject, "suggestion": suggestion,
                         "line": line}}

    def compile_error(message):
        m = re.match(r"line (\d+):", message)
        rng = _line_span(text, int(m.group(1)), None) if m else _zero_range()
        return make("compile-error", 1, message, rng)

    try:
        module = lower(parse(text), _module_name(uri))
    except (LexError, ParseError, LowerError) as exc:
        return [compile_error(str(exc))]
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return [compile_error("internal compiler error: %s: %s"
                              % (type(exc).__name__, exc))]
    out = [make(d.code, _SEVERITY[d.severity], d.message,
                _line_span(text, d.line, d.subject), d.subject, d.suggestion,
                d.line)
           for d in module.diagnostics]
    try:
        records = extension_diagnostic_records(module.to_document())
    except ExtensionDiagnosticsError as exc:
        out.append(compile_error("extension diagnostics: %s" % exc))
        return out
    for rec in records:
        out.append(make(rec["code"], _SEVERITY.get(rec["severity"], 1),
                        rec["message"],
                        _line_span(text, rec.get("line"), rec.get("subject")),
                        rec.get("subject"), None, rec.get("line")))
    return out


def _uri(params):
    doc = params.get("textDocument")
    uri = doc.get("uri") if isinstance(doc, dict) else None
    if not isinstance(uri, str):
        raise _InvalidParams("textDocument.uri is required")
    return uri


def _pos_tuple(pos):
    return (pos["line"], pos["character"])


def _valid_range(rng):
    if not isinstance(rng, dict):
        return False
    for key in ("start", "end"):
        pos = rng.get(key)
        if not isinstance(pos, dict):
            return False
        for field in ("line", "character"):
            value = pos.get(field)
            if not isinstance(value, int) or isinstance(value, bool):
                return False
    return True


def _intersects(a, b):
    if not _valid_range(b):
        raise _InvalidParams("range is required")
    return not (_pos_tuple(a["end"]) < _pos_tuple(b["start"])
                or _pos_tuple(b["end"]) < _pos_tuple(a["start"]))


# ---- hover ------------------------------------------------------------------

def _heading_text(heading):
    return heading.lstrip("#").strip()


def _heading_slug(text):
    """GitHub's heading anchor: lower-case, spaces to `-`, punctuation dropped."""
    out = []
    for ch in text.lower():
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        elif ch == " ":
            out.append("-")
    return "".join(out)


def _rfc_url(verb):
    file, heading = VERB_RFC[verb]
    return RFC_BASE_URL + file + "#" + _heading_slug(_heading_text(heading))


def _hover_value(verb):
    effect, attrs = VERB_LEXICON[verb]
    extra = "" if not attrs else " (" + ", ".join(
        "%s=%s" % (k, attrs[k]) for k in sorted(attrs)) + ")"
    file, heading = VERB_RFC[verb]
    return "`%s` → `%s`%s\n\n[RFC-%s §%s](%s)" % (
        verb, effect, extra, file[:4], _heading_text(heading), _rfc_url(verb))


def _lsp_lines(text):
    return _LSP_BREAK.split(text)


def _workflow_body_lines(lines):
    """Indexes of the lines that are steps of a `workflow` body (spec bodies
    nested in it excluded)."""
    found = set()
    in_workflow = False
    spec_indent = None
    for index, line in enumerate(lines):
        body = line.split("#", 1)[0]
        if not body.strip():
            continue
        indent = len(body) - len(body.lstrip())
        head = body.split()[0]
        if indent == 0:
            in_workflow = head == "workflow"
            spec_indent = None
            continue
        if not in_workflow:
            continue
        if spec_indent is not None and indent > spec_indent:
            continue
        spec_indent = None
        if head == "spec":
            spec_indent = indent
        else:
            found.add(index)
    return found


# ---- server -----------------------------------------------------------------

class LspServer:
    def __init__(self, stdin, stdout):
        self.stdin = stdin
        self.stdout = stdout
        self.state = "uninitialized"
        self.literal_support = False
        self.documents = {}
        self.requests = {
            "initialize": self._initialize,
            "shutdown": self._shutdown,
            "textDocument/codeAction": self._code_action,
            "textDocument/hover": self._hover,
        }
        self.notifications = {"initialized": self._ignore}
        self.notifications.update({
            "textDocument/didOpen": self._did_open,
            "textDocument/didChange": self._did_change,
            "textDocument/didClose": self._did_close,
        })

    def _respond(self, id_, result):
        _write_message(self.stdout, {"jsonrpc": "2.0", "id": id_,
                                     "result": result})

    def _error(self, id_, code, message):
        _write_message(self.stdout, {"jsonrpc": "2.0", "id": id_,
                                     "error": {"code": code,
                                               "message": message}})

    def _notify(self, method, params):
        _write_message(self.stdout, {"jsonrpc": "2.0", "method": method,
                                     "params": params})

    def run(self):
        while True:
            body = _read_message(self.stdin)
            if body is None:
                return 0 if self.state == "shutdown" else 1
            try:
                msg = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                # RecursionError: CPython's json scanner on deeply nested input.
                self._error(None, PARSE_ERROR, "Parse error")
                continue
            code = self._dispatch(msg)
            if code is not None:
                return code

    def _dispatch(self, msg):
        """Handle one message; return an exit status only for `exit`. The one
        place a handler exception is caught and logged (stderr)."""
        if not isinstance(msg, dict):
            self._error(None, INVALID_REQUEST, "Invalid Request")
            return None
        method = msg.get("method")
        raw_id = msg.get("id")
        valid_id = (isinstance(raw_id, (int, str))
                    and not isinstance(raw_id, bool))
        if not isinstance(method, str):
            if "result" in msg or "error" in msg:
                return None  # a response to a server request; none are sent
            self._error(raw_id if valid_id else None, INVALID_REQUEST,
                        "Invalid Request")
            return None
        if "id" not in msg:
            return self._notification(method, msg.get("params", {}))
        if not valid_id:
            self._error(None, INVALID_REQUEST, "Invalid Request")
            return None
        id_ = raw_id
        if self.state == "uninitialized" and method != "initialize":
            self._error(id_, SERVER_NOT_INITIALIZED, "Server not initialized")
            return None
        if self.state == "shutdown":
            self._error(id_, INVALID_REQUEST, "Server is shut down")
            return None
        handler = self.requests.get(method)
        if handler is None:
            self._error(id_, METHOD_NOT_FOUND, "Method not found: %s" % method)
            return None
        params = msg.get("params", {})
        if not isinstance(params, dict):
            self._error(id_, INVALID_PARAMS, "params must be an object")
            return None
        try:
            result = handler(params)
        except _RpcError as exc:
            self._error(id_, exc.code, exc.message)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            self._error(id_, INTERNAL_ERROR,
                        "%s: %s" % (type(exc).__name__, exc))
        else:
            self._respond(id_, result)
        return None

    def _notification(self, method, params):
        if method == "exit":
            return 0 if self.state == "shutdown" else 1
        if self.state in ("uninitialized", "shutdown"):
            return None
        handler = self.notifications.get(method)
        if handler is None:  # `$/` notifications included: ignore
            return None
        try:
            handler(params)
        except Exception:
            traceback.print_exc(file=sys.stderr)
        return None

    def _ignore(self, params):
        return None

    def _initialize(self, params):
        if self.state != "uninitialized":
            raise _RpcError(INVALID_REQUEST, "initialize may be sent only once")
        node = params.get("capabilities")
        for key in ("textDocument", "codeAction", "codeActionLiteralSupport"):
            node = node.get(key) if isinstance(node, dict) else None
        self.literal_support = isinstance(node, dict)
        self.state = "initialized"
        code_action = ({"codeActionKinds": ["quickfix"]}
                       if self.literal_support else True)
        return {"capabilities": {"positionEncoding": "utf-16",
                                 "textDocumentSync": {"openClose": True,
                                                      "change": 1},
                                 "hoverProvider": True,
                                 "codeActionProvider": code_action},
                "serverInfo": {"name": "lnpl", "version": __version__}}

    def _shutdown(self, params):
        self.state = "shutdown"
        return None

    # ---- documents ----------------------------------------------------------

    def _publish(self, uri, text, version):
        diags = _compile(text, uri)
        self.documents[uri] = {"text": text, "version": version,
                               "diagnostics": diags}
        params = {"uri": uri, "diagnostics": diags}
        if isinstance(version, int) and not isinstance(version, bool):
            params["version"] = version
        self._notify("textDocument/publishDiagnostics", params)

    def _did_open(self, params):
        doc = params.get("textDocument")
        if not (isinstance(doc, dict) and isinstance(doc.get("uri"), str)
                and isinstance(doc.get("text"), str)):
            print("lnpl lsp: didOpen without textDocument.uri/text — ignored",
                  file=sys.stderr)
            return
        self._publish(doc["uri"], doc["text"], doc.get("version"))

    def _did_change(self, params):
        doc = params.get("textDocument")
        changes = params.get("contentChanges")
        if not (isinstance(doc, dict) and isinstance(doc.get("uri"), str)
                and isinstance(changes, list) and changes
                and isinstance(changes[-1], dict)
                and isinstance(changes[-1].get("text"), str)):
            print("lnpl lsp: didChange without textDocument.uri or a full-text "
                  "change — ignored", file=sys.stderr)
            return
        self._publish(doc["uri"], changes[-1]["text"], doc.get("version"))

    def _did_close(self, params):
        doc = params.get("textDocument")
        if not (isinstance(doc, dict) and isinstance(doc.get("uri"), str)):
            print("lnpl lsp: didClose without textDocument.uri — ignored",
                  file=sys.stderr)
            return
        uri = doc["uri"]
        self.documents.pop(uri, None)
        self._notify("textDocument/publishDiagnostics",
                     {"uri": uri, "diagnostics": []})

    # ---- requests -----------------------------------------------------------

    def _code_action(self, params):
        if not self.literal_support:
            return []
        uri = _uri(params)
        doc = self.documents.get(uri)
        if doc is None:
            return []
        context = params.get("context")
        if not isinstance(context, dict):
            context = {}
        only = context.get("only")
        if isinstance(only, list) and "quickfix" not in only:
            return []
        given = context.get("diagnostics") or []
        if not given:
            rng = params.get("range")
            given = [d for d in doc["diagnostics"]
                     if _intersects(d["range"], rng)]
        actions = []
        for d in given:
            if not isinstance(d, dict) or d.get("code") != "unknown-verb":
                continue
            data = d.get("data")
            if not isinstance(data, dict):
                data = next((s["data"] for s in doc["diagnostics"]
                             if s["code"] == d.get("code")
                             and s["range"] == d.get("range")), None)
            suggestion = data.get("suggestion") if data else None
            if not suggestion:
                continue
            actions.append({
                "title": "Replace '%s' with '%s'" % (data.get("subject"),
                                                    suggestion),
                "kind": "quickfix",
                "diagnostics": [d],
                "isPreferred": True,
                "edit": {"changes": {uri: [{"range": d["range"],
                                            "newText": suggestion}]}},
            })
        return actions

    def _hover(self, params):
        uri = _uri(params)
        pos = params.get("position")
        if not (isinstance(pos, dict)
                and all(isinstance(pos.get(k), int)
                        and not isinstance(pos.get(k), bool)
                        for k in ("line", "character"))):
            raise _InvalidParams("position is required")
        doc = self.documents.get(uri)
        if doc is None:
            return None
        lines = _lsp_lines(doc["text"])
        n, character = pos["line"], pos["character"]
        if not 0 <= n < len(lines) or n not in _workflow_body_lines(lines):
            return None
        m = re.match(r"\s*(\S+)", lines[n].split("#", 1)[0])
        if m is None:
            return None
        verb = m.group(1)
        c0 = _utf16_len(lines[n][:m.start(1)])
        c1 = c0 + _utf16_len(verb)
        if not c0 <= character < c1 or verb not in VERB_LEXICON:
            return None
        return {"contents": {"kind": "markdown", "value": _hover_value(verb)},
                "range": {"start": {"line": n, "character": c0},
                          "end": {"line": n, "character": c1}}}


def serve(stdin, stdout):
    """Run one LSP session over binary streams; return the process exit status (0 or 1)."""
    return LspServer(stdin, stdout).run()
