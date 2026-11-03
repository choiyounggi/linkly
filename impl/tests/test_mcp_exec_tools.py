"""The MCP execution tools (issue #250) and the transport rules in `handle()`.

`lnpl_run`, `lnpl_openapi` and `lnpl_generate` are driven through `serve()`
like every other tool. Their contract is parity with the CLI — the same
document `lnpl run --json` prints, the same bytes `lnpl openapi` prints and
`lnpl generate --out` writes — so each parity test compares against
`cli.main` on the same input instead of a hand-written expectation.

`lnpl_run` must stay on the fake backend and the virtual clock: the sandbox
test runs it with sockets and every write-mode `open` turned into tripwires,
after first proving the tripwires fire.

`handle(..., allow_paths=False)` is what the HTTP transport calls: every
argument that names a server-side file is refused before any tool runs, and
the census test fails when a new tool argument is not classified.
"""
import builtins
import contextlib
import io
import json
import os
import shutil
import socket
import tempfile
import unittest
from unittest import mock

from lnpl import cli, mcp_server
from lnpl.mcp_server import (FILESYSTEM_ARGUMENTS, PROTOCOL_VERSION,
                             SUPPORTED_PROTOCOL_VERSIONS, TOOLS, handle)
from tests.test_mcp_server import CLEAN, REPO, call, converse, payload_of

LOGIN = os.path.join(REPO, "examples", "login.lnpl")
CHECKOUT = os.path.join(REPO, "examples", "checkout.lnpl")
NO_WORKFLOW = "entity Note\n    field\n        id UUID\n"
UNKNOWN_CAP = os.path.join(REPO, "impl", "tests", "golden", "deploy", "unknown-cap.lnpl")
EIGHT = ["lnpl_compile", "lnpl_kb_route", "lnpl_spec", "lnpl_vocabulary",
         "lnpl_capabilities", "lnpl_run", "lnpl_openapi", "lnpl_generate"]


def cli_stdout(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        cli.main(argv)
    return out.getvalue()


def text_of(response):
    return response["result"]["content"][0]["text"]


class ScratchCase(unittest.TestCase):

    def scratch(self):
        base = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        d = tempfile.mkdtemp(dir=base)
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def chdir(self, path):
        old = os.getcwd()
        os.chdir(path)
        self.addCleanup(os.chdir, old)


class RunToolTest(unittest.TestCase):

    def test_run_on_a_file_returns_the_cli_json_document(self):
        res = call("lnpl_run", {"path": LOGIN})
        self.assertIs(res["result"]["isError"], False, text_of(res))
        payload = payload_of(res)
        self.assertEqual(set(payload), {"result", "trace", "diagnostics"})
        self.assertIsInstance(payload["diagnostics"], list)
        expected = json.loads(cli_stdout(["run", LOGIN, "--json"]))
        self.assertEqual(len(payload["diagnostics"]), len(expected["diagnostics"]))
        self.assertEqual(payload["result"], expected["result"])

    def test_clean_text_has_an_empty_diagnostics_list(self):
        payload = payload_of(call("lnpl_run", {"text": CLEAN}))
        self.assertEqual(payload["diagnostics"], [])

    def test_an_unknown_workflow_names_the_valid_ones(self):
        res = call("lnpl_run", {"path": LOGIN, "workflow": "wf.nope"})
        self.assertIs(res["result"]["isError"], True)
        self.assertIn("(valid: wf.login)", text_of(res))
        self.assertIn("wf.nope", text_of(res))
        self.assertNotIn("--workflow", text_of(res))

    def test_a_source_without_workflows_is_a_tool_error(self):
        res = call("lnpl_run", {"text": NO_WORKFLOW})
        self.assertIs(res["result"]["isError"], True)
        self.assertIn("no workflow to run", text_of(res))

    def test_argument_types_are_checked(self):
        for args, needle in (({"text": CLEAN, "payload": [1]}, "payload"),
                             ({"text": CLEAN, "no_row": "yes"}, "no_row"),
                             ({"text": CLEAN, "workflow": 3}, "workflow"),
                             ({"text": 7}, "must be strings"),
                             ({}, "`text`")):
            with self.subTest(args=args):
                res = call("lnpl_run", args)
                self.assertIs(res["result"]["isError"], True)
                self.assertIn(needle, text_of(res))

    def test_no_row_true_starts_from_an_empty_repository(self):
        res = call("lnpl_run", {"text": CLEAN, "no_row": True})
        self.assertIs(res["result"]["isError"], False, text_of(res))
        self.assertIn("diagnostics", payload_of(res))

    def test_the_schema_offers_no_backend_choice(self):
        schema = next(t for t in TOOLS if t["name"] == "lnpl_run")["inputSchema"]
        props = set(schema["properties"])
        self.assertEqual(props, {"text", "path", "module", "workflow", "payload", "no_row"})
        self.assertFalse({"backend", "network", "cache", "clock", "endpoint"} & props)


class RunToolSandboxTest(ScratchCase):

    def test_run_opens_no_socket_and_writes_no_file(self):
        scratch = self.scratch()
        real_open, real_os_open = builtins.open, os.open

        def guarded_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in ("w", "a", "x", "+")):
                raise AssertionError("write: %r" % (file,))
            return real_open(file, mode, *args, **kwargs)

        def guarded_os_open(path, flags, *args, **kwargs):
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND):
                raise AssertionError("write: %r" % (path,))
            return real_os_open(path, flags, *args, **kwargs)

        def boom(*_args, **_kwargs):
            raise AssertionError("network")

        self.chdir(scratch)
        with mock.patch.object(socket, "socket", boom), \
                mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(builtins, "open", guarded_open), \
                mock.patch.object(os, "open", guarded_os_open):
            # negative controls: the tripwires fire, reads still work
            with self.assertRaises(AssertionError):
                socket.socket()
            with self.assertRaises(AssertionError):
                open(os.path.join(scratch, "probe"), "w")
            with self.assertRaises(AssertionError):
                os.open(os.path.join(scratch, "probe"), os.O_WRONLY | os.O_CREAT)
            with open(LOGIN, encoding="utf-8") as fh:
                self.assertIn("workflow", fh.read())
            for args in ({"text": CLEAN}, {"path": LOGIN}):
                with self.subTest(args=args):
                    res = call("lnpl_run", args)
                    self.assertIs(res["result"]["isError"], False, text_of(res))
        self.assertEqual(os.listdir(scratch), [])


