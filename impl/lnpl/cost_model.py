"""The per-operation execution cost contract (issue #164).

Unlike `vocab.py`/`grammar.py`, this module does not serialize an existing
compiler constant table — no Big-O fact lives anywhere else in the codebase
as a literal. `COST_TABLE` below is the first place those facts are written
down. Whether any given row is still true has to be checked by re-reading
the file:line range its `evidence` field names — if `repo_policy.py` or
`drivers.py` change shape, re-examine this table first.
"""

# Exactly 7 rows (this issue's scope): `list where` with and without driver
# pushdown, `order by`, `limit`, the 5 aggregate functions (one row — they
# share a complexity class), cache get/set, and the single-row read.
COST_TABLE = [
    {
        "operation": "list_where_no_pushdown",
        "complexity": "O(n) filter, O(n log n) if order by",
        "status": "current",
        "evidence": "impl/lnpl/repo_policy.py:218-239",
        "note": ("전체 행 fetch 후 Python에서 필터/정렬, limit은 조기 종료 "
                 "없이 슬라이스"),
    },
    {
        "operation": "list_where_pushdown",
        "complexity": "O(n) — 인덱스 없음, 복잡도 불변",
        "status": "current",
        "evidence": "impl/lnpl/drivers.py:394-425",
        "note": ("json_extract 필드에 CREATE INDEX 없음 — pushdown은 IO/"
                 "전송량 개선일 뿐, SQLite도 풀스캔"),
    },
    {
        "operation": "order_by",
        "complexity": "O(n log n)",
        "status": "current",
        "evidence": "impl/lnpl/repo_policy.py:236",
        "note": ("Python Timsort(무pushdown) 또는 SQLite 외부 정렬"
                 "(pushdown) — 양쪽 경로 동일 클래스"),
    },
    {
        "operation": "limit",
        "complexity": "O(n) (조기 종료 없음)",
        "status": "current",
        "evidence": "impl/lnpl/repo_policy.py:239",
        "note": ("필터링된 전체 리스트를 만든 뒤 슬라이스 — limit이 스캔 "
                 "범위를 줄이지 않음"),
    },
    {
        "operation": "aggregate_count_sum_avg_min_max",
        "complexity": "O(n) 단일 패스",
        "status": "current",
        "evidence": "impl/lnpl/interp.py:928-1150",
        "note": "5종 전부 메모리의 RowSet 위 단일 패스, 별도 정렬 없음",
    },
    {
        "operation": "cache_get_set",
        "complexity": "드라이버/서버 의존적 — 이 레포가 계약 불가",
        "status": "current",
        "evidence": ("impl/lnpl/drivers.py:299-306, "
                     "impl/lnpl/interp.py:278"),
        "note": ("코어에는 FakeCache 참조 구현(O(1) dict)만; 영속 캐시는 "
                 "외부 바인딩 lnpl-redis(#143, 단일 원자 `SET key value "
                 "PX ttl_ms` — docs/backends.md:263)로 출하됨. 복잡도는 "
                 "Redis 서버 특성(GET/SET 평균 O(1))이며 외부 저장소의 "
                 "특성이라 이 레포의 계약으로 승격할 수 없다"),
    },
    {
        "operation": "single_row_read",
        "complexity": "O(log n) 근사(B-tree)",
        "status": "current",
        "evidence": "impl/lnpl/drivers.py:394-403",
        "note": ("유일하게 PRIMARY KEY(entity_id,row_key) 인덱스를 타는 "
                 "행 — 표에서 가장 강한 보장"),
    },
]


def cost_model_document(table=None):
    """Envelope match `grammar_json_document()`'s `_generated` sibling-key
    pattern (issue #162 machine-artifact-path)."""
    table = table if table is not None else COST_TABLE
    return {
        "_generated": {
            "by": "scripts/gen_plugin_references.py",
            "source": "impl/lnpl/cost_model.py:cost_model_document()",
            "hand_edit": False,
        },
        "cost_model": table,
    }
