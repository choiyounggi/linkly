# FINDINGS — payment-refund

측정 대상: 결제 승인·환불 워크플로우의 .lnpl 표현력과 런타임 집행 — 민감정보 마스킹,
정책 선언, 금액·기간 경계값. 기준 commit 713a4cb, lnpl 0.2.0, 2026-08-05.
차터·시도 계수 규칙·타임라인: evidence/session-log.md. 명령·출력 원문: evidence/raw/.

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| authoring | PASS | evidence/01-authoring-discovery.md, evidence/02-compile.md | 편집 9회 (가드 3·엔티티 2·spec 4) |
| parse | PASS | evidence/02-compile.md, evidence/raw/compile-a*.err | 8 (에러 3·성공 5) |
| lower | PASS (24 nodes) | evidence/02-compile.md | 8 (parse와 동일 명령) |
| validate | PASS | evidence/03-validate.md | 4 (재컴파일마다 재검증, 전부 PASS) |
| modeA | PASS | evidence/04-modeA-masking.md, evidence/raw/run-*.out | 워크플로당 2 (+경계 프로브 6실행) |
| modeB | PASS | evidence/05-modeB.md | 1 |
| differential | PASS (EQUIVALENT 4/4 ×2 워크플로) | evidence/06-differential.md | 1 |
| openapi | PASS | evidence/07-openapi.md | 1 |
| spec | PASS (4 passed, 0 failed) | evidence/08-spec.md | 6 |

전 단계 PASS이지만 이는 **우회를 누적한 뒤의 초록**이다 — 요구사항 원형(입력 금액 검증,
0<금액≤한도 범위, 30일 기간, 전액/부분 환불 비교, 3시나리오 spec)은 어느 것도 원형대로
표현되지 못했다. 상세는 Frictions.

## Frictions

### F-1: 가드가 read된 저장 행만 참조 가능 — "입력값 검증" 표현 불가
- 단계: parse(바인딩 검사) · 심각도: major
- 재현: `workflow Approval / validate payment / when payment.amount > 0 / create payment`로 컴파일 (evidence/raw/compile-a3.err)
- 기대: 워크플로 입력 payment의 금액을 가드로 검증 (케이스 요구 "결제 승인(금액 검증)")
- 실제: `compile error: workflow Approval: guard condition 'payment.amount <= 10000' reads entity.payment, but this workflow never reads it — no binding can ever exist, so the guard would be false forever`
- 재시도: 1 · 우회: 있음 — `find payment` 후 `update payment`로 "기존 pending 결제의 승인"으로 의미 재해석(RFC-0012 실행 스코프의 checkout 패턴). 진단 품질은 높음(원인+귀결 설명).

### F-2: 연쇄 `when` 가드 중 첫 번째가 진단 없이 IR에서 탈락
- 단계: lower · 심각도: major (귀결은 자금 무결성 — F-6과 결합 시 심각)
- 재현: `when payment.amount > 0`과 `when payment.amount <= 10000`을 연달아 선언 → IR 확인: `wf.approval.guard.1` 하나만 존재, condition은 두 번째 것 (evidence/02-compile.md; T05 런타임 증명: amountCents 0·-1 payload가 **승인됨**, evidence/04)
- 기대: 두 가드 모두 집행되거나, 최소한 진단으로 탈락을 경고
- 실제: 컴파일 rc=0·무경고, 하한 가드 소실 — 0원·음수 결제가 completed
- 재시도: 0 (IR 검사로 발견) · 우회: 부분 — 가드를 1개로 줄여 상한만 유지, 하한은 소실 문서화. `unknown-verb`류 no-op에는 진단이 있지만 가드 탈락에는 없다 — "선언이 파싱만 되고 무시되는" 사례의 가드 판.

