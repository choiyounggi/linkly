"""설치된 확장 카탈로그 — 실패 없는 발견 표면 (issue #134).

`pg_available_extensions`처럼, 등록된 확장을 실제로 써 보고 틀린 값으로
실패해야만 알 수 있는 상태를 끝낸다. `capabilities_document()`가 그 표면의
유일한 소스다: `lnpl capabilities`(CLI), `lnpl_capabilities`(MCP) 둘 다 이
함수 하나를 부른다.

슬롯당 entry-point 발견은 drivers.py/wsgi.py/kb.py가 이미 갖고 있는 비공개
발견 함수(`_driver_entry_points` 등)를 그대로 재사용한다 — 새 발견 로직을
만들지 않고, 그 함수들의 시그니처도 바꾸지 않는다. 슬롯 이름은 계약이다:
`repository`/`cache`/`network`/`token`/`exporter`/`kb`(issue #134 plan D1) —
`diagnostics`(`lnpl.diagnostics`)와 `generators`(`lnpl.generators`)는 각각
t-diag·t-gen이 소유하는 별도 카탈로그 행이라 여기 없다.

로드 가능 여부는 여기서 독립적으로 판정한다: 각 entry point에 `.load()`를
시도하고, 실패는 예외를 전파하지 않고 `loadable: false`로만 나열한다 —
카탈로그는 진단이지 게이트가 아니다(plan D4). 내장 이름과 같은 이름이
등록되어도(섀도잉) 숨기거나 걸러내지 않고 그대로 나열한다.
"""

from lnpl import __version__
from lnpl import drivers as _drivers
from lnpl import kb as _kb
from lnpl import wsgi as _wsgi

# slot -> (entry-point 그룹명, 내장 이름들, entry-point 발견 함수). 나중 슬롯
#추가는 이 시퀀스에 행 하나를 더하는 일이 되게 한다(plan D2).
SLOTS = (
    ("repository", _drivers.DRIVERS_ENTRY_POINT_GROUP, _drivers.BACKENDS,
     _drivers._driver_entry_points),
    ("cache", _drivers.CACHES_ENTRY_POINT_GROUP, _drivers.CACHES,
     _drivers._cache_entry_points),
    ("network", _drivers.NETWORKS_ENTRY_POINT_GROUP, _drivers.NETWORKS,
     _drivers._network_entry_points),
    ("token", _drivers.TOKENS_ENTRY_POINT_GROUP, _drivers.BUILTIN_TOKEN_PROVIDERS,
     _drivers._token_entry_points),
    ("exporter", _wsgi.EXPORTERS_ENTRY_POINT_GROUP, _wsgi.EXPORTERS,
     _wsgi._exporter_entry_points),
    ("kb", _kb.KB_ENTRY_POINT_GROUP, (), _kb._kb_pack_entry_points),
)


def _registered_entries(entry_points_fn):
    """Name-sorted `{"name", "loadable"}` records — `.load()` failure never
    propagates (plan D4); it is recorded as `loadable: false` instead."""
    entries = []
    for ep in sorted(entry_points_fn(), key=lambda e: e.name):
        try:
            ep.load()
            loadable = True
        except Exception:
            loadable = False
        entries.append({"name": ep.name, "loadable": loadable})
    return entries


def capabilities_document():
    """설치 확장 카탈로그. 최상위 키는 고정이다 — 빠지지 않는다.

    빈 등록은 `[]`로 실린다 — 빈 카탈로그도 성공이다(rc 0).
    """
    return {
        "lnpl_version": __version__,
        "slots": {
            slot: {
                "builtin": list(builtin),
                "registered": _registered_entries(entry_points_fn),
            }
            for slot, _group, builtin, entry_points_fn in SLOTS
        },
    }
