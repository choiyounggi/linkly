# CASE-SPEC — inventory-order (Task 02)

브리프 제품 스펙을 Given/When/Then으로 고정한다(D3: 구체값, edge twin 전부 결정).
경계값 도출 근거: testing-quality-minimum-case-set §3 Number 행 — 0, 정확한 한계,
한계+1. 정확 한계(qty=stock)는 **inclusive(허용)** 로 결정한다. 수량 0 주문은
**무효(거부)** 로 결정한다 — 이 두 결정이 요구사항의 미결정 edge를 지금 닫는다.

## 시나리오

| ID | Given | When | Then | 종류 |
|----|-------|------|------|------|
| S1 | Product stock=5 | 주문 qty=2 | 주문 생성·confirmed, 재고 5→3 | 정상 |
| S2 | Product stock=1 | 주문 qty=2 | 거부 — 주문 미생성, 재고 1 유지 | 에러 |
| S3 | Product stock=0 | 주문 qty=1 | 거부 — 주문 미생성 | 경계(재고 0) |
| S4 | Product stock=5 | 주문 qty=0 | 거부 — 수량 0 주문은 무효 | 경계(수량 0) |
| S5 | Product stock=5 | 주문 qty=5 | 주문 생성·confirmed, 재고 5→0 | 경계(정확 한계) |

## 판정 관측 지점 (시나리오별)

- S1: mode A `--json` trace의 효과 목록(create Order 존재, update Product 존재) + spec 정상 케이스 `completed`.
- S2: 가드 불통과 경로의 관측 — trace에서 create가 스킵되었는가, 또는 spec `failed`. (거부 의미론이 표현 불가하면 P5 F-기록으로 대체)
- S3: `given stored Product stock 0` spec 케이스 또는 mode A 변형 실행의 가드 스킵 관측.
- S4: qty=0 입력 구동 — payload 또는 spec `given quantity 0`. 무효 판정을 표현할 어휘가 없으면 P6 F-기록.
- S5: stock=qty 정확 한계 — 가드 통과 여부 관측(가드 부등호가 `>` 뿐이면 `>=` 표현 가능성 자체가 P2 프로브 대상).

## 모호어 감사 (D3)

"적절히/그럴듯/graceful/등등/알아서" 0건 — 본 문서의 모든 Then은 관측 가능한
사실(생성/미생성, 재고 수치, completed/failed)로만 기술했다.
