# evidence/04-modeA — IR 인터프리터 실행 (재측정 Task 03)

재시도 수: **1** (--strict 귀속 통제를 위한 서술 선언 제거 — 아래 §strict 귀속.
시나리오 실행 자체는 전 변형 1회 통과)

payload: 원 실측과 동형 — 두 엔티티 필드가 평평하게 병합된 단일 JSON 객체
(`.claude/tmp/qa-r1/pS*.json`, 내용은 아래 표의 stock/quantity만 다름):

```json
{"id":"3f2504e0-4f89-41d3-9a0c-0305e82c3301","name":"widget",
 "price":{"amount":"10","currency":"USD"},"status":"created",
 "placedAt":"2026-08-07T09:00:00Z","stock":<S별>,"quantity":<S별>}
```

F-10 재관측: 병합 구조 동일(엔티티 네임스페이스 없음; `id`가 Product·Order에
공용) — 변화 없음, 이 케이스에선 무해.

## 시나리오 변형 (S1~S5 × --strict on/off)

커맨드: `lnpl run <src> --payload .claude/tmp/qa-r1/pS<n>.json [--strict]`

| 시나리오 | rc(기본) | rc(--strict) | 관측(실행된 스텝 목록 기준) | CASE-SPEC 기대와 비교 |
|----------|----------|--------------|------------------------------|----------------------|
| S1 stock=5, qty=2 | 0 | **0** | 5스텝 전부: validate·find·create·**set(Assignment target=product.stock, value=3)**·update — completed | ✅ 주문 생성 + **재고 5→3 차감 실측**(binding product.stock=3, update 영속) |
| S2 stock=1, qty=2 | 0 | **2** | validate·find만 실행. 상태줄 `completed (3 step(s) skipped by guard)` + `guard-skipped-steps` 진단 + skipped 목록 출력 | ✅(--strict) 주문 미생성·재고 유지. 기본 rc는 여전히 0(호출자 구별은 --strict 또는 레코드로) |
| S3 stock=0, qty=1 | 0 | **2** | S2와 동일 패턴(가드 false, 3스텝 스킵) | ✅(--strict) 거부 — 주문 미생성 |
| S4 stock=5, qty=0 | **1** | **1** | validate에서 실패(attempts=4, 700ms) → `workflow PlaceOrder -> failed` | ✅ **qty=0이 런타임 거부** — refinement min=1 집행(원 F-6의 "미집행" 소멸) |
| S5 stock=5, qty=5 | 0 | **0** | 5스텝 전부, set value=**0** — completed | ✅ 정확 한계 inclusive(`>=`) + 재고 0 도달 실측 |

가드 양방향 대조표(D5 — 판정은 실행된 스텝 목록으로):

| 가드 | true 런 | false 런 | true 신호 | false 신호 |
|------|---------|----------|-----------|------------|
| `wf.place.order.guard.1` `product.stock >= input.quantity` | S1·S5 | S2·S3 | steps에 create/set/update 존재 | steps 2개뿐 + skipped 레코드(guard id·조건·스텝 3개) + strict rc=2 |

## 거부 신호의 기계 관측 (`--json`, S2)

```json
"status": "completed",
"skipped": [{"guard": "wf.place.order.guard.1", "mode": "when",
  "condition": "product.stock >= input.quantity",
  "steps": ["create order", "set product.stock to …", "update product"],
  "rounds": null}]
```

`guard-skipped-steps` 진단 원문(stderr):

> the `when` guard did not run create order, …; the workflow still reports
> completed, so a caller reading only the status cannot tell this run from one
> that ran every step

— 원 F-5의 증상("성공으로 위장된 스킵")을 런타임이 **스스로 진단**하고,
--strict가 그것을 rc=2로 승격한다.

## --strict 귀속 통제 (재시도 1의 내역)

첫 strict 매트릭스에서 S1~S5 전부 rc=2가 나왔다 — 원인이 가드 스킵이 아니라
의도적 서술 선언(`performance response`)의 `declared-measured-only` 경고였다.
컨트롤: 서술 선언 2줄 제거(수정→재실행 1회) 후:

```
compile --strict rc=0   # 경고 0건
S1 strict rc=0 / S2 strict rc=2 / S3 strict rc=2 / S4 rc=1 / S5 strict rc=0
```

→ --strict rc=2가 **guard-skipped-steps 단독으로** 발생함을 분리 증명.
부작용 관찰(신규 마찰 N-1): --strict는 "의도된 서술 선언"과 "실수"를 구분할
억제 구문이 없어, 서술 선언을 쓰는 소스는 --strict 게이트와 양립 불가 —
게이트를 쓰려면 서술(response SLO 문서화)을 포기해야 한다.

## validate 특성화 프로브 (동형 재실행)

id를 `not-a-uuid`로 바꾼 payload: rc=1, `failed at: validate order`,
attempts=4(재시도 3회 발동, 700ms) — 원 실측과 동일. S4(qty=0)도 동일하게
attempts=4 소모: **결정론적 검증 실패에 여전히 일괄 재시도**(F-11 잔존).

판정: PASS — 원 실측에서 오답이던 S2(재고 초과 판매)·S4(수량 0 주문)가
언어 기제(가드 우변 필드 참조 + refinement 집행)로 차단된다.
