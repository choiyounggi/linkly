# FINDINGS — inventory-order

환경(전 항목 공통): 커밋 `713a4cb`, macOS(Darwin 25.1.0), python3.13 자체 `.venv`
(상대경로), lnpl 0.2.0, LLVM `/opt/homebrew/opt/llvm` + `CPATH`/`LIBRARY_PATH`
SDK 경로, `bash scripts/dev_doctor.sh` rc=0 (evidence/00-env.md).
개발자 시뮬레이션 조건: AGENTS.md 라우팅 + plugins/lnpl/skills/ 문서 +
examples/ 샘플만 사용(플랫폼 내부는 특성화 목적의 읽기만, 수정 0건).

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| authoring | PASS | evidence/01-authoring.md | 5 (.lnpl 수정→재실행 총계; 내역: 컴파일 3 + spec 2) |
| parse | PASS | evidence/02-parse-lower.md | 0 |
| lower | PASS | evidence/02-parse-lower.md | 0 |
| validate | PASS | evidence/03-validate.md | 0 |
| modeA | PASS | evidence/04-modeA.md | 0 (변형 6회 전부 구동; 의미 갭은 F-1·F-5·F-6) |
| modeB | PASS | evidence/05-modeB.md | 1 (`--field` 키 형식 규명) |
| differential | PASS | evidence/06-differential.md | 0 (EQUIVALENT 4/4) |
| openapi | PASS | evidence/07-openapi.md | 0 |
| spec | PASS | evidence/08-spec.md | 2 (3케이스→1케이스 축소 — F-7) |

파이프라인 기계는 9단계 전부 초록. 단, 아래 Frictions가 보여주듯 "초록"과
"요구사항 충족"은 다르다 — S2·S4는 완주(completed)했지만 제품 스펙 기준 오답이다.

## Frictions

### F-1: 가드 우변에 필드 참조 불가 — 수량 인지 재고 검사 표현 불가
- 단계: authoring | 심각도: **blocker**
- 재현: `when product.stock >= order.quantity` 를 가드로 두고 `lnpl compile <src>` → rc=2.
- 진단 원문: `compile error: line 44: invalid condition: invalid value 'order.quantity': 'product.stock >= order.quantity'` — 행·토큰은 정확히 지목하나 "우변은 리터럴만"이라는 규칙은 에러에도 레퍼런스에도 없음.
- 기대 vs 실제: 요구사항 "주문 수량 ≤ 재고 확인" vs 가드는 `필드 비교연산자 리터럴`만 허용.
- 재시도: 1 | 우회: **없음**(리터럴 `> 0`로 후퇴). 귀결: S2(stock=1, qty=2)가 mode A에서 **completed·주문 생성**(evidence/04) — 재고 초과 판매를 언어로 막을 수 없다.

### F-2: 산술·할당 문법 부재 — 재고 차감 표현 불가
- 단계: authoring | 심각도: **blocker**
- 재현: grammar.md·verbs.md 전수 확인 — 산술 연산자·할당 구문 없음. `update product`는 op=update RepositoryCall만 낳는다(IR 확인).
- 기대 vs 실제: "충분하면 차감" vs 차감량(`stock - quantity`)을 표현할 문법 자체가 없음.
- 재시도: 0(시도 불가 — 문법 비존재는 레퍼런스로 판정) | 우회: 부분 — `update product`로 update 효과 발생만 관측(값 의미론 없음). S1의 "재고 5→3"·S5의 "재고 0 도달"은 검증 불가.

### F-3: 상태 전이 규칙 표현 불가 (타입은 가능, 전이는 불가)
- 단계: authoring | 심각도: major
- 재현: `refine OrderStatus of Text` + `enum created confirmed` → IR facets.enum 생성 성공(evidence/01). 그러나 "created에서만 confirmed로" 전이 제약·상태 설정 구문 없음.
- 기대 vs 실제: 주문 상태 전이(created→confirmed) vs enum 타입 선언까지만 표현됨.
- 재시도: 0 | 우회: 부분 — 타입 문서화는 됨. 단 facet 문법 예시가 레퍼런스에 없어 추측으로 성공(운이 좋았음 — 문서 갭).

