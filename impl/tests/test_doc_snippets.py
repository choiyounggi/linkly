"""`scripts/check_doc_snippets.py`의 검사 로직.

RFC/README/docs 산문에 박힌 ```lnpl 코드 블록이 실제로 컴파일되는지 CI에서
기계로 검사하는 게이트다. 여기서는 합성 임시 레포로 함수 자체의 정오만
검사한다 — 실제 레포 34개 블록의 마커 부착은 이 파일이 아니라 문서 자체와
`.orchestration/verify/t2-doc-snippet-gate.md`가 증거를 들고 있다.
"""
import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO / "scripts" / "check_doc_snippets.py"

_spec = importlib.util.spec_from_file_location("check_doc_snippets", SCRIPT_PATH)
cds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cds)

# 실제로 컴파일되는 최소 프로그램 (entity + create-as-바인딩 + respond).
OK_PROGRAM = (
    "entity Order\n"
    "    field\n"
    "        id UUID\n"
    "        total Integer\n"
    "\n"
    "workflow PlaceOrder\n"
    "    create order as newOrder\n"
    "    set newOrder.total to 10\n"
    "    respond newOrder.id newOrder.total\n"
)

# entity 선언 없이 `read`만 있는 조각 — 컴파일러가 거부한다.
FRAGMENT_PROGRAM = "read payment\n"

# 구조적으로는 유효하지만(entity 선언 있음, 앞서 어떤 선언도 어기지 않음)
# 존재하지 않는 동사를 쓴 프로그램. 컴파일러는 이걸 warning severity로만
# 낸다(rc=0) — `--strict=warning` 없이는 절대 위반으로 잡히지 않는다. 이
# 게이트의 존재 이유(AGENTS.md: 그럴듯한 낱말이 파싱에 성공하고 런타임이
# 아무것도 하지 않는다) 그 자체를 재현하는 픽스처다.
UNKNOWN_VERB_PROGRAM = (
    "entity Order\n"
    "    field\n"
    "        id UUID\n"
    "\n"
    "workflow FrobnicateTest\n"
    "    frobnicate order\n"
)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def md_with_block(body, marker_line=None):
    lines = []
    if marker_line is not None:
        lines.append(marker_line)
    lines.append("```lnpl")
    lines.extend(body.splitlines())
    lines.append("```")
    return "\n".join(lines) + "\n"


def run_git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True)


def init_repo(root):
    run_git(["init", "-q"], root)
    run_git(["config", "user.email", "t@example.com"], root)
    run_git(["config", "user.name", "T"], root)


def commit_all(root, message):
    run_git(["add", "-A"], root)
    run_git(["commit", "-q", "-m", message], root)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                          capture_output=True, text=True, check=True)
    return out.stdout.strip()


def call_main(args, repo_root):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cds.main(args, repo_root=repo_root)
    return rc, out.getvalue()


class ExtractBlocksTest(unittest.TestCase):
    def test_finds_a_block_and_its_start_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.md"
            write(path, "prelude prose\n\n" + md_with_block(OK_PROGRAM))
            blocks = cds.extract_blocks(path)
            self.assertEqual(len(blocks), 1)
            self.assertEqual(blocks[0]["line"], 3)
            self.assertIsNone(blocks[0]["marker"])

    def test_a_file_with_no_lnpl_fence_yields_no_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.md"
            write(path, "just prose, no fences here\n")
            self.assertEqual(cds.extract_blocks(path), [])

    def test_marker_directly_above_the_fence_is_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.md"
            marker = "<!-- lnpl-check: skip — 조각 -->"
            write(path, md_with_block(FRAGMENT_PROGRAM, marker_line=marker))
            blocks = cds.extract_blocks(path)
            self.assertEqual(blocks[0]["marker"], "skip — 조각")


