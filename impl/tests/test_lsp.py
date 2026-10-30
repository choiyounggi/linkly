"""`lnpl lsp` — the stdio LSP 3.17 server (issue #254).

Most cases drive `LspServer` in-process over `io.BytesIO` pairs: the same
frames an editor sends, without a process per case. `LspProcessTest` runs the
real `python -m lnpl lsp` once per exit-code path, because the CLI wiring
(binary stdio, stdout reserved for frames) only exists in a real process.
"""
import builtins
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

import lnpl
from lnpl.diagnostics import ExtensionDiagnosticsError
from lnpl.lower import VERB_LEXICON
from lnpl.lsp import (VERB_RFC, LspServer, _heading_slug, _line_span,
                      _module_name, _utf16_len)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RFCS = os.path.join(REPO, "rfcs")


def frame(message):
    body = message if isinstance(message, bytes) else json.dumps(message).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def read_frames(data):
    """Parse every Content-Length frame in `data`; fail on trailing garbage."""
    frames = []
    pos = 0
    while pos < len(data):
        end = data.index(b"\r\n\r\n", pos)
        headers = data[pos:end].decode("ascii").split("\r\n")
        length = None
        for header in headers:
            name, value = header.split(":", 1)
            if name.strip().lower() == "content-length":
                length = int(value.strip())
        if length is None:
            raise AssertionError("frame without Content-Length: %r" % headers)
        start = end + 4
        body = data[start:start + length]
        if len(body) != length:
            raise AssertionError("truncated frame body")
        frames.append(json.loads(body.decode("utf-8")))
        pos = start + length
    return frames


def converse(*messages, setup=None):
    out = io.BytesIO()
    # dicts are framed here; bytes are written as-is (pre-framed via frame(b"...") or deliberately raw)
    server = LspServer(io.BytesIO(b"".join(m if isinstance(m, bytes) else frame(m) for m in messages)), out)
    if setup is not None:
        setup(server)
    rc = server.run()
    return rc, read_frames(out.getvalue())


INIT_LITERAL = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {"textDocument": {"codeAction": {"codeActionLiteralSupport": {"codeActionKind": {"valueSet": ["quickfix"]}}}}}}}
INIT_PLAIN = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "initialized", "params": {}}
SHUTDOWN = {"jsonrpc": "2.0", "id": 99, "method": "shutdown"}
EXIT = {"jsonrpc": "2.0", "method": "exit"}

CLEAN = "entity Note\n    field\n        id UUID\n\nworkflow Save\n    create note\n"
PERSIST = "entity Note\n    field\n        id UUID\n\nworkflow Save\n    persist note\n"
NO_MATCH = "workflow Save\n    return note\n"
TWO_UNKNOWN = "entity Note\n    field\n        id UUID\n\nworkflow Save\n    persist note\n    retrun note\n"
UNKNOWN_ENTITY ="entity Note\n    field\n        id UUID\n\nworkflow Save\n    create nothing\n"
INFO = "entity Note\n    field\n        id UUID\n\nservice S\n    performance\n        prefetch\n\nworkflow Save\n    create note\n"
NOTE_CAP = "workflow Save\n" + "".join('    note "n%d"\n' % i for i in range(17))
PARSE_FAIL = "entity\n"
LEX_FAIL = "workflow X\n\tcreate a\n"
FF_SPLIT = "entity Note\n    field\n        id UUID\n\x0c\nworkflow Save\n    persist note\n"
NEL = "entity Note\x85    field\n        id UUID\n\nworkflow Save\n    persist note\n"
URI = "file:///x/save.lnpl"


def did_open(text, version=1, uri=URI):
    return {"jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "lnpl",
                                        "version": version, "text": text}}}


def published(frames):
    return [f["params"] for f in frames if f.get("method") == "textDocument/publishDiagnostics"]


def rng(l0, c0, l1, c1):
    return {"start": {"line": l0, "character": c0}, "end": {"line": l1, "character": c1}}


