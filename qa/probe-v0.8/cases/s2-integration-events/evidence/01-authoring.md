# 01-authoring — orders-lite

충전: "s2.md R1/R2/R5로 outbound call·결과 바인딩·fallback·이벤트 발행을
선언할 수 있는지 탐색" (90분 타임박스, task 02 §1)

round 1 | `create order as order` | 컴파일 거부: `as order`가 entity Order의 단일 행 바인딩 소문자 이름과 충돌 (RFC-0027 §2) | rfcs/0037-http-resilience.md 예제(`call ... as fxResult`)를 그대로 따랐으나 create 대상 엔티티와 같은 소문자 이름을 결과 바인딩에 재사용할 수 없다는 점은 그 예제에 없었다 — 컴파일러 자체가 유일한 문서
round 2 | `as order` → `as o` | 컴파일 거부: `set o.fxStatus to "live"` — invalid operand '"live"' | rfcs/0015-value-semantics.md L118-119 `Operand ::= Reference \| Integer \| Duration` — 리터럴 Text 없음. `set ... to`로 문자열 상수를 못 씀
round 3 | `set o.fxStatus to "live"` → `format o.fxStatus "live"` | 컴파일 거부: "format needs a target and `from \"<template>\"`" — 컴파일러가 정확한 형태를 스스로 제시 | plugins/lnpl/skills/lnpl-authoring/references/verbs.md는 `format`이 `Assignment`라고만 적고 문법을 안 보여줌; rfcs/0039 L59-61이 "format의 저장 표현식 문법"을 언급만 하고 정확한 `from` 키워드는 어디에도 문서화돼 있지 않음(진단 메시지가 유일한 출처) — doc 마찰 후보
round 4 | `format o.fxStatus "live"` → `format o.fxStatus from "live"` | 컴파일 거부: `o.totalKrw`(Decimal)에 산술(`*`) 불가 — "RFC-0016 computes over whole numbers and instants only (Money and the composite types have no evaluator in either mode)" | rfcs/0028-arithmetic-and-alternative-guards.md L50 "정수 나눗셈으로 좁히고(Decimal 없음)"과 완전히 일치 — Decimal/Money 필드는 `set` 산술의 대상이 될 수 없음이 두 문서(RFC-0028 motivation, 컴파일러 진단)에서 교차 확인됨
round 5 | `totalUsd`/`totalKrw` 타입을 Decimal → Integer로 변경, payload도 `10.00` → `10`(정수)으로 변경 | **컴파일 성공, rc=0, 진단 0건(`--strict=warning`, `--strict` 둘 다)** | 우회 성공하되 의미 손실: 요구사항 원문의 "10.00 USD"라는 소수 화폐 표현을 잃는다 — Money/Decimal이 산술 불가능하므로 정수 단위(달러 정수)로 표현을 낮췄다. 실서비스라면 센트 단위 정수로 정밀도를 지킬 수 있지만, 그래도 통화 곱셈(달러×환율)의 정밀도 손실 위험은 남는다(F-항목으로 기록, task 07)

round 6 | (task 03) round 5 소스로 `lnpl run --payload order-1.json --network http --endpoint Fx=...` 실행 | **런타임 실패**: `status: failed`, `failure_reason: "Cannot compare non-numeric fxResult.rate=1350.5 in condition 'o.totalUsd * fxResult.rate'"` | Integer 필드(o.totalKrw)로 컴파일은 통과했지만, 실행 시 곱셈 상대인 `fxResult.rate`(스텁이 실제로 낸 1350.5, 실수)가 "non-numeric"으로 거부됨 — 메시지 자체가 부정확하다(1350.5는 수치다, "정수가 아니다"가 맞는 서술) → 진단 품질 마찰(축 diag) 겸 표현력 마찰(축 expr)
round 7 | `set o.totalKrw to o.totalUsd * fxResult.rate` → `set o.totalKrw to o.totalUsd`(곱셈 제거, 그대로 복사) | **런타임 성공**(rc=0, `status: completed`), 그러나 저장값 `totalKrw=10`은 `10 × 1350.5 = 13505`가 아니다 | 우회 성공, 의미 손실 명시: 실제 환율 반영이 전혀 이뤄지지 않음(요구사항의 핵심 계산 자체를 포기) — R1 커버리지 표에 `우회(의미 손실: total_krw가 실제 환율로 곱해지지 않고 total_usd를 그대로 복사)`로 기록. 3회 우회 시도(round 5/6/7 자체가 이미 그 상한) 끝에 "실제 환산 곱셈"은 **불가**로 확정 — Decimal에 산술 평가기가 없고(RFC-0028), Integer 산술도 비정수 피연산자를 거부하므로, lnpl 0.8.0에서 실수 계수를 정수/화폐 필드에 곱하는 방법이 전혀 없다(검토한 대안: 정수 단위 유지, 소수 반올림, format 재파싱 모두 산술 evaluator 자체가 실수를 안 받아 무의미)

