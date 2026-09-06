# FINDINGS — s1-order-platform

환경: 커밋 264e344, lnpl 0.8.0, python 3.13.1, 드라이버 sqlite(내장)/none, dev_doctor rc=1 (evidence/00-env.md — MLIR/LLVM 미설치, 환경 문제·모드 A만 사용해 무관)
조건: 블랙박스(requirements/README.md §2), impl/ 열람 2회(각 F-항목에 표기), impl/ 수정 0건
**Round 2 (rework, `.orchestration/reviews/t1-r1.md` 대응):** F1–F4 전부 실행/재현으로 대응 — 답변은 그 파일 자체에 append됨.

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| authoring | PASS | evidence/01-authoring.md | 42 (`## Rounds` 절, `- round N:` 그레프 가능 — F-16 해소) |
| compile(--strict=warning) | PASS | evidence/02-compile.md | 4 (entity-only) |
| modeA run | PASS | evidence/03-run.md | R1–R7 전체 그린, F-6/F-9/F-11 예외 (F-11은 round 2에서 실행으로 재확인) |
| spec | PASS | evidence/04-spec.md | 9 블록/33 단언, A1–A8 전건 그린 + D3 flip-red-restore-green 실증 (round 2, F1 해소) |
| openapi | 불가(blocker) | evidence/05-openapi.md | 크래시 1건(F-12), 우회 기각 1건(F-13) — 최신(정확한) 소스로는 재생성 자체가 안 됨 |
| serve(실 HTTP) | 불가(blocker, F-12 연쇄) | evidence/06-serve.md | round 2: 정확한 소스로 `lnpl serve` 기동 자체가 크래시함을 확인 — "시간 상한"이 아니라 "불가"로 재분류. 격리된 동치 픽스처로 F-4의 200/500 상태코드는 실 HTTP로 검증 |
| R10 변경 요청 | PASS(4라운드, 1회 자체 버그) | evidence/07-change-request.md | 4 |

## 요구사항 커버리지

| R | 요구 | 판정 | 근거(evidence 경로 + 실행 출력 인용) |
|---|------|------|--------------------------------------|
| R1 | 코드베이스 구조·Stock 가시성 | 충족 | evidence/02-compile.md — `internal/` 디렉터리 하나로 팀 분리+가시성 거부(rc=2, `not visible from namespace 'payments'`)까지 코드 0줄 추가 |
| R2 | 주문 생성·재고 검사·원자성 | 부분 — 예약 생성·거부·원자성(부분 잔존 없음)은 충족, **on_hand 차감은 불가**(F-6, 우회 시도 실패) | evidence/03-run.md A1/A3 — 성공 시 정확한 예약 1행, 재고 부족 시 진짜 실패(rc, 0 rows 확인)로 거부(둘 다 충족); 그러나 Stock.onHand 필드 자체는 어떤 성공 주문 뒤에도 시드값에서 전혀 줄지 않는다(F-3의 연쇄, 우회안도 시간 상한 안에 실패) — 반복/동시 주문에 대한 과다판매를 막지 못하는 실제 결함(reviewer F4) |
| R3 | 금액 계산 | 부분(우회: 반올림 규칙 상이 — F-5) | evidence/03-run.md A1/A2 — subtotal 100% 일치, tax/total은 반올림 규칙 차이로 s1.md 기대값과 1원 단위로 어긋남(둘 다 evidence에 실제값 기록) |
| R4 | 상태 전이 | 부분 | evidence/03-run.md A6 — 불법 전이 거부(데이터 레벨)는 확인, 다만 거부가 200(가드 스킵)으로 나가 s1.md의 "4xx 또는 동등" 기대와 다름(F-4) |
| R5 | 결제 | 부분(우회: PAN 미추출 — F-8) | evidence/03-run.md A4/A5 — 성공·불일치 거부 둘 다 확인, last4는 클라이언트가 이미 분리해 보낸다고 가정(서버 측 substring 연산 없음) |
| R6 | 취소 원자성 | 부분 | evidence/03-run.md A7 — round 2에서 read-back 재검증: round 1 DB는 Refund 행이 없었으나(증거 결함, F-18) 격리 재현에서는 order.status==4 + Refund 행(amountCents 일치)이 실제로 영속됨을 직접 조회로 확인. 이 정확한 이음매의 실패 주입은 별도로 못 만듦(F-9) |
| R7 | 환불 한도·권한 | 부분(major: count-cap 미집행 — F-11, round 2에서 실행으로 재확인; 권한 accept 경로 미검증 — F-14) | evidence/03-run.md §payments A8 — 누적 금액 한도는 실제로 거부(rc, 0 rows 확인); **3회 카운트 한도는 실행으로 미집행 확인**(1센트 환불 4회 전부 성공, 4행 존재 — round 2, 더 이상 코드 리뷰 추정이 아님); role=admin 승인 경로는 lnpl token에 --role 자체가 없어 검증 불가 |
| R8 | OpenAPI + 실 서버 | 불가(blocker: F-12/F-13) | evidence/05/06 — round 1엔 경로 23개가 생성됐지만 그건 F-13을 유발하는 임시 우회가 적용된 소스였다. **정확한(런타임이 옳은) 소스로는 `lnpl openapi`도 `lnpl serve`도 기동 자체가 크래시한다**(`serve`가 동일한 `openapi.generate()`를 기동 시점에 호출) — R8은 이 케이스의 정상 워크플로 형태에서 구조적으로 불가능하다. 격리 픽스처로 F-4의 200/500 코드 자체는 실 HTTP로 검증(evidence/06) |
| R9 | spec 전건 통과 | 충족 | evidence/04-spec.md — A1–A8 전건 9블록/33단언 그린 + D3 flip-red-restore-green 실증(round 2). round 1의 "불가(시간 상한)"는 오판이었다 — 실제 장벽은 `stored` 시드의 색인 폼(`Entity[0]`) 누락이었고 문서를 다시 읽어 해결했다(F-17) |
| R10 | 변경 요청 | 충족 | evidence/07-change-request.md — gift_wrap +200(physical)/거부(digital) 모두 확인, A1 회귀 없음(자체 버그 1건 포함 4라운드) |

