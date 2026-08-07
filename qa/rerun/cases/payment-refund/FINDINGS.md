# FINDINGS — payment-refund (재측정 r2)

측정 대상: 결제 승인·환불 워크플로우의 .lnpl 표현력과 런타임 집행 — 민감정보 마스킹,
정책 선언, 금액·기간 경계값. 기준 commit 6d84bd6 (#43~#50 구현, RFC-0014~0017),
lnpl 0.2.0, 2026-08-07. 원 실측(713a4cb, 2026-08-05, qa/cases/payment-refund/) 대비
재측정이며, 원 F-1~F-14 대비 판정은 DELTA.md에 있다.
차터: LLM-only 개발자 페르소나 — 스킬 문서(plugins/lnpl/skills/**)·examples·rfcs
0015/0016만 읽고 개발, impl/ 미열람, 플랫폼 무수정. 명령·출력 원문: evidence/raw/.

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| authoring | PASS | evidence/01-authoring-discovery.md | 비의도 실패 0 (의도적 거부 프로브 3: b1·b2·b3) + spec 블록 수정 3 (evidence/08) |
| parse | PASS | evidence/01, raw/compile-b4-final.err | 0 (최종 파일 1회 통과) |
| lower | PASS (18 nodes) | evidence/02-compile.md | 0 |
| validate | PASS | evidence/03-validate.md | 0 |
| modeA | PASS | evidence/04-modeA-masking.md, raw/run-*.out | 워크플로 재실행 0 (+경계·창·부분 payload 프로브 14실행) |
| modeB | PASS | evidence/05-modeB.md, raw/build-*.out | 0 |
| differential | PASS (EQUIVALENT 4/4 ×2 워크플로) | evidence/06-differential.md | 0 |
| openapi | PASS | evidence/07-openapi.md | 0 |
| spec | **PARTIAL (10 passed, 1 failed)** | evidence/08-spec.md | 3 (수정 시도 한도 소진) |

원 실측과 달리 이 초록은 **우회의 누적이 아니다** — 제품 요구 5개(입력 금액 검증,
0<금액≤한도, 30일 환불 창, 전액/부분 환불 구분, 정상+에러+경계 spec)가 전부
**원형대로 선언**됐고, spec 1단언(가드-참 정상 경로의 steps 2)만 spec 러너 제약으로
FAIL이 남았다(그 경로 자체는 mode A/B 실행으로 실증 — N-2).

## Frictions (재측정에서 새로 관측된 것)

### N-1: 합집합 payload의 동명 필드 충돌 — mode A run으로 비대칭 값 주입 불가
- 단계: modeA · 심각도: minor
- 재현: payload는 전 엔티티 필드의 합집합이고 read 행 시드도 같은 payload에서 온다 —
  `amountCents`가 Payment·Refund 양쪽에 선언돼 있어 `input.amountCents ≠
  payment.amountCents`인 실행을 `lnpl run`으로 만들 수 없다 (evidence/04 §6:
  bindings.payment에 requestedAt·paymentId까지 복사됨, raw/run-refund-day5.out)
- 기대: 입력 금액과 저장 행 금액을 독립 지정(전액/부분/초과 구분의 런타임 실측)
- 실제: run 채널에서는 항상 동치 — 구분 실측은 mode B `--field`(성공, evidence/05)
  또는 spec stored(N-2로 불완전)로만
- 재시도: 0 · 우회: 있음 — mode B `--field input.amountCents=… payment.amountCents=…`
  독립 주입으로 전액/부분/초과 전부 관측 완료

### N-2: spec에서 read-행 참조 가드를 참으로 만들 수 없음 — 가드-참 정상 경로의 spec 계약화 불가
- 단계: spec · 심각도: major
- 재현: RefundRequest 정상 블록에 `stored payment id/amountCents/createdAt` 3필드 +
  `amountCents 3`(부분 환불) given → 4회 시도 전부 steps=1 (create refund 스킵,
  raw/spec-run{,2,3,4}.out). 같은 가드가 CLI run(payload 시드)·mode B에서는 참
  (evidence/04 §2, 05)
- 기대: stored로 행을 깔면 read가 그 행을 바인딩하고 가드가 참 — `expect steps 2`
- 실제: stored 행 명시에도 가드 거짓 평가. FAIL 행은 어느 항이 거짓인지·바인딩이
  무엇인지 출력하지 않아(spec 실패의 진단 채널 부재) 문서 표면만으로 원인 확정 불가
- 재시도: 3 · 우회: 부분 — 가드-참 경로는 run/build 증적으로 대체, spec 기대치는
  원형(steps 2)대로 남겨 rc=1을 측정값으로 기록

### N-3: create 충돌 의미 관측 불가 — 중복 결제 에러 시나리오 표현 수단 부재
- 단계: spec · 심각도: minor
- 재현: `given stored Payment id 3f2504e0-…`(create가 쓸 payload id와 동일) 후
  `create payment` → completed·attempts=1, 충돌 없음 (raw/spec-run2.out)
- 기대: 같은 키의 사전 행이 있으면 create 실패(중복 결제 거부) 또는 그 의미의 문서화
- 실제: 조용히 completed — upsert인지 별도 키인지 문서·출력 어느 쪽도 답하지 않음
- 재시도: 1 · 우회: 있음 — 에러 클래스는 empty repository(find 실패→retry→failed)로
  계약화(RefundRequest 블록 2 PASS)

### N-4: 시간 문법의 발견 경로가 RFC 번호 인지에 의존
- 단계: authoring(발견 과정) · 심각도: info
- 재현: grammar.md는 단위 `d`와 "(RFC-0016)" 괄호 표기까지만 제공 — 30일 창의 원형
  (`input.requestedAt - payment.createdAt <= 30d`)과 "주입식 now" 관례는 RFC-0016
  본문에만 있고, 스킬 라우팅 표에는 rfcs/로 가는 행이 없다 (evidence/01 홉 표)
- 기대: authoring 라우팅에서 시간창 질의가 문서로 연결
- 실제: RFC 번호 단서로 2홉 만에 도달(재시도 0) — 원 실측(3실패 후 우회) 대비 극적
  개선이나, kb 질의 "환불 기간 제한 정책"은 여전히 no match(F-14 잔여)
- 재시도: 0 · 우회: 불필요

## 총평

원 실측의 판정 근거였던 **무증상 실패 양식이 소멸했다.** 연쇄 가드는 무진단 탈락
대신 교정 안내를 담은 파싱 에러가 되고(F-2), Money 가드는 런타임 크래시 대신 컴파일
시점 도메인 진단이 되고(F-4), 가드 skip은 구조화 레코드+진단+`--strict` rc=2로
기계 판독 가능하며(F-6), 카드번호는 trace·bindings 양 채널에서 `***`다(F-7 — 채널별
네거티브 컨트롤 동반 확인). 제품 요구 5개는 전부 원형 표현으로 도달했다: `input.`
가드(입력 검증), `and` 범위(0·음수·한도초과 거부 + 정확히 한도 승인), DateTime 산술
30일 창(30일째 포함, 존 없는 값은 도메인 진단), `==`/`<=` 필드 간 비교(전액/부분/
초과), spec 5블록(정상·에러·경계 공존, 블록 독립 평가). 재시도 곡선도 뒤집혔다 —
원 실측은 우회 도달까지 편집 9회·spec 6회였으나, 재측정은 본선 표현이 1회 컴파일에
통과하고 재시도는 spec 러너 제약(N-2) 진단에만 3회 쓰였다. 남은 마찰은 spec 러너의
시드 의미(N-2·N-3)와 run payload의 네임스페이스 평면성(N-1)으로, 정책 표현력이 아니라
**검증 하네스의 커버리지**에 몰려 있다. 케이스 판정과 원 F-1~F-14 전건 대비는
DELTA.md에 있다.