class OpenApiToolTest(ScratchCase):

    def test_path_output_is_byte_identical_to_the_cli(self):
        res = call("lnpl_openapi", {"path": LOGIN})
        self.assertIs(res["result"]["isError"], False, text_of(res))
        self.assertEqual(text_of(res), cli_stdout(["openapi", LOGIN]))

    def test_text_with_the_module_name_gives_the_same_bytes(self):
        with open(LOGIN, encoding="utf-8") as fh:
            source = fh.read()
        res = call("lnpl_openapi", {"text": source, "module": "login"})
        self.assertEqual(text_of(res), cli_stdout(["openapi", LOGIN]))

    def test_a_parse_error_is_a_tool_error(self):
        res = call("lnpl_openapi", {"text": "entity N\n    field\n        id UUID\n\n"
                                            "workflow S\n    if x\n"})
        self.assertIs(res["result"]["isError"], True)

    def test_neither_text_nor_path_is_a_tool_error(self):
        res = call("lnpl_openapi", {})
        self.assertIs(res["result"]["isError"], True)
        self.assertIn("`path`", text_of(res))

    def test_a_missing_path_is_a_tool_error(self):
        res = call("lnpl_openapi", {"path": os.path.join(self.scratch(), "no-such.lnpl")})
        self.assertIs(res["result"]["isError"], True)
        self.assertIn("no-such.lnpl", text_of(res))


class GenerateToolTest(ScratchCase):

    def generated(self, name, argv_set, options, source=LOGIN):
        out = self.scratch()
        argv = ["generate", name, source, "--out", out]
        for item in argv_set:
            argv += ["--set", item]
        cli_stdout(argv)
        res = call("lnpl_generate", {"generator": name, "path": source, "options": options})
        self.assertIs(res["result"]["isError"], False, text_of(res))
        return out, payload_of(res)

    def test_k8s_text_matches_the_written_file(self):
        out, payload = self.generated("k8s", ["image=ghcr.io/x/app:1"],
                                      {"image": "ghcr.io/x/app:1"})
        with open(os.path.join(out, "k8s.yaml"), encoding="utf-8") as fh:
            self.assertEqual(payload["files"]["k8s.yaml"], fh.read())
        self.assertEqual(payload["generator"], "k8s")
        self.assertEqual(payload["warnings"], [])

    def test_compose_text_matches_the_written_files(self):
        out, payload = self.generated("compose", [], {})
        self.assertEqual(sorted(payload["files"]), sorted(os.listdir(out)))
        for name, text in payload["files"].items():
            with self.subTest(file=name), open(os.path.join(out, name), encoding="utf-8") as fh:
                self.assertEqual(text, fh.read())

    def test_a_skipped_capability_warning_reaches_the_caller(self):
        res = call("lnpl_generate", {"generator": "compose", "path": UNKNOWN_CAP})
        payload = payload_of(res)
        self.assertEqual(len(payload["warnings"]), 1, payload["warnings"])
        self.assertIn("'foo'", payload["warnings"][0])

    def test_nothing_is_written(self):
        here = self.scratch()
        self.chdir(here)
        res = call("lnpl_generate", {"generator": "k8s", "path": LOGIN})
        self.assertIs(res["result"]["isError"], False, text_of(res))
        self.assertEqual(os.listdir(here), [])

    def test_bad_arguments_are_tool_errors(self):
        for args, needle in (
                ({"generator": "helm", "path": LOGIN}, "compose, k8s"),
                ({"path": LOGIN}, "compose, k8s"),
                ({"generator": "k8s", "path": LOGIN, "options": {"replicas": "zero"}}, "replicas"),
                ({"generator": "k8s", "path": LOGIN, "options": {"replicas": 3}}, "options.replicas"),
                ({"generator": "k8s", "path": LOGIN, "options": []}, "options"),
                ({"generator": "k8s", "path": LOGIN, "options": {"bogus": "1"}}, "bogus")):
            with self.subTest(args=args):
                res = call("lnpl_generate", args)
                self.assertIs(res["result"]["isError"], True)
                self.assertIn(needle, text_of(res))

    def test_empty_options_object_equals_absent_options(self):
        a = payload_of(call("lnpl_generate", {"generator": "k8s", "path": LOGIN}))
        b = payload_of(call("lnpl_generate", {"generator": "k8s", "path": LOGIN, "options": {}}))
        self.assertEqual(a, b)


