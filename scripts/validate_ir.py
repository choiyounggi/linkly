#!/usr/bin/env python3
"""LIR 문서를 schemas/lir.schema.json으로 검증한다.

사용법:
    python3 scripts/validate_ir.py <file.lir.json>    # 단일 문서 검증
    python3 scripts/validate_ir.py --self-test        # 골든 예제 + 부정 케이스 자기검증
    python3 scripts/validate_ir.py --self-test-meta   # 그 부정 케이스들 자체의 역방향 통제

--self-test는 examples/login.lir.json과 REFINEMENT_FIXTURE, ASSIGNMENT_FIXTURE,
SCHEDULE_EVENT_FIXTURE가 스키마를 통과하고(positive 4), 고의로 깨뜨린 변형들 —
필수 필드 삭제 / 미정의 kind 주입 / 미정의 추가 필드 주입, refinement 표기
(RFC-0001 부록 A.6)의 7종, Assignment 표기(RFC-0015)의 5종, 그리고 schedule 이벤트
소스(RFC-0016)의 6종 — 이 전부 거부돼야 exit 0이다. 부정 케이스가
하나라도 통과하면 검증기가 결함을 잡지 못한다는 뜻이므로 exit 1 — 실패할 수 없는
검증은 검증이 아니다.

--self-test-meta는 그 한 단계 위를 본다. "거부됐다"는 사실은 **무엇이** 거부했는지
말해주지 않는다: `Refinement` kind를 스키마에 넣기 전에는 7종 부정 케이스가 전부
"그런 kind가 없다"는 이유로 거부됐고, 그 초록은 새 표기에 대해 아무것도 증명하지
못했다. 그래서 제약을 하나씩 무력화해 **그 제약이 소유한 케이스만** 통과로
바뀌는지 확인한다 — 각 제약이 실효 있고 서로 겹치지 않음의 증거다.
"""

import copy
import json
import sys
from pathlib import Path

try:
    import jsonschema
    from jsonschema import exceptions as jsonschema_exceptions
except ModuleNotFoundError:
    sys.stderr.write(
        "validate_ir.py needs the `jsonschema` package, and this interpreter "
        "(%s) does not have it.\n"
        "Use the project venv, which pins the toolchain regardless of what\n"
        "`python3` resolves to on your PATH:\n"
        "    python3 -m venv .venv && .venv/bin/pip install jsonschema\n"
        "    .venv/bin/python scripts/validate_ir.py <file>\n" % sys.executable)
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "lir.schema.json"
GOLDEN_PATH = REPO_ROOT / "examples" / "login.lir.json"

# refinement 표기(RFC-0001 부록 A.6)의 최소 적합 픽스처.
# 골든 예제에는 Refinement 노드가 없어서 그것을 변형해 만드는 부정 케이스로는
# 새 표기의 수용/거부를 한 건도 증명할 수 없다. `examples/`는 다른 태스크가
# 소유하므로 픽스처를 게이트 옆에 인라인으로 둔다.
# 세 preset(URL/Slug/PositiveInteger)을 전부 실어 A.6.4의 emit-on-use 자기완결성
# — 소비자가 컴파일러 내장표 없이 문서 안에서 이름을 해소할 수 있음 — 을 보인다.
REFINEMENT_FIXTURE = {
    "lir_version": "0.1",
    "module": "refinement",
    "nodes": [
        {
            "kind": "Refinement",
            "id": "refine.slug",
            "name": "Slug",
            "base": "Text",
            "facets": {"pattern": "^[a-z0-9-]{1,64}$", "maxLength": 64},
        },
        {
            "kind": "Refinement",
            "id": "refine.url",
            "name": "URL",
            "base": "Text",
            "facets": {"pattern": "^https?://[^\\s]+$", "maxLength": 2048},
        },
        {
            "kind": "Refinement",
            "id": "refine.positive.integer",
            "name": "PositiveInteger",
            "base": "Integer",
            "facets": {"min": 1},
        },
        {
            "kind": "Entity",
            "id": "entity.link",
            "name": "Link",
            "fields": [
                {"name": "slug", "type": "Slug"},
                {"name": "target", "type": "URL"},
                {"name": "hits", "type": "PositiveInteger"},
            ],
        },
    ],
}


ASSIGNMENT_FIXTURE = {
    "lir_version": "0.1",
    "module": "assignment",
    "nodes": [
        {
            "kind": "Entity",
            "id": "entity.product",
            "name": "Product",
            "fields": [
                {"name": "id", "type": "UUID"},
                {"name": "stock", "type": "Integer"},
            ],
        },
        {
            "kind": "Workflow",
            "id": "wf.place.order",
            "name": "PlaceOrder",
            "children": ["wf.place.order.step.1"],
        },
        {
            "kind": "WorkflowStep",
            "id": "wf.place.order.step.1",
            "name": "set product.stock to product.stock - input.quantity",
            "children": ["wf.place.order.step.1.assign"],
        },
        {
            "kind": "Assignment",
            "id": "wf.place.order.step.1.assign",
            "target": "product.stock",
            "expression": "product.stock - input.quantity",
            "entity": "entity.product",
        },
    ],
}


