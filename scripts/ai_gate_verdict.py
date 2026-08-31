#!/usr/bin/env python3
"""AI 게이트 에이전트의 구조화 출력(JSON)을 검증해 exit code를 정한다.

    python scripts/ai_gate_verdict.py --schema schemas/ai-gate-verdict.schema.json \\
        --input structured_output.json --gate rfc-conformance [--expect-nonempty]

에이전트가 뱉은 산문은 exit code를 정하지 않는다 — 이 스크립트가 고정 스키마
(schemas/ai-gate-verdict.schema.json)로 검증한 JSON만 보고 판정한다.

exit code:
  0  통과 (verdict=pass, blocker 없음)
  1  위반 (verdict=fail 이거나 severity=blocker인 finding이 1건 이상)
  2  형식 오류 (입력 없음/비어 있음/JSON 아님, 스키마 위반, gate 불일치)
  3  공허한 통과 (--expect-nonempty인데 verdict=pass이면서 examined.files가 비어 있음)

이 스크립트 자체의 검증 로직은 `impl/tests/test_ai_gate_verdict.py`가 합성
입력으로 검사한다.
"""
import argparse
import json
import sys

import jsonschema


def load_json_input(path):
    """(data, error) — 파일 없음/빈 파일/JSON 아님을 예외로 던지지 않고
    사람이 읽을 사유 문자열로 돌려준다."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return None, "입력 파일 없음: %s" % path
    if not text.strip():
        return None, "입력 파일이 비어 있음: %s" % path
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, "입력 파일이 JSON이 아님(%s): %s" % (path, exc)


def load_schema(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def schema_violations(schema, data):
    """스키마 위반 메시지 목록. 위반 없으면 []."""
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.path)))
    return ["%s: %s" % ("/".join(str(p) for p in e.path) or "(root)", e.message)
            for e in errors]


def format_finding(finding):
    location = finding["file"]
    if "line" in finding:
        location += ":%d" % finding["line"]
    return "%s %s — %s" % (finding["severity"], location, finding["claim"])


def evaluate(schema, data, gate, expect_nonempty):
    """(exit_code, [출력 줄]) — 스키마 검증부터 vacuous-pass까지 판정 전체."""
    lines = []

    violations = schema_violations(schema, data)
    if violations:
        lines.append("스키마 위반:")
        lines.extend("  %s" % v for v in violations)
        return 2, lines

    if data["gate"] != gate:
        lines.append("gate 불일치: 입력은 %r, 요청은 %r" % (data["gate"], gate))
        return 2, lines

    examined_files = data["examined"]["files"]
    findings = data["findings"]
    verdict = data["verdict"]

    lines.append("gate: %s" % data["gate"])
    lines.append("verdict: %s" % verdict)
    lines.append("examined: %d file(s)" % len(examined_files))
    for name in examined_files:
        lines.append("  %s" % name)
    if findings:
        lines.append("findings:")
        lines.extend("  %s" % format_finding(f) for f in findings)
    else:
        lines.append("findings: none")

    if expect_nonempty and verdict == "pass" and not examined_files:
        lines.append("공허한 통과: --expect-nonempty인데 examined.files가 비어 있다")
        return 3, lines

    has_blocker = any(f["severity"] == "blocker" for f in findings)
    if verdict == "fail" or has_blocker:
        return 1, lines
    return 0, lines


def build_parser():
    parser = argparse.ArgumentParser(
        description="AI 게이트 구조화 출력을 검증해 exit code를 정한다.")
    parser.add_argument("--schema", required=True, help="JSON Schema 파일 경로")
    parser.add_argument("--input", required=True, help="검증할 구조화 출력 JSON 경로")
    parser.add_argument("--gate", required=True, help="기대하는 gate 이름")
    parser.add_argument("--expect-nonempty", action="store_true",
                         help="verdict=pass이면서 examined.files가 비면 exit 3")
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(argv)

    data, error = load_json_input(args.input)
    if error:
        print(error)
        return 2

    schema = load_schema(args.schema)
    code, lines = evaluate(schema, data, args.gate, args.expect_nonempty)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
