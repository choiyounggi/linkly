"""어휘 매니페스트 — CLI·MCP·생성 스크립트가 공유하는 단일 소스 (issue #135).

닫힌 어휘가 학습 데이터에 없다는 문제는 지금까지 Claude Code 플러그인의 한국어
마크다운(`plugins/lnpl/skills/lnpl-authoring/references/`)에서만 풀렸다 —
벤더 중립 채널이 없었다. `vocabulary_document()`가 그 채널의 유일한 소스다:
`lnpl vocab`(CLI), `lnpl_vocabulary`(MCP), `scripts/gen_plugin_references.py`
(마크다운 생성) 셋 다 이 함수 하나를 부른다.

정본은 여전히 컴파일러 모듈의 상수다(VERB_LEXICON, KEYWORDS_TOP, CODES 등) —
이 모듈은 그 상수를 JSON 직렬화 가능한 형태로 옮기기만 한다. 새 상수를 만들지
않는다.
"""

from lnpl import __version__
from lnpl.diagnostics import CODES, ENFORCEMENT, SEVERITY_OF
from lnpl.lexer import (ARITH_OPS, ASSIGN_KEYWORDS, COMPARATORS,
                        DURATION_UNITS, GUARD_ALT_KEYWORD, KEYWORDS_CLAUSE,
                        KEYWORDS_CONTROL, KEYWORDS_TOP, LOGICAL_OPS,
                        PAYLOAD_NAMESPACE, RESERVED, SCHEDULE_AT,
                        SCHEDULE_KEYWORD, SCHEDULE_RECURRENCES, SCHEDULE_ZONES)
from lnpl.lower import (ARGUMENT_MECHANISMS, PERF_METRICS, POLICY_NAMES,
                        READ_VERBS, SECURITY_MECHANISMS, VALUELESS_PERF,
                        VERB_LEXICON)
from lnpl.refinements import BASE_CATEGORY, CATEGORY_FACETS, PRESETS
from lnpl.spec import EXPECTATIONS, GIVEN_FORMS
from lnpl.types import SEMANTIC_TYPES


def _json_safe_check(check):
    """`SEMANTIC_TYPES[...]["check"]` as JSON — `("py", pytype)` names the type.

    `check` is `None` (no Phase 1 rule), so this returns `[]` rather than
    `null` (D2: no empty-collection key is ever `null`).
    """
    if check is None:
        return []
    return [item.__name__ if isinstance(item, type) else item for item in check]


def vocabulary_document():
    """벤더 중립 어휘 매니페스트. 최상위 키는 고정이다 — 빠지지 않는다.

    빈 컬렉션은 `[]`/`{}`로 실린다 — `null`은 어디에도 쓰지 않는다(예: 검사
    규칙이 없는 semantic type의 `check`는 `None`이 아니라 `[]`).
    """
    return {
        "lnpl_version": __version__,
        "verbs": {
            verb: {"effect": effect, "attrs": dict(attrs)}
            for verb, (effect, attrs) in VERB_LEXICON.items()
        },
        "keywords": {
            "top": list(KEYWORDS_TOP),
            "clause": list(KEYWORDS_CLAUSE),
            "control": list(KEYWORDS_CONTROL),
            "read_verbs": list(READ_VERBS),
            "duration_units": list(DURATION_UNITS),
            "comparators": list(COMPARATORS),
            "arithmetic_operators": list(ARITH_OPS),
            "logical_operators": list(LOGICAL_OPS),
            "guard_alt_keyword": GUARD_ALT_KEYWORD,
            "assign_keywords": list(ASSIGN_KEYWORDS),
            "payload_namespace": PAYLOAD_NAMESPACE,
            "schedule_keyword": SCHEDULE_KEYWORD,
            "schedule_at": SCHEDULE_AT,
            "schedule_recurrences": list(SCHEDULE_RECURRENCES),
            "schedule_zones": list(SCHEDULE_ZONES),
        },
        "types": {
            "semantic": {
                name: {
                    "openapi": meta["openapi"],
                    "sample": meta["sample"],
                    "check": _json_safe_check(meta["check"]),
                }
                for name, meta in SEMANTIC_TYPES.items()
            },
            "base_category": dict(BASE_CATEGORY),
            "category_facets": {
                category: sorted(facets)
                for category, facets in CATEGORY_FACETS.items()
            },
            "presets": {
                name: {"base": spec["base"], "facets": dict(spec["facets"])}
                for name, spec in PRESETS.items()
            },
        },
        "clauses": {
            "policy": list(POLICY_NAMES),
            "security": list(SECURITY_MECHANISMS),
            "performance": list(PERF_METRICS),
            "security_argument_mechanisms": list(ARGUMENT_MECHANISMS),
            "performance_valueless": list(VALUELESS_PERF),
        },
        "enforcement": [
            {"clause": clause, "name": name, "status": status, "why": why}
            for (clause, name), (status, why) in ENFORCEMENT.items()
        ],
        "diagnostics": [
            {"code": code, "severity": SEVERITY_OF[code]} for code in CODES
        ],
        "reserved": list(RESERVED),
        "spec_expectations": {
            "expects": sorted(EXPECTATIONS),
            "given_forms": [
                {"id": key, "pattern": form, "doc": doc}
                for key, form, doc in GIVEN_FORMS
            ],
        },
    }