## Frictions

### F-1: Money는 `set`/가드 산술의 피연산자가 될 수 없다
- 단계: authoring | 심각도: blocker | 축: expr
- 재현: `set line.lineTotal to line.unitPrice * line.qty` (양쪽 Money) → `compile error: ... declared type Money is neither Integer nor DateTime`
- 기대 vs 실제: s1.md는 Money 필드로 subtotal/discount/tax/total을 계산하길 기대 vs `rfcs/0044-money-arithmetic.md`가 Money 산술을 집계(RowSet aggregation)에만 열고 일반 `set`/가드에는 명시적으로 닫아둠(§Guide-level Explanation)
- 재시도: 3 | 우회: 성공 — 모든 금액 필드를 Integer(센트)로 재선언(R3 자체가 "센트 정수 정밀도"라고 이미 요구해 큰 왜곡은 아님). 의미 손실: 필드가 더 이상 `{amount, currency}` Money 구조가 아니어서 다중 통화·OpenAPI의 Money 스키마 표현을 잃는다
- 보완 제안: Money를 `set`의 피연산자로 열거나(§Open Questions 1이 이미 이월), 최소한 "센트 정수 필드 + 통화 상수"라는 이 우회를 공식 패턴으로 문서화

### F-3: 한 실행에서 건드리는 모든 엔티티가 payload 하나의 `id`를 공유한다
- 단계: authoring | 심각도: blocker | 축: expr
- 재현: `find product`(기존 상품 조회) + `create order as newOrder`(새 주문 생성)를 한 워크플로에 두면, 서로 다른 두 주문이 같은 상품을 참조할 때 두 번째 주문 생성이 `repository create conflicts: entity.order already exists`로 거부됨(`.claude/tmp/find_probe/probe5.lnpl`로 재현)
- 기대 vs 실제: `find`/`create`가 서로 다른 자연키(주문 자신의 id vs 참조하는 상품의 id)로 동작할 것을 기대 vs `impl/lnpl/repo_policy.py::row_key`가 어떤 엔티티든 `payload["id"]` 하나만 쓴다(근인, impl 열람)
- 재시도: 6 | 우회: 성공 — `find` 대신 `list <entity> where id == input.<field>`(RFC-0038 등가 predicate, id에 종속되지 않음) + `max`/`sum`으로 필드를 뽑아낸다. 의미 손실: 없음(읽기 전용 참조에는 완전 대체), 다만 발견 비용이 6라운드
- 보완 제안: `find`/`create`에 조회 키 필드를 지정하는 표기(`find product by input.productId`류)를 열면 이 우회 자체가 불필요해진다

