# FINDINGS — inventory-order (재측정 r1)

환경(전 항목 공통): 커밋 `6d84bd6`(이슈 #43~#50 구현 + RFC-0014~0017 이후 main),
macOS(Darwin 25.1.0), python3.13 자체 `.venv`(상대경로), lnpl 0.2.0, LLVM
`/opt/homebrew/opt/llvm` + `CPATH`/`LIBRARY_PATH` SDK 경로,
`bash scripts/dev_doctor.sh` rc=0 (evidence/00-env.md).
개발자 시뮬레이션 조건: 원 실측과 동일 — AGENTS.md 라우팅 + plugins/lnpl/skills/
문서(#50이 보강한 naming.md·cli-surface.md 포함) + examples/ 샘플만 사용,
플랫폼 수정 0건(evidence/09-purity.md). 대조 기준: `qa/cases/inventory-order/`
(원 실측, 커밋 `713a4cb`) — 시나리오 S1~S5·커맨드를 동형 재실행.

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| authoring | PASS | evidence/01-authoring.md | 6 (.lnpl 수정→재실행 총계; 내역: 컴파일 3 + modeA 1 + spec 2) — 원 5 |
| parse | PASS | evidence/02-parse-lower.md | 0 |
| lower | PASS | evidence/02-parse-lower.md | 0 |
| validate | PASS | evidence/03-validate.md | 0 |
| modeA | PASS | evidence/04-modeA.md | 1 (--strict 귀속 통제용 서술 선언 제거; 시나리오 5종×strict on/off 전부 구동) |
| modeB | PASS | evidence/05-modeB.md | 0 (원 1 — 오키가 이제 즉시 거부돼 키 규명이 불필요) |
| differential | PASS | evidence/06-differential.md | 0 (EQUIVALENT — 기본 1 + 강제 입력 3: 가드 거짓·qty=0·빈 시드) |
| openapi | PASS | evidence/07-openapi.md | 0 |
| spec | PASS | evidence/08-spec.md | 2 (given 필드 해석 갭 우회 — 3케이스 9단언 통과) |

파이프라인 기계는 이번에도 9단계 전부 초록 — 그리고 이번에는 "초록"이
"요구사항 충족"과 대부분 겹친다: S2(재고 초과)·S4(수량 0)가 언어 기제로
차단되고(각각 가드 스킵+--strict rc=2, validate rc=1), S1의 재고 5→3 차감이
실측된다(Assignment value=3, evidence/04).

## Frictions

원 F-1~F-12의 건별 해소/부분/잔존 판정과 근거는 DELTA.md가 정본이다. 아래는
**이번 실측에서 관측된** 마찰만 기록한다 — 신규는 N-n, 원 마찰의 재관측은 원
번호를 인용한다.

### N-1: --strict가 의도된 서술 선언과 실수를 구분하지 못함
- 단계: modeA(--strict 측정) | 심각도: minor
- 재현: `performance response < 50ms`(의도적 서술, 원 소스와 동일)를 둔 채 `lnpl run <src> --payload pS1.json --strict` → rc=2. 제거 후 동일 커맨드 → rc=0 (evidence/04 §strict 귀속).
- 기대 vs 실제: 요구사항 기준 — 거부 게이트(--strict)는 "가드 스킵·검증 실패"를 잡되 의도 선언은 통과시켜야 SLO 문서화와 게이트를 함께 쓸 수 있다 vs 진단 1건이면 종류 불문 rc=2. 억제/승인 구문 없음(레퍼런스 전수 확인).
- 재시도: 1 | 우회: 성공 — 서술 선언 제거. 귀결: --strict 게이트를 쓰려면 measured-only 선언(SLO 문서화)을 포기해야 한다.

### N-2: mode B 출력에 스킵 레코드 부재 — 거부 관측성의 모드 간 비대칭
- 단계: modeB | 심각도: minor
- 재현: `lnpl build <src> --run --field product.stock=1 --field input.quantity=2` → 2스텝 + `status completed`만 출력. mode A 동일 시나리오는 `skipped by …` 목록 + `guard-skipped-steps` 진단 + JSON `skipped[]` 레코드 (evidence/05 §기타, evidence/04 §기계 관측).
- 기대 vs 실제: 두 모드가 같은 거부 관측을 제공 vs mode B는 스텝 수 축소로만 간접 관측(diff 하네스는 `| 3 skip(s)`로 계수하므로 내부 관측은 존재 — 표면화만 안 됨).
- 재시도: 0 | 우회: 부분 — `lnpl diff --payload`의 skip 계수 또는 스텝 수 비교로 대체.

### N-3: `--field`는 비교 가드 전용이라 검증 경로에 도달하지 않음 — 오독 유도
- 단계: modeB | 심각도: minor
- 재현: `--field input.quantity=0` → 가드만 5>=0 참으로 평가, validate는 기본 샘플 payload(quantity=1)를 검사 → 5스텝 completed. 같은 qty=0을 `lnpl diff --payload pS4.json`으로 주면 양 모드 failed (evidence/05 §S4 해석, evidence/06 §강제 2).
- 기대 vs 실제: qty=0 주입이 검증에도 반영(또는 문서가 상호작용을 명시) vs cli-surface.md는 "비교 가드 필드의 값"까지만 서술 — validate와의 상호작용 무서술. refinement 미집행으로 오판하기 쉬운 표면.
- 재시도: 0 | 우회: 성공 — payload 채널(diff --payload) 사용.

### N-4: spec `given <field> <value>`가 읽힌 엔티티의 필드만 해석 — 입력 필드 경계 spec 차단
- 단계: spec | 심각도: **major**
- 재현: `given` … `quantity 2`(Order.quantity — 선언된 필드) → `lnpl spec <src> --run` rc=2 `unsupported given: 'quantity 2' (… naming a declared field …)`. 특성화 프로브: Product 필드(`stock 5`·`name widget`)는 수용, Order 필드(`quantity`·`placedAt`·`no quantity`)는 타입 불문 거부 (evidence/08 §특성화 프로브).
- 기대 vs 실제: references/spec.md "‘<field> <value>’ — 선언된 필드를 설정" vs 워크플로가 **읽는** 엔티티(Product)의 필드만 해석 — 검증 대상인 입력 엔티티(Order) 필드, 즉 경계 spec(qty=0)에 가장 필요한 필드가 설정 불가. 진단은 "naming a declared field"라고만 말해 원인(읽힘 엔티티 한정)을 가리키지 않고, 문서에도 이 한정이 없다.
- 재시도: 2 | 우회: 부분 — stock 측 제어로 정상+경계(정확 한계)+에러(재고 0) 3케이스는 구성했으나, qty=0 경계는 spec 밖(payload 런타임 실측)으로 밀림.

### N-5: pipeline 블록의 종결 규칙이 문서에 없음
- 단계: authoring | 심각도: minor
- 재현: grammar.md의 블록 가드 예시는 `parallel … merge`뿐. `pipeline` 뒤에 `merge`를 두면 `compile error: line 55: 'merge' closes a 'parallel' block, but none is open` — pipeline이 어디서 끝나는지(다음 절에서 암묵 종결)는 진단으로만 역추정 (evidence/01 시도 1).
- 기대 vs 실제: 블록 시작·종결 규칙 명시 vs merge가 parallel 전용이라는 사실도, pipeline의 암묵 종결도 무서술.
- 재시도: 1 | 우회: 성공 — merge 제거.

### 원 마찰 재관측(잔존분 — 상세 판정은 DELTA.md)
- **F-3 재관측**: 상태 전이(created→confirmed) 여전히 표현 불가 — `set order.status to confirmed`는 "미읽힘 바인딩" 거부(evidence/01 시도 3), 값 문법에 텍스트 리터럴 없음, 전이 제약 구문 부재.
- **F-10 재관측**: payload 평평 병합 동일(evidence/04 §payload) — 이 케이스에선 무해.
- **F-11 재관측**: 결정론적 검증 실패(qty=0, not-a-uuid)에 여전히 retry 3회·700ms 소모 후 확정(evidence/04 §프로브).

## 총평

원 실측에서 "표현 자체가 불가"였던 핵심 비즈니스 규칙 셋이 전부 언어 안으로
들어왔다 — 수량 인지 재고 검사는 `when product.stock >= input.quantity`로(가드
우변 필드 참조, 진단이 철자까지 안내), 재고 차감은 `set product.stock to
product.stock - input.quantity`로(S1에서 5→3, S5에서 5→0 실측), 거부는 스킵
레코드(텍스트·JSON)와 `guard-skipped-steps` 진단, 그리고 --strict rc=2로 호출자가
구별 가능하다. 선언 타입 제약(PositiveInteger min=1)은 이제 양 모드 런타임이
집행하고(mode A rc=1, diff에서 양 모드 failed), spec은 3블록이 3케이스로 분리돼
정상+에러+경계를 언어 안에서 검증한다 — 원 케이스의 "S2·S4가 completed로
통과하는 서비스"는 재현되지 않는다. 잔존·신규 마찰은 주변부다: 상태 전이(F-3)와
qty=0 경계 spec(N-4)은 여전히 언어 밖 실측에 의존하고, --strict는 서술 선언과
양립하지 못하며(N-1), mode B의 거부 관측은 표면화가 덜 됐다(N-2). **판정: 이
케이스(다중 엔티티 CRUD + 수량 비즈니스 규칙 + 상태 전이)는 상태 전이 문서화
한계를 안고 프로덕션 사용 가능** — 원 판정 "사용 불가"의 근거였던 값 의미론
부재가 RFC-0015/0016 구현으로 해소됐기 때문이다.
