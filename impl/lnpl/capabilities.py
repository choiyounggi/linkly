"""설치된 확장 카탈로그 — 실패 없는 발견 표면 (issue #134).

`pg_available_extensions`처럼, 등록된 확장을 실제로 써 보고 틀린 값으로
실패해야만 알 수 있는 상태를 끝낸다. `capabilities_document()`가 그 표면의
유일한 소스다: `lnpl capabilities`(CLI), `lnpl_capabilities`(MCP) 둘 다 이
함수 하나를 부른다.

슬롯당 entry-point 발견은 drivers.py/wsgi.py/kb.py/diagnostics.py/generators.py가
이미 갖고 있는 비공개 발견 함수(`_driver_entry_points` 등)를 그대로 재사용한다 —
새 발견 로직을 만들지 않고, 그 함수들의 시그니처도 바꾸지 않는다. 슬롯 이름은
계약이다: `repository`/`cache`/`network`/`token`/`exporter`/`kb`(issue #134 plan
D1), `diagnostics`(`lnpl.diagnostics`, issue #138)·`generators`(`lnpl.generators`,
issue #139) — 뒤 두 행은 t-diag·t-gen이 각각 연 그룹을 얹은 것으로, 카탈로그
표 형태(슬롯·그룹·내장·발견 함수 4-튜플)는 바뀌지 않는다(additive).

로드 가능 여부는 여기서 독립적으로 판정한다: 각 entry point에 `.load()`를
시도하고, 실패는 예외를 전파하지 않고 `loadable: false`로만 나열한다 —
카탈로그는 진단이지 게이트가 아니다(plan D4). 내장 이름과 같은 이름이
등록되어도(섀도잉) 숨기거나 걸러내지 않고 그대로 나열한다.
"""

from lnpl import __version__
from lnpl import diagnostics as _diagnostics
from lnpl import drivers as _drivers
from lnpl import generators as _generators
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
    ("generators", _generators.GENERATORS_ENTRY_POINT_GROUP,
     _generators.BUILTIN_GENERATORS, _generators._generator_entry_points),
    ("diagnostics", _diagnostics.DIAGNOSTICS_ENTRY_POINT_GROUP, (),
     _diagnostics._extension_entry_points),
    ("kb", _kb.KB_ENTRY_POINT_GROUP, (), _kb._kb_pack_entry_points),
)


# RFC-0043 (issue #138/#140): a driver factory's optional class/static
# `lnpl_enforcement` attribute self-reports how it actually behaves along a
# closed set of axes. Scalar axes validate against a fixed value vocabulary;
# `token_claims` is list-shaped and validated separately below. This table is
# the axis vocabulary's single source in this codebase (plan D1) —
# `docs/ENFORCEMENT-MATRIX.md` §B and `docs/backends.md`'s SPI section are
# human-readable copies of it, not independent definitions.
ENFORCEMENT_AXIS_VALUES = {
    "delivery": ("at-most-once", "at-least-once", "exactly-once"),
    "isolation": ("read-uncommitted", "read-committed", "repeatable-read",
                  "serializable"),
    "cache_scope": ("process-local", "shared"),
}
TOKEN_CLAIMS_AXIS = "token_claims"

# `capability <name>` declaration -> the slot it activates for matching
# purposes (RFC-0043 §매칭 규칙; reuses `SLOTS`' own slot vocabulary above).
# A name outside this table does not participate in enforcement matching —
# it stays a purely descriptive node, same as today.
CAPABILITY_SLOT = {
    "postgres": "repository",
    "redis": "cache",
    "jwt": "token",
    "http": "network",
}