### F-6 (F-3의 연쇄): Stock.onHand가 실제로 갱신되지 않는다
- 단계: modeA run | 심각도: blocker 후보 | 축: expr
- 재현: A1(P1 qty2)·A2(P1 qty3) 이후 P1 재고를 다시 조회해도 `onHand`는 여전히 시드값(5)
- 기대 vs 실제: R2는 "성공 시 그만큼 on_hand를 차감" 요구 vs F-3 때문에 Stock을 `find`+`update`할 방법이 없어(주문 자신의 id와 상품의 id가 같은 실행에서 공존 못 함) 매 요청이 원본 onHand만 재확인
- 재시도: 3(대안 설계 검토) | 우회: 실패 — StockReservation 누적합으로 가용재고를 동적 계산하는 대안도 검토했으나 그마저 가드 제약(아래 F-3/가드 절 참고)에 막혀 시간 상한 안에 완성 못함. 최종 구현은 정적 onHand만 확인(의미 손실: 동시/반복 주문에 대한 과다판매 방지 없음)
- 보완 제안: F-3이 풀리면 자동 해결

### F-4: 업무 규칙 거부(가드 스킵)는 HTTP 200이다
- 단계: modeA/serve run | 심각도: major | 축: doc
- 재현: A5(금액 불일치) → `status: completed`, `skipped: [...]`, 응답 없음 — `lnpl serve`라면 200
- 기대 vs 실제: s1.md의 모든 A-거부 시나리오가 "거부(4xx 또는 동등)"를 기대 vs `docs/serving.md` M9 "가드 거부는 200이다"(RFC-0014)가 명시적으로 그렇게 설계됨
- 재시도: 0(설계 문서로 확인) | 우회: 부분 — 업무 규칙을 `when` 대신 `list where`(공백 RowSet 강제 실패, F-10)로 재구성하면 진짜 500(RunError)로 거부할 수 있음(R2/R7이 이 방식). R4/R5/R6은 상태 전이 조건이 이미 찾은 엔티티의 필드라 이 우회를 적용하지 않음(의미 손실: 그 셋은 200으로 남음)
- 보완 제안: `when`에 "게이트 실패 시 4xx로 응답"을 선언하는 옵션을 열면 이 비대칭이 사라진다

### F-5: 반올림 규칙이 s1.md의 기대(반올림)와 다르다(플랫폼은 절삭)
- 단계: modeA run | 심각도: minor | 축: doc
- 재현: A1 tax: `(3998−0)×0.08=319.84` → 실제 319(절삭), 기대 320. A2 discount: `5997×0.10=599.7` → 실제 599, 기대 600
- 기대 vs 실제: s1.md 자체가 "반올림/내림 중 플랫폼이 정한 대로"라고 열어뒀고, `rfcs/0028-arithmetic-and-alternative-guards.md`의 Integer `/` 계약(0 방향 절삭)이 정본
- 재시도: 0(문서로 이미 예견된 차이) | 우회: 불필요 — 문서화만
- 보완 제안: 없음(설계상 의도된 차이, s1.md도 이를 인지하고 기록만 요구)

### F-10: `list where`의 우변은 이 워크플로가 방금 `set`한 필드를 참조할 수 있다(가드는 못 한다) — 이것이 R7 캡 집행을 가능하게 한 발견
- 단계: authoring | 심각도: (발견 자체, 심각도 표기 대상 아님) | 축: doc, llm
- 재현: `when newOrder.x == 1`(x를 이 워크플로가 앞서 set) → 컴파일 거부("guard must not depend on a value this workflow changed"). 반면 `list payment where id == input.payment and amountCents >= newRefund.cumulativeCents`(cumulativeCents도 이 워크플로가 앞서 set) → 컴파일·실행 모두 성공(evidence/03 §A8)
- 기대 vs 실제: 두 문법 위치가 같은 `Condition` 파서(condition.py)를 공유한다고 문서가 강조하는데(RFC-0038 §Motivation), 자기-대입 필드 참조 가능 여부는 위치마다 다르다 — 어느 레퍼런스 문서에도 이 비대칭이 없다
- 재시도: 2(가드 제약을 먼저 만나고, list where로 우회를 재발견) | 우회: 성공, 의미 손실 없음
- 보완 제안: grammar.md/spec.md에 "이 제약은 `when`/`until`에만 적용되고 `list where`에는 적용되지 않는다"를 명시