def assignment_negatives():
    """RFC-0015의 Assignment 분기 — 이 분기가 **더한 키워드마다** 부정 하나.

    골든(`examples/login.lir.json`)에는 Assignment 노드가 없다. 그래서 그 골든을
    변형해 만든 기존 부정 케이스들은 새 분기를 한 번도 지나지 않는다 — 초록이
    나와도 그것은 변경 이전에 대한 판정이다. 새 kind를 담은 픽스처와, 분기가
    도입한 키워드(required / type / enum / additionalProperties / 교차참조)마다
    하나씩의 부정이 있어야 그 초록이 이 변경에 대한 판정이 된다.
    """
    n1 = copy.deepcopy(ASSIGNMENT_FIXTURE)
    del n1["nodes"][3]["target"]                        # required 누락

    n2 = copy.deepcopy(ASSIGNMENT_FIXTURE)
    n2["nodes"][3]["expression"] = 3                    # type 불일치

    n3 = copy.deepcopy(ASSIGNMENT_FIXTURE)
    n3["nodes"][3]["kind"] = "Assign"                   # enum(kind) 밖

    n4 = copy.deepcopy(ASSIGNMENT_FIXTURE)
    n4["nodes"][3]["operation"] = "update"              # 미선언 속성

    n5 = copy.deepcopy(ASSIGNMENT_FIXTURE)
    n5["nodes"][3]["entity"] = "Entity.Product"         # nodeId 형식 위반(교차참조)

    return [
        ("required field removed: Assignment.target", n1),
        ("expression is not a string: 3", n2),
        ("kind outside the catalogue: 'Assign'", n3),
        ("undeclared property on Assignment: operation", n4),
        ("entity is not a node id: 'Entity.Product'", n5),
    ]


SCHEDULE_EVENT_FIXTURE = {
    "lir_version": "0.1",
    "module": "rollup",
    "nodes": [
        {
            "kind": "Event",
            "id": "event.daily.rollup",
            "name": "DailyRollup",
            "source": {"every": "daily", "at": "00:00", "zone": "UTC"},
        },
    ],
}


def schedule_negatives():
    """RFC-0016의 schedule 소스 분기 — 이 분기가 **더한 키워드마다** 부정 하나.

    `nodeEvent.source`는 이제 두 분기의 `oneOf`다. 골든의 이벤트는 전부 엔티티
    소스라서 스케줄 분기를 한 번도 지나지 않는다 — 그 초록은 변경 이전에 대한
    판정이다. 마지막 케이스가 `oneOf` 자체를 겨눈다: 두 분기의 키를 한 객체에
    섞으면 어느 쪽으로도 유효하지 않아야 한다(둘 다 additionalProperties:false).
    """
    n1 = copy.deepcopy(SCHEDULE_EVENT_FIXTURE)
    del n1["nodes"][0]["source"]["every"]               # required 누락

    n2 = copy.deepcopy(SCHEDULE_EVENT_FIXTURE)
    n2["nodes"][0]["source"]["at"] = 0                  # type 불일치

    n3 = copy.deepcopy(SCHEDULE_EVENT_FIXTURE)
    n3["nodes"][0]["source"]["every"] = "hourly"        # enum(every) 밖

    n4 = copy.deepcopy(SCHEDULE_EVENT_FIXTURE)
    n4["nodes"][0]["source"]["cron"] = "0 0 * * *"      # 미선언 속성

    n5 = copy.deepcopy(SCHEDULE_EVENT_FIXTURE)
    n5["nodes"][0]["source"]["ref"] = "entity.report"   # 두 분기 혼합 -> oneOf 0매칭

    n6 = copy.deepcopy(SCHEDULE_EVENT_FIXTURE)
    n6["nodes"][0]["source"]["at"] = "24:00"            # pattern(시각 범위) 밖

    return [
        ("required field removed: Event.source.every", n1),
        ("at is not a string: 0", n2),
        ("every outside the closed set: 'hourly'", n3),
        ("undeclared property on the schedule source: cron", n4),
        ("entity and schedule keys mixed: oneOf matches neither", n5),
        ("at outside 00:00..23:59: '24:00'", n6),
    ]


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