### F-4: 가드는 바로 다음 1스텝만 감싼다 — 문서화 없음
- 단계: authoring | 심각도: minor
- 재현: `when` 가드 뒤에 `create order`·`update product` 2스텝을 두고 compile → IR에서 guard.1 children=[step.3(create)]만, update는 가드 밖(evidence/01 시도 2).
- 기대 vs 실제: 가드가 후속 블록을 감싼다고 기대(grammar.md에 스코프 규칙 無) vs 1스텝만.
- 재시도: 1 | 우회: **성공** — 가드 라인을 스텝마다 중복(시도 3, IR에서 Guard 2개 확인). 발견 비용: IR JSON을 직접 읽어야만 알 수 있었음.

### F-5: "거부" 의미론 부재 — 가드 스킵이어도 completed/rc=0
- 단계: modeA | 심각도: major
- 재현: `lnpl run <src> --payload pS3.json`(stock=0) → create·update 스킵, `workflow PlaceOrder -> completed`, rc=0 (evidence/04 S3; modeB 동일 — evidence/05).
- 기대 vs 실제: 재고 부족 주문은 "거부"(실패 응답) vs 스텝 스킵 후 **성공 종료** — 호출자는 주문 성사와 거부를 상태·rc로 구별할 수 없다(rows 조회로만 간접 구별).
- 재시도: 0 | 우회: 부분 — spec `rows Order 0` 단언으로는 구별 가능하나 F-7 때문에 경계 케이스를 spec에 실을 수 없음.

### F-6: refinement facet 런타임 미집행 — qty=0 주문이 통과
- 단계: modeA | 심각도: major
- 재현: `quantity PositiveInteger`(min=1) 선언 후 qty=0 payload로 run → 4스텝 completed (evidence/04 S4). 대조: id를 `not-a-uuid`로 주면 validate가 **실패**(rc=1, retry 발동).
- 기대 vs 실제: min=1 위반 거부 vs 의미 타입(UUID 등)만 집행되고 facet(min/max/enum)은 미집행. IR의 Validation rule이 `semantic-types`로 고정됨. openapi 400 서술과 실제 거동이 어긋나는 지점(evidence/07).
- 재시도: 0 | 우회: 없음(언어 내). declarations.md의 집행 매트릭스에 refinement 행이 없어 문서로는 예측 불가.

### F-7: spec은 워크플로당 1케이스 — 복수 블록은 침묵 병합
- 단계: spec | 심각도: major
- 재현: spec 블록 3개(정상/에러/경계) 작성 → `lnpl compile` rc=0(무진단) → `lnpl spec -o` 가 `1 case(s)`로 병합(given 연결, when 3회 반복, expect에 completed·failed 동시 포함 — evidence/08 manifest 원문) → `--run`은 우연한 충돌 검사로만 실패.
- 진단 원문: `` compile error: `empty repository` and `stored ...` contradict each other: there is no row to store into an empty store. Drop one. `` — 메시지는 명확하나 **진짜 원인(블록 병합)** 을 가리키지 않음.
- 기대 vs 실제: DoD "정상≥1+에러≥1+경계≥1 시나리오" vs 케이스 1개만 표현 가능.
- 재시도: 2 | 우회: 부분 — 정상 케이스만 spec에 싣고(5 단언 PASS), 에러(retry attempts=4)·경계(stock 0 등)는 evidence/04·05 런타임 실측으로 대체(DoD 허용 조항).