### F-3: 조건 결합(AND)·등가(==) 표현 불가 — 범위·전액 환불 검증 불가
- 단계: authoring · 심각도: major
- 재현: grammar.md 연산자 목록(`<= >= < >`)에 등가·논리 결합 부재; F-2로 연쇄도 불가; `refund.amount <= payment.amount`는 F-4의 형식 제한(`<value>`는 Integer/Duration 리터럴만)으로 불가
- 기대: 0 < amount ≤ 한도 범위 검증, 전액(==)/부분(<)/초과(>) 환불 구분
- 실제: 단일 가드에 단일 비교·리터럴 우변만 — 범위는 상한 하나로 축소, 환불 상한은 주석 문서화만
- 재시도: 2 · 우회: 부분(축소 표현만 가능)

### F-4: Money 필드 가드 — 컴파일 통과 후 런타임 raw traceback 크래시
- 단계: modeA · 심각도: major
- 재현: `when payment.amount <= 10000` (Money 타입) 컴파일(무경고) 후 `lnpl run --workflow wf.approval --json …` (evidence/raw/run-approval-default.err 시도 1)
- 기대: 컴파일 시점 타입 거부, 또는 런타임 도메인 진단
- 실제: rc=1, `TypeError: '<=' not supported between instances of 'dict' and 'int'` — interp.py:289 Python 스택트레이스 그대로 노출
- 재시도: 1 · 우회: 있음 — `amountCents Integer` 필드 추가(F-16 성격의 이중 필드 부담). 진단 품질 최하(내부 구현 누출, 원인 위치 미안내).

### F-5: 기간 정책(결제 후 30일 이내) 표현 불가
- 단계: authoring·modeA · 심각도: major
- 재현: ① `refund.requestedAt - payment.createdAt <= 30d` → `compile error: … unsupported condition form … <value> is Integer or Duration` ② `… <= 30d` → `invalid value '30d'` (day 단위 없음 — 단위는 ms/s/m뿐) ③ `payment.createdAt <= 43200m` → 컴파일 통과 후 런타임 `runtime error: Cannot compare non-numeric payment.createdAt='2026-07-31T09:00:00Z' in condition …`
- 기대: 시간창 정책 선언 (케이스 요구 "결제 후 30일 이내만 환불 가능")
- 실제: DateTime 산술·비교 모두 불가; ③은 컴파일과 런타임의 판정 불일치(늦은 실패)
- 재시도: 3 · 우회: 있음(고통) — 사전 계산 `ageDays Integer` 필드 + `when payment.ageDays <= 30`; 나이 갱신 책임이 플랫폼 밖(데이터 적재층)으로 전가됨.

### F-6: 가드 false = 조용한 skip, 워크플로는 completed·rc=0
- 단계: modeA · 심각도: major (F-2와 결합 시 정책 위반이 무증상)
- 재현: amountCents=1000001 payload로 `lnpl run` (evidence/raw/run-approval-amt1000001.out)
- 기대: 한도 초과 결제는 실패(또는 최소한 비-성공 상태)로 관측
- 실제: `"status": "completed"`, rc=0, 흔적은 `"skipped": ["wf.approval.guard.1"]`와 trace INFO `"guard skipped the guarded item"`뿐 — 승인 거절과 승인 성공이 최상위 신호로 구별 불가
- 재시도: 0 · 우회: 부분 — 호출자가 skipped 배열을 검사해야 함(문서화된 계약 아님). spec의 `expect completed steps 2`로 이 동작을 계약화할 수는 있음(단 F-10·11로 불가했음).