### F-11: 환불 "3회 상한"은 누적 금액 상한과 별개로 집행되지 않는다
- 단계: modeA run | 심각도: major | 축: expr
- 재현(round 2, 실행으로 재확인): 108000센트 결제에 1센트 환불을 4회 연속 요청(누적 4 << 108000, 금액 상한과 분리) → 4회 전부 `completed`, `entity.payments.refund` 실제 행 4개 확인(`select count(*) ...` → 4). round 1은 코드 리뷰로만 추정했었다(reviewer F3 — 이제 실행 증거로 대체)
- 기대 vs 실제: R7 "환불은 최대 3회" vs 구현은 누적 금액만 `list where`로 강제, 횟수 자체는 어떤 필드로도 세지 않음
- 재시도: 1(경계 테스트 설계+실행) | 우회: 실패 — 아래 보완 제안 방향은 미검증인 채 시간 상한
- 보완 제안: F-10과 같은 기법으로 `list refund where payment==input.payment` 다음 `count`를 같은 방식(우변에 자기-set 필드) 활용해 두 번째 캡을 추가하면 될 것으로 보임(미검증)

### F-17: `given: stored <Entity> <field> <value>`(색인 없는 형태)는 `list where`에 보이지 않는다
- 단계: spec | 심각도: minor | 축: doc
- 재현: `stored Customer id X` + `find customer` → 정상; `stored Customer id X` + `list customer` → `row_count 0`(빈 RowSet처럼 취급). `stored Customer[0] id X`(색인 폼)로 바꾸면 즉시 해결(`.claude/tmp/spec_probe/probe2.lnpl` vs `probe4.lnpl`로 대조 재현)
- 기대 vs 실제: `spec.md`가 색인 폼을 "`list <entity>`가 읽는 RowSet을 이렇게 채운다"고 명시하지만, 바로 위 문단의 색인-없는 폼과 나란히 있어 "이 RowSet 채우기가 필수"라는 인상을 주지 않는다 — `list`가 압도적으로 흔해질 이 케이스류 설계(F-3 우회의 필연적 결과)에서는 색인 폼이 사실상 기본값이어야 한다
- 재시도: 2(라운드 41 격리 재현 포함) | 우회: 성공, 의미 손실 없음
- 보완 제안: spec.md가 "엔티티를 `list`로 읽는 워크플로는 색인 없는 `stored`가 조용히 아무 효과가 없다"를 명시적으로 경고

### F-18: round 1의 A7 증거가 read-back 없이(응답 JSON만으로) 작성됐고, 사후 재조회에서 실제로 어긋났다
- 단계: modeA run(증거 절차) | 심각도: major(증거 신뢰성) | 축: (해당 없음 — 검증 관행)
- 재현: round 1 evidence/03의 A7은 `lnpl run --json`의 `response` 필드(`newRefund.amountCents: 1078`)만 인용했다. round 2에서 원본 `.claude/tmp/s1.db`를 직접 조회하니 `entity.payments.refund` 아래 그 주문 id로 된 행이 **하나도 없었다**(`order`/`order.line`/`stock.reservation`/`payment` 행은 있음). 완전히 격리된 새 DB에서 동일 소스로 재현하면 Refund 행이 정상적으로 영속된다(read-back으로 재확인)
- 기대 vs 실제: FINDINGS-SCHEMA의 "초록≠충족" 원칙 vs round 1은 정확히 그 원칙이 막으려는 패턴(실행 응답을 곧 저장 상태로 착각)을 범했다
- 재시도: 1(재현 1회로 CancelOrder 자체는 정상 확인) | 우회: 실패 — round 1 DB의 결측을 확정적으로 재현하거나 원인을 특정하지 못했다(같은 세션에서 F-12/F-13 조사 중 여러 차례 재컴파일한 것이 원인일 가능성이 높다고 추정할 뿐, 검증된 근인 아님)
- 보완 제안: (이 케이스 자신에 대한 제안, 플랫폼 아님) 모든 create/update 주장은 `response` 인용이 아니라 반드시 별도 sqlite 조회로 맺을 것 — 이번 세션에서 그렇게 하지 않은 다른 evidence 항목이 더 있는지는 재검토하지 못함(시간 상한)

