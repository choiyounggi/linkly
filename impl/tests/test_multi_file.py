"""다중 파일 컴파일 단위 (issue #77, RFC-0031).

`load_sources`(impl/lnpl/lower.py)가 단일 정본 로더이고, CLI 전 서브커맨드·
진단 훅·MCP `lnpl_compile`이 그 함수만 소비한다는 것이 이 파일이 지키는 계약
전부다. 분할 픽스처는 `impl/tests/lnpl_fixtures/linkhub/`
(`01_entity.lnpl` + `02_workflow.lnpl`) — `examples/linkhub.lnpl`을 파일명
정렬로 병합했을 때 선언 순서가 원본과 정확히 같도록 나눈 것.

각 노드의 `line`(RFC-0024)은 그 노드가 속한 **파일 안에서의** 줄이라, 분할
전/후 비교에서는 항상 다르다(RFC-0031 §IR 동일성) — 그래서 병합 정확성은
`line`을 뺀 문서 비교로 판정한다.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest

from lnpl import cli
from lnpl.lower import LoaderError, load_sources, lower
from lnpl.parser import parse
from lnpl.mcp_server import serve as mcp_serve

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINKHUB_SINGLE = os.path.join(REPO, "examples", "linkhub.lnpl")
LINKHUB_GOLDEN = os.path.join(REPO, "examples", "linkhub.lir.json")
LINKHUB_SPLIT_DIR = os.path.join(REPO, "impl", "tests", "lnpl_fixtures", "linkhub")
LINKHUB_ENTITY_FILE = os.path.join(LINKHUB_SPLIT_DIR, "01_entity.lnpl")
LINKHUB_WORKFLOW_FILE = os.path.join(LINKHUB_SPLIT_DIR, "02_workflow.lnpl")
HOOK = os.path.join(REPO, "plugins", "lnpl", "hooks", "lnpl-diagnostics.sh")


def _stripped(document):
    """document, 각 노드에서 `line`을 뺀 사본 — 병합 정확성 비교용."""
    return {**document,
            "nodes": [{k: v for k, v in n.items() if k != "line"}
                      for n in document["nodes"]]}


def _ir_hash(document):
    """RFC-0031 §IR 동일성: `line`을 뺀 문서의 정렬-키 JSON sha256."""
    import hashlib
    blob = json.dumps(_stripped(document), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run_cli(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


class TestSplitFixtureIRHash(unittest.TestCase):
    """(정상) 2파일 분할 = 단일 파일 IR 해시 동일. (경계) 디렉터리 병합과
    이미 정렬된 명시적 파일 나열이 완전히 일치. (경계) 파일 1개는 커밋된
    골든과 바이트 동일 — RFC 이전 동작 보존(D7)."""

    def test_directory_split_matches_single_file_ir_hash(self):
        single = load_sources([LINKHUB_SINGLE])
        split = load_sources([LINKHUB_SPLIT_DIR])
        doc_single = lower(single, "linkhub").to_document()
        doc_split = lower(split, "linkhub").to_document()

        self.assertEqual(_stripped(doc_single), _stripped(doc_split))
        self.assertEqual(_ir_hash(doc_single), _ir_hash(doc_split))
        # `line`은 실제로 다르다 (파일 경계 밖으로 흐르지 않는다, RFC-0031 D4) —
        # 그 사실 자체를 확인해, 위 hash 비교가 우연히 전체 동일이라 통과한
        # 것이 아님을 증명한다.
        workflow_node = next(n for n in doc_split["nodes"]
                             if n["id"] == "wf.save.bookmark")
        self.assertEqual(workflow_node["line"], 4)  # 02_workflow.lnpl의 4번째 줄
        single_workflow_node = next(n for n in doc_single["nodes"]
                                    if n["id"] == "wf.save.bookmark")
        self.assertNotEqual(workflow_node["line"], single_workflow_node["line"])

    def test_directory_mode_agrees_with_the_same_files_given_explicitly_in_order(self):
        via_dir = load_sources([LINKHUB_SPLIT_DIR])
        via_files = load_sources([LINKHUB_ENTITY_FILE, LINKHUB_WORKFLOW_FILE])
        doc_dir = lower(via_dir, "linkhub").to_document()
        doc_files = lower(via_files, "linkhub").to_document()
        self.assertEqual(doc_dir, doc_files)  # line 포함 완전 동일 — 같은 파일들, 같은 순서

    def test_single_file_argument_stays_byte_identical_to_the_committed_golden(self):
        decls = load_sources([LINKHUB_SINGLE])
        doc = lower(decls, "linkhub").to_document()
        with open(LINKHUB_GOLDEN, encoding="utf-8") as fh:
            golden = json.load(fh)
        # `provenance` (issue #136) is excluded from golden comparisons — its
        # digests are environment-dependent (docs/compatibility.md §2).
        doc.pop("provenance")
        self.assertEqual(doc, golden)

    def test_cli_compile_accepts_a_directory_and_produces_the_split_module_name(self):
        rc, out = run_cli(["compile", LINKHUB_SPLIT_DIR])
        self.assertEqual(rc, 0, out)
        doc = json.loads(out)
        self.assertEqual(doc["module"], "linkhub")

    def test_cli_compile_accepts_multiple_explicit_files(self):
        rc, out = run_cli(["compile", LINKHUB_ENTITY_FILE, LINKHUB_WORKFLOW_FILE])
        self.assertEqual(rc, 0, out)
        doc = json.loads(out)
        self.assertEqual(doc["module"], "01_entity")  # D3: 첫 파일 basename
        node_ids = [n["id"] for n in doc["nodes"]]
        self.assertIn("wf.save.bookmark", node_ids)
        self.assertIn("entity.bookmark", node_ids)


class TestDuplicateDeclaration(unittest.TestCase):
    """(에러) 중복 선언 두 위치 병기 진단, 빈 디렉터리 거부."""

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "multi-file-dup")
        shutil.rmtree(self.workdir, ignore_errors=True)
        os.makedirs(self.workdir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self.workdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_duplicate_name_across_two_files_names_both_locations(self):
        a = self._write("a.lnpl", "entity Bookmark\n    field\n        id UUID\n")
        b = self._write("b.lnpl", "\n\nentity Bookmark\n    field\n        id UUID\n")
        with self.assertRaises(LoaderError) as ctx:
            load_sources([a, b])
        message = str(ctx.exception)
        self.assertIn("Bookmark", message)
        self.assertIn("%s:1" % a, message)
        self.assertIn("%s:3" % b, message)

    def test_duplicate_reversed_argument_order_still_names_the_first_declared_file(self):
        # 먼저 준 파일이 "first declared"다 — 인자 순서가 병합 순서를 정한다
        # (RFC-0031 §Guide-level Explanation).
        a = self._write("a2.lnpl", "entity Bookmark\n    field\n        id UUID\n")
        b = self._write("b2.lnpl", "entity Bookmark\n    field\n        id UUID\n")
        with self.assertRaises(LoaderError) as ctx:
            load_sources([b, a])
        message = str(ctx.exception)
        self.assertIn("first declared at %s:1" % b, message)
        self.assertIn("again at %s:1" % a, message)

    def test_cli_reports_duplicate_declaration_and_exits_nonzero(self):
        a = self._write("a3.lnpl", "entity Bookmark\n    field\n        id UUID\n")
        b = self._write("b3.lnpl", "entity Bookmark\n    field\n        id UUID\n")
        rc, out = run_cli(["compile", a, b])
        self.assertNotEqual(rc, 0)
        self.assertIn("duplicate declaration", out)
        self.assertIn("Bookmark", out)

    def test_empty_directory_is_rejected(self):
        empty = os.path.join(self.workdir, "empty")
        os.makedirs(empty, exist_ok=True)
        with self.assertRaises(LoaderError) as ctx:
            load_sources([empty])
        self.assertIn(empty, str(ctx.exception))

    def test_directory_with_no_lnpl_files_is_rejected(self):
        no_lnpl = os.path.join(self.workdir, "no_lnpl")
        os.makedirs(no_lnpl, exist_ok=True)
        with open(os.path.join(no_lnpl, "readme.txt"), "w", encoding="utf-8") as fh:
            fh.write("not an lnpl file\n")
        with self.assertRaises(LoaderError):
            load_sources([no_lnpl])

    def test_mixing_a_directory_with_explicit_files_is_rejected_cleanly(self):
        # 디렉터리 1개는 "그 자체로 디렉터리 모드"지만, 다른 경로와 섞이면
        # 어느 모드인지 모호하다 — open()이 IsADirectoryError를 던지게 두지
        # 않고 LoaderError로 명시적으로 거부한다.
        with self.assertRaises(LoaderError) as ctx:
            load_sources([LINKHUB_SINGLE, LINKHUB_SPLIT_DIR])
        self.assertIn(LINKHUB_SPLIT_DIR, str(ctx.exception))

    def test_duplicate_within_a_single_file_is_not_a_loader_concern(self):
        # load_sources는 파일 "경계를 넘는" 중복만 본다(RFC-0031). entity와
        # refine이 이름을 두고 부딪히는 건 RFC-0011 A.7(e)의 기존 규칙 —
        # lower()가 LowerError로 잡는다. load_sources는 그걸 가로채지 않는다
        # (파일이 하나뿐이면 "서로 다른 두 파일"이 없으므로 LoaderError는
        # 절대 나오지 않는다).
        collide = ("refine Bookmark of Text\n    minLength 1\n\n"
                  "entity Bookmark\n    field\n        id UUID\n")
        path = self._write("collide.lnpl", collide)
        decls = load_sources([path])  # 로더 단계는 통과한다
        from lnpl.lower import LowerError
        with self.assertRaises(LowerError):
            lower(decls, "collide")


class TestHookAndMcpMultiFile(unittest.TestCase):
    """(정상) 진단 훅과 MCP lnpl_compile이 다중 파일 구성에서 동작한다."""

    def _run_hook(self, file_path):
        payload = json.dumps({"session_id": "test-t77", "tool_input": {"file_path": file_path}})
        env = dict(os.environ)
        venv_bin = os.path.join(REPO, ".venv", "bin")
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
        return subprocess.run(["bash", HOOK], input=payload, capture_output=True,
                              text=True, cwd=REPO, env=env, timeout=60)

    def test_hook_compiles_one_file_of_a_multi_file_split_cleanly(self):
        # 01_entity.lnpl은 그 자체로 자기완결적이다(workflow가 없어도 컴파일된다)
        # — 훅은 편집된 파일 하나만 받으므로, 그 파일이 다중 파일 구성의 일부일
        # 때도 조용히(exit 0) 동작해야 한다. 훅 코드는 변경되지 않는다
        # (RFC-0031 §Reference-level Specification) — 이 테스트는 그 무변경이
        # 실제로 유지됨을 증명한다.
        res = self._run_hook(LINKHUB_ENTITY_FILE)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stderr.strip(), "")

    def test_mcp_lnpl_compile_merges_a_directory(self):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "lnpl_compile",
                             "arguments": {"path": LINKHUB_SPLIT_DIR}}}
        out = io.StringIO()
        mcp_serve(stdin=io.StringIO(json.dumps(request) + "\n"), stdout=out)
        response = json.loads(out.getvalue().splitlines()[0])
        self.assertIs(response["result"]["isError"], False, response)
        body = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(body["source"], LINKHUB_SPLIT_DIR)
        self.assertEqual(body["diagnostics"], [])
        self.assertGreater(body["nodes"], 0)

    def test_mcp_lnpl_compile_reports_a_cross_file_duplicate_as_a_tool_error(self):
        workdir = os.path.join(REPO, ".claude", "tmp", "multi-file-mcp-dup")
        shutil.rmtree(workdir, ignore_errors=True)
        os.makedirs(workdir, exist_ok=True)
        try:
            for name in ("a.lnpl", "b.lnpl"):
                with open(os.path.join(workdir, name), "w", encoding="utf-8") as fh:
                    fh.write("entity Bookmark\n    field\n        id UUID\n")
            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "lnpl_compile",
                                 "arguments": {"path": workdir}}}
            out = io.StringIO()
            mcp_serve(stdin=io.StringIO(json.dumps(request) + "\n"), stdout=out)
            response = json.loads(out.getvalue().splitlines()[0])
            self.assertIs(response["result"]["isError"], True)
            self.assertIn("duplicate declaration",
                          response["result"]["content"][0]["text"])
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
