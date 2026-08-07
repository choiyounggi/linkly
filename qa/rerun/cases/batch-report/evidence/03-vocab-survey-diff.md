# 어휘 표 재조사 diff — 원 evidence/03 대비 (재측정 r3)

조사 대상(정본): `plugins/lnpl/skills/lnpl-authoring/references/{verbs,grammar,declarations,types,spec}.md`
— 컴파일러 테이블 생성물. 조사 전 생성물 동기화 확인(D3):
`python scripts/gen_plugin_references.py --check` → **rc=0** (evidence/03-genref-check.log)
— references는 컴파일러 테이블과 일치, drift 없음.

원 표: `qa/cases/batch-report/evidence/03-vocab-survey.md` (HEAD=713a4cb 당시).
본 재측정 HEAD: `git rev-parse HEAD` = 00-baseline.md 참조 (main 6d84bd6 이후).
판정 규율(D4, 원 D5 승계): "부재"는 파일+검색어+hits 인용 필수. target missing vs
content missing 구분.

## 원 grep 낱말 전체 재실행 diff

명령(원과 동일 3파일): `for w in <낱말>; do grep -ci "\b$w\b" verbs.md grammar.md declarations.md; done`
(references 디렉터리에서 실행, 3파일 합산)

| 낱말 | 원 hits | 현 hits | 변화 |
|------|---------|---------|------|
| sum | 0 | **0** | 불변 — 집계 동사 여전히 부재 |
| count | 0 | **0** | 불변 |
| aggregate | 0 | **0** | 불변 |
| group | 0 | **0** | 불변 |
| total | 0 | **0** | 불변 |
| reduce | 0 | **0** | 불변 |
| compute | 0 | **0** | 불변 |
| calculate | 0 | **0** | 불변 |
| schedule | 0 | **3** | **신설** — grammar.md:80,82 + declarations.md:34 (아래 원문) |
| cron | 0 | **0** | 불변 |
| daily | 0 | **2** | **신설** — grammar.md:80,82 (스케줄 주기 리터럴) |
| every | 1(산문) | 1(산문) | 불변 — declarations.md:30 "every CacheAccess set" 영어 산문 |
| timer | 0 | **0** | 불변 |
| midnight | 0 | **0** | 불변 (자정은 `at 00:00`으로 표기 — 낱말 아님) |
| interval | 0 | **0** | 불변 |
| idempotent | 1(산문) | 1(산문) | 불변 — declarations.md:22 retry 설명 |
| once | 0 | **0** | 불변 |
| unique | 0 | **0** | 불변 |
| upsert | 0 | **0** | 불변 |
| overlap | 0 | **0** | 불변 |
| singleton | 0 | **0** | 불변 |

## 신규 표면 (원 표에 없던 어휘·문법)

### 동사: 16 → **17** (`set` 신설)

verbs.md:11: `| set | Assignment | — |` — **새 Effect 종류 `Assignment`** 동반
(원 실측: "Effect 체계에 계산 Effect 자체가 없음" → 이제 Assignment가 존재).

### 값 표현식 (grammar.md "## 값 표현식 (RFC-0015)" 절 신설)

- 산술 연산자: `+` `-` (원: 없음)
- 비교 연산자: `<=` `>=` `==` `!=` `<` `>` — **6개** (원 표: "비교 연산자 4개")
- 논리 결합: `and` (`or`·`not`·괄호는 없다 — grammar.md:37 명시)
- 할당: `set <바인딩>.<필드> to <값>` (grammar.md:39)
- 입력 네임스페이스: `input` (grammar.md:41)
- 제약(grammar.md:43): 값은 참조·정수·기간, 이항 산술 **1개**까지
  (`product.stock - input.quantity`), 중첩·괄호 없음.

### 스케줄 선언 (grammar.md:80-84 신설)

```
- `on schedule <주기> at <HH:MM> <존>` — 주기: `daily` / 존: `UTC`
예: `event DailyRollup on schedule daily at 00:00 UTC`
```

grammar.md:84: "스케줄 트리거는 **집행되지 않는다** — IR과 OpenAPI의
`x-lnpl-schedules`까지만 도달하고 실행기는 없다. 선언하면 `declared-not-enforced`
진단이 나온다(집행 매트릭스 참조)."

집행 매트릭스(declarations.md:34): `| event schedule | **unenforced** | no scheduler
runs it; the declaration reaches the IR and the OpenAPI schedule metadata only —
issue #26 (the serving layer) owns the executor |`

### 타입 (types.md)

`DateTime`(`2026-07-31T09:00:00Z`)·`Duration` 등재 (RFC-0016) — 원 표에 없던 시간 값 타입.

### 불변 항목

- 최상위 선언 6개 그대로: `entity service workflow event capability refine` (grammar.md:11)
- 제어 어휘 6개 그대로: `when repeat parallel until pipeline merge` (grammar.md:19)
- policy 허용 이름 4개 그대로: `retry rollback timeout parallel` (declarations.md:11)
- performance 허용 이름 5개 그대로: `response cache parallel prefetch batch`
  (declarations.md:13); `performance batch`는 여전히 **unenforced** (declarations.md:33)

## D12 — 집계 로드맵의 발견 가능성 (F-1 부분 판정 근거)

측정: LLM-only 개발자가 문서 라우팅(authoring references 5종 + SKILL.md + lnpl-kb)으로
"집계는 로드맵에 있다"(RFC-0015 §Alternatives, rfcs/0015-value-semantics.md:322)에
닿을 수 있는가.

```
$ grep -rn -iE "\b(sum|count|aggregate|aggregation)\b|집계" \
    plugins/lnpl/skills/lnpl-authoring/references/*.md \
    plugins/lnpl/skills/lnpl-authoring/SKILL.md \
    plugins/lnpl/skills/lnpl-kb/
→ 1 hit: naming.md:18 `ClickCount → refine.click.count` (네이밍 예시 — 집계와 무관한 우연 일치)
```

**판정: 발견 불가** — 로드맵 결정은 `rfcs/0015-value-semantics.md:322`
"### 집계(`sum`/`count`)를 이번 개정에 넣지 않는 이유"에 존재하나, authoring 문서
라우팅 경로 어디에도 그리로 향하는 포인터가 없다(hits 1건은 우연 일치). sum을 시도해
막힌 저자는 "없다"만 알고 "왜 없는지·언제 오는지"에 닿지 못한다.

## 요구별 판정 갱신 (원 표와 동일 형식 — 사전 판정, 실측은 04~07 증적)

| 요구 | 원 판정 | 갱신 판정 | 근거 |
|------|---------|-----------|------|
| (a) 집계: N행 sum/count | target missing (blocker) | **target missing 잔존** — 단 `set`+산술로 파생값 기록의 절반이 열림(사전 판정, probe-a2/a3에서 실측) | sum/count 0 hits 불변; `set`/`Assignment`/`+`/`-` 신설; 로드맵 발견 불가(위 D12) |
| (b) 스케줄 트리거 | target missing (blocker) | **content missing으로 이동(사전 판정)** — 선언 문법·IR·OpenAPI 메타데이터는 존재, 실행기는 부재(unenforced 명시) | grammar.md:80-84, declarations.md:34; probe-b1에서 실측 |
| (b2) 중복 실행 정책 | target missing | **target missing 잔존** | overlap/singleton/once 전부 0 hits 불변 |
| (b3) 재실행 멱등 | target missing | **target missing 잔존** | idempotent 1 hit(산문) 불변 |
| (c) 집계 결과 조회 | 표현 가능 | **표현 가능 유지** | load/find/read 동사 존속(verbs.md 17개 표) |