### F-12: `lnpl openapi`가 `create ... as` + `respond`에서 크래시한다(RFC-0030 골든 예제 자체가 이 조합)
- 단계: openapi | 심각도: blocker | 축: rt
- 재현: 최소 2줄 엔티티 + `create order as newOrder` / `respond newOrder.id` → `lnpl openapi` → `KeyError: 'newOrder'`(`impl/lnpl/openapi.py:475`, 근인 impl 열람)
- 기대 vs 실제: RFC-0030 §Guide-level Explanation의 첫 예제가 정확히 이 형태 vs `openapi.py`의 `_response_schema`가 `create ... as` 별칭 바인딩을 모른다(`find`/`read` 바인딩만 안다) — RFC-0030이 인터프리터만 갱신하고 openapi.py는 갱신하지 않음
- 재시도: 2 | 우회: 시도했으나 기각(F-13 유발) — 최종적으로 정확한 런타임을 택하고 openapi 생성 실패를 그대로 기록
- 보완 제안: `openapi.py`의 `by_binding`이 `create ... as` 별칭도 인식하도록 RFC-0030 반영을 마저 한다

### F-13: (F-12의 회피책이 유발) `find`가 방금 `create ... as`로 만든 같은 엔티티를 다시 읽으면, 그 `create` 자체가 허위 충돌로 실패한다
- 단계: modeA/serve run | 심각도: blocker | 축: rt
- 재현: `create order as newOrder` / `set ...` / `find order` / `respond order.id` — 완전히 새 빈 DB, 한 번도 안 쓴 id로 실행해도 `status: failed`, `repository create conflicts: entity.order already exists`(`.claude/tmp/find_probe/probe11.lnpl`로 최소 재현)
- 기대 vs 실제: `find`가 그저 방금 만든 행을 다시 읽어올 뿐이어야 함 vs 인터프리터의 기본 행 시딩("이 워크플로가 읽는 엔티티"를 미리 채우는 로직, RFC-0030 시대 `repo_policy`)이 "방금 이 실행에서 만든 엔티티" 예외를 두지 않아 `create`보다 먼저 스켈레톤 행을 심는 것으로 추정(근인, impl 열람 — `interp.py`의 create/read 순서 훅)
- 재시도: 2 | 우회: 실패 — 발견 즉시 F-12 회피책 자체를 철회
- 보완 제안: 근본적으로 F-12를 고치면 이 조합을 아무도 다시 밟지 않는다; 별도로도 "이 실행에서 이미 create한 엔티티는 사전 시딩 대상에서 제외" 수정 필요

### F-14: 참조 토큰 발급기(`lnpl token`)로는 역할(role) 클레임을 넣을 수 없다
- 단계: serve | 심각도: major | 축: ops
- 재현: `lnpl token --help`/`cli-surface.md`의 `token` 표에 `--role` 없음; `docs/serving.md`는 `security role`이 검증된 토큰의 `role`/`roles` 클레임을 읽는다고 명시
- 기대 vs 실제: 내장 CLI만으로 admin 승인 경로까지 왕복 검증 가능할 것을 기대 vs 실제로는 거부 경로(역할 부재 → 403)만 검증 가능
- 재시도: 0(플래그 부재 확인만) | 우회: 실패(외부 IdP `--token-provider` 필요, 이 케이스 범위 밖)
- 보완 제안: `lnpl token --role <r>` 최소 플래그 추가

### F-15: `pipeline`의 암묵 종결 규칙이 저자 실수를 유발한다
- 단계: authoring | 심각도: minor | 축: llm
- 재현: R10 round 2 — `when X / pipeline Y`(3줄) 뒤에 제어 키워드 없이 이어지는 나머지 워크플로 전체가 같은 가드에 흡수됨(evidence/07)
- 기대 vs 실제: "가드는 다음 항목 하나만 소유"라는 문서 문구가 pipeline의 "다음 줄 몇 개만" 직관을 주지만, 실제로는 다음 제어 키워드까지 전부 흡수
- 재시도: 1(즉시 자체 발견·수정) | 우회: 성공(빈 `pipeline` 하나 추가해 강제 종결) — 의미 손실 없음
- 보완 제안: `guard-skipped-steps` 경고에 스텝 개수/이름이 예상보다 많으면 별도 강조(예: "N개 스텝, 워크플로의 마지막 스텝까지 포함")를 주면 저자가 더 빨리 알아챈다

