# evidence/01-authoring — 원형 .lnpl 작성 (재측정 Task 02)

재시도 수: **3** (.lnpl 수정→재실행 총계; 내역은 아래 시도 이력. 원 실측 같은
단계는 컴파일 3이었음 — 횟수는 같으나 성격이 다르다: 원 3회는 "표현 불가 발견
후 후퇴", 이번 3회는 "원형 표현의 철자 교정"으로 전부 원형 유지).

## 문법 존재 표 (D2 6항목 × 레퍼런스 확인)

| D2 항목 | 문법 존재? | 출처(공개 문서) | 결과 |
|---------|-----------|----------------|------|
| ① 수량 인지 가드 우변 필드 참조 | **있음** — 가드 조건 `<값> <비교연산자> <값>`, 값은 참조·정수·기간 | references/grammar.md §값 표현식(RFC-0015) | `when product.stock >= input.quantity` **원형 성립** (엔티티 참조 `order.quantity`는 미읽힘 바인딩으로 거부 — 진단이 `input.quantity`를 직접 안내) |
| ② 재고 차감 | **있음** — `set <바인딩>.<필드> to <값>`, 이항 산술 1개 | references/grammar.md §값 표현식, references/verbs.md(`set`→Assignment) | `set product.stock to product.stock - input.quantity` **원형 성립**(정적) — 런타임 5→3 관측은 evidence/04 |
| ③ 상태 전이 | **없음** | grammar.md 값 문법(참조·정수·기간 — 텍스트 리터럴 無), naming/declarations 전수 확인 | `set order.status to confirmed` 시도 → 거부(아래 시도 3). 전이 제약 구문도 여전히 없음 → **표현 불가 잔존**, enum 타입 선언까지만(원 F-3과 동일 우회) |
| ④ 거부 신호 | 런타임 측정 항목 | cli-surface.md(rc 표, `--strict`, `guard-skipped-steps` 진단) | evidence/04에서 측정 |
| ⑤ 수량 0 거부 | **있음**(선언) — `PositiveInteger` 프리셋 min=1 | references/types.md | 런타임 집행 여부는 evidence/04에서 측정 |
| ⑥ spec 3블록 분리 | **있음** — "블록마다 독립 케이스 하나가 된다 — 정상/에러/경계 시나리오는 블록을 나눠 쓴다" | references/spec.md | 3블록(S1 정상/S2 에러/S4 경계) 작성. 실행 결과는 evidence/08 |

가드 스코프: grammar.md §가드의 스코프가 이제 **명문화**(원 F-4의 문서 갭 해소)
— "블록으로 묶으면 블록 전체가 가드 안" 규칙대로 `pipeline` 블록 사용.

## 시도 이력 (수정→재실행 각 1회)

| 시도 | rc | 진단 원문(발췌) | 조치 |
|------|----|----------------|------|
| 1 | 2 | `compile error: line 55: 'merge' closes a 'parallel' block, but none is open` | pipeline 블록 뒤 `merge` 제거(merge는 parallel 전용 — 문서에 pipeline 종결 규칙 없음, 아래 N-후보) |
| 2 | 2 | `compile error: workflow PlaceOrder: guard condition 'product.stock >= order.quantity' reads entity.order, but this workflow never reads it — no binding can ever exist, so the guard would be false forever (to check the run's input instead, write 'input.quantity')` | 진단의 안내 그대로 `input.quantity`로 교정(가드+set 산술 양쪽). **진단이 원인·수리를 모두 말한다** — 원 F-1의 "규칙이 에러에 없음"과 대조적 |
| 3 | 2 | `compile error: workflow PlaceOrder: guard condition 'set order.status to confirmed' reads entity.order, …` | 상태 전이 프로브 제거(F-3 잔존 판정 근거로 채택). 부수 관찰: set 스텝이 진단에서 "guard condition"으로 지칭됨(메시지 라벨 부정확 — 아래 N-후보) |
| 4 | **0** | `warning: declared-measured-only [perf.order] performance response — declared but measured …` / `1 warning(s), 0 error(s)` | 성공 — `wrote inventory-order.lir.json (22 nodes)` |

## --strict 컴파일 (D8)

```
$ lnpl compile … --strict
# rc=2  (진단 1건 — 위 declared-measured-only 경고가 게이트에 걸림)
```

관찰: `performance response`는 **의도적 서술**(원 소스와 동일)인데 --strict가
이를 에러로 승격한다. 의도 선언과 실수 선언을 구분하는 억제 구문은 문서에 없음
(N-후보; 런타임 --strict 측정에 간섭 — evidence/04에서 처리).

## IR 생존 계수 (D6 — 조건 텍스트 기준)

```
'product.stock >= input.quantity': 1   # 가드 조건 원문 그대로 1회
'product.stock - input.quantity' : 2   # Assignment 표현식(+표시 중복 1)
'confirmed': 2 / 'created': 1          # OrderStatus enum facet
'PositiveInteger': 2 / 'min': 1        # quantity refinement
```

노드 트리(발췌):

```
Guard wf.place.order.guard.1 cond='product.stock >= input.quantity'
  └ Pipeline wf.place.order.pipeline.1
      ├ step.3 create order      (RepositoryCall)
      ├ step.4 set …             (Assignment)
      └ step.5 update product    (RepositoryCall)
```

판정: 가드 1선언=1노드(조건 원문 일치), **pipeline 3스텝 전부 가드 아래** —
원 F-4의 "1스텝만 감싸고 문서 없음"이 블록 문법+명문화로 원형 해결(정적).
spec 블록은 IR에 실리지 않음(매니페스트 별도 — evidence/08).

## D18 — 발견 출처 기록 (F-12 재검용)

이 태스크에서 쓴 모든 문법·커맨드·플래그: `compile -o/--strict`(cli-surface.md),
동사 `set/validate/find/create/update`(verbs.md), `pipeline` 블록·가드 스코프·값
표현식(grammar.md), `PositiveInteger`/refine facet(types.md), 스텝 객체 소문자
연결형(naming.md), spec 3블록(spec.md). **소스(impl/) 열람 0건.**
미해결 문서 갭: pipeline 블록의 종결 규칙(merge 불가만 진단으로 발견).