class CheckBlockCompileTest(unittest.TestCase):
    """정상 1 + 에러(마커 관련) + 경계값(빈 블록)을 실제 컴파일러로 검증한다."""

    def test_a_compiling_block_with_no_marker_is_not_a_violation(self):
        block = {"path": Path("doc.md"), "line": 1, "body": OK_PROGRAM.splitlines(), "marker": None}
        self.assertEqual(cds.check_block(block, REPO), [])

    def test_an_uncompiling_block_with_no_marker_is_reported_with_file_and_line(self):
        block = {"path": Path("doc.md"), "line": 42, "body": FRAGMENT_PROGRAM.splitlines(), "marker": None}
        violations = cds.check_block(block, REPO)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].line, 42)
        self.assertIn("appears before any declaration", violations[0].message)

    def test_skip_with_no_reason_is_a_violation(self):
        block = {"path": Path("doc.md"), "line": 5, "body": FRAGMENT_PROGRAM.splitlines(), "marker": "skip"}
        violations = cds.check_block(block, REPO)
        self.assertEqual(len(violations), 1)
        self.assertIn("requires a reason", violations[0].message)

    def test_skip_marker_on_a_block_that_now_compiles_is_a_stale_exception(self):
        block = {
            "path": Path("doc.md"), "line": 7,
            "body": OK_PROGRAM.splitlines(), "marker": "skip — no longer needed",
        }
        violations = cds.check_block(block, REPO)
        self.assertEqual(len(violations), 1)
        self.assertIn("stale skip", violations[0].message)

    def test_skip_marker_on_a_genuinely_broken_block_passes(self):
        block = {
            "path": Path("doc.md"), "line": 9,
            "body": FRAGMENT_PROGRAM.splitlines(), "marker": "skip — fragment, no entity in scope",
        }
        self.assertEqual(cds.check_block(block, REPO), [])

    def test_an_unknown_verb_is_caught_because_compile_uses_strict_warning(self):
        """구조적으로는 유효한 프로그램(entity 선언 있음)이 존재하지 않는
        동사만 쓴다. 컴파일러는 이걸 warning severity로 낸다 — plain
        `lnpl compile`이면 rc=0으로 조용히 통과한다. 이 테스트가 위반으로
        잡는다는 것 자체가 `compile_source`가 `--strict=warning`을 실제로
        쓰고 있다는 증거다: 그 플래그를 빼면 이 assertion이 깨진다."""
        block = {
            "path": Path("doc.md"), "line": 20,
            "body": UNKNOWN_VERB_PROGRAM.splitlines(), "marker": None,
        }
        violations = cds.check_block(block, REPO)
        self.assertEqual(len(violations), 1)
        self.assertIn("unknown-verb", violations[0].message)

    def test_an_unknown_verb_block_can_be_exempted_as_documented_drift(self):
        """`skip — drift: ...` 마커가 unknown-verb warning 블록도 정확히
        면제한다(정상 컴파일 실패와 같은 경로) — fragment/drift 접두사는
        면제 메커니즘 자체에는 아무 영향이 없고 이유 문자열의 관례일 뿐임을
        확인한다."""
        block = {
            "path": Path("doc.md"), "line": 22,
            "body": UNKNOWN_VERB_PROGRAM.splitlines(),
            "marker": "skip — drift: pre-RFC-0002 문법, RFC 개정 대상",
        }
        self.assertEqual(cds.check_block(block, REPO), [])

    def test_an_empty_block_body_compiles_as_a_vacuous_program(self):
        block = {"path": Path("doc.md"), "line": 11, "body": [], "marker": None}
        self.assertEqual(cds.check_block(block, REPO), [])

    def test_unknown_directive_is_a_violation(self):
        block = {
            "path": Path("doc.md"), "line": 13,
            "body": OK_PROGRAM.splitlines(), "marker": "frobnicate x",
        }
        violations = cds.check_block(block, REPO)
        self.assertEqual(len(violations), 1)
        self.assertIn("unknown lnpl-check directive", violations[0].message)

    def test_prelude_path_that_does_not_exist_is_a_violation(self):
        block = {
            "path": Path("doc.md"), "line": 15,
            "body": FRAGMENT_PROGRAM.splitlines(), "marker": "prelude no/such/file.lnpl",
        }
        violations = cds.check_block(block, REPO)
        self.assertEqual(len(violations), 1)
        self.assertIn("does not exist", violations[0].message)

    def test_prelude_with_a_real_file_supplies_the_missing_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            prelude_path = repo_root / "context.lnpl"
            write(prelude_path, "entity Payment\n    field\n        id UUID\n")
            block = {
                "path": Path("doc.md"), "line": 17,
                "body": ["workflow ReadPayment", "    read payment"],
                "marker": "prelude context.lnpl",
            }
            self.assertEqual(cds.check_block(block, repo_root), [])


class MainCliFullScanTest(unittest.TestCase):
    def test_a_single_compiling_block_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            write(repo_root / "docs" / "example.md", md_with_block(OK_PROGRAM))
            rc, out = call_main([], repo_root)
            self.assertEqual(rc, 0, out)
            self.assertIn("all lnpl blocks OK", out)

    def test_an_uncompiling_unmarked_block_exits_one_with_file_and_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            write(repo_root / "docs" / "example.md", md_with_block(FRAGMENT_PROGRAM))
            rc, out = call_main([], repo_root)
            self.assertEqual(rc, 1)
            self.assertIn("example.md:1", out)

    def test_no_lnpl_blocks_at_all_exits_zero_and_reports_zero_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            write(repo_root / "docs" / "example.md", "prose only, no fences\n")
            rc, out = call_main([], repo_root)
            self.assertEqual(rc, 0, out)
            self.assertIn("0 lnpl block(s) examined", out)


class ChangedOnlyTest(unittest.TestCase):
    def test_zero_changed_target_files_exits_zero_with_an_explicit_skip_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            init_repo(repo_root)
            write(repo_root / "notes.txt", "v1\n")
            base = commit_all(repo_root, "base")
            write(repo_root / "notes.txt", "v2\n")
            commit_all(repo_root, "unrelated change")
            rc, out = call_main(["--changed-only", "--base", base], repo_root)
            self.assertEqual(rc, 0, out)
            self.assertIn("no .md files changed — skipped", out)

    def test_a_changed_target_file_with_a_bad_block_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            init_repo(repo_root)
            write(repo_root / "README.md", "# hello\n")
            base = commit_all(repo_root, "base")
            write(repo_root / "rfcs" / "0099-x.md", md_with_block(FRAGMENT_PROGRAM))
            commit_all(repo_root, "add rfc with bad snippet")
            rc, out = call_main(["--changed-only", "--base", base], repo_root)
            self.assertEqual(rc, 1, out)
            self.assertIn("0099-x.md", out)

    def test_a_shallow_clone_is_detected_and_a_full_clone_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_root = Path(tmp) / "base"
            clone_root = Path(tmp) / "clone"
            base_root.mkdir()
            init_repo(base_root)
            write(base_root / "notes.txt", "v1\n")
            commit_all(base_root, "base")
            run_git(["clone", "-q", "--depth", "1", f"file://{base_root}", str(clone_root)], Path(tmp))
            self.assertFalse(cds.is_shallow_repo(base_root))
            self.assertTrue(cds.is_shallow_repo(clone_root))


if __name__ == "__main__":
    unittest.main()
