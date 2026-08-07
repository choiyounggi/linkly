# 01 — authoring 발견 과정 (재측정)

페르소나 규율(D10): `plugins/lnpl/skills/**` + `examples/` + `rfcs/0015·0016`만 읽음.
impl/·scripts/ 소스 미열람. 원 실측의 우회(의미 재해석·축소·ageDays·주석 문서화)는
재사용하지 않고 원형 표현을 먼저 시도.

## 문서 라우팅 홉 (11홉)

| 홉 | 읽은 것 | 얻은 것 |
|----|---------|---------|
| 1 | lnpl-authoring/SKILL.md | 라우팅 표, 3함정(no-op 동사·비집행 선언·if/for 예약어) |
| 2 | references/grammar.md | **`and` 결합·`==`/`!=`·`input` 네임스페이스·기간 단위 `d`** (RFC-0015/0016 반영); 가드는 다음 항목 1개 소유, 연쇄 가드는 파싱 에러; 가드 피연산자 Integer/DateTime 한정 |
| 3 | references/types.md | 의미 타입 표(Password·Money·DateTime 샘플 값), refinement facet |
| 4 | references/declarations.md | 집행 매트릭스(retry/timeout enforced, jwt/encrypt unenforced), 진단 코드 5종 |
| 5 | references/verbs.md | 동사 17종(`set` 추가), no-op 정책 |
| 6 | references/naming.md | 노드 id 도출(`Approval`→`wf.approval`), 스텝 객체 소문자 연결형 |
| 7 | references/spec.md | **spec 블록 = 블록당 독립 케이스**(issue #46), given 필드 단위 덮어쓰기·`no <field>`·`stored`가 선언명도 수용 |
| 8 | cli-surface.md | 서브커맨드·rc 표(0/1/2/3/4)·`--strict`·`--field`/`--skip`(모드 B)·`--payload`는 JSON **파일** |
| 9 | examples/guarded.lnpl·checkout.lnpl | 가드 양방향 관측법, 모드 B `--field` 기본 0, 스텝 이름 유일성(diff 관측기), 가드 아래 저장소 호출의 모드 B 제약 |
| 10 | rfcs/0016-time-and-schedule-semantics.md | **30일 창 원형**: `when input.requestedAt - payment.createdAt <= 30d` — 주입식 now 관례(payload DateTime 필드), 차원 규칙(instant/scalar), 존 지정자 필수, `<=` 포함 경계 |
| 11 | rfcs/0015-value-semantics.md | `input.` 검사 의미(선언 안 된 필드 거부), 정적 거부 표(Money 피연산자·리터럴 양변·할당 후 가드), i64 도메인, §5.2가 t2 재현 예제 제공 |

**30일 창 payload 주입 방식 찾기 난이도(브리프 지정 측정 항목):** grammar.md(홉 2)가
단위 `d`와 "가드 필드는 Integer 또는 DateTime"을 언급 → RFC-0016(홉 10)의 Guide-level
예제가 정확한 원형과 "주입식 now" 관례를 명시. 스킬 문서에서 RFC로 넘어가는 링크는
없어 RFC 번호를 알아야 도달한다(grammar.md에 "(RFC-0016)" 괄호 표기가 단서). 총 2홉,
재시도 0회 — 원 실측(3회 실패 후 ageDays 우회)과 대조적.

## kb 재검 (원 F-14 재현 동형 3질의)

| 질의 | 원 실측 결과 | 재측정 결과 | raw |
|------|--------------|------------|-----|
| "결제 카드번호 필드 마스킹" | `naming-entity-field-conventions` (오라우팅) | **`security-sensitive-field-masking`** 1순위 + naming 2순위 | kb-q1.out |
| "환불 기간 제한 정책" | (no match) | (no match — 정직) | kb-q2.out |
| "amount limit validation" | (no match) | (no match — 정직) | kb-q3.out |

`kb --load security-sensitive-field-masking`(kb-load-masking.out): #43 수정 내역 —
**4채널(trace·bindings·모드 B·diff 마스킹 클래스)이 같은 chokepoint(mask_payload)를
지난다** 명시 + diff masking PASS의 스코프 한계를 문서가 스스로 밝힘. 원 F-14의 기대
("security 매칭 또는 정직한 no match")를 충족.

## D11 원형 표현 시도 표

| # | 시도 형태 (원 마찰) | rc | 결과 1줄 | raw |
|---|--------------------|----|---------| ----|
| b1 | Money 필드 가드 `input.amount > 0 and input.amount <= 10000` (F-4) | **2** | 컴파일 거부 — "declared type Money is neither Integer nor DateTime — RFC-0016 computes over whole numbers and instants only" (원: 무경고 컴파일 후 런타임 raw TypeError) | compile-b1-money-guard.err |
| b2 | 연쇄 `when` 2개 (F-2) | **2** | 파싱 에러 — "a guard owns exactly one step or block; write the two conditions as one guard joined by `and` (RFC-0015)" (원: 무진단 첫 가드 탈락) | compile-b2-stacked-guards.err |
| b3 | `payment.createdAt <= 43200m` (F-5③) | **2** | 컴파일 거부 — "compares … (instant) with a duration literal (scalar) … subtract two instants … then compare that to a duration such as `30d`" (원: 컴파일 통과 후 런타임 늦은 실패) | compile-b3-instant-scalar.err |
| b4 | **최종 원형 파일** — `input.` 가드, `and` 범위, DateTime 산술 30d 창, 필드 간 `<=`, spec 5블록(정상3+정상·에러2) | **0** | 컴파일 성공, 경고 2건(의도적 jwt/encrypt unenforced 프로브) — **1회 시도** | compile-b4-final.{out,err} |
| b5 | 전액 환불 `input.amountCents == payment.amountCents` 필드 간 등가 (F-3) — 별도 변형 파일 | **0** | 컴파일 성공, 무경고 | compile-b5-full-refund-eq.err |

`--strict` 구분: b4를 `--strict`로 컴파일하면 경고 2건이 rc=2로 승격(compile-b4-strict.err)
— 진단 게이팅이 존재하며 선택 가능(원 실측에는 없던 옵션).

## 재시도 계수 (원 대비)

- 원 실측: 편집 9회(가드 3·엔티티 2·spec 4), parse 재시도 8회(에러 3·성공 5).
- 재측정: **의도적 거부 프로브 3건(b1·b2·b3) 외 비의도 실패 0회** — 최종 파일은
  첫 컴파일에 rc=0. 스펙 블록 포함 원형이 문서만으로 1회에 도달.

## 잔존 제한 (authoring 단계에서 확인된 것)

- 가드 피연산자는 Integer/DateTime뿐 — **Money는 여전히 가드 불가**(단, 이제 컴파일
  시점 도메인 진단). 금액을 Integer 센트로 모델링해야 하며, Money 타입의 문서 표면
  (OpenAPI Money 스키마)과 가드 가능성은 양립 불가. 원 이중 필드(amount Money +
  amountCents) 우회는 재사용하지 않고 Integer 단일 필드로 모델링 — 이 선택 자체가
  "Money 도메인 산술 부재"(RFC-0015 §Open Questions 4)의 흔적.
- `or`·`not`·괄호 없음(RFC-0015가 결정으로 명시) — 이 케이스 요구에는 불필요.