def by_id(frames, id_):
    matches = [f for f in frames if f.get("id") == id_ and "method" not in f]
    if len(matches) != 1:
        raise AssertionError("expected one response with id %r, got %r" % (id_, frames))
    return matches[0]


def code_action(uri, range_, diagnostics, only=None):
    context = {"diagnostics": diagnostics}
    if only is not None:
        context["only"] = only
    params = {"textDocument": {"uri": uri}, "context": context}
    if range_ is not None:
        params["range"] = range_
    return {"jsonrpc": "2.0", "id": 5, "method": "textDocument/codeAction", "params": params}


def hover(line, character, uri=URI, id_=7):
    return {"jsonrpc": "2.0", "id": id_, "method": "textDocument/hover",
            "params": {"textDocument": {"uri": uri},
                       "position": {"line": line, "character": character}}}


class BaseProtocolTest(unittest.TestCase):
    def test_initialize_advertises_capabilities_with_literal_support(self):
        rc, frames = converse(INIT_LITERAL)
        result = by_id(frames, 1)["result"]
        self.assertEqual(result["capabilities"], {
            "positionEncoding": "utf-16",
            "textDocumentSync": {"openClose": True, "change": 1},
            "hoverProvider": True,
            "codeActionProvider": {"codeActionKinds": ["quickfix"]},
        })
        self.assertEqual(result["serverInfo"], {"name": "lnpl", "version": lnpl.__version__})

    def test_initialize_without_literal_support_advertises_true(self):
        rc, frames = converse(INIT_PLAIN)
        self.assertIs(by_id(frames, 1)["result"]["capabilities"]["codeActionProvider"], True)

    def test_request_before_initialize_is_server_not_initialized(self):
        rc, frames = converse(hover(0, 0, id_=3))
        self.assertEqual(by_id(frames, 3)["error"]["code"], -32002)

    def test_second_initialize_is_invalid_request(self):
        rc, frames = converse(INIT_PLAIN, dict(INIT_PLAIN, id=2))
        self.assertIn("result", by_id(frames, 1))
        self.assertEqual(by_id(frames, 2)["error"]["code"], -32600)

    def test_shutdown_then_exit_returns_zero(self):
        rc, frames = converse(INIT_PLAIN, INITIALIZED, SHUTDOWN, EXIT)
        response = by_id(frames, 99)
        self.assertIn("result", response)
        self.assertIsNone(response["result"])
        self.assertEqual(rc, 0)

    def test_exit_without_shutdown_returns_one(self):
        rc, frames = converse(INIT_PLAIN, EXIT)
        self.assertEqual(rc, 1)

    def test_eof_without_shutdown_returns_one(self):
        # boundary: no messages at all
        rc, frames = converse()
        self.assertEqual(rc, 1)
        self.assertEqual(frames, [])

    def test_request_after_shutdown_is_invalid_request(self):
        rc, frames = converse(INIT_PLAIN, SHUTDOWN, hover(0, 0, id_=4))
        self.assertEqual(by_id(frames, 4)["error"]["code"], -32600)

    def test_malformed_json_is_parse_error_and_server_continues(self):
        rc, frames = converse(frame(b"{nope"), INIT_PLAIN)
        self.assertEqual(frames[0]["error"]["code"], -32700)
        self.assertIsNone(frames[0]["id"])
        self.assertIn("result", frames[1])

    def test_non_utf8_body_is_parse_error(self):
        rc, frames = converse(frame(b"\xff\xfe"))
        self.assertEqual(frames[0]["error"]["code"], -32700)

    def test_deeply_nested_json_is_parse_error_and_server_continues(self):
        # CPython's json scanner raises RecursionError, not ValueError, here
        rc, frames = converse(frame(b"[" * 100000), INIT_PLAIN)
        self.assertEqual(frames[0]["error"]["code"], -32700)
        self.assertIsNone(frames[0]["id"])
        self.assertIn("result", by_id(frames, 1))

    def test_lone_surrogate_method_is_method_not_found_and_server_continues(self):
        # valid JSON whose string has no UTF-8 form: the reply echoes it, escaped
        rc, frames = converse(INIT_PLAIN, frame(b'{"jsonrpc": "2.0", "id": 2, "method": "\\ud800"}'),
                              {"jsonrpc": "2.0", "id": 3, "method": "foo/bar"})
        self.assertEqual(by_id(frames, 2)["error"], {"code": -32601, "message": "Method not found: \ud800"})
        self.assertEqual(by_id(frames, 3)["error"]["code"], -32601)

    def test_lone_surrogate_id_is_echoed(self):
        rc, frames = converse(INIT_PLAIN, frame(b'{"jsonrpc": "2.0", "id": "\\ud800", "method": "foo/bar"}'))
        self.assertEqual(by_id(frames, "\ud800")["error"]["code"], -32601)

    def test_content_length_beyond_int_digit_limit_ends_the_session(self):
        # error case: int() refuses more than 4300 digits
        rc, frames = converse(b"Content-Length: " + b"9" * 5000 + b"\r\n\r\n{}")
        self.assertEqual(rc, 1)
        self.assertEqual(frames, [])

    def test_content_length_beyond_index_size_ends_the_session(self):
        # boundary: a length no stream read() can take as an index
        rc, frames = converse(b"Content-Length: 99999999999999999999999999999\r\n\r\n{}")
        self.assertEqual(rc, 1)
        self.assertEqual(frames, [])

    def test_huge_content_length_on_a_buffered_stream_ends_the_session(self):
        # error case: BufferedReader.read(n) preallocates n bytes, so one read(10**15) is a MemoryError
        stdin = io.BufferedReader(io.BytesIO(frame(INIT_PLAIN) + b"Content-Length: 1000000000000000\r\n\r\n{}"))
        out = io.BytesIO()
        rc = LspServer(stdin, out).run()
        self.assertEqual(rc, 1)
        self.assertIn("result", by_id(read_frames(out.getvalue()), 1))

    def test_non_object_message_is_invalid_request(self):
        rc, frames = converse(frame(b"42"))
        self.assertEqual(frames[0]["error"]["code"], -32600)
        self.assertIsNone(frames[0]["id"])

    def test_unknown_request_is_method_not_found(self):
        rc, frames = converse(INIT_PLAIN, {"jsonrpc": "2.0", "id": 3, "method": "foo/bar"})
        self.assertEqual(by_id(frames, 3)["error"]["code"], -32601)

    def test_dollar_notification_gets_no_reply(self):
        rc, frames = converse(INIT_PLAIN, {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 1}})
        self.assertEqual(len(frames), 1)  # the initialize response only
        self.assertEqual(frames[0]["id"], 1)

    def test_params_not_an_object_is_invalid_params(self):
        rc, frames = converse(dict(INIT_PLAIN, params=[1]))
        self.assertEqual(by_id(frames, 1)["error"]["code"], -32602)

    def test_handler_exception_is_internal_error_and_loop_continues(self):
        def boom(params):
            raise RuntimeError("x")

        def setup(server):
            server.requests["test/boom"] = boom

        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc, frames = converse(INIT_PLAIN, {"jsonrpc": "2.0", "id": 2, "method": "test/boom"},
                                  {"jsonrpc": "2.0", "id": 3, "method": "foo/bar"}, setup=setup)
        self.assertEqual(by_id(frames, 2)["error"], {"code": -32603, "message": "RuntimeError: x"})
        self.assertEqual(by_id(frames, 3)["error"]["code"], -32601)
        self.assertIn("RuntimeError", err.getvalue())

    def test_missing_content_length_ends_the_session(self):
        rc, frames = converse(b"Content-Type: x\r\n\r\n{}")
        self.assertEqual(rc, 1)
        self.assertEqual(frames, [])

    def test_short_body_ends_the_session(self):
        # boundary: the header promises more bytes than arrive before EOF
        rc, frames = converse(b"Content-Length: 50\r\n\r\n" + json.dumps(INIT_PLAIN).encode("utf-8")[:20])
        self.assertEqual(rc, 1)
        self.assertEqual(frames, [])