def _enforcement_of(loaded):
    """Validate `getattr(loaded, "lnpl_enforcement", None)` against the closed
    axis table (RFC-0043 §신고 SPI/§신고 어휘와 축).

    - absent, or not a `dict` -> `None` ("no report" — the RFC does not
      specify a malformed-attribute case, so it is treated the same as
      absence, same forward-compat spirit as the "unknown key" rule below).
    - present -> every unknown key is dropped silently (RFC-0043 §신고 SPI,
      explicit forward-compat: a driver may report an axis this core does
      not know yet without failing to load). A known key whose value is
      outside the closed vocabulary (or, for `token_claims`, not a
      `list[str]`) is dropped silently too — the RFC does not specify this
      case; plan D1 treats it the same as an unknown key, by the same
      forward-compat reasoning, rather than rejecting the whole report over
      one bad axis.
    - if nothing survives validation, returns `None` — indistinguishable
      from "no report" for every consumer (a diagnostic needs a validated
      axis to anchor; a catalog entry with nothing to show is not a report
      either), so the two cases collapse rather than surfacing an
      unactionable empty `dict`.
    """
    raw = getattr(loaded, "lnpl_enforcement", None)
    if not isinstance(raw, dict):
        return None
    validated = {}
    for axis, value in raw.items():
        if axis in ENFORCEMENT_AXIS_VALUES:
            if value in ENFORCEMENT_AXIS_VALUES[axis]:
                validated[axis] = value
        elif axis == TOKEN_CLAIMS_AXIS:
            if isinstance(value, list) and all(isinstance(v, str) for v in value):
                validated[axis] = list(value)
        # else: unknown axis key -> ignored (RFC-0043 §신고 SPI)
    return validated or None


def enforcement_reports(slot):
    """`{entry-point name: validated report}` for every installed driver in
    `slot`'s entry-point group that reports at least one axis (RFC-0043
    §매칭 규칙). A driver that fails to load can't report anything
    (`loadable: false` in the catalog) — silently excluded here, same
    load-failure handling `_registered_entries` already applies. A driver
    with no `lnpl_enforcement` (every built-in driver, and any external one
    that does not opt in) contributes nothing either.

    `slot` must be one of `SLOTS`'s own names — an unknown slot is a
    programming error at the call site, not a runtime input, so it raises.
    """
    for slot_name, _group, _builtin, entry_points_fn in SLOTS:
        if slot_name == slot:
            break
    else:
        raise ValueError("unknown slot %r" % slot)
    reports = {}
    for ep in entry_points_fn():
        try:
            loaded = ep.load()
        except Exception:
            continue
        report = _enforcement_of(loaded)
        if report is not None:
            reports[ep.name] = report
    return reports


def _entry_point_version(ep):
    """`ep`'s owning distribution's version, or `None` when the distribution
    can't be resolved (orphaned metadata, a hand-built `EntryPoint`, etc.) —
    never raises (plan D4)."""
    try:
        dist = ep.dist
        return dist.version if dist is not None else None
    except Exception:
        return None


def _registered_entries(entry_points_fn):
    """Name-sorted `{"name", "entry_point", "version", "loadable"}` records —
    `.load()` failure never propagates (plan D4); it is recorded as
    `loadable: false` instead. `entry_point`/`version` are additive (issue
    #134 follow-up, plan D4) — existing `name`/`loadable` keys are unchanged.

    `enforcement` (RFC-0043, issue #138/#140) is additive again: present only
    when `.load()` succeeded and the loaded object's `lnpl_enforcement`
    validates to at least one axis (`_enforcement_of`) — absent otherwise,
    never an empty `dict` ("no report" and "empty report" are different
    facts, RFC-0043 §매트릭스 실측 렌더링 1). The catalog and the compile-time
    diagnostics bridge (`enforcement_diagnostic_records`) read the exact same
    validated report, so they can never disagree about what a driver
    reported."""
    entries = []
    for ep in sorted(entry_points_fn(), key=lambda e: e.name):
        try:
            loaded = ep.load()
            loadable = True
        except Exception:
            loaded = None
            loadable = False
        entry = {"name": ep.name, "entry_point": ep.value,
                 "version": _entry_point_version(ep), "loadable": loadable}
        if loadable:
            report = _enforcement_of(loaded)
            if report is not None:
                entry["enforcement"] = report
        entries.append(entry)
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


# ---------------------------------------------------------------------------
# RFC-0043 §검사 주체/§매칭 규칙: the core bridge from a driver's self-report
# to a `capability` declaration's compile-time diagnostic. Anchors and field
# shapes below were measured, not guessed, against `lnpl compile
# examples/login.lnpl --json` (plan D5) — see each branch's comment for the
# exact node shape it reads.
# ---------------------------------------------------------------------------

def _enforcement_slug(axis, value):
    """`<axis '_'->'-'>-<value>` for a scalar axis; the fixed `token-claims`
    code (no value suffix — a list can't safely ride in a slug) for
    `token_claims` (RFC-0043 §검사 주체)."""
    if axis == TOKEN_CLAIMS_AXIS:
        return "token-claims"
    return "%s-%s" % (axis.replace("_", "-"), value)


