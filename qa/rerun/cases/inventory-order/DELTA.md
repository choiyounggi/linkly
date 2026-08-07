# DELTA — inventory-order

대조: 원 실측 `qa/cases/inventory-order/FINDINGS.md`(커밋 `713a4cb`, 2026-08-05,
판정 "프로덕션 사용 불가") vs 재측정 `qa/rerun/cases/inventory-order/`(커밋
`6d84bd6`, 2026-08-07). 판정 어휘: 해소(원형 표현 성립+원 증상 소멸, 증적 필수) /
부분(개선됐으나 제약 잔존) / 잔존(변화 없음).

| 원 F | 원 증상 요약 | 판정 | 근거(명령·출력 인용 또는 evidence 경로) |
|------|--------------|------|------------------------------------------|
| F-1 | 가드 우변에 필드 참조 불가 — 수량 인지 재고 검사 표현 불가(blocker) | **해소** | `when product.stock >= input.quantity` compile rc=0, IR Guard 조건 원문 생존(evidence/01). S2(stock=1,qty=2): create 스킵+`--strict` rc=2, S5(stock=5,qty=5): 정확 한계 통과·차감 0 도달(evidence/04). 엔티티 참조(`order.quantity`)는 미읽힘 바인딩으로 거부되나 진단이 `input.quantity`를 직접 안내 — 원 증상(규칙 미문서·표현 불가) 소멸 |
| F-2 | 산술·할당 문법 부재 — 재고 차감 표현 불가(blocker) | **해소** | `set product.stock to product.stock - input.quantity`(RFC-0015). S1 실행 트레이스 `[Assignment target=product.stock, value=3]`(5→3), S5 `value=0`(5→0), 바인딩 최종값 stock=3 확인(evidence/04). mode B도 동일 스텝 실행(evidence/05 컨트롤 페어) |
| F-3 | 상태 전이 표현 불가 — enum 타입 선언까지만(major) | **잔존** | `set order.status to confirmed` → `compile error: … reads entity.order, but this workflow never reads it`(evidence/01 시도 3). 값 문법에 텍스트 리터럴 없음(grammar.md §값 표현식: 참조·정수·기간), 전이 제약 구문 부재 — 원 우회(enum 문서화)와 동일. 단 facet 문법은 이제 types.md에 문서화(원 "추측 성공" 갭은 소멸) |
| F-4 | 가드가 1스텝만 감쌈 — 스코프 규칙 무문서(minor) | **해소** | grammar.md §가드의 스코프 명문화 + 블록 문법: `pipeline` 블록이 Guard의 child로 create·set·update 3스텝 소유(IR 노드 트리, evidence/01 §IR 생존 계수). 원 우회(가드 라인 중복)·IR 직독 불필요 |
| F-5 | "거부" 의미론 부재 — 가드 스킵이어도 completed/rc=0(major) | **부분** | 개선: 상태줄 `completed (3 step(s) skipped by guard)` + `guard-skipped-steps` 진단 + JSON `skipped[]`(guard id·조건·스텝) + `--strict` rc=2 — 호출자 구별 수단 3종 신설(evidence/04). 잔존: 기본 실행은 여전히 status=completed·rc=0(구별은 opt-in `--strict` 또는 레코드 판독 필요), mode B는 레코드 표면화 없음(N-2)·strict 플래그 자체가 없음(`unrecognized arguments: --strict`, evidence/05) |
| F-6 | refinement facet 런타임 미집행 — qty=0 통과(major) | **해소** | S4(qty=0): `workflow PlaceOrder -> failed`, rc=1(strict 무관, evidence/04). `lnpl diff --payload pS4.json`: 양 모드 status=failed EQUIVALENT(evidence/06 강제 2) — mode B 집행도 확인. openapi 400 서술과 거동 일치(evidence/07) |
| F-7 | spec 복수 블록 침묵 병합 — 워크플로당 1케이스(major) | **해소** | `lnpl spec <src> -o` → `wrote … (3 case(s))`(원: `1 case(s)` 병합). `--run`: `spec: 9 passed, 0 failed` — 정상+경계(정확 한계)+에러(재고 0) 3케이스 언어 내 검증(evidence/08). qty=0 경계만 N-4로 spec 밖(런타임 실측 대체) |
| F-8 | `stored` 소문자만 + 진단 시점 불일치(minor) | **부분** | 개선: `stored Product stock 5`(대문자 선언명) 수용 — spec.md에 양형 명문화(evidence/08). 잔존: given 검증 시점은 여전히 `--run`에서만 — 잘못된 given(`quantity 2`)이 `compile` rc=0·`spec -o` rc=0(매니페스트에 그대로 실림)을 통과하고 `--run`에서야 거부(evidence/08 타임라인) |
| F-9 | modeB `--field` 오키 침묵 무시 — 기본값 0 평가(minor) | **해소** | `--field stock=5` → rc=2 `error: --field name(s) stock do not match any comparison-guard field of workflow wf.place.order (valid: input.quantity, product.stock)`(evidence/05) — 침묵 무시 소멸, 유효 키 목록 제시 |
| F-10 | payload 엔티티 네임스페이스 없이 평평 병합(info) | **잔존** | 재관측 동일: 단일 dict 병합, `id` 공용(evidence/04 §payload) — 이 케이스에선 무해(원 판정과 동일) |
| F-11 | 결정론적 검증 실패에도 retry 3회(info) | **잔존** | qty=0·not-a-uuid 모두 attempts=4·700ms 후 확정(evidence/04 §프로브) — 원 실측과 동일 거동 |
| F-12 | CLI 표면의 문서 라우팅 갭 — 소스 열람 강제(minor) | **해소** | cli-surface.md(수기+AST 테스트 가드) 신설. 이번 실측에서 쓴 전 커맨드·플래그(compile -o/--strict, run --payload/--json/--strict, spec -o/--run, build --run/--field/--workdir, diff --payload/--no-row/--workdir, openapi -o)를 공개 문서에서 발견 — **impl/ 소스 열람 0건**(evidence/01 §D18, 각 evidence 커맨드 원문) |