class DiagnosticsTest(unittest.TestCase):
    def test_unknown_verb_is_published_with_range_severity_and_data(self):
        rc, frames = converse(INIT_PLAIN, did_open(PERSIST))
        pubs = published(frames)
        self.assertEqual(len(pubs), 1)
        self.assertEqual(pubs[0]["uri"], URI)
        self.assertEqual(pubs[0]["version"], 1)
        self.assertEqual(len(pubs[0]["diagnostics"]), 1)
        diag = pubs[0]["diagnostics"][0]
        self.assertEqual(diag["range"], rng(5, 4, 5, 11))
        self.assertEqual(diag["severity"], 2)
        self.assertEqual(diag["code"], "unknown-verb")
        self.assertEqual(diag["source"], "lnpl")
        self.assertEqual(diag["data"], {"subject": "persist", "suggestion": "create", "line": 6})

    def test_clean_source_publishes_empty_list(self):
        rc, frames = converse(INIT_PLAIN, did_open(CLEAN))
        self.assertEqual(published(frames)[0]["diagnostics"], [])

    def test_empty_document_publishes_empty_list(self):
        # boundary: an empty buffer compiles to an empty module
        rc, frames = converse(INIT_PLAIN, did_open(""))
        self.assertEqual(published(frames)[0]["diagnostics"], [])

    def test_info_grade_maps_to_severity_3(self):
        rc, frames = converse(INIT_PLAIN, did_open(INFO))
        diags = published(frames)[0]["diagnostics"]
        self.assertTrue(diags)
        self.assertEqual({d["severity"] for d in diags}, {3})

    def test_diagnostic_without_line_gets_zero_range(self):
        rc, frames = converse(INIT_PLAIN, did_open(NOTE_CAP))
        diags = published(frames)[0]["diagnostics"]
        self.assertTrue(diags)
        lineless = [d for d in diags if d["data"]["line"] is None]
        self.assertTrue(lineless)
        for d in lineless:
            self.assertEqual(d["range"], rng(0, 0, 0, 0))

    def test_parse_error_is_one_compile_error_on_its_line(self):
        rc, frames = converse(INIT_PLAIN, did_open(PARSE_FAIL))
        diags = published(frames)[0]["diagnostics"]
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0]["code"], "compile-error")
        self.assertEqual(diags[0]["severity"], 1)
        self.assertEqual(diags[0]["range"], rng(0, 0, 0, 6))

    def test_lex_error_points_at_the_tab_line(self):
        rc, frames = converse(INIT_PLAIN, did_open(LEX_FAIL))
        diags = published(frames)[0]["diagnostics"]
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0]["code"], "compile-error")
        self.assertEqual(diags[0]["range"]["start"]["line"], 1)
        self.assertEqual(diags[0]["range"]["end"]["line"], 1)

    def test_server_answers_after_a_compile_error(self):
        rc, frames = converse(INIT_PLAIN, did_open(PARSE_FAIL),
                              {"jsonrpc": "2.0", "id": 3, "method": "foo/bar"})
        self.assertEqual(by_id(frames, 3)["error"]["code"], -32601)

    def test_did_change_replaces_text_and_republishes(self):
        change = {"jsonrpc": "2.0", "method": "textDocument/didChange",
                  "params": {"textDocument": {"uri": URI, "version": 2}, "contentChanges": [{"text": CLEAN}]}}
        rc, frames = converse(INIT_PLAIN, did_open(PERSIST), change)
        pubs = published(frames)
        self.assertEqual(len(pubs), 2)
        self.assertEqual(len(pubs[0]["diagnostics"]), 1)
        self.assertEqual(pubs[1]["diagnostics"], [])
        self.assertEqual(pubs[1]["version"], 2)

    def test_did_change_without_changes_is_ignored(self):
        # error case: an empty contentChanges list publishes nothing new
        change = {"jsonrpc": "2.0", "method": "textDocument/didChange",
                  "params": {"textDocument": {"uri": URI, "version": 2}, "contentChanges": []}}
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc, frames = converse(INIT_PLAIN, did_open(PERSIST), change)
        self.assertEqual(len(published(frames)), 1)
        self.assertIn("didChange", err.getvalue())

    def test_did_close_clears_diagnostics(self):
        close = {"jsonrpc": "2.0", "method": "textDocument/didClose", "params": {"textDocument": {"uri": URI}}}
        rc, frames = converse(INIT_PLAIN, did_open(PERSIST), close)
        pubs = published(frames)
        self.assertEqual(len(pubs), 2)
        self.assertEqual(pubs[1], {"uri": URI, "diagnostics": []})

    def test_form_feed_line_break_maps_to_lsp_lines(self):
        rc, frames = converse(INIT_PLAIN, did_open(FF_SPLIT))
        self.assertEqual(published(frames)[0]["diagnostics"][0]["range"], rng(5, 4, 5, 11))

    def test_nel_maps_to_lsp_lines(self):
        rc, frames = converse(INIT_PLAIN, did_open(NEL))
        self.assertEqual(published(frames)[0]["diagnostics"][0]["range"], rng(4, 4, 4, 11))

    def test_crlf_source_matches_lf_ranges(self):
        rc, frames = converse(INIT_PLAIN, did_open(PERSIST.replace("\n", "\r\n")))
        self.assertEqual(published(frames)[0]["diagnostics"][0]["range"], rng(5, 4, 5, 11))

    def test_non_bmp_prefix_counts_utf16_units(self):
        self.assertEqual(_line_span("ab\n\U0001F600 persist x\n", 2, "persist"), rng(1, 3, 1, 10))
        self.assertEqual(_utf16_len("\U0001F600"), 2)

    def test_extension_records_are_published(self):
        record = {"code": "acme/x", "severity": "error", "where": "line 6", "subject": "persist",
                  "message": "m", "line": 6, "hint": None}
        with mock.patch("lnpl.lsp.extension_diagnostic_records", return_value=[record]):
            rc, frames = converse(INIT_PLAIN, did_open(PERSIST))
        diags = published(frames)[0]["diagnostics"]
        self.assertEqual(len(diags), 2)
        self.assertEqual(diags[1]["code"], "acme/x")
        self.assertEqual(diags[1]["severity"], 1)
        self.assertEqual(diags[1]["range"], rng(5, 4, 5, 11))

    def test_extension_registry_error_is_a_compile_error(self):
        with mock.patch("lnpl.lsp.extension_diagnostic_records", side_effect=ExtensionDiagnosticsError("bad")):
            rc, frames = converse(INIT_PLAIN, did_open(CLEAN))
        diags = published(frames)[0]["diagnostics"]
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0]["code"], "compile-error")
        self.assertEqual(diags[0]["message"], "extension diagnostics: bad")

    def test_module_name_from_uri(self):
        self.assertEqual(_module_name("file:///a/b/Save%20It.lnpl"), "Save It")
        self.assertEqual(_module_name("untitled:"), "lsp")


