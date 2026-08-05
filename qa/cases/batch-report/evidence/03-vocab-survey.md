# 어휘 조사 — 세 요구 vs lnpl 0.2.0 어휘 표

조사 대상(정본): `plugins/lnpl/skills/lnpl-authoring/references/{verbs,grammar,declarations,types,spec}.md`
(컴파일러 테이블 생성물, lnpl 0.2.0). 보조: `examples/{shorten,checkout}.lnpl`.
판정 규칙(D5): "부재"는 파일+검색어+0 hits 인용 필수. target missing(어휘 자체 없음)
vs content missing(이름은 있으나 의미 불충분) 구분.

## 확보된 어휘 전체 (탐색 공간의 상한)

- **동사 16개** (verbs.md — 이 표 밖 동사는 no-op): validate, authenticate, load,
  find, read, create, insert, update, delete, cache, invalidate, call, request,
  emit, publish, authorize
- **최상위 선언 6개** (grammar.md): entity, service, workflow, event, capability, refine
- **제어 어휘 6개** (grammar.md): when, repeat, parallel, until, pipeline, merge
- **policy 절 허용 이름** (declarations.md): retry, rollback, timeout, parallel
- **performance 절 허용 이름** (declarations.md): response, cache, parallel, prefetch, batch
- **event 문법** (examples 실측): `event <Name> on <Entity> <lifecycle>` — 엔티티
  생명주기 훅. 시간 트리거 형태 없음.

## 요구별 판정 근거

| 요구 | 후보 어휘 | 근거 | 구분 | 다음 액션 |
|------|-----------|------|------|-----------|
| (a) 집계: sum/count 계산 | sum, count, aggregate, group, total, reduce, compute, calculate | verbs.md+grammar.md+declarations.md grep -ci 전부 **0 hits** (각 낱말별 실행 기록은 아래 grep 로그) | **target missing** — 계산/집계 동사가 어휘에 없음. Effect 체계(Validation/RepositoryCall/CacheAccess/NetworkCall/EventEmit/Authorization)에 계산 Effect 자체가 없음 | 프로브 a1(그럴듯한 동사 → no-op 확인), a2(어휘 내 동사만으로 어디까지 가는지), a3(repeat/until로 우회 시도) |
| (a) 보조 증거 | — | examples/checkout.lnpl 헤더 주석이 `total`(Money 필드)을 스스로 "서술" — 계산되지 않는 필드로 분류 | 공식 예제도 합계를 계산하지 않음 | a2에서 실측 확인 |
| (b1) 스케줄 트리거 | schedule, cron, daily, every, timer, midnight, interval | 동일 3파일 grep **0 hits** (`every`의 1 hit는 declarations.md:30 "every CacheAccess set" — 영어 산문, 어휘 아님) | **target missing** — 시간 트리거 어휘 없음. 최상위 선언 6개·제어 어휘 6개·policy/performance 허용 이름 어디에도 시간 표현 없음. 기간 단위(ms/s/m)는 timeout/cache TTL 값에만 쓰임 | 프로브 b1(그럴듯한 스텝 동사 → no-op), b2(policy 절에 미허용 이름 → 거부되는지), b3(`performance batch` — 이름은 있으나 unenforced 명시 실측) |
| (b1) 유사 이름 함정 | `performance batch` | declarations.md:13,16,33 — 이름은 허용 목록에 **존재**하나 집행 매트릭스가 "**unenforced** — parsed, but the execution plan never reads it" 명시 | **content missing** — 이름이 파싱되지만 배치 실행 의미 없음 (브리프의 핵심 함정 유형과 정확히 일치) | 프로브 b3에서 진단 노출 여부 실측 |
| (b2) 중복 실행 정책 | overlap, singleton, once | grep **0 hits**; policy 허용 이름은 retry/rollback/timeout/parallel 닫힌 4개 (declarations.md:12) | **target missing** | b1 결과에 연동 — b1 부재 시 N/A(blocked)로 기록 (checks-that-cannot-pass: 부재의 연쇄를 FAIL로 부풀리지 않음) |
| (b3) 재실행 멱등 | idempotent, unique, upsert | grep **0 hits** (`idempotent` 1 hit는 declarations.md:22 retry 설명 산문 — "재실행이 멱등일 때만 retry" 즉 멱등을 선언하는 게 아니라 전제함) | **target missing** — 멱등 선언 어휘 없음 | b1과 동일 처리 |
| (c) 집계 결과 조회 | load, find, read + workflow + entity | verbs.md 표에 세 동사 모두 존재(RepositoryCall read); examples/shorten.lnpl·checkout.lnpl이 동형 패턴 실증 | **표현 가능(사전 판정)** | Task 05에서 조립·실측 |

## grep 실행 기록 (D5 증거)

```
$ cd plugins/lnpl/skills/lnpl-authoring/references
$ for w in sum count aggregate group total reduce compute calculate schedule cron \
    daily every timer midnight interval idempotent once unique upsert overlap singleton; do
    grep -ci "\b$w\b" verbs.md grammar.md declarations.md ...
sum:0 count:0 aggregate:0 group:0 total:0 reduce:0 compute:0 calculate:0
schedule:0 cron:0 daily:0 every:1(산문) timer:0 midnight:0 interval:0
idempotent:1(산문) once:0 unique:0 upsert:0 overlap:0 singleton:0
```

산문 히트 2건의 원문:
- declarations.md:22 `policy retry | enforced | run_workflow re-runs a failed step while its effects are idempotent`
- declarations.md:30 `performance cache | enforced | owns the TTL budget every CacheAccess set is written with`