### F-7: 마스킹 부분 집행 — trace는 `***`, result.bindings는 원문 노출
- 단계: modeA · 심각도: **blocker** (민감정보 누출 경로, .lnpl 내 우회 없음)
- 재현: `lnpl run --workflow wf.approval --json …` 출력에서 cardNumber(Password 타입) 검색 (evidence/04-modeA-masking.md; run-approval-amt1000001.out 30행 vs 122행)
- 기대: Password 타입 주도 마스킹이 모든 출력 채널에 적용 (declarations.md: "Password masking is a separate, type-driven behaviour")
- 실제: trace 채널 `"cardNumber": "***"` (마스킹 집행 확인 — 네거티브 컨트롤: 같은 출력의 amountCents는 평문), **result.bindings 채널 `"cardNumber": "4111111111111111"` 원문** — 시드 값 `s3cret-value`도 동일 노출. grep 전수: json 출력마다 원문 1히트.
- 재시도: 0 · 우회: **없음** — 필드는 필수(F-13)라 제거 불가, 응답 채널 선택 수단 없음. 마스킹 기제는 실재하나 채널 하나가 새면 없는 것과 같다.

### F-8: OpenAPI `writeOnly` 계약과 런타임 동작의 모순
- 단계: openapi · 심각도: major
- 재현: 생성된 payment-refund.openapi.json의 `cardNumber: {"type":"string","format":"password","writeOnly":true}` vs F-7의 bindings 원문 반환 (evidence/07-openapi.md)
- 기대: 문서 계약 = 런타임 동작
- 실제: 문서는 "응답에 미출현(writeOnly)"을 약속, 런타임은 원문 반환 — 문서가 런타임보다 안전을 과대 광고
- 재시도: 0 · 우회: 없음(생성물 수정 금지). 문서 표면 자체는 우수(예시 누출 0, bearerAuth 오퍼레이션별 적용) — F-7 해소 시 자동 정합.

### F-9: differential의 마스킹 검사가 누수 채널을 비교 표면에 포함하지 않음
- 단계: differential · 심각도: minor
- 재현: `lnpl diff` → `PASS 4/4 masking — no secret marker in either mode's output` + `EQUIVALENT`인 상태에서 F-7 누수 공존 (evidence/06-differential.md)
- 기대: "masking PASS"가 모든 출력 채널의 마스킹을 의미
- 실제: 비교 표면에 mode A `--json` result.bindings 미포함 — 검사 초록이 '검증됨'이 아니라 '본 표면에 없음'
- 재시도: 0 · 우회: 해당 없음(도구 신뢰성 노트로 기록).

### F-10: spec 블록 간 given 병합 — 워크플로당 시나리오 1개만 가능
- 단계: spec · 심각도: major
- 재현: Approval에 spec 블록 3개(정상/에러/경계) 선언 → ① `compile error: 'empty repository' and 'stored ...' contradict each other … Drop one.` ② stored 제거 후: `spec: 4 passed, 6 failed` — 정상·경계 블록이 에러 블록의 `empty repository`에 오염돼 `status=failed`·`steps=1`로 평가 (evidence/08-spec.md 시도 2·3)
- 기대: spec 블록별 독립 시나리오 (정상+에러+경계 공존 — 테스트 최소셋의 기본)
- 실제: 한 워크플로의 모든 given이 병합된 단일 실행에 모든 expect를 평가
- 재시도: 2 · 우회: 부분 — 파일 전체 2워크플로에 시나리오를 1개씩 분산(정상+에러), 경계는 F-11로 불가.

### F-11: spec `given`이 payload를 통째 대체 + Money 값 표현 수단 부재 — 경계 시나리오 spec 불가
- 단계: spec · 심각도: major
- 재현: ① `given amountCents 1000001` 단독 → `status=failed`·`steps=1`(필수 필드 소실 — CLI 부분 payload의 `missing required field 'id'`와 동일 거동) ② 전체 필드 given에 `amount {'amount': '10000.01', 'currency': 'USD'}` 포함 → `compile error: unsupported given: …` ③ amount 제외 전체 given → 여전히 `steps=1` 실패 (evidence/08-spec.md 시도 4·5)
- 기대: 필드 하나만 바꾼 경계값 시나리오 선언
- 실제: given은 기본(유효) payload에 병합되지 않고 통째 대체하며, Money 리터럴 표기가 없어 필수 amount를 채울 수 없음
- 재시도: 3 · 우회: 있음 — 경계 실측을 mode A `--payload`(JSON이라 Money 표현 가능)로 대체(evidence/04 매트릭스), DoD의 경계 spec은 F-기록 대체.