class QuickFixTest(unittest.TestCase):
    def _published_diag(self, text=PERSIST):
        rc, frames = converse(INIT_LITERAL, did_open(text))
        return published(frames)[0]["diagnostics"][0]

    def test_quick_fix_replaces_the_verb(self):
        diag = self._published_diag()
        rc, frames = converse(INIT_LITERAL, did_open(PERSIST), code_action(URI, diag["range"], [diag]))
        actions = by_id(frames, 5)["result"]
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["kind"], "quickfix")
        self.assertIs(action["isPreferred"], True)
        self.assertEqual(action["title"], "Replace 'persist' with 'create'")
        self.assertEqual(action["diagnostics"], [diag])
        self.assertEqual(action["edit"]["changes"][URI], [{"range": rng(5, 4, 5, 11), "newText": "create"}])

    def test_no_suggestion_gives_no_action(self):
        rc, frames = converse(INIT_LITERAL, did_open(NO_MATCH))
        diags = published(frames)[0]["diagnostics"]
        unknown = [d for d in diags if d["code"] == "unknown-verb"]
        self.assertEqual(len(unknown), 1)
        self.assertIsNone(unknown[0]["data"]["suggestion"])
        rc, frames = converse(INIT_LITERAL, did_open(NO_MATCH), code_action(URI, unknown[0]["range"], unknown))
        self.assertEqual(by_id(frames, 5)["result"], [])

    def test_other_diagnostic_with_a_suggestion_gives_no_action(self):
        # unknown-entity also carries a did-you-mean suggestion; the Quick Fix is unknown-verb only
        rc, frames = converse(INIT_LITERAL, did_open(UNKNOWN_ENTITY))
        diags = published(frames)[0]["diagnostics"]
        entity = [d for d in diags if d["code"] == "unknown-entity"]
        self.assertEqual(len(entity), 1)
        self.assertEqual(entity[0]["data"]["suggestion"], "note")
        self.assertNotIn("unknown-verb", [d["code"] for d in diags])
        rc, frames = converse(INIT_LITERAL, did_open(UNKNOWN_ENTITY), code_action(URI, entity[0]["range"], entity))
        self.assertEqual(by_id(frames, 5)["result"], [])
        rc, frames = converse(INIT_LITERAL, did_open(UNKNOWN_ENTITY), code_action(URI, entity[0]["range"], []))
        self.assertEqual(by_id(frames, 5)["result"], [])

    def test_empty_context_uses_published_diagnostics_at_cursor(self):
        rc, frames = converse(INIT_LITERAL, did_open(PERSIST), code_action(URI, rng(5, 6, 5, 6), []))
        actions = by_id(frames, 5)["result"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["edit"]["changes"][URI][0]["newText"], "create")

    def test_empty_context_away_from_the_diagnostic_gives_no_action(self):
        # boundary: a cursor on line 0 does not intersect the line-5 diagnostic
        rc, frames = converse(INIT_LITERAL, did_open(PERSIST), code_action(URI, rng(0, 0, 0, 0), []))
        self.assertEqual(by_id(frames, 5)["result"], [])

    def test_only_without_quickfix_gives_no_action(self):
        diag = self._published_diag()
        rc, frames = converse(INIT_LITERAL, did_open(PERSIST),
                              code_action(URI, diag["range"], [diag], only=["refactor"]))
        self.assertEqual(by_id(frames, 5)["result"], [])

    def test_missing_data_falls_back_to_published(self):
        diag = self._published_diag()
        del diag["data"]
        rc, frames = converse(INIT_LITERAL, did_open(PERSIST), code_action(URI, diag["range"], [diag]))
        actions = by_id(frames, 5)["result"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["title"], "Replace 'persist' with 'create'")

    def test_missing_data_falls_back_to_the_diagnostic_at_the_same_range(self):
        # two unknown-verb diagnostics; only the first has a suggestion. With `data`
        # stripped, the fallback must pick the stored diagnostic at the same range.
        rc, frames = converse(INIT_LITERAL, did_open(TWO_UNKNOWN))
        diags = [d for d in published(frames)[0]["diagnostics"] if d["code"] == "unknown-verb"]
        self.assertEqual([d["data"]["suggestion"] for d in diags], ["create", None])
        first, second = diags
        del first["data"]
        del second["data"]
        rc, frames = converse(INIT_LITERAL, did_open(TWO_UNKNOWN), code_action(URI, second["range"], [second]))
        self.assertEqual(by_id(frames, 5)["result"], [])
        rc, frames = converse(INIT_LITERAL, did_open(TWO_UNKNOWN), code_action(URI, first["range"], [first]))
        actions = by_id(frames, 5)["result"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["edit"]["changes"][URI], [{"range": rng(5, 4, 5, 11), "newText": "create"}])

    def test_unknown_uri_gives_no_action(self):
        diag = self._published_diag()
        rc, frames = converse(INIT_LITERAL, did_open(PERSIST),
                              code_action("file:///other.lnpl", diag["range"], [diag]))
        self.assertEqual(by_id(frames, 5)["result"], [])

    def test_client_without_literal_support_gets_no_action(self):
        diag = self._published_diag()
        rc, frames = converse(INIT_PLAIN, did_open(PERSIST), code_action(URI, diag["range"], [diag]))
        self.assertEqual(by_id(frames, 5)["result"], [])

    def test_code_action_without_range_is_invalid_params(self):
        rc, frames = converse(INIT_LITERAL, did_open(PERSIST), code_action(URI, None, []))
        self.assertEqual(by_id(frames, 5)["error"]["code"], -32602)

    def test_server_never_writes_files(self):
        writes = []
        real_open = builtins.open

        def recording_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                writes.append((file, mode))
            return real_open(file, mode, *args, **kwargs)

        diag = self._published_diag()
        with mock.patch("builtins.open", recording_open):
            rc, frames = converse(INIT_LITERAL, did_open(PERSIST), code_action(URI, diag["range"], [diag]))
        self.assertEqual(len(by_id(frames, 5)["result"]), 1)
        self.assertEqual(writes, [])


