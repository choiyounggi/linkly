# evidence/04-modeA — IR 인터프리터 실행 (Task 05)

재시도 수: 0 (기본 1회 + 변형 6회 전부 구동 성공 — 단 결과 의미는 아래 판정 참조)
payload: 두 엔티티 필드가 **평평하게 병합**된 단일 JSON 객체
(`sample_payload` 실측: `{"id":…,"name":…,"stock":1,"price":…,"quantity":1,"status":"created","placedAt":…}`).
엔티티별 네임스페이스 없음 — 동명 필드는 충돌한다.

## 기본 실행

```
$ .venv/bin/lnpl run qa/cases/inventory-order/inventory-order.lnpl
# rc=0
workflow PlaceOrder -> completed  (24ms, correlation_id=cid-0001)
  step validate order     6ms attempts=1 [Validation -]
  step find product       6ms attempts=1 [RepositoryCall found=True]
  step create order       6ms attempts=1 [RepositoryCall found=True]
  step update product     6ms attempts=1 [RepositoryCall found=True]
  response SLO 50ms: met (measured, not enforced)
```

## 시나리오 변형 (`--payload .claude/tmp/qa-t1/pS*.json`)

| 시나리오 | payload 핵심 | rc | 관측 | CASE-SPEC 기대와 비교 |
|----------|--------------|----|------|----------------------|
| S1 stock=5, qty=2 | 4스텝 모두 실행 | 0 | completed | ✅ 생성됨. 단 재고 5→3 차감은 **관측 불가**(P3 표현 불가의 귀결) |
| S2 stock=1, qty=2 | 4스텝 모두 실행 | 0 | completed — **주문이 생성됨** | ❌ 기대는 거부. 수량 인지 검사(P2) 표현 불가 → 재고 초과 판매를 막을 수 없음 |
| S3 stock=0, qty=1 | validate·find만 실행, create·update 스킵 | 0 | **completed** (2스텝) | ⚠️ 가드 스킵은 작동하나 "거부" 신호가 없음 — 상태는 성공(completed), rc=0 |
| S4 stock=5, qty=0 | 4스텝 모두 실행 | 0 | completed — qty=0 주문 생성 | ❌ 기대는 무효. `PositiveInteger`(min=1)가 런타임 **미집행** |
| S5 stock=5, qty=5 | 4스텝 모두 실행 | 0 | completed | ⚠️ 생성은 맞으나 재고 0 도달은 관측 불가(P3) |

## validate 특성화 프로브 (S4 이해를 위한 추가 1회)

id를 `not-a-uuid`로 바꾼 payload:

```
# rc=1
workflow PlaceOrder -> failed  (700ms, correlation_id=cid-0001)
  step validate order   700ms attempts=4 [Validation -] …
  failed at: validate order
  WARN  step retry  (×3)
  ERROR step failed
```

판정: `validate`는 **의미 타입**(UUID 형식)은 집행하고 실패 시 `policy retry 3`이
발동(attempts=4 — N+1 정확). 그러나 **refinement facet**(min=1)은 집행하지 않는다.
부가 관찰: 결정론적 검증 실패를 3회 재시도(700ms 소모) — 재시도가 무의미한
실패 유형을 구분하지 않음(info).