### F-8: `stored` 엔티티명은 소문자만 + 진단 시점 불일치
- 단계: spec | 심각도: minor
- 재현: `stored Product stock 0` → `lnpl compile` rc=0 통과 후 `lnpl spec --run`에서야 `compile error: given 'stored Product stock 0' names 'Product', which is not a declared entity`.
- 기대 vs 실제: 선언명 그대로(`Product`, 대문자) 인식 — 같은 파일의 `rows Order 1`은 대문자를 받는다 — vs `stored`만 소문자 요구(비일관). spec 절 검증이 compile 단계에 없음.
- 재시도: 1 | 우회: 성공(소문자 표기).

### F-9: modeB `--field` 오키 침묵 무시 — 기본값 0으로 가드 평가
- 단계: modeB | 심각도: minor
- 재현: `lnpl build <src> --run --field stock=5` → create·update 스킵(2스텝 completed). 정답 키는 조건식 점 표기 전체 `product.stock=5`(4스텝) — evidence/05.
- 기대 vs 실제: 오키 경고 vs 무진단 무시(help의 "ignored"가 유일한 단서).
- 재시도: 1 | 우회: 성공(점 표기 키).

### F-10: payload가 엔티티 네임스페이스 없이 평평하게 병합됨
- 단계: modeA | 심각도: info
- 재현: `sample_payload` 실측 — Product·Order 필드가 한 dict에 병합, 시드 행에도 통째로 복사(evidence/04 상단).
- 기대 vs 실제: 엔티티별 구분 vs 동명 필드 충돌 구조(이 케이스는 충돌 필드 없어 무해).
- 재시도: 0 | 우회: 해당 없음(관찰).

### F-11: 결정론적 검증 실패에도 retry 3회 발동
- 단계: modeA | 심각도: info
- 재현: 잘못된 UUID payload → validate 실패가 4회 시도(700ms) 후 확정(evidence/04 프로브). attempts=N+1 규칙 자체는 문서와 정확히 일치.
- 기대 vs 실제: 불변 실패는 즉시 확정 vs 일괄 재시도.
- 재시도: 0 | 우회: 해당 없음(관찰).

### F-12: 파이프라인 명령·플래그의 라우팅 갭
- 단계: authoring(사전 탐색) | 심각도: minor
- 재현: 스킬 문서에는 `compile`/`spec --run`/`diff`만 등장. `-o`, `run --payload/--no-row`, `build --field/--workdir`, openapi 서브커맨드 존재는 `impl/lnpl/cli.py`를 직접 읽어야 전모 파악(evidence/01 관찰). "공개 문서만으로 개발" 시뮬레이션에서 이탈을 강제하는 지점.
- 기대 vs 실제: 스킬 라우팅으로 전 파이프라인 도달 vs CLI 표면의 문서 커버리지 부분적.
- 재시도: 0 | 우회: 성공(소스 열람 — 단 실전 SaaS 상황이면 불가능한 우회).

## 총평

LLM-only 개발자 관점에서 파이프라인 기계 자체는 인상적으로 견고하다 — 9단계
전부 첫 나절에 초록이 되고, differential까지 EQUIVALENT가 나오며, 에러 메시지
대부분이 행과 토큰을 정확히 가리킨다. 그러나 이 케이스의 핵심 비즈니스 규칙
셋 중 둘(수량 인지 재고 검사 F-1, 재고 차감 F-2)이 언어에 표현 자체가 불가하고,
나머지 하나(거부 F-5)는 "성공으로 위장된 스킵"이 되며, 선언한 타입 제약(F-6)마저
런타임이 무시한다 — 결과적으로 재고 초과 판매(S2)와 수량 0 주문(S4)이 completed로
통과하는 서비스가 만들어진다. spec은 워크플로당 1케이스 한계(F-7)로 경계값
검증을 언어 안에 담을 수 없어, 품질 증명이 파이프라인 밖 수동 실측으로 밀려난다.
**판정: 이 케이스(다중 엔티티 CRUD + 수량 비즈니스 규칙 + 상태 전이)에 대해
프로덕션 사용 불가** — 값 의미론(비교 우변 필드 참조·산술·할당·거부 신호)이
언어에 도입되기 전까지는 선언 골격+문서 생성용으로만 적합하다.
