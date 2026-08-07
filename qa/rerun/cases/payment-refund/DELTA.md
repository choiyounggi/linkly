# DELTA — payment-refund: 원 실측(2026-08-05, 713a4cb) vs 재측정(2026-08-07, 6d84bd6)

판정 룰릭(D12): **해소** = 원 마찰의 재현 커맨드 동형이 원 기대 동작을 내고 raw 인용
가능. **부분** = 개선됐으나 제약 잔존(1줄 명시). **잔존** = 동일 실패 양식 재현.
**미검** = 이번 실행이 그 차원을 평가하지 못함. 모든 행은 원 증적(qa/cases/
payment-refund/evidence/)과 재측정 증적(qa/rerun/cases/payment-refund/evidence/) 양쪽
을 인용한다.

## 원 F-1~F-14 전건 판정 (14행)

| F | 원 마찰 (심각도) | 판정 | 근거 1줄 | 원 증적 | 재측정 증적 |
|---|------------------|------|----------|---------|-------------|
| F-1 | 가드가 read 행만 참조 — 입력 검증 불가 (major) | **해소** | `input.` 네임스페이스로 read 없는 Approval이 입력 금액을 가드 — 의미 재해석 우회 소멸 | raw/compile-a3.err | 04 §1, raw/run-approval-amt1.out |
| F-2 | 연쇄 when 첫 가드 무진단 IR 탈락 (major) | **해소** | 연쇄 가드는 이제 파싱 에러(교정 안내 포함) + `and` 결합 제공; IR 생존 2/2 내용 계수; 0·-1 **거부** 실측 (원 T05는 승인) | 02-compile.md, raw/run-approval-amt0.out(원) | 02, raw/compile-b2-stacked-guards.err, raw/run-approval-amt0.out(재) |
| F-3 | AND 결합·등가 == 표현 불가 (major) | **해소** | 한 가드 안 `and` 범위 + `==`/`!=`/필드 간 비교 컴파일·집행; 전액(==)/부분(<)/초과 거부 mode B 관측 | evidence/02(원) | 01 시도 표, raw/compile-b5-*.err, 05 §비대칭 |
| F-4 | Money 가드 — 컴파일 통과 후 런타임 raw traceback (major) | **해소** | 재현 동형이 이제 **컴파일 시점 도메인 진단**(타입·RFC 사유 명시) — 원 기대문("컴파일 시점 타입 거부") 충족. 잔존 제약: Money 필드 자체는 여전히 가드 불가 → Integer 센트 모델링 필요(04 예비 '부분'을 기대문 기준으로 최종 조정) | raw/run-approval-default.err(원) | raw/compile-b1-money-guard.err |
| F-5 | 30일 기간 정책 표현 불가 (major) | **해소** | `input.requestedAt - payment.createdAt <= 30d` 컴파일·집행; 5d/정확히 30d 승인(포함, RFC-0016 문서 일치)·30d+1s 거부; 존 없는 값은 도메인 진단 rc=3; ageDays 우회 소멸 | FINDINGS(원) F-5 | 04 §2, raw/run-refund-day30*.out, raw/run-refund-nozone.err |
| F-6 | 가드 false = 조용한 skip, completed·rc=0 (major) | **해소** | skipped가 구조화 레코드(가드 id·condition 원문·스킵 스텝 목록)로 계약화 + stderr `guard-skipped-steps` 진단 + `--strict` rc=2 최상위 게이트 — 거절/성공 기계 판독 가능 | raw/run-approval-amt1000001.out(원) | 04 §3·4, raw/run-approval-amt1000001-strict.err |
| F-7 | 마스킹 부분 집행 — bindings 원문 노출 (**blocker**) | **해소** | 재현 동형(run --json)에서 **bindings `"***"`(28행)·trace `"***"`(119행) 양 채널 마스킹**, 같은 채널 컨트롤(amountCents) 평문, 전 raw grep 원문 0히트 | 04-modeA-masking.md(원), run-approval-amt1000001.out 30행 vs 122행 | 04 §6, raw/run-refund-day5.out 28·119행 |
| F-8 | OpenAPI writeOnly 계약 vs 런타임 모순 (major) | **해소** | 문서 계약(writeOnly·format password) 동일 + 런타임이 원문 대신 `***` — 안전 과대 광고 모순 소멸(원 FINDINGS의 "F-7 해소 시 자동 정합" 예측대로) | evidence/07(원) | 07, payment-refund.openapi.json |
| F-9 | diff 마스킹 검사가 누수 채널 미포함 (minor) | **부분** | 검사 스코프는 여전히 전 채널이 아니나 플랫폼 문서가 그 한계를 명시("모든 채널을 봤다는 뜻이 아니다") + #43 채널 통일로 원 공존 누수 소멸(독립 sweep 0히트) — "초록=전 채널 검증" 기대 자체는 미충족 | evidence/06(원) | 06, raw/kb-load-masking.out |
| F-10 | spec 블록 간 given 병합 — 워크플로당 1시나리오 (major) | **해소** | Approval 3블록이 각자 given으로 독립 평가(경계 블록이 정상 블록 미오염) — issue #46 | evidence/08 시도 2·3(원) | 08, raw/spec-run4.out |
| F-11 | given 통째 대체 + Money 리터럴 부재 — 경계 spec 불가 (major) | **해소** | `given amountCents 1000001` 필드 단위 덮어쓰기 경계 블록 선언·PASS (상한·하한 양쪽) | evidence/08 시도 4·5(원) | 08, raw/spec-run4.out |
| F-12 | `stored Payment` 오도 진단 (minor) | **해소** | 선언명(PascalCase)·바인딩명 모두 수용(문서 명시, 실행 수용 확인) | evidence/08 시도 1(원) | 08, raw/spec-run2.out |
| F-13 | run payload 전체 필드 강제 (minor) | **해소** | `{"amountCents": 0}`·`{"amountCents": 5}` 부분 payload 실행 — 경계 프로브에 카드번호 제출 불필요 | evidence/04(원) | 04 §5, raw/run-approval-partial*.out |
| F-14 | KB 마스킹 질의 오라우팅 (info) | **해소** | 동일 질의가 `security-sensitive-field-masking`(신설 문서) 정라우팅; 나머지 2질의는 정직한 no match(원 기대문 충족) | evidence/01(원) | 01, raw/kb-q1.out, raw/kb-load-masking.out |