def _owner_map(nodes):
    """child node id -> immediate parent node id, built from every
    `children`/`constraints` list any node carries — the only two
    parent-pointing edges the IR uses (measured: `Workflow`/`Guard`/
    `WorkflowStep` chain effects through `children`; `Service` reaches its
    `Security`/`Performance`/`Policy` constraint nodes through
    `constraints`). A `Capability` node has neither kind of incoming edge —
    only a `Service.requires` list points at it, handled separately by
    `_owning_service_by_requires`."""
    owner = {}
    for n in nodes:
        for key in ("children", "constraints"):
            for child_id in (n.get(key) or []):
                owner[child_id] = n["id"]
    return owner


def _nearest_ancestor(node_id, owner, by_id, kind):
    """Walk `owner` up from `node_id` to the nearest ancestor whose `kind`
    matches, or `None` if the chain never reaches one (or `node_id` has no
    parent at all)."""
    current = owner.get(node_id)
    while current is not None:
        node = by_id.get(current)
        if node is not None and node["kind"] == kind:
            return current
        current = owner.get(current)
    return None


def _owning_service_by_requires(cap_id, nodes):
    """The id of the `Service` node whose `requires` list names `cap_id` —
    the one IR edge `_owner_map` cannot see (a `Capability` node is not a
    `children`/`constraints` child of the `Service` that requires it).
    Falls back to `cap_id` itself if no service claims it (a declared-but-
    unattributed capability is not rejected elsewhere in the compiler, so
    this stays defensive rather than raising)."""
    for n in nodes:
        if n["kind"] == "Service" and cap_id in (n.get("requires") or []):
            return n["id"]
    return cap_id


_DELIVERY_MESSAGE = ("the installed %s driver guarantees %s delivery only; "
                      "%s may be delivered more than once")
_ISOLATION_MESSAGE = "the installed %s driver reports %s isolation"
_CACHE_SCOPE_MESSAGE = "the installed %s driver reports %s cache scope"
_TOKEN_CLAIMS_MESSAGE = "the installed %s driver issues claims: %s"


def _delivery_records(ep_name, value, nodes, by_id, owner):
    """Anchor: each `EventEmit` node (RFC-0043 §매칭 규칙 anchor table). The
    direct parent is always its owning `WorkflowStep` (measured: an emit is
    never a bare top-level id, guarded or not — `Guard` wraps the
    `WorkflowStep`, not the effect), whose `name` is the step's surface text
    (e.g. `"emit userCreated"`) — reused verbatim as `subject`, same
    `declared-not-enforced` convention (`lower.py:744`). `where` is the
    nearest ancestor `Workflow`. The event's own surface name (for the
    message) comes from the referenced `Event` node's `name` field."""
    records = []
    for n in nodes:
        if n["kind"] != "EventEmit":
            continue
        step_id = owner.get(n["id"])
        step = by_id.get(step_id)
        subject = step["name"] if step is not None else "emit"
        where = _nearest_ancestor(n["id"], owner, by_id, "Workflow") or step_id
        event = by_id.get(n.get("event"))
        event_name = event["name"] if event is not None else n.get("event")
        records.append({
            "code": "%s/%s" % (ep_name, _enforcement_slug("delivery", value)),
            "severity": "info", "where": where, "subject": subject,
            "message": _DELIVERY_MESSAGE % (ep_name, value, event_name),
            "line": n.get("line"),
        })
    return records


def _isolation_records(ep_name, value, nodes, by_id, owner):
    """Anchor: the module's `capability postgres` declaration node (at most
    one per module, RFC-0043 §매칭 규칙 anchor table). `where` is the
    `Service` whose `requires` names it (no `children`/`constraints` edge
    reaches a `Capability` node, measured). `subject` is `"capability
    postgres"`, the same `"%s %s" % (clause, name)` shape
    `declared-not-enforced` uses."""
    records = []
    for n in nodes:
        if n["kind"] != "Capability" or n.get("name") != "postgres":
            continue
        where = _owning_service_by_requires(n["id"], nodes)
        records.append({
            "code": "%s/%s" % (ep_name, _enforcement_slug("isolation", value)),
            "severity": "info", "where": where, "subject": "capability postgres",
            "message": _ISOLATION_MESSAGE % (ep_name, value),
            "line": n.get("line"),
        })
    return records


