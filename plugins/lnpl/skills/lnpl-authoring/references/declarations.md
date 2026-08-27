<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# 선언과 집행 (ENFORCEMENT)

> lnpl 0.5.0 기준.

선언했다고 집행되는 것이 아니다. 아래 표가 정본이다 — `enforced`만 실행을 바꾼다. `measured`는 관측·보고하되 막지 않고, `unenforced`는 런타임이 완전히 무시한다(issue #38).

## 절별 허용 이름

- `policy`: `retry` `rollback` `timeout` `parallel`
- `security`: `jwt` `role`
- `performance`: `response` `cache` `parallel` `prefetch` `batch`

인자를 받는 security 기제: `role`
값 없이 쓰는 performance 지표: `parallel` `prefetch` `batch`

## 집행 매트릭스

| 선언 | 상태 | 런타임이 실제로 하는 일 |
|------|------|--------------------------|
| `policy retry` | **enforced** | run_workflow re-runs a failed step while its effects are idempotent |
| `policy timeout` | **enforced** | a workflow deadline is computed, and exceeding it fails the run |
| `policy rollback` | **enforced** | run_workflow opens a transaction before its first step and rolls it back on any failure, discarding every write (and outbox registration) that run made |
| `policy parallel` | **unenforced** | parsed, but the execution plan never reads it |
| `security jwt` | **unenforced** | the default path issues and verifies nothing; `lnpl serve --jwt-secret-env NAME` verifies the bearer token per request (docs/serving.md M3a, docs/backends.md) |
| `security role` | **enforced** | every route the declaring service owns requires the verified token's role to exactly match `<r>`; mismatch or absence is 403 `forbidden` (docs/serving.md M3b) |
| `performance response` | **measured** | measured and reported per run, but an over-budget run is not blocked |
| `performance cache` | **enforced** | owns the TTL budget every CacheAccess set is written with |
| `performance parallel` | **unenforced** | parsed, but the execution plan never reads it |
| `performance prefetch` | **unenforced** | parsed, but the execution plan never reads it |
| `performance batch` | **unenforced** | parsed, but the execution plan never reads it |
| `event schedule` | **unenforced** | by default nothing calls it; `lnpl trigger --schedule NAME` and `POST /-/schedules/<slug>` (`lnpl serve`) run the linked workflow on demand, but only when an external scheduler (cron/systemd — see `lnpl schedules`) is configured to call one of them (issue #81) |

## 진단 코드

등급은 `--strict[=LEVEL]`이 무엇을 게이팅하는지를 정한다(RFC-0021). `warning`은 프로그램을 고치면 사라지는 것이고, `info`는 고쳐도 사라지지 않는 플랫폼 상태의 진술이다.

| 코드 | 등급 |
|------|------|
| `unknown-verb` | **warning** |
| `unknown-entity` | **warning** |
| `declared-not-enforced` | **info** |
| `declared-measured-only` | **info** |
| `authorization-not-verified` | **warning** |
| `guard-skipped-steps` | **warning** |
| `guard-orphaned-steps` | **warning** |
| `validation-sample-derived` | **info** |
| `aggregation-orphaned-list` | **warning** |
| `event-source-mismatch` | **warning** |
| `event-source-orphaned` | **info** |
| `derived-never-assigned` | **warning** |
| `declared-not-bound` | **info** |
| `stored-row-shape-mismatch` | **warning** |
| `rollback-escapes-network` | **warning** |
| `retry-on-non-idempotent` | **warning** |
