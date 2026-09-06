# FINDINGS — s2-integration-events

환경: 커밋 264e3442d653e5534d827687ebac5ede956e801a, lnpl 0.8.0, python 3.13.1,
드라이버 none(내장 sqlite/http만), dev_doctor rc=1(MLIR/LLVM 미설치 — mode B
미사용이라 이 케이스에는 무관, evidence/00-env.md)
조건: 블랙박스(requirements/README.md §2), impl/ 열람 0회, impl/ 수정 0건

최종 purity (`git status --porcelain -uall`, 케이스 디렉터리 밖 라인 0개):
```
$ git status --porcelain -uall | grep -v '^?? qa/probe-v0.8/cases/s2-integration-events/'
(출력 없음)
```
전체 출력은 `qa/probe-v0.8/cases/s2-integration-events/**` 아래 34개 `??`
라인뿐(evidence 파일들 + src/**) — 이 케이스 밖 변경 0건, `impl/` 수정 0건.
스텁/serve/relay 프로세스는 매 태스크 종료마다 kill 후 `ps aux`로 확인,
`.claude/tmp/s2-pids.txt`는 최종적으로 비어 있음.

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| authoring | PASS | evidence/01-authoring.md | 15 (round 1-15, 내역은 해당 문서) |
| compile(--strict=warning) | PASS | evidence/02-compile.md | (authoring 라운드에 포함) |
| modeA run | PASS | evidence/03-run.md | 0 (B1 1회로 성공) |
| spec | PASS(부분) | evidence/04-spec.md | 2 (round 14 실패 → round 15 우회) |
| openapi | PASS | evidence/05-openapi.md | 0 |
| serve(실 HTTP) | PASS | evidence/06-serve.md | 0 |
| failure-branches(B2-B5) | PASS(혼합) | evidence/07-failure-branches.md | 3(B3 재시도 조사 3회) |
| outbox-relay | PASS(부분) | evidence/08-outbox-relay.md | 0 |
| idempotency-compensation-correlation | PASS(부분) | evidence/09-idempotency-compensation-correlation.md | 0 |

## 요구사항 커버리지

| R | 요구 | 판정 | 근거(evidence 경로 + 실행 출력 인용) |
|---|------|------|--------------------------------------|
| R1 | 실 아웃바운드 호출 + total_krw 실반영 | 우회(의미 손실: total_krw가 실제 환율로 곱해지지 않고 total_usd를 그대로 복사함) | evidence/03-run.md — 스텁 로그 1줄로 실 소켓 증명, `fxResult:{"rate":1350.5,"status":200}` 실제 반영은 됨; evidence/01-authoring.md round 6/7 — 곱셈 자체가 런타임에서 "Cannot compare non-numeric fxResult.rate=1350.5"로 거부됨 |
| R2 | 실패 분기(fx_status live/fallback) | 충족 | evidence/07-failure-branches.md B1/B2 — fx_status가 정확히 live/fallback으로 갈림; "이전 성공 환율 캐시" 세부는 미구현(곱셈 자체가 불가라 캐시해도 의미 없음, 본문 참고) |
| R3 | 재시도·타임아웃 | 우회(의미 손실: 타임아웃은 충족하나 재시도는 불가) | evidence/07-failure-branches.md B4 — wall=1.15s(<2s), 실 소켓 연결 확인; B3 — `capability http Fx`에 `retry 2`를 선언·IR에도 반영됐지만 스텁 로그가 GET 1회뿐(재시도 미발동), 3가지 각도로 재확인(evidence/01-authoring.md round 8/9) |
| R4 | 응답 검증(비수치 값 거부) | 불가 | evidence/07-failure-branches.md B5 — `{"rate":"abc"}`(status 200)가 live로 오분류됨; 가드로 형식검증 시도 시 rc=3 크래시(round 10) — "Cannot compare non-numeric fxResult.rate='abc'" |
| R5 | outbox 발행(both-or-neither) | 우회(의미 손실: 원자성은 충족하나 이벤트 페이로드에 total_krw/fx_status를 못 실음) | evidence/08-outbox-relay.md — 정상경로 both 존재 확인; 실패주입(가드 크래시)으로 both **부재** 확인(원자성 실측); outbox emission payload가 `{"id":"o-1","totalUsd":10}`뿐 — `emit`에 필드 매핑 문법이 없음 |
| R6 | relay→소비→웹훅 | 충족 | evidence/08-outbox-relay.md, evidence/06-serve.md — Notification 행 생성, hook 1회 POST 200 확인; `event_id`는 CloudEvents 봉투의 `id`가 워크플로 input에 노출 안 돼 order id로 대체(minor, F-9) |
| R7 | 멱등 소비 | 충족 | evidence/09-idempotency-compensation-correlation.md §B6 — 같은 CloudEvents id 2회 POST, Notification 1행·hook 1회·응답 correlation_id까지 바이트 동일(재생 증명) |
| R8 | 보상 | 우회(의미 손실: needs_manual 상태 자체는 충족하나 "3회 연속 실패" 조건은 불가 — 1회 실패로 즉시 전환) | evidence/09-idempotency-compensation-correlation.md §B7 — needsManual 세팅 확인, 다음 이벤트(o-b7-2) 정상 처리 확인; 구조적 이유(NetworkCall이 HTTP 상태와 무관하게 예외를 안 던져 RFC-0040 §7의 503 재시도 사다리가 발동할 방법이 없음) 상세 서술 |
| R9 | correlation id 추적 | 불가 | evidence/09-idempotency-compensation-correlation.md §R9 — 6홉 표, cid-0001/emission_id/outbox-seq-id/req-id 4개의 무관한 식별자로 쪼개짐(hop 1→2에서 이미 끊김), outbox 스키마에 correlation 컬럼 자체가 없음 |
| R10 | spec 표현 | 부분 | evidence/04-spec.md — R2/R4는 `fxResult.status`(대리 신호)로만 부분 표현(엔티티 저장값 `o.fxStatus`는 Text라 `result`로 단언 자체가 컴파일 거부됨); R3/R7은 spec 어휘에 다중 응답 시퀀스·반복 호출 시나리오가 없어 불가; spec이 R4의 실제 결함(레드 1건)을 기계로 포착 |

## Frictions

### F-1: Decimal/Money 필드는 산술의 대상이 될 수 없다
- 단계: authoring | 심각도: blocker | 축: expr
- 재현: `set order.totalKrw to order.totalUsd * fxResult.rate`(둘 다 Decimal)
  → `lnpl compile` "invalid arithmetic operator... whose declared type
  Decimal is neither Integer nor DateTime — RFC-0016 computes over whole
  numbers and instants only (Money and the composite types have no
  evaluator in either mode)"
- 기대 vs 실제: rfcs/0037-http-resilience.md 예제(`call PaymentGateway`)를
  따라 실 환율을 곱하는 워크플로를 기대 vs `set` 산술 자체가 Decimal을
  거부
- 재시도: 1 | 우회: 성공 — Integer로 필드 타입 강등(F-2로 이어짐)
- 보완 제안: Decimal/Money 전용 산술 evaluator(최소 곱셈 1건)를 열거나,
  "화폐 계산은 이 언어 밖(호스트 코드)에서 하라"는 것을 authoring 문서에
  명시해야 한다 — 지금은 시도해 보기 전까지 이 제약 자체를 알 방법이
  없다(RFC-0028 motivation을 안 읽으면 영원히 모름).

### F-2: Integer 필드도 실수(비정수) 피연산자와의 산술이 런타임에 크래시한다
- 단계: modeA run | 심각도: blocker | 축: expr
- 재현: `o.totalKrw`(Integer) = `o.totalUsd * fxResult.rate`(1350.5, 스텁이
  실제로 낸 실수) → rc=1, `failure_reason: "Cannot compare non-numeric
  fxResult.rate=1350.5 in condition ...`
- 기대 vs 실제: F-1의 우회(Integer로 강등)로 컴파일은 통과했지만 실행이
  또 다른 이유로 실패 — 문서 어디에도 "산술 evaluator가 정수만 받는다"고
  명시적으로 경고하지 않음(RFC-0028이 "정수 나눗셈으로 좁혔다"고만 서술)
- 재시도: 1 | 우회: 성공 — 곱셈 자체를 포기하고 totalUsd를 그대로 복사
  (의미 손실 — R1 참고)
- 보완 제안: 진단 메시지를 "non-numeric"에서 "non-integer"로 정정하면
  최소한 원인 파악 시간이 줄어든다(지금 메시지는 1350.5가 수치가 아니라고
  말해 저자를 오도한다).

### F-3: `set`은 Integer/DateTime 필드만 대상으로 삼을 수 있다(산술 유무 무관), 문자열 대입은 `format ... from`만 가능하며 정확한 문법이 컴파일러 진단에만 있다
- 단계: authoring | 심각도: major | 축: expr, doc
- 재현: `set order.fxStatus to "live"` → "invalid operand '\"live\"'";
  `set n.orderId to input.id`(순수 참조 복사, 산술 없음) → "declared type
  Text is neither Integer nor DateTime"; `format o.fxStatus "live"` →
  "format needs a target and `from \"<template>\"`"
- 기대 vs 실제: `references/verbs.md`는 `format`이 `Assignment`라고만 적고
  문법을 보여주지 않는다. 정확한 형태(`format <target> from "<template>"
  [with <ref>...]`)는 어느 참조 문서·RFC에도 없다 — 컴파일러 진단이 유일한
  출처
- 재시도: 3(round 1-3, round 12) | 우회: 성공, 의미 손실 없음
- 보완 제안: `references/verbs.md`의 `format` 행에 정확한 문법을 한 줄
  추가하면 이 마찰 전체(라운드 3회)가 없어진다.

### F-4: `capability http`의 `retry` 선언이 컴파일·IR엔 정확히 반영되지만 `--network http` 실행에서 전혀 발동하지 않는다
- 단계: failure-branches(B3) | 심각도: blocker | 축: rt
- 재현: `capability http Fx: retry 2 backoff 200ms`, IR 확인(`retry:
  {"count":2,"backoff_ms":200}`), 500,500,200 스텁 대상 실행 → 스텁 로그
  GET **1회만**. 쿼리스트링 제거·`policy retry 3` 추가 두 가지 각도로도
  재현(evidence/01-authoring.md round 8/9)
- 기대 vs 실제: rfcs/0037-http-resilience.md §Reference-level 2 "재시도
  대상: ... 5xx(501 제외)" vs 실측 0회 재시도
- 재시도: 3 | 우회: 실패 — 불가로 확정
- 보완 제안: `HttpNetworkDriver`가 회복성 코어(`_call_with_resilience`)를
  실제로 호출하는지 회귀 테스트가 필요해 보인다(측정 대상 플랫폼 버그
  가능성 — 수리는 이 태스크 범위 밖).

### F-5: 응답 본문 형식 검증(비수치 값 거부)을 이 언어로 표현할 방법이 없고, 시도하면 워크플로 전체가 크래시한다
- 단계: failure-branches(B5) | 심각도: blocker | 축: expr, rt
- 재현: `when fxResult.status == 200 and fxResult.rate >= 0` 컴파일은
  성공하지만 실행이 rc=3으로 크래시(비수치 비교)
- 기대 vs 실제: s2.md R4 "빈 본문이나 비수치 값이면 fallback" vs 이 조건을
  가드로 표현하면 조용한 skip이 아니라 예외로 전체 워크플로가 죽음
- 재시도: 1(가드 시도) | 우회: 실패 — 불가로 확정
- 보완 제안: 가드 조건에 "값이 숫자인가"를 판정하는 안전한 predicate(예:
  `is-numeric`)가 없으면, 외부 API 응답의 shape을 방어적으로 검사하는
  워크플로 자체가 이 언어로 원천적으로 못 써진다 — 통합 시나리오의
  핵심 요구.

### F-6: `emit <eventName>`의 페이로드는 워크플로 입력으로 고정되고, 서버 계산 필드(`set`/`format`으로 채운 값)를 실을 방법이 없다
- 단계: outbox-relay(R5) | 심각도: blocker | 축: expr
- 재현: `create order as o` → `format o.fxStatus from "live"` → `emit
  orderPlaced` 이후 `lnpl_outbox`의 payload가 `{"id":"o-1","totalUsd":10}`
  — 워크플로 INPUT과 바이트 동일. `fxStatus`/`totalKrw`는 없음
- 기대 vs 실제: s2.md R5 "OrderPlaced{order_id, total_krw, fx_status}" vs
  실제로는 order_id에 해당하는 값만 자동으로 실림(그나마 필드명이 `id`라
  우연히 겹침)
- 재시도: 0(문법 자체가 없어 시도할 지점이 없음 — grammar.md/
  ENFORCEMENT-MATRIX.md 재확인, `emit`에 `with`/필드매핑 절 없음) | 우회:
  실패 — 불가로 확정
- 보완 제안: `emit <event> with <ref>...` 같은 명시적 페이로드 매핑 절이
  필요하다 — 지금은 RFC-0001의 `EventEmit.payloadMap` IR 필드가 저작
  문법에 전혀 노출되지 않는다.

### F-7: NetworkCall이 어떤 HTTP 상태에도 예외를 던지지 않아, "N회 연속 실패 후 보상"류의 사다리(RFC-0040 §7 503-재시도)를 구성할 방법이 없다
- 단계: idempotency-compensation-correlation(B7) | 심각도: major | 축: rt
- 재현: hook 500 응답에도 `call Hook as hookResult`가 정상 반환(예외
  없음) → 워크플로가 항상 `completed`로 끝나 인입 라우트가 항상 200을
  반환 → relay가 503을 볼 일이 없어 재시도 사다리 자체가 발동 안 됨.
  needsManual은 1회 실패만으로 즉시 세팅됨(3회 아님)
- 기대 vs 실제: s2.md R8 "3회 연속 실패하면 needs_manual" vs 1회 실패로
  즉시 needs_manual, 그리고 "연속" 자체를 셀 방법(명시적 fail/abort 동사
  없음)이 없음
- 재시도: 0(구조적 한계 확인 — 우회 시도할 지점 자체가 없음, VERB_LEXICON에
  워크플로를 명시적으로 실패시키는 동사가 없음) | 우회: 부분 성공(상태값
  자체는 세팅되나 횟수 조건은 불가)
- 보완 제안: RFC-0040의 D7 3갈래 분류가 저작 표면에서 발동되려면, NetworkCall
  결과에 "이 실패를 워크플로 실패로 승격한다"는 명시적 선택지(가드 실패 시
  RunError로 escalate하는 동사 등)가 필요하다.

### F-8: correlation id가 6홉 전체를 관통하지 않는다 — 서로 무관한 식별자 4개로 쪼개짐
- 단계: idempotency-compensation-correlation(R9) | 심각도: major | 축: ops
- 재현: orders-lite `lnpl run`의 `correlation_id`(고정값 `cid-0001`,
  CLI가 명시적으로 안 넘기면) → outbox `emission_id`(effect-id 카운터,
  무관) → relay가 만드는 CloudEvents `id`(`outbox-<seq>`, 무관) →
  notifier 접속로그 `correlation_id`(요청마다 새로 채번되는 `req-...`,
  무관) — 4개 전부 다른 값
- 기대 vs 실제: s2.md R9 "하나의 correlation id로 이어진 로그" vs
  `lnpl_outbox` 스키마 자체에 correlation 컬럼이 없음(seq/emission_id/
  event/payload/created_at/delivered_at 6컬럼뿐, docs/backends.md §3)
- 재시도: 0(스키마 확인만으로 결론 — 우회 지점 없음) | 우회: 실패 — 불가
- 보완 제안: outbox·CloudEvents 봉투·서빙 로그 세 지점 모두에 "originating
  correlation_id"를 명시적으로 실어 나르는 컬럼/필드가 필요하다(지금은
  order_id 같은 도메인 필드가 우연히 살아남는 것에 의존).

### F-9: notifier가 CloudEvents 봉투의 진짜 `event_id`를 워크플로 안에서 알 수 없다
- 단계: outbox-relay(R6) | 심각도: minor | 축: expr
- 재현: 워크플로 `input`은 봉투의 `data`뿐(RFC-0040 §6) — 봉투 자체의
  `id`/`source`/`type`은 멱등 클레임에만 쓰이고 워크플로에 안 넘어옴
- 기대 vs 실제: s2.md R6 "Notification{event_id, order_id, status}" vs
  event_id를 채울 참조가 없어 order id로 대체
- 재시도: 0 | 우회: 부분 성공(대체 필드로 스키마 형태는 맞춤, 의미는 다름)
- 보완 제안: 인입 워크플로 input에 `_envelope.id`류의 예약 필드를 추가
  하면 해소된다.

### F-10: `guard-skipped-steps` 경고와 event-consume 접속 로그의 `workflow: null`이 정상 분기 실행 관측을 방해한다
- 단계: modeA run / serve | 심각도: minor | 축: diag, ops
- 재현: 모든 정상적인 `when`/`else` 분기 선택마다 "the workflow still
  reports completed, so a caller reading only the status cannot tell this
  run from one that ran every step" 경고가 뜬다(설계된 분기인데도). serve
  의 `--log-format json` 접속 로그는 event-consume 라우트에서 `workflow`
  필드를 항상 `null`로 남긴다(evidence/06-serve.md)
- 기대 vs 실제: 경고 자체는 의도된 관측 장치이나, 매 실행마다 뜨는 것이라
  실제 이상 징후와 구분이 안 됨; 접속 로그로 "이 요청이 어느 워크플로를
  돌렸는지" 알 수 없음
- 재시도: 0 | 우회: 해당 없음(관측 마찰이지 기능 결함 아님)
- 보완 제안: 접속 로그의 `workflow` 필드를 event-consume 라우트에서도
  채우면 R9 관측이 한 홉만큼은 나아진다.

### F-11: OpenAPI에 event-consume 라우트가 전혀 안 실려 "이 서비스가 어떤 이벤트를 소비하는지"를 API 계약만으로 알 수 없다
- 단계: openapi | 심각도: minor | 축: doc
- 재현: notifier.lnpl의 OpenAPI 문서 `paths`가 완전히 빈 배열(`service`
  미선언이라 일반 라우트도 없고, event-consume 라우트는 설계상 OpenAPI
  제외 대상 — RFC-0040 §4)
- 기대 vs 실제: R10 "네트워크 분기를 spec으로 표현" 검증 과정에서 발견 —
  OpenAPI만 보고 통합 지점을 파악하려는 개발자(또는 LLM 에이전트)는
  이 서비스가 이벤트를 소비한다는 사실 자체를 놓친다
- 재시도: 0 | 우회: 해당 없음
- 보완 제안: OpenAPI 확장 필드(`x-lnpl-schedules`와 같은 자리에
  `x-lnpl-consumes`)로 이벤트 소비 계약을 노출하면 해소된다.

## 케이스 판정

**Block** — F-4, F-5, F-6이 우회 불가(3회 이상 우회 시도 실패 또는 시도할
문법 지점 자체가 없음, FINDINGS-SCHEMA §1 blocker 정의 "요구사항을
우회로도 충족 못 함"에 정확히 부합)로 확정된 채 남는다:

1. `capability http`의 `retry` 선언이 실행에서 완전히 no-op이다(F-4) —
   3가지 각도(기본 endpoint·쿼리스트링 제거·`policy retry` 추가)로도
   재시도가 한 번도 발동하지 않았다. 이건 "느리지만 된다"가 아니라
   **조용히 아무 일도 안 하는** 성격이라, 재시도가 필요한 아웃바운드
   연동은 이 선언을 신뢰할 수 없고 우회할 방법도 없다(자체 재시도
   래퍼를 lnpl 밖에 새로 짜는 것은 "이 언어의 기능을 우회"가 아니라
   "이 언어의 기능을 포기하고 대체"하는 것 — README의 "우회" 기준을
   충족하지 못한다).
2. 응답 본문 검증(비수치 값 거부)은 표현 문법 자체가 없고, 시도하면
   워크플로 전체가 크래시한다(F-5) — 외부 API의 방어적 응답 검증이
   필요한 모든 통합에 적용되는 근본 제약이며 우회 지점이 없다.
3. `emit`은 서버 계산 필드를 이벤트에 실을 수 없다(F-6) — 저작 문법에
   페이로드 매핑 절 자체가 없어(grammar.md/ENFORCEMENT-MATRIX.md
   재확인) 시도할 지점조차 없다. 이벤트 기반 통합(S2의 핵심 축)에서
   "발행 시점에 계산된 값을 이벤트에 담아 보낸다"는 요구를 이 언어의
   저작 표면으로는 절대 만들 수 없다.

F-1/F-2(Decimal/Money 산술 불가)도 blocker로 유지한다 — "환율 계산을
lnpl 밖에서 미리 하고 정수 결과만 넘긴다"는 완화책은 검토했지만, 이는
R1이 실제로 묻는 것("네트워크 응답값을 워크플로가 스스로 계산에
반영하는가")을 포기하고 다른 질문으로 바꿔치기하는 것이라 README §4
의 "우회"(요구사항의 일부를 포기하고 나머지를 충족) 기준으로도 인정하기
어렵다 — R1의 핵심 주장 자체가 성립하지 않는다.

F-4/F-5/F-6 세 가지가 각각 이 시나리오의 세 축(연동 신뢰성·응답 방어·
이벤트 payload 설계) 전부에서 "우회로도 안 됨"으로 확정됐고, 그 중 어느
하나도 소유자가 "known issue로 받아들이고 넘어갈" 성격이 아니다(F-4는
조용한 데이터/신뢰성 손실, F-5는 정상적인 방어 코드가 오히려 크래시를
유발, F-6은 이벤트 기반 아키텍처의 전제 자체를 무너뜨림) — qa/rerun/
REPORT.md의 규약대로 "아무도 못 받아들이는 known issue는 Block"에
해당한다. R2/R6/R7이 충족되고 both-or-neither 원자성(R5의 절반)이
실측으로 증명된 것은 이 언어가 완전히 못 쓸 정도는 아님을 보여주지만,
S2가 시험하려는 "연동 상품"의 세 핵심 축이 전부 막혀 있어 Ship 계열
어느 쪽으로도 정당화되지 않는다.