### F-12: `stored` given의 오도적 진단 — 선언된 엔티티를 "not a declared entity"로 보고
- 단계: spec · 심각도: minor
- 재현: `stored Payment ageDays 31` (Payment는 선언된 엔티티) → `compile error: given 'stored Payment ageDays 31' names 'Payment', which is not a declared entity` (evidence/08-spec.md 시도 1)
- 기대: 소문자 바인딩명 요구라면 그렇게 안내 (`did you mean 'payment'?`)
- 실제: 존재하는 선언을 "선언되지 않음"으로 보고 — 소문자 `payment`로 바꾸면 통과
- 재시도: 1 · 우회: 있음(대소문자 변경).

### F-13: run payload가 전체 필드 제출을 강제 — 경계 프로브에도 카드번호 제출
- 단계: modeA · 심각도: minor
- 재현: `--payload '{"amountCents": 0, "cardNumber": "…"}'` → `failed: missing required field 'id'` (evidence/04)
- 기대: 관심 필드만으로 프로브 실행(또는 선택 필드 구분)
- 실제: 모든 선언 필드 필수 — 금액 경계 테스트에도 민감 필드(cardNumber) 제출 강제, F-7 누수 표면 확대
- 재시도: 1 · 우회: 있음(합성값 제출).

### F-14: KB 보안 커버리지 공백 — 마스킹 질의가 네이밍 문서로 오라우팅
- 단계: authoring(발견 과정) · 심각도: info
- 재현: `lnpl kb --route "결제 카드번호 필드 마스킹"` → `naming-entity-field-conventions`; "환불 기간 제한 정책"·"amount limit validation" → `(no match)` (evidence/01)
- 기대: security 카테고리 매칭 또는 정직한 no match
- 실제: 마스킹 질의가 무관한 네이밍 문서로 매칭 — KB에 마스킹·정책·한도 항목 부재
- 재시도: 0 · 우회: references/declarations.md에서 직접 발견. 반면 네이밍 문서는 camelCase·동작 명사 규칙을 사전에 잡아줘 재시도를 절약(+).

## 총평

선언·문서 표면은 인상적이다 — 2홉 문서 라우팅, 행 번호와 RFC 근거를 명시하는 컴파일 진단,
`writeOnly`·bearerAuth까지 정확한 OpenAPI, retry에서 attempts=3을 기계 도출하는 spec, 그리고
mode A/B differential 4/4 EQUIVALENT까지 파이프라인 9단계가 모두 초록이 된다. 그러나 그 초록은
우회의 누적이다: 이 케이스의 제품 요구 5개(입력 금액 검증, 0<금액≤한도, 30일 환불 창, 전액/부분
환불 구분, 정상+에러+경계 spec) 중 **원형대로 표현된 것은 하나도 없고**, 각각 의미 재해석(F-1)·
축소(F-2·F-3)·사전 계산 필드(F-5)·주석 문서화(F-3)·F-기록 대체(F-10·11)로 도달했다. 더 심각한
것은 실패의 양식이다 — 가드 탈락(F-2)·가드 skip(F-6)·마스킹 누수(F-7)·문서 과대 계약(F-8)이 전부
**무증상**이어서, 컴파일도 differential도 초록인 채로 0원 결제가 승인되고 카드번호 원문이 응답에
실린다. 판정: **민감정보·결제 도메인 프로덕션 사용 불가** — blocker F-7(우회 없는 카드번호 노출)
단독으로도 충분하며, 조용한 정책 소실(F-2+F-6)이 이를 보강한다. 마스킹 집행 채널 통일과 가드
탈락·skip의 관측 가능화가 선결 조건이다.