### F-16: D4 라운드 로그 형식(`- round N: <이유>`)을 이 케이스가 지키지 않았다
- 단계: authoring | 심각도: minor | 축: (해당 없음 — 자기 절차 위반)
- 재현: evidence/01/07이 서술형 불릿을 씀
- 기대 vs 실제: t1 plan D4가 grep 가능한 고정 포맷을 요구
- 재시도: 1(round 2에서 재구성) | 우회: 성공(round 2) — evidence/01-authoring.md에 `## Rounds (D4 format)` 절을 추가해 42개 `- round N:` 라인으로 재구성(reviewer F3). 기존 서술형 절은 지우지 않고 남김(리뷰어 지시: "기존 프로즈를 다시 쓰지 말 것")
- 보완 제안: 다음 케이스는 처음부터 `- round N:` 접두를 쓸 것(플랫폼 문제 아님, 이 실행의 프로세스 결함)

## 케이스 판정

**Block** — round 3 수정. round 2의 "Ship-with-known-issues"는 자기모순이었다:
조건 (2)(3)이 스스로 "우회를 찾지 못했다"/"가장 심각한 단일 결함"이라고 적어
놓고도 결론은 Ship이었다. `qa/rerun/REPORT.md`의 규칙(수용자 없는
known-issue는 Block)을 그대로 적용하면 t2·t3와 같은 결론이 나온다.

**주 사유(driver): F-12.** `lnpl openapi`뿐 아니라 `lnpl serve` 자체가 기동
시점에 크래시한다(`serve`가 동일한 `openapi.generate()`를 호출) — 이
케이스의 정상적인 워크플로 형태(RFC-0030이 권장하는 `create ... as` +
`respond` 그 자체)로는 API 문서화도 실 서빙도 전혀 불가능하다. "OrderHub"가
REST로 서비스되는 것이 R1/R8의 문면 그대로의 요구인데, 그 표면 자체가
존재할 수 없다. 우회를 하나 시도했으나(F-13 유발) 철회했고, 다른 우회를
찾지 못했다(round 1/2 전체).

**보조 사유(supporting): F-6.** `Stock.onHand`가 어떤 성공 주문 뒤에도 전혀
줄지 않는다(F-3의 구조적 한계 — 한 실행이 read-existing과 create-new를 각자
다른 id로 못 한다) — 반복·동시 주문에 대한 과다판매를 막을 방법이 없고,
대안(예약 합계로 가용재고 동적 계산)도 가드 제약에 막혀 완성하지 못했다.
이것은 코너케이스가 아니라 R2가 요구하는 원자적 재고 관리의 절반이다.

**Block을 뒤집을 조건 (수용 목록이 아니라 해소 조건이다):**
1. F-12/F-13이 고쳐져 `lnpl openapi`/`lnpl serve`가 이 케이스의 정상적인
   `create ... as` + `respond` 형태에서 기동·생성된다 — R8 전체가 복구된다.
2. F-3(한 실행 = 하나의 payload id)이 고쳐지거나 우회 표기(`find <entity> by
   <field>`류)가 생겨, Stock.onHand를 실제로 갱신하는 R2 원자성이 구현
   가능해진다 — F-6이 해소된다.
3. (1)+(2)가 해소된 뒤에도 소유자가 별도로 수용해야 할 항목들 — Block의
   원인은 아니고, 그 시점에 다시 판단할 부차 조건: Money가 산술 불가(F-1,
   센트-정수 우회로 이미 흡수됨), 업무 규칙 거부 대부분이 HTTP 200(F-4),
   환불 3회 카운트 상한 미집행(F-11), PAN 서버측 미추출(F-8), role 발급
   불가(F-14).

**별도로 채점되는 사실 — R9는 이 Block과 무관하다.** spec 표현력 자체는
문제가 아니었다: A1–A8 전건이 9블록/33단언으로 실제로 통과했고(D3
flip-red-restore 실증 포함, evidence/04), 이 케이스를 Block으로 만드는
것은 spec이 아니라 서빙 표면(F-12)과 재고 원자성(F-6)이다. t6가 "s1 =
Block"을 "spec으로 이 도메인을 표현할 수 없다"로 오독하지 않도록 이 문단을
분리해 둔다.

**증거 신뢰성 메모 (F-18, Block과 별개).** round 1의 A7 증거는 read-back
없이 응답 JSON만으로 작성됐고, 사후 검증에서 원본 DB와 어긋난 사실이
드러났다 — CancelOrder 메커니즘 자체는 격리 재현으로 정상 확인됐지만, 이
사실은 이 리포트의 나머지 mode-A 주장들에 대해서도 "기록 당시 read-back을
했는가"를 신뢰의 조건으로 남긴다.