집계: 해소 7 / 부분 2 / 잔존 3 (blocker 2건 전부 해소, major 4건 중 해소 2·부분 1·잔존 1).

## 재시도 비교

| 단계 | 원 재시도 | 이번 재시도 | 비고 |
|------|-----------|-------------|------|
| authoring | 5 (컴파일 3 + spec 2) | 6 (컴파일 3 + modeA 1 + spec 2) | 총량 유사하나 성격이 다름: 원 3회는 표현 불가 발견 후 **후퇴**(리터럴 가드·차감 포기), 이번 3회는 **원형 유지 철자 교정**(merge 제거·input 네임스페이스·전이 프로브 제거) — 진단이 수리 방법을 안내(F-1 행) |
| parse/lower/validate | 0 | 0 | — |
| modeA | 0 | 1 | --strict 귀속 통제(서술 선언 제거) — 신규 게이트 측정 과정에서 발생(N-1) |
| modeB | 1 | 0 | 원인이던 오키 침묵 무시가 즉시 거부로 바뀜(F-9 해소의 직접 효과) |
| differential | 0 | 0 | 이번은 강제 입력 3종 추가에도 0 |
| openapi | 0 | 0 | — |
| spec | 2 | 2 | 원인 교체: 원=블록 병합(F-7) 우회, 이번=given 필드 해석 갭(N-4) 우회 |
| **총 수정→재실행** | **6** | **6** | 총량 동일하나 blocker 우회가 0건이 됨 |

## 신규 마찰 (상세: FINDINGS.md §Frictions)

- N-1 (minor): `--strict`가 의도된 서술 선언(declared-measured-only)과 실수를 구분 못함 — 게이트와 SLO 문서화 양립 불가
- N-2 (minor): mode B 출력에 스킵 레코드·진단 부재 — 거부 관측성 모드 간 비대칭
- N-3 (minor): `--field`는 비교 가드 전용으로 검증 경로 미도달 — refinement 미집행으로 오독 유도, 문서에 상호작용 무서술
- N-4 (**major**): spec `given <field> <value>`가 읽힌 엔티티 필드만 해석 — 입력 엔티티 필드(qty=0 경계)의 spec 표현 차단, 진단·문서 모두 원인 미지시
- N-5 (minor): pipeline 블록 종결 규칙 무문서 — merge가 parallel 전용임을 진단으로만 발견

## 케이스 판정

원: **"프로덕션 사용 불가"** → 이번: **"프로덕션 사용 가능(상태 전이 자동화 제외)"**.
원 판정의 근거였던 값 의미론 부재 — 비교 우변 필드 참조(F-1)·산술/할당(F-2)·거부
신호(F-5)·refinement 집행(F-6) — 가 RFC-0015 구현으로 해소·개선되어, 원 실측에서
오답으로 완주하던 S2(재고 초과 판매)와 S4(수량 0 주문)가 이제 언어 기제만으로
차단되고 그 사실이 spec 3케이스와 diff 강제 입력으로 언어 안에서 증명된다.
잔존 갭은 상태 전이 표현(F-3)과 입력 필드 경계 spec(N-4)로, 전자는 서술(문서화)
수준으로 후퇴가 필요하고 후자는 런타임 실측 대체 우회가 있어 — 둘 다 이 케이스의
핵심 재고 무결성을 훼손하지 않는다. 단 거부의 기본 의미론은 여전히
completed/rc=0이므로(F-5 부분) 호출 측 계약에 `--strict` 게이트 또는 `skipped[]`
레코드 판독을 명시적으로 포함해야 안전하다.