class HoverTest(unittest.TestCase):
    def test_table_covers_exactly_the_verb_lexicon(self):
        self.assertEqual(set(VERB_RFC), set(VERB_LEXICON))

    def test_every_heading_exists_in_an_accepted_rfc(self):
        for verb, (name, heading) in VERB_RFC.items():
            path = os.path.join(RFCS, name)
            self.assertTrue(os.path.isfile(path), "%s: %s missing" % (verb, name))
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().split("\n")
            self.assertIn(heading, lines, "%s: heading not in %s" % (verb, name))
            status = lines.index("## Status")
            first = next(line for line in lines[status + 1:] if line.strip())
            self.assertIn("Accepted", first, "%s: %s is not Accepted" % (verb, name))

    def test_heading_slug_matches_github_anchors(self):
        cases = {
            "부록 A: Lowering 매핑": "부록-a-lowering-매핑",
            "Workflow body & control": "workflow-body--control",
            "3. 입력 경계 — `validate`와 `null`": "3-입력-경계--validate와-null",
            "D2. `authorize` 동사의 (a)/(b) 판단 기준": "d2-authorize-동사의-ab-판단-기준",
            "RFC-0051: `set`·가드의 Money 산술 — 같은 통화 부분집합": "rfc-0051-set가드의-money-산술--같은-통화-부분집합",
            "1. 문법 — RFC-0027 §2 표기 재사용, `create`/`insert`로 확장 (D1)": "1-문법--rfc-0027-2-표기-재사용-createinsert로-확장-d1",
            "1. `list` 표면 문법 — RFC-0025 §1 갱신 (치환 후 최종 텍스트) (D1)": "1-list-표면-문법--rfc-0025-1-갱신-치환-후-최종-텍스트-d1",
        }
        for text, slug in cases.items():
            self.assertEqual(_heading_slug(text), slug)

    def test_hover_on_a_step_verb_links_its_rfc(self):
        rc, frames = converse(INIT_PLAIN, did_open(CLEAN), hover(5, 6))
        result = by_id(frames, 7)["result"]
        self.assertEqual(result["contents"]["kind"], "markdown")
        value = result["contents"]["value"]
        self.assertIn("RepositoryCall", value)
        self.assertIn("(operation=create)", value)
        self.assertIn("https://github.com/choiyounggi/linkly/blob/main/rfcs/"
                      "0030-create-result-binding-and-payload-seed.md#rfc-0030-create-결과-바인딩과-payload-시드", value)
        self.assertEqual(result["range"], rng(5, 4, 5, 10))

    def test_hover_on_the_object_is_null(self):
        rc, frames = converse(INIT_PLAIN, did_open(CLEAN), hover(5, 11))
        self.assertIsNone(by_id(frames, 7)["result"])

    def test_hover_at_token_end_is_null(self):
        # boundary: character 10 is one past `create`
        rc, frames = converse(INIT_PLAIN, did_open(CLEAN), hover(5, 10))
        self.assertIsNone(by_id(frames, 7)["result"])

    def test_hover_on_unknown_verb_is_null(self):
        rc, frames = converse(INIT_PLAIN, did_open(PERSIST), hover(5, 6))
        self.assertIsNone(by_id(frames, 7)["result"])

    def test_hover_on_performance_cache_is_null(self):
        rc, frames = converse(INIT_PLAIN, did_open("service S\n    performance\n        cache 5m\n"), hover(2, 9))
        self.assertIsNone(by_id(frames, 7)["result"])

    def test_hover_on_spec_expectation_is_null(self):
        with open(os.path.join(REPO, "examples", "login.lnpl"), encoding="utf-8") as fh:
            text = fh.read()
        lines = text.split("\n")
        expect_line = lines.index("            cache written")
        step_line = lines.index("    cache user")
        rc, frames = converse(INIT_PLAIN, did_open(text, uri="file:///x/login.lnpl"),
                              hover(expect_line, 13, uri="file:///x/login.lnpl", id_=7),
                              hover(step_line, 5, uri="file:///x/login.lnpl", id_=8))
        self.assertIsNone(by_id(frames, 7)["result"])
        self.assertIsNotNone(by_id(frames, 8)["result"])
        self.assertIn("cache", by_id(frames, 8)["result"]["contents"]["value"])

    def test_hover_line_out_of_range_is_null(self):
        rc, frames = converse(INIT_PLAIN, did_open(CLEAN), hover(99, 0))
        self.assertIsNone(by_id(frames, 7)["result"])

    def test_hover_without_position_is_invalid_params(self):
        request = {"jsonrpc": "2.0", "id": 7, "method": "textDocument/hover",
                   "params": {"textDocument": {"uri": URI}}}
        rc, frames = converse(INIT_PLAIN, did_open(CLEAN), request)
        self.assertEqual(by_id(frames, 7)["error"]["code"], -32602)

    def test_hover_on_unknown_uri_is_null(self):
        rc, frames = converse(INIT_PLAIN, did_open(CLEAN), hover(5, 6, uri="file:///other.lnpl"))
        self.assertIsNone(by_id(frames, 7)["result"])