**집계: 해소 13 · 부분 1 (F-9) · 잔존 0 · 미검 0.**

### 브리프 핵심 재검 5항 대조

| 항 | 결과 |
|----|------|
| 0원·음수·한도초과 결제의 관측 가능한 거부 | ✓ 가드 거부 — skipped 레코드+진단+strict rc=2 (04 §1; 컴파일 거부가 아닌 런타임 가드 거부이며, 연쇄 가드 오선언은 컴파일 거부) |
| 카드번호 trace·bindings 양 채널 마스킹 | ✓ 양 채널 `***` + 채널별 네거티브 컨트롤 (04 §6) |
| 30일 창의 언어 내 표현 (ageDays 불필요) | ✓ DateTime 산술, 경계 포함 문서 일치 (04 §2) |
| 전액/부분 환불의 `==`/산술 구분 | ✓ ==·<·<= 필드 간 비교, mode B 3셀 관측 (05) |
| spec 3시나리오 원형 통과 | **부분** — 정상·에러·경계 5블록 선언·독립 평가(10 단언 PASS), 가드-참 정상 경로 1단언 FAIL(N-2: spec 러너 시드 제약, 해당 경로는 run/build로 실증) |

### --strict 유/무 구분 (제약 3)

컴파일: 경고 2건(의도적 unenforced 프로브)이 --strict에서 rc=2. 런타임: 가드-거부
실행이 --strict에서 rc=2(비-strict rc=0 + skipped 레코드). evidence/04 §4.

## 재시도 비교 (원 Scorecard vs 재측정)

| 단계 | 원 재시도 | 재측정 재시도 |
|------|-----------|---------------|
| authoring | 편집 9회 (가드 3·엔티티 2·spec 4) | 비의도 실패 0 (의도적 거부 프로브 3) + spec 블록 수정 3 |
| parse/lower | 8회 (에러 3·성공 5) | 0 (최종 파일 1회 통과) |
| validate | 4회 재검증 | 1회 |
| modeA | 워크플로당 2 + 프로브 6실행 | 재실행 0 + 프로브 14실행 |
| modeB | 1 | 0 |
| differential | 1 | 0 |
| openapi | 1 | 0 |
| spec | 6 | 4 (1 FAIL 잔존 — N-2) |

원형 표현 도달 비용이 "우회 탐색 9회"에서 "문서 라우팅 11홉·컴파일 1회"로 이동 —
재시도가 표현력 공백이 아니라 spec 하네스 제약 진단에만 쓰였다.

## 신규 마찰

FINDINGS.md N-1(run payload 동명 필드 충돌, minor) · N-2(spec에서 read-행 가드 참
불가 + 실패 진단 채널 부재, major) · N-3(create 충돌 의미 관측 불가, minor) ·
N-4(시간 문법 발견이 RFC 번호 의존, info).

## 케이스 판정

원 판정 "**민감정보·결제 도메인 프로덕션 사용 불가**"(blocker F-7 단독 + F-2·F-6
조용한 정책 소실)의 차단 사유가 **전부 소멸했다**: 카드번호는 양 채널 마스킹이고
(F-7), 정책 소실은 문법적으로 불가능하며(F-2), 정책 거부는 기계 판독 가능하다(F-6).
제품 요구 5개가 전부 언어 원형으로 표현·집행·관측된다.

재판정: **결제·민감정보 도메인 사용 가능(조건부)** — 조건은 (1) 정상 경로의 spec
계약화 공백(N-2, major): 가드-참 경로 검증을 spec이 아닌 실행 증적(run/build)으로
유지해야 하며, (2) diff 마스킹 초록의 스코프 한정 인용(F-9 부분): 채널 sweep을
릴리스 절차에 별도 유지할 것. 두 조건 모두 우회 가능한 검증 절차 이슈로, 원 실측의
표현력·안전 차단과 질이 다르다.
