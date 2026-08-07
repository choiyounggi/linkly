# 재측정 마찰 정규화 표 (46건 전건)

대조: 원 실측 커밋 `713a4cb`(2026-08-05) → 재측정 커밋 `6d84bd6`(2026-08-07,
이슈 #43~#50 구현 + RFC-0014~0017 이후 main). 판정·심각도·근거 셀은 아래 4개
DELTA.md 표에서 문자 그대로 전사했고(요약 셀만 축약), 주 클러스터는 원
`qa/REPORT.md` §4의 배정을 전사했다(F 1건당 주 클러스터 1개 — t2 F-5의 C6 교차
관측은 주 클러스터 C8로만 계수). 이 표가 케이스×판정 수치의 정본이다.

소스(읽기 전용):

- r1(=원 t1): `.worktrees/qa-r1-inventory-order/qa/rerun/cases/inventory-order/DELTA.md`
- r2(=원 t2): `.worktrees/qa-r2-payment-refund/qa/rerun/cases/payment-refund/DELTA.md`
- r3(=원 t3): `.worktrees/qa-r3-batch-report/qa/rerun/cases/batch-report/DELTA.md`
- r4(=원 t4): `.worktrees/qa-r4-rate-notify/qa/rerun/cases/rate-notify/DELTA.md`
- 클러스터 배정: 원 `qa/REPORT.md` §4 (98~174행)

## §1 — 46건 전건 표

각 행의 근거 열은 해당 DELTA 행이 인용한 evidence 경로의 요약이다(경로는 각
케이스 워크트리의 `qa/rerun/cases/<case>/` 기준).

| 케이스 | F | 원 심각도 | 판정 | 주 클러스터 | 근거(DELTA 행 요약) |
|--------|---|-----------|------|-------------|----------------------|
| r1 | F-1 | blocker | 해소 | C7 | `when product.stock >= input.quantity` compile rc=0·IR 생존(evidence/01); S2 스킵+`--strict` rc=2, S5 정확 한계 통과(evidence/04) |
| r1 | F-2 | blocker | 해소 | C6 | `set … to product.stock - input.quantity`(RFC-0015); Assignment 5→3·5→0 실측(evidence/04), mode B 동일(evidence/05) |
| r1 | F-3 | major | 잔존 | C6 | `set order.status to confirmed` compile error(evidence/01 시도 3); 값 문법에 텍스트 리터럴·전이 제약 구문 부재 |
| r1 | F-4 | minor | 해소 | C10 | grammar.md §가드 스코프 명문화 + `pipeline` 블록이 3스텝 소유(evidence/01 §IR 생존 계수) |
| r1 | F-5 | major | 부분 | C2 | 상태줄+`guard-skipped-steps`+JSON `skipped[]`+`--strict` rc=2 신설(evidence/04); 기본 실행은 여전히 completed·rc=0, mode B 표면화 없음(N-2) |
| r1 | F-6 | major | 해소 | C5 | S4(qty=0) failed rc=1(evidence/04); diff 양 모드 failed EQUIVALENT(evidence/06); openapi 400 서술과 일치(evidence/07) |
| r1 | F-7 | major | 해소 | C1 | `spec -o` 3 case(s)·`--run` 9 passed 0 failed(evidence/08) |
| r1 | F-8 | minor | 부분 | C9 | `stored Product`(대문자) 수용·spec.md 명문화(evidence/08); given 검증 시점은 여전히 `--run` 한정 |
| r1 | F-9 | minor | 해소 | C4 | `--field stock=5` → rc=2 + 유효 키 목록 제시(evidence/05) |
| r1 | F-10 | info | 잔존 | 미배정 | 평평 병합 재관측 동일(evidence/04 §payload) — 이 케이스 무해 |
| r1 | F-11 | info | 잔존 | 미배정 | 결정론 실패에도 attempts=4·700ms(evidence/04 §프로브) — 원과 동일 |
| r1 | F-12 | minor | 해소 | C10 | cli-surface.md 신설 — 전 커맨드·플래그 공개 문서 발견, impl/ 열람 0건(evidence/01 §D18) |
| r2 | F-1 | major | 해소 | C7 | `input.` 네임스페이스로 read 없는 입력 금액 가드(04 §1, raw/run-approval-amt1.out) |
| r2 | F-2 | major | 해소 | C3 | 연쇄 가드 파싱 에러+교정 안내+`and` 결합; 0·-1 거부 실측(raw/compile-b2-stacked-guards.err, raw/run-approval-amt0.out) |
| r2 | F-3 | major | 해소 | C7 | `and` 범위·`==`/`!=`·필드 간 비교 컴파일·집행(01, raw/compile-b5-*.err, 05) |
| r2 | F-4 | major | 해소 | C7 | Money 가드가 컴파일 시점 도메인 진단(raw/compile-b1-money-guard.err); 잔존 제약: Integer 센트 모델링 필요 |
| r2 | F-5 | major | 해소 | C8 | `input.requestedAt - payment.createdAt <= 30d` 집행; 정확히 30d 포함·30d+1s 거부·존 없는 값 rc=3(04 §2, raw/run-refund-day30*.out) |
| r2 | F-6 | major | 해소 | C2 | skipped 구조화 레코드+진단+`--strict` rc=2(04 §3·4, raw/run-approval-amt1000001-strict.err) |
| r2 | F-7 | blocker | 해소 | C5 | bindings `"***"`(28행)·trace `"***"`(119행) 양 채널 마스킹, 전 raw grep 원문 0히트(04 §6, raw/run-refund-day5.out) |
| r2 | F-8 | major | 해소 | C5 | writeOnly 문서 계약 + 런타임 `***` 정합 — 과대 광고 모순 소멸(07, payment-refund.openapi.json) |
| r2 | F-9 | minor | 부분 | C5 | #43 채널 통일로 공존 누수 소멸+한계 문서 명시(06, raw/kb-load-masking.out); "초록=전 채널 검증" 기대는 미충족 |
| r2 | F-10 | major | 해소 | C1 | Approval 3블록 독립 평가(08, raw/spec-run4.out) — issue #46 |
| r2 | F-11 | major | 해소 | C9 | `given amountCents 1000001` 필드 단위 덮어쓰기 — 상한·하한 경계 블록 PASS(08) |
| r2 | F-12 | minor | 해소 | C9 | 선언명(PascalCase)·바인딩명 모두 수용(08, raw/spec-run2.out) |
| r2 | F-13 | minor | 해소 | 미배정 | 부분 payload 실행 — 경계 프로브에 카드번호 불필요(04 §5, raw/run-approval-partial*.out) |
| r2 | F-14 | info | 해소 | C10 | 마스킹 질의가 신설 문서로 정라우팅, 나머지는 정직한 no match(01, raw/kb-q1.out) |
| r3 | F-1 | blocker | 부분 | C6 | `set`+이항 산술 파생값 실계산(orderCount 1→2, 04-probe-a2-*); Money 산술 rc=2·sum/count 어휘 잔존, 로드맵 포인터 0건(03-vocab-survey-diff.md §D12) |
| r3 | F-2 | blocker | 부분 | C8 | `on schedule daily at 00:00 UTC` parse→IR→OpenAPI `x-lnpl-schedules` 도달(05-probe-b1-*); 실행기 부재(issue #26)·멱등 어휘 0 hits |
| r3 | F-3 | major | 해소 | C3 | `--strict` rc=2(compile·run), clean rc=0 — 양방향 검증(08-strict-{off,on,run,clean}.log); 기본값 rc=0은 opt-in |
| r3 | F-4 | major | 해소 | C10 | `create DailyReport` rc=0, IR 내용 일치 — 재시도 4→0회(08-probe-c1-compile.log) |
| r3 | F-5 | major | 해소 | C1 | 3블록→3케이스 `--run` 7 passed; 원 재현은 rc=2+교정 지시(07-spec-validate.log, 07-probe-d1-compile.log) |
| r3 | F-6 | minor | 해소 | C10 | `load orders` rc=0, IR entity.order(08-probe-c2-compile.log) |
| r3 | F-7 | minor | 해소 | C10 | 선언명 입력 시 rc=2+전 후보 목록 — IR grep 불요(06-pipeline-wfname.log) |
| r3 | F-8 | info | 부분 | C3 | `--strict` exit 채널 신설(08-diag-channel.log); JSON 진단 스트림·진단 등급 부재(→N-4) |
| r4 | F-1 | minor | 잔존 | C6 | verbs.md에 `send`/`notify` 여전히 없음 — create+emit 근사 우회 동일(01-authoring.md) |
| r4 | F-2 | major | 해소 | C3 | 심은-참조 probe compile rc=2+선언 후보 제시 — 참조 해석 컴파일 타임 이동(02-compile.md) |
| r4 | F-3 | major | 해소 | C4 | bare 이름 rc=2+valid 목록 — 무경고 무시 소멸(05-modeB.md) |
| r4 | F-4 | major | 해소 | C1 | 3블록 → "3 case(s)", given/expect 블록별 분리(08-spec.md 시도 1) |
| r4 | F-5 | major | 해소 | C9 | given id 적용 — 케이스 1이 4스텝 완주, 8/8 PASS(08-spec.md 시도 2) |
| r4 | F-6 | minor | 잔존 | C9 | `no priorNotification` 동일 문구 거부, 스코프 규정 여전히 무문서(08-spec.md 시도 1) |
| r4 | F-7 | info | 해소 | C7 | grammar.md 31행 `==`/`!=` 정본화 + probe compile rc=0(01, 02) |
| r4 | F-8 | info | 해소 | C10 | examples/guarded.lnpl 존재 — 실행 커맨드·until 미수록 사유 정본화(01-authoring.md) |
| r4 | F-9 | info | 해소 | C2 | until 0라운드 구조화 레코드+진단 when/until 대칭(04-modeA.md) |
| r4 | F-10 | info | 부분 | 미배정 | run --json rows 직접 신호 부재 지속; spec rows 단언은 실작동(04-modeA.md, 08-spec.md) |
| r4 | F-11 | info | 잔존 | C10 | 진단에 파일:라인 여전히 없음(구성명 맥락만 추가 — 02-compile.md) |
| r4 | F-12 | minor | 해소 | C9 | 단언 불일치 인라인·런타임 실패 사유 직접 출력(08-spec.md probe 2건) |

## §2 — 판정 집계

행 재계산 결과이며, 각 DELTA의 자기 집계행과 대조해 일치를 확인했다(r1
"해소 7 / 부분 2 / 잔존 3", r2 "해소 13 · 부분 1 · 잔존 0", r3 "해소 5 / 부분 3
/ 잔존 0", r4 "해소 8 · 부분 1 · 잔존 3" — 각 DELTA 집계행 원문).

| 케이스 | 행 수 | 해소 | 부분 | 잔존 |
|--------|-------|------|------|------|
| r1 | 12 | 7 | 2 | 3 |
| r2 | 14 | 13 | 1 | 0 |
| r3 | 8 | 5 | 3 | 0 |
| r4 | 12 | 8 | 1 | 3 |
| **계** | **46** | **33** | **7** | **6** |

## §3 — 클러스터 상태 (원 REPORT §4 대응)

유도 규칙: 구성원 전원 해소 → 해소 / 혼합 → 부분(잔존 요소 명시) / 전원 잔존 →
잔존. 구성원 배정은 원 §4 전사(계수 합 46 — 미배정 4건 포함).

| C | 원 명명 · 심각도 | 구성원(판정) | 상태 | 잔존 요소 |
|---|------------------|--------------|------|-----------|
| C1 | spec 블록 무음 병합 · major | r1F7(해소), r2F10(해소), r3F5(해소), r4F4(해소) | **해소** | — |
| C2 | 가드 skip=completed·rc=0 · major | r1F5(부분), r2F6(해소), r4F9(해소) | **부분** | 기본 실행은 여전히 completed·rc=0 — 구별은 opt-in `--strict`/`skipped[]` 판독(r1F5) |
| C3 | 선언·참조의 무음 증발 · major | r2F2(해소), r3F3(해소), r3F8(부분), r4F2(해소) | **부분** | JSON 진단 스트림·진단 등급 부재(r3F8) |
| C4 | `--field` 오키 무경고 무시 · major | r1F9(해소), r4F3(해소) | **해소** | — |
| C5 | 채널 간 집행 불일치(마스킹) · blocker | r2F7(해소), r2F8(해소), r2F9(부분), r1F6(해소) | **부분** | diff 마스킹 검사 스코프가 전 채널 아님(r2F9) |
| C6 | 값 의미론 부재 · blocker | r1F2(해소), r1F3(잔존), r3F1(부분), r4F1(잔존) | **부분** | 상태 전이 표현·sum/count·Money 산술·notify/send 어휘(r1F3·r3F1·r4F1) |
| C7 | 가드 조건 표현력 한계 · blocker | r1F1(해소), r2F1(해소), r2F3(해소), r2F4(해소), r4F7(해소) | **해소** | — (r2F4의 Money 가드 자체는 Integer 센트 모델링 제약으로 남음 — 행 참조) |
| C8 | 시간·기간·스케줄 공백 · blocker | r2F5(해소), r3F2(부분) | **부분** | 스케줄 실행기 부재(issue #26)·멱등 어휘(r3F2) |
| C9 | spec given 의미론 결함 · major | r1F8(부분), r2F11(해소), r2F12(해소), r4F5(해소), r4F6(잔존), r4F12(해소) | **부분** | given 검증 시점 `--run` 한정(r1F8)·`no <field>` 스코프 무문서(r4F6) |
| C10 | 미문서 규칙·문서-구현 불일치 · major | r1F4(해소), r1F12(해소), r2F14(해소), r3F4(해소), r3F6(해소), r3F7(해소), r4F8(해소), r4F11(잔존) | **부분** | 진단 파일:라인 부재(r4F11) |
| 미배정 | 단독 관찰 4건 | r1F10(잔존), r1F11(잔존), r2F13(해소), r4F10(부분) | 혼합 — 개별 표기 | payload 평평 병합·결정론 retry·rows 신호 |
