"""`scripts/ai_gate_verdict.py`의 판정 로직 — 실제 `schemas/ai-gate-verdict.schema.json`을
정본으로 검증한다(D2: 액션의 `--json-schema`와 이 스크립트가 같은 파일을 읽는다).

핵심 가치: 에이전트가 뱉은 산문이 아니라 이 스크립트가 exit code를 정한다.
exit 0=통과, 1=위반(verdict=fail 또는 blocker finding), 2=형식 오류(입력 없음/
빈 파일/JSON 아님/스키마 위반/gate 불일치), 3=공허한 통과(--expect-nonempty인데
verdict=pass이면서 examined.files가 비어 있음).
"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(REPO, "scripts", "ai_gate_verdict.py")
SCHEMA_PATH = os.path.join(REPO, "schemas", "ai-gate-verdict.schema.json")

_spec = importlib.util.spec_from_file_location("ai_gate_verdict", SCRIPT_PATH)
agv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agv)


def write(path, content):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def verdict_doc(gate="rfc-conformance", verdict="pass", files=None, findings=None,
                note="변경 파일을 전부 확인했다"):
    return {
        "gate": gate,
        "verdict": verdict,
        "examined": {"files": [] if files is None else files, "note": note},
        "findings": [] if findings is None else findings,
    }


def blocker(file="a.py", line=None):
    finding = {"severity": "blocker", "file": file, "claim": "안전하지 않은 패턴",
               "evidence": "12번 줄이 사용자 입력을 검증 없이 실행한다"}
    if line is not None:
        finding["line"] = line
    return finding


def warning(file="a.py"):
    return {"severity": "warning", "file": file, "claim": "사소한 지적",
            "evidence": "스타일 불일치"}


def run_cli(input_path, gate="rfc-conformance", expect_nonempty=False, schema_path=None):
    argv = ["--schema", schema_path or SCHEMA_PATH, "--input", input_path, "--gate", gate]
    if expect_nonempty:
        argv.append("--expect-nonempty")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = agv.main(argv)
    return code, out.getvalue()


class MainExitCodeTest(unittest.TestCase):
    """계획서 Step 4가 열거한 11개 케이스(정상 2 + 에러 5 + 경계값 3 + 공허 1)."""

    # -- 정상 2 --------------------------------------------------------
    def test_pass_with_no_findings_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, json.dumps(verdict_doc(files=["a.py"], findings=[])))
            code, out = run_cli(path)
            self.assertEqual(code, 0, out)
            self.assertIn("a.py", out)

    def test_pass_with_only_warning_findings_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, json.dumps(verdict_doc(files=["a.py"], findings=[warning()])))
            code, out = run_cli(path)
            self.assertEqual(code, 0, out)
            self.assertIn("warning", out)

    # -- 에러 5 ----------------------------------------------------------
    def test_verdict_fail_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, json.dumps(verdict_doc(verdict="fail", files=["a.py"])))
            code, out = run_cli(path)
            self.assertEqual(code, 1, out)

    def test_blocker_finding_exits_1_even_if_verdict_says_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, json.dumps(
                verdict_doc(verdict="pass", files=["a.py"], findings=[blocker(line=12)])))
            code, out = run_cli(path)
            self.assertEqual(code, 1, out)
            self.assertIn("blocker", out)

    def test_input_that_is_not_json_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, "{not valid json")
            code, out = run_cli(path)
            self.assertEqual(code, 2, out)
            self.assertIn("JSON", out)

    def test_missing_required_evidence_field_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            doc = verdict_doc(files=["a.py"])
            doc["findings"] = [{"severity": "blocker", "file": "a.py", "claim": "x"}]
            write(path, json.dumps(doc))
            code, out = run_cli(path)
            self.assertEqual(code, 2, out)
            self.assertIn("evidence", out)

    def test_gate_mismatch_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, json.dumps(verdict_doc(gate="golden-approval", files=["a.py"])))
            code, out = run_cli(path, gate="rfc-conformance")
            self.assertEqual(code, 2, out)
            self.assertIn("gate", out)

    # -- 공허 1 ------------------------------------------------------------
    def test_expect_nonempty_with_pass_and_no_examined_files_exits_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, json.dumps(verdict_doc(verdict="pass", files=[])))
            code, out = run_cli(path, expect_nonempty=True)
            self.assertEqual(code, 3, out)
            self.assertIn("공허한", out)

    # -- 경계값 3 ------------------------------------------------------
    def test_empty_string_input_file_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, "")
            code, out = run_cli(path)
            self.assertEqual(code, 2, out)
            self.assertIn("비어", out)

    def test_nonexistent_input_file_exits_2(self):
        code, out = run_cli("/nonexistent-dir-for-test/verdict.json")
        self.assertEqual(code, 2, out)
        self.assertIn("없음", out)

    def test_empty_findings_and_empty_examined_without_expect_nonempty_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, json.dumps(verdict_doc(verdict="pass", files=[], findings=[])))
            code, out = run_cli(path, expect_nonempty=False)
            self.assertEqual(code, 0, out)


class ExitCodePriorityTest(unittest.TestCase):
    """`evaluate()`가 지키는 고정 우선순위(스키마/gate 불일치 > 공허한 통과 >
    verdict=fail/blocker) — 두 조건이 동시에 성립하는 문서로, 순서가 뒤바뀌면
    exit code가 달라짐을 증명한다. 각 조건을 단독으로만 쓰는 픽스처는 어느
    쪽이 이겼는지 구분하지 못한다(순서를 바꿔도 계속 통과한다)."""

    def test_gate_mismatch_wins_over_vacuous_pass(self):
        """gate 불일치(exit 2)와 공허한 통과(exit 3) 조건이 둘 다 성립하는
        문서. gate 검사가 먼저이므로 exit 2여야 한다 — vacuous 검사가 먼저로
        뒤바뀌면 이 케이스는 3을 냈을 것이다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, json.dumps(verdict_doc(gate="golden-approval", verdict="pass", files=[])))
            code, out = run_cli(path, gate="rfc-conformance", expect_nonempty=True)
            self.assertEqual(code, 2, out)
            self.assertNotIn("공허한", out)

    def test_vacuous_pass_wins_over_blocker(self):
        """공허한 통과(exit 3)와 blocker finding(exit 1) 조건이 둘 다 성립하는
        문서. 공허 검사가 먼저이므로 exit 3이어야 한다 — blocker 검사가
        먼저로 뒤바뀌면 이 케이스는 1을 냈을 것이다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "verdict.json")
            write(path, json.dumps(
                verdict_doc(verdict="pass", files=[], findings=[blocker()])))
            code, out = run_cli(path, expect_nonempty=True)
            self.assertEqual(code, 3, out)
            self.assertIn("공허한", out)


class SchemaViolationsTest(unittest.TestCase):
    """스키마 검증 함수 자체의 단위 테스트 — 어떤 필드가 어떤 위반을 내는지."""

    def setUp(self):
        self.schema = agv.load_schema(SCHEMA_PATH)

    def test_valid_document_has_no_violations(self):
        violations = agv.schema_violations(self.schema, verdict_doc(files=["a.py"]))
        self.assertEqual(violations, [])

    def test_unknown_top_level_field_is_a_violation(self):
        doc = verdict_doc(files=["a.py"])
        doc["extra"] = "not allowed"
        violations = agv.schema_violations(self.schema, doc)
        self.assertTrue(any("extra" in v for v in violations))

    def test_invalid_verdict_enum_value_is_a_violation(self):
        doc = verdict_doc(files=["a.py"])
        doc["verdict"] = "maybe"
        violations = agv.schema_violations(self.schema, doc)
        self.assertTrue(any("maybe" in v for v in violations))


class FormatFindingTest(unittest.TestCase):
    def test_finding_without_line_omits_colon_suffix(self):
        text = agv.format_finding(warning())
        self.assertEqual(text, "warning a.py — 사소한 지적")

    def test_finding_with_line_includes_it(self):
        text = agv.format_finding(blocker(line=42))
        self.assertIn("a.py:42", text)


if __name__ == "__main__":
    unittest.main()