def run_lsp(stdin_bytes, *extra):
    return subprocess.run([sys.executable, "-m", "lnpl", "lsp", *extra], input=stdin_bytes,
                          capture_output=True, timeout=30, cwd=REPO,
                          env=dict(os.environ, PYTHONPATH=os.path.join(REPO, "impl")))


class LspProcessTest(unittest.TestCase):
    def test_shutdown_then_exit_exits_zero_with_only_frames_on_stdout(self):
        proc = run_lsp(b"".join(frame(m) for m in (INIT_LITERAL, INITIALIZED, did_open(PERSIST), SHUTDOWN, EXIT)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        frames = read_frames(proc.stdout)
        pubs = published(frames)
        self.assertEqual(len(pubs), 1)
        self.assertEqual([d["code"] for d in pubs[0]["diagnostics"]], ["unknown-verb"])

    def test_exit_without_shutdown_exits_one(self):
        proc = run_lsp(frame(INIT_LITERAL) + frame(EXIT))
        self.assertEqual(proc.returncode, 1)

    def test_empty_stdin_exits_one(self):
        # boundary
        proc = run_lsp(b"")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, b"")

    def test_huge_content_length_exits_one_without_a_traceback(self):
        # error case: the real binary stdin is a BufferedReader
        proc = run_lsp(frame(INIT_PLAIN) + b"Content-Length: 1000000000000000\r\n\r\n{}")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stderr, b"")
        self.assertIn("result", by_id(read_frames(proc.stdout), 1))

    def test_unknown_option_is_rejected(self):
        # pins D18: the VS Code client must not append `--stdio`
        proc = run_lsp(b"", "--stdio")
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