def rejecting_keyword(validator, doc):
    """거부를 일으킨 스키마 키워드 이름. 초록 실행이 '무엇을 증명했는지' 말하게 한다.

    노드는 `anyOf` 21분기로 판별되므로 문서 전체를 검증하면 최상위 오류가 늘
    `anyOf`로 뭉개진다. `kind`가 사실상의 판별자이므로, 문제의 노드를 그 kind의
    하위 스키마(`#/$defs/node<Kind>`)에 직접 걸어 실제로 위반된 키워드를 얻는다.
    `kind` 자체가 카탈로그 밖이면 대응 분기가 없는 것이 곧 결함이므로 그렇게 적는다.
    """
    err = next(iter(validator.iter_errors(doc)), None)
    if err is None:
        return "?"
    path = list(err.absolute_path)
    if len(path) >= 2 and path[0] == "nodes":
        node = doc["nodes"][path[1]]
        ref = "node{}".format(node.get("kind"))
        if ref in validator.schema["$defs"]:
            sub = jsonschema.Draft202012Validator({
                "$defs": validator.schema["$defs"],
                "$ref": "#/$defs/{}".format(ref),
            })
            match = jsonschema_exceptions.best_match(sub.iter_errors(node))
            if match is not None:
                return match.validator
        else:
            return "anyOf (no branch for kind={!r})".format(node.get("kind"))
    match = jsonschema_exceptions.best_match(validator.iter_errors(doc))
    return match.validator if match is not None else "?"


def refinement_negatives():
    """RFC-0001 부록 A.6 표기의 부정 케이스.

    각 변형은 픽스처의 **딱 한 곳만** 건드리고 서로 다른 스키마 키워드를
    겨냥한다 — 하나의 빨간불이 어느 속성의 실패인지 이름을 갖게 하기 위함이다.
    """
    n1 = copy.deepcopy(REFINEMENT_FIXTURE)
    n1["nodes"][0]["facets"]["maxLenght"] = 64          # 어휘 밖 facet(오탈자)

    n2 = copy.deepcopy(REFINEMENT_FIXTURE)
    del n2["nodes"][0]["base"]                          # 필수 필드 누락

    n3 = copy.deepcopy(REFINEMENT_FIXTURE)
    n3["nodes"][0]["name"] = "slug"                     # PascalCase 아님

    n4 = copy.deepcopy(REFINEMENT_FIXTURE)
    n4["nodes"][0]["base"] = "Slugg"                    # 18종 밖 base

    n5 = copy.deepcopy(REFINEMENT_FIXTURE)
    n5["nodes"][0]["facets"]["pattern"] = 64            # facet 값 타입 불일치

    n6 = copy.deepcopy(REFINEMENT_FIXTURE)
    n6["nodes"][0]["children"] = []                     # Refinement는 children 없음

    n7 = copy.deepcopy(REFINEMENT_FIXTURE)
    n7["nodes"][3]["fields"][0]["type"] = "slug"        # 타입 이름이 PascalCase 아님

    return [
        ("unknown facet keyword: facets.maxLenght", n1),
        ("required field removed: Refinement.base", n2),
        ("name not PascalCase: 'slug'", n3),
        ("base outside the 18 semantic types: 'Slugg'", n4),
        ("facet value type mismatch: pattern = 64", n5),
        ("children on a Refinement node", n6),
        ("fields[].type not PascalCase: 'slug'", n7),
    ]


def self_test():
    validator = make_validator()
    golden = load_json(GOLDEN_PATH)
    failures = 0

    # positive 2종: 골든 예제와 refinement 픽스처는 통과해야 한다
    positives = [
        ("examples/login.lir.json", golden),
        ("REFINEMENT_FIXTURE (RFC-0001 부록 A.6)", REFINEMENT_FIXTURE),
        ("ASSIGNMENT_FIXTURE (RFC-0015 Assignment)", ASSIGNMENT_FIXTURE),
        ("SCHEDULE_EVENT_FIXTURE (RFC-0016 schedule source)",
         SCHEDULE_EVENT_FIXTURE),
    ]
    for label, doc in positives:
        errors = list(validator.iter_errors(doc))
        if errors:
            print("FAIL (positive): {} must validate, but got:".format(label))
            for e in errors[:5]:
                print("  - {}: {}".format(list(e.absolute_path), e.message))
            failures += 1
        else:
            print("PASS (positive): {} validates".format(label))

    # negative: 각 변형은 반드시 거부돼야 한다
    mutated_missing = copy.deepcopy(golden)
    del find_node(mutated_missing, "wf.login")["name"]

    mutated_kind = copy.deepcopy(golden)
    mutated_kind["nodes"][0]["kind"] = "Foo"

    mutated_extra = copy.deepcopy(golden)
    find_node(mutated_extra, "svc.login")["extra"] = True

    # RFC-0024: `line` is `{"type": "integer", "minimum": 1}` on every node
    # kind — one negative per keyword it introduces (wf.login carries a `line`
    # in the golden, so both mutants actually exercise the new branch).
    mutated_line_zero = copy.deepcopy(golden)
    find_node(mutated_line_zero, "wf.login")["line"] = 0

    mutated_line_string = copy.deepcopy(golden)
    find_node(mutated_line_string, "wf.login")["line"] = "4"

    negatives = [
        ("required field removed: wf.login.name", mutated_missing),
        ("undefined kind injected: Foo", mutated_kind),
        ("undefined extra field injected: svc.login.extra", mutated_extra),
        ("line below minimum: wf.login.line = 0", mutated_line_zero),
        ("line is not an integer: wf.login.line = '4'", mutated_line_string),
    ] + refinement_negatives() + assignment_negatives() + schedule_negatives()

    for label, doc in negatives:
        if validator.is_valid(doc):
            print("FAIL (negative): mutation passed validation — {}".format(label))
            failures += 1
        else:
            print("REJECTED (negative): {}  [caught by: {}]".format(
                label, rejecting_keyword(validator, doc)))

    if failures:
        print("self-test: FAIL ({} case(s))".format(failures))
        return 1
    print("self-test: OK ({} positives passed, {} negatives rejected)".format(
        len(positives), len(negatives)))
    return 0


