#!/usr/bin/env python3
"""LIR 문서를 schemas/lir.schema.json으로 검증한다.

사용법:
    python3 scripts/validate_ir.py <file.lir.json>   # 단일 문서 검증
    python3 scripts/validate_ir.py --self-test        # 골든 예제 + 부정 케이스 자기검증

--self-test는 examples/login.lir.json이 스키마를 통과하고(positive 1),
고의로 깨뜨린 3가지 변형(필수 필드 삭제 / 미정의 kind 주입 / 미정의 추가
필드 주입)이 전부 거부돼야 exit 0이다. 부정 케이스가 하나라도 통과하면
검증기가 결함을 잡지 못한다는 뜻이므로 exit 1 — 실패할 수 없는 검증은
검증이 아니다.
"""

import copy
import json
import sys
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "lir.schema.json"
GOLDEN_PATH = REPO_ROOT / "examples" / "login.lir.json"


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print("ERROR: file not found: {}".format(path))
        sys.exit(1)
    except json.JSONDecodeError as e:
        print("ERROR: invalid JSON in {}: {}".format(path, e))
        sys.exit(1)


def make_validator():
    schema = load_json(SCHEMA_PATH)
    return jsonschema.Draft202012Validator(schema)


def find_node(doc, node_id):
    for node in doc["nodes"]:
        if node.get("id") == node_id:
            return node
    print("ERROR: self-test fixture broken — node {} not in golden example".format(node_id))
    sys.exit(1)


def self_test():
    validator = make_validator()
    golden = load_json(GOLDEN_PATH)
    failures = 0

    # positive: 골든 예제는 통과해야 한다
    errors = list(validator.iter_errors(golden))
    if errors:
        print("FAIL (positive): examples/login.lir.json must validate, but got:")
        for e in errors[:5]:
            print("  - {}: {}".format(list(e.absolute_path), e.message))
        failures += 1
    else:
        print("PASS (positive): examples/login.lir.json validates")

    # negative 3종: 각 변형은 반드시 거부돼야 한다
    mutated_missing = copy.deepcopy(golden)
    del find_node(mutated_missing, "wf.login")["name"]

    mutated_kind = copy.deepcopy(golden)
    mutated_kind["nodes"][0]["kind"] = "Foo"

    mutated_extra = copy.deepcopy(golden)
    find_node(mutated_extra, "svc.login")["extra"] = True

    negatives = [
        ("required field removed: wf.login.name", mutated_missing),
        ("undefined kind injected: Foo", mutated_kind),
        ("undefined extra field injected: svc.login.extra", mutated_extra),
    ]
    for label, doc in negatives:
        if validator.is_valid(doc):
            print("FAIL (negative): mutation passed validation — {}".format(label))
            failures += 1
        else:
            print("REJECTED (negative): {}".format(label))

    if failures:
        print("self-test: FAIL ({} case(s))".format(failures))
        return 1
    print("self-test: OK (1 positive passed, 3 negatives rejected)")
    return 0


def validate_file(path):
    validator = make_validator()
    doc = load_json(Path(path))
    errors = list(validator.iter_errors(doc))
    if errors:
        print("INVALID: {}".format(path))
        for e in errors:
            print("  - at {}: {}".format(list(e.absolute_path), e.message))
        return 1
    print("PASS: {}".format(path))
    return 0


def main(argv):
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        print((__doc__ or "usage: validate_ir.py <file.lir.json> | --self-test").strip())
        return 1
    if argv[1] == "--self-test":
        return self_test()
    return validate_file(argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