class ToolSurfaceTest(unittest.TestCase):

    def test_eight_tools_in_order_and_no_write_tools(self):
        names = [t["name"] for t in mcp_server.TOOLS]
        self.assertEqual(names, EIGHT)
        self.assertEqual(set(mcp_server.HANDLERS), set(EIGHT))
        self.assertEqual({"serve", "build", "relay", "diff"} & set(names), set())
        self.assertFalse(any(n.endswith(("_serve", "_build", "_relay")) for n in names))


def tools_call(name, args=None, mid=5):
    params = {"name": name}
    if args is not None:
        params["arguments"] = args
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": params}


class VersionNegotiationTest(unittest.TestCase):

    def negotiated(self, requested):
        return converse({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": requested}})[0]["result"]["protocolVersion"]

    def test_unsupported_versions_get_our_own(self):
        for requested in ("1999-01-01", "2026-07-28", ""):
            with self.subTest(requested=requested):
                self.assertEqual(self.negotiated(requested), PROTOCOL_VERSION)

    def test_supported_versions_are_echoed(self):
        for requested in ("2025-11-25", "2024-11-05", "2025-03-26"):
            with self.subTest(requested=requested):
                self.assertEqual(self.negotiated(requested), requested)
        self.assertIn(PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS)
        self.assertIn("2025-06-18", SUPPORTED_PROTOCOL_VERSIONS)


class PathRefusalTest(unittest.TestCase):

    def test_path_is_refused_when_paths_are_disallowed(self):
        res = handle(tools_call("lnpl_compile", {"path": "/etc/hosts"}), allow_paths=False)
        self.assertIs(res["result"]["isError"], True)
        self.assertIn("argument `path` is disabled", text_of(res))

    def test_root_is_refused_when_paths_are_disallowed(self):
        res = handle(tools_call("lnpl_kb_route", {"task": "x", "root": "/"}), allow_paths=False)
        self.assertIs(res["result"]["isError"], True)
        self.assertIn("`root`", text_of(res))

    def test_the_refusal_happens_before_the_handler_runs(self):
        with mock.patch.dict(mcp_server.HANDLERS,
                             {"lnpl_compile": mock.Mock(side_effect=AssertionError("ran"))}):
            res = handle(tools_call("lnpl_compile", {"path": "/etc/hosts"}), allow_paths=False)
        self.assertIn("is disabled", text_of(res))

    def test_text_is_still_allowed(self):
        res = handle(tools_call("lnpl_run", {"text": CLEAN}), allow_paths=False)
        self.assertIs(res["result"]["isError"], False, text_of(res))

    def test_the_default_still_allows_paths(self):
        res = handle(tools_call("lnpl_compile", {"path": CHECKOUT}))
        self.assertIs(res["result"]["isError"], False, text_of(res))

    def test_absent_arguments_are_fine(self):
        res = handle(tools_call("lnpl_vocabulary"), allow_paths=False)
        self.assertIs(res["result"]["isError"], False)

    def test_allow_paths_is_keyword_only(self):
        with self.assertRaises(TypeError):
            handle(tools_call("lnpl_vocabulary"), False)


class ArgumentCensusTest(unittest.TestCase):

    NOT_FILESYSTEM = {"text", "module", "task", "workflow", "payload", "no_row",
                      "generator", "options"}

    def test_every_tool_argument_is_classified(self):
        known = set(FILESYSTEM_ARGUMENTS) | self.NOT_FILESYSTEM
        for tool in TOOLS:
            for arg in tool["inputSchema"].get("properties", {}):
                with self.subTest(tool=tool["name"], arg=arg):
                    self.assertIn(arg, known)
        self.assertEqual(set(FILESYSTEM_ARGUMENTS), {"path", "root"})


if __name__ == "__main__":
    unittest.main()