def disable_constraint(schema, which):
    """스키마 사본에서 제약 **하나만** 무력화해 돌려준다(원본 불변)."""
    schema = copy.deepcopy(schema)
    defs = schema["$defs"]
    if which == "facets.additionalProperties":
        defs["facets"]["additionalProperties"] = True
    elif which == "nodeRefinement.required[base]":
        defs["nodeRefinement"]["required"].remove("base")
    elif which == "nodeRefinement.name.pattern":
        del defs["nodeRefinement"]["properties"]["name"]["pattern"]
    elif which == "baseTypeName.enum":
        defs["baseTypeName"] = {"type": "string"}
    elif which == "facets.pattern.type":
        defs["facets"]["properties"]["pattern"] = {}
    elif which == "nodeRefinement.additionalProperties":
        defs["nodeRefinement"]["additionalProperties"] = True
    elif which == "fieldList.type.pattern":
        del defs["fieldList"]["items"]["properties"]["type"]["pattern"]
    else:
        raise ValueError("unknown constraint: {}".format(which))
    return schema


# 제약 → 그 제약이 **혼자서** 잡아야 하는 부정 케이스.
CONSTRAINT_OWNERS = [
    ("facets.additionalProperties", "unknown facet keyword: facets.maxLenght"),
    ("nodeRefinement.required[base]", "required field removed: Refinement.base"),
    ("nodeRefinement.name.pattern", "name not PascalCase: 'slug'"),
    ("baseTypeName.enum", "base outside the 18 semantic types: 'Slugg'"),
    ("facets.pattern.type", "facet value type mismatch: pattern = 64"),
    ("nodeRefinement.additionalProperties", "children on a Refinement node"),
    ("fieldList.type.pattern", "fields[].type not PascalCase: 'slug'"),
]


def self_test_meta():
    """검사기 자신을 검사한다(역방향 통제).

    부정 케이스가 '거부됐다'는 사실만으로는 **무엇이** 거부했는지 알 수 없다 —
    새 kind를 추가하기 전에는 7개 부정 케이스가 전부 "Refinement라는 kind가
    없다"는 이유로 거부됐고, 그 초록은 아무것도 증명하지 못했다.
    그래서 제약을 하나씩 무력화해, **딱 그 제약이 소유한 부정 케이스만**
    통과로 바뀌는지 확인한다. 통과로 바뀌지 않으면 그 제약은 없어도 되는
    것이거나(실효 없음) 다른 제약과 겹친 것이다.
    """
    schema = load_json(SCHEMA_PATH)
    negatives = dict(refinement_negatives())
    labels = list(negatives)
    failures = 0

    for which, owned in CONSTRAINT_OWNERS:
        validator = jsonschema.Draft202012Validator(disable_constraint(schema, which))
        now_valid = [l for l in labels if validator.is_valid(negatives[l])]
        if now_valid == [owned]:
            print("CONTROL OK: disabling {} lets exactly its own case through".format(which))
            print("    -> {}".format(owned))
        else:
            failures += 1
            print("CONTROL FAIL: disabling {} should free exactly 1 case".format(which))
            print("    expected: [{!r}]".format(owned))
            print("    actual:   {!r}".format(now_valid))

    if failures:
        print("self-test-meta: FAIL ({} control(s))".format(failures))
        return 1
    print("self-test-meta: OK ({} constraints each proved load-bearing "
          "and non-overlapping)".format(len(CONSTRAINT_OWNERS)))
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
    if argv[1] == "--self-test-meta":
        return self_test_meta()
    return validate_file(argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