def _cache_scope_records(ep_name, value, nodes, by_id, owner):
    """Anchor: each `performance cache <ttl>` budget entry, inside any
    `Performance` node in the module (RFC-0043 §매칭 규칙 anchor table —
    module-wide, not scoped to the service that declared `capability
    redis`, same as the `delivery`/kafka-outbox-adjacent example). `where`
    is the nearest ancestor `Service` (a `Performance` node is always a
    direct `constraints` child of one). Measured: neither the `Performance`
    node nor its `budgets` entries carry a `line` field in the current IR
    schema (`lower.py`'s `_node("Performance", perfid, budgets=budgets)`
    passes no `line=`) — extending that schema is a `lower.py` change, out
    of this task's scope, so `line` is `None` here (RFC-0024's documented
    fallback for "no node the diagnostic is about carries a line")."""
    records = []
    for n in nodes:
        if n["kind"] != "Performance":
            continue
        where = _nearest_ancestor(n["id"], owner, by_id, "Service") or n["id"]
        for budget in n.get("budgets") or []:
            if budget.get("metric") != "cache":
                continue
            records.append({
                "code": "%s/%s" % (ep_name, _enforcement_slug("cache_scope", value)),
                "severity": "info", "where": where,
                "subject": "performance cache %s" % budget.get("value"),
                "message": _CACHE_SCOPE_MESSAGE % (ep_name, value),
                "line": None,
            })
    return records


def _token_claims_records(ep_name, value, nodes, by_id, owner):
    """Anchor: each `security jwt`/`security role <r>` mechanism entry,
    inside any `Security` node in the module (RFC-0043 §매칭 규칙 anchor
    table — module-wide, same reasoning as `cache_scope` above). `where` is
    the nearest ancestor `Service`. Measured: a `Security` node's
    `mechanisms` entries are bare strings (`"jwt"`, `"role admin"`) with no
    per-entry `line` — same schema gap as `Performance`, same `line=None`
    resolution."""
    records = []
    for n in nodes:
        if n["kind"] != "Security":
            continue
        where = _nearest_ancestor(n["id"], owner, by_id, "Service") or n["id"]
        for mechanism in n.get("mechanisms") or []:
            if mechanism != "jwt" and not mechanism.startswith("role "):
                continue
            records.append({
                "code": "%s/%s" % (ep_name, _enforcement_slug("token_claims", value)),
                "severity": "info", "where": where,
                "subject": "security %s" % mechanism,
                "message": _TOKEN_CLAIMS_MESSAGE % (ep_name, ", ".join(value)),
                "line": None,
            })
    return records


_AXIS_RECORD_FNS = {
    "delivery": _delivery_records,
    "isolation": _isolation_records,
    "cache_scope": _cache_scope_records,
    TOKEN_CLAIMS_AXIS: _token_claims_records,
}


def enforcement_diagnostic_records(document):
    """Synthesize RFC-0043's per-axis `info` diagnostics for `document` — the
    core bridge between a driver's self-reported `lnpl_enforcement` and a
    `capability` declaration (RFC-0043 §검사 주체/§매칭 규칙, issue #140).
    Returns the same 6-key record shape
    `diagnostics.extension_diagnostic_records` returns (`code`, `severity`,
    `where`, `subject`, `message`, `line`), so a caller can concatenate the
    two lists without branching.

    Slot activation is module-wide: any `Capability` node whose `name` is in
    `CAPABILITY_SLOT` turns that slot on for the whole document — which
    service (if any) declared it does not narrow which axis anchors fire.
    Once a slot is active, every installed driver in that slot's
    entry-point group is checked, not just the one `--backend` might select
    at run time (RFC-0043 §매칭 규칙: the kafka-outbox-adjacent example has
    `capability postgres` alone activate `repository`, and an unrelated
    `kafka` entry-point's `delivery` report still fires against every
    `EventEmit` in the module).
    """
    nodes = document["nodes"]
    by_id = {n["id"]: n for n in nodes}
    owner = _owner_map(nodes)

    active_slots = set()
    for n in nodes:
        if n["kind"] == "Capability" and n.get("name") in CAPABILITY_SLOT:
            active_slots.add(CAPABILITY_SLOT[n["name"]])

    records = []
    for slot in active_slots:
        for ep_name, report in enforcement_reports(slot).items():
            for axis, value in report.items():
                record_fn = _AXIS_RECORD_FNS.get(axis)
                if record_fn is None:
                    continue
                records.extend(record_fn(ep_name, value, nodes, by_id, owner))
    return records