round 8 | (task 03, B3) `capability http Fx`에 `retry 2 backoff 200ms` 선언한 상태로 500,500,200 스텁 실행, 쿼리스트링 없는 endpoint로 재시도(격리) | **재시도가 전혀 발생하지 않음** — 스텁 로그에 GET 1회만 기록, `fxResult.status=500`으로 즉시 fallback. IR을 직접 검사해 `capability` 노드에 `retry:{count:2,backoff_ms:200}`가 정확히 실려 있음을 확인(선언 자체는 올바름) | rfcs/0037-http-resilience.md §Reference-level 2 "재시도 대상: ... 5xx(501 제외)"를 그대로 따랐다. 컴파일은 통과하고 IR도 올바른데 `--network http`(HttpNetworkDriver) 실행이 재시도를 안 함 — 축 rt(런타임 의미론), severity 후보 blocker
round 9 | round 8에 `policy retry 3`(워크플로 스텝 레벨)을 추가로 얹어 재시도 유도 시도(별도 실험 파일, 소스에는 반영 안 함) | 여전히 스텁 로그 1회만 — `policy retry`는 "스텝이 예외로 실패했을 때" 재시도이지, "스텝은 성공했지만 HTTP 500을 받았다"는 상황에 적용되지 않음(RFC-0037의 capability-레벨 회복성과 별개 메커니즘) | 우회 실패 — 3번째 시도. capability http의 `retry` 선언이 실측상 재시도를 집행하지 않는다는 것을 **3회 서로 다른 각도**(기본 endpoint, 쿼리스트링 제거, policy retry 추가)로 확인 → R3의 "재시도" 부분은 **불가**로 기록(재시도 횟수 자체를 관측할 수 없음). B4(타임아웃)는 별도로 동작함(round 11 참고) — 타임아웃과 재시도는 이 플랫폼에서 독립 실측 결과를 낸다
round 10 | (task 03, B5) `when fxResult.status == 200`만으로는 `{"rate":"abc"}`(status 200)를 "live"로 오분류함을 실행으로 확인 → `when fxResult.status == 200 and fxResult.rate >= 0`로 응답 바디 형태 검증 시도 | 컴파일은 성공(rc=0)하지만 **실행이 rc=3(런타임 에러)로 크래시** — "Cannot compare non-numeric fxResult.rate='abc'" — 가드 평가 자체가 예외를 던져 워크플로 전체가 죽음(거짓으로 평가돼 조용히 다른 분기로 넘어가는 게 아니라 크래시) | 가드로 응답 바디의 자료형을 검사하는 시도가 "우회"는커녕 원래보다 더 나쁜 결과(정상 완료도 아니고 fallback도 아니고 크래시)를 냄 — R4의 "본문 검증" 요구는 **불가**로 기록. 이 언어에는 문자열/숫자 판별 가드가 없고, 숫자가 아닌 값을 산술/비교 컨텍스트에 넣으면 그 실행 전체가 죽는다(가드가 그 스텝만 skip하는 게 아니라 워크플로를 RunError로 끝냄)

round 11 | (task 04) notifier: `refine NotificationStatus of Text enum delivered needs_manual` | 컴파일 거부: "'needs_manual' is not a valid enum value (a Word or a Number)" | enum 리터럴 어휘가 스네이크_케이스를 허용하지 않음(밑줄 금지) — camelCase로 전환
round 12 | `needsManual`로 수정, `set n.orderId to input.id`(순수 참조 복사, 산술 없음) | 컴파일 거부: round 4/7과 **글자까지 같은 메시지** — "declared type Text is neither Integer nor DateTime" | **정정**: round 4에서는 이 제약이 산술(`*`) 때문이라고 가정했으나, 이 라운드가 반증한다 — 산술이 전혀 없는 단순 참조 대입도 같은 진단으로 거부된다. `set`은 애초에 **Integer/DateTime 필드만** 타겟으로 삼을 수 있다(RFC-0016 스코프) — Text/UUID/Money 등 그 외 타입 필드는 산술 유무와 무관하게 `set`으로 못 씀, 무조건 `format`만 가능
round 13 | `format n.orderId from "{}" with input.id` | **컴파일 성공(rc=0)** | 우회 성공, 의미 손실 없음 — `format`의 `{}` 치환이 순수 참조 복사의 일반 수단(문자열류 필드는 전부 이 경로)

round 14 | (task 06) orders.lnpl에 spec 3블록 추가, `result o.fxStatus == live/fallback` | 컴파일 거부: round 4/7/12와 같은 계열의 진단 — "Cannot compare non-numeric o.fxStatus='live'" | `result`도 `set`/가드와 같은 비교 평가기를 공유 — Text/enum 필드는 spec에서도 값 단언 불가(플랫폼 전역 제약의 4번째 확인)
round 15 | `result o.fxStatus == ...` → `result fxResult.status == 200`/`!= 200`(우회: Integer 필드로 대체) | **컴파일+실행 성공** — 8 passed, 1 failed(의도적 레드, R4 결함을 spec이 포착) | 우회 성공, 의미 손실: 실제 저장값이 아니라 네트워크 응답의 status 코드를 판별 신호로 대체 — R2/R4는 부분 충족으로 기록

## 요약

- 라운드: 5 (authoring→compile 사이클)
- 첫 컴파일 성공까지 라운드: 5
- 핵심 발견: Decimal/Money 필드는 `set`의 산술 피연산자가 될 수 없다(RFC-0028
  motivation이 이미 "Decimal 없음"이라고 명시). `set`은 문자열 리터럴을 받지
  않는다 — `format <target> from "<template>"`가 유일한 문자열 대입 경로이고,
  그 정확한 문법(`from` 키워드)은 어떤 참조 문서에도 없고 컴파일러 진단에만
  있다.
