# 07 — OpenAPI 생성·정합 (재측정)

커맨드: `lnpl openapi -o payment-refund.openapi.json payment-refund.lnpl` → rc=0, 재시도 0.

## cardNumber 계약 vs 런타임 (원 F-8 재검)

- 문서: `"cardNumber": {"type": "string", "format": "password", "writeOnly": true}` —
  원 실측과 동일한 계약 표면.
- 런타임(evidence/04 §6): result.bindings가 원문 대신 `"***"` 반환 — **문서가 약속한
  "민감값은 응답에 실리지 않는다"가 이제 지켜진다.** 원 모순(문서 안전 과대 광고 vs
  원문 반환) 소멸.
- 뉘앙스: writeOnly의 엄밀 의미(응답에 필드 자체 미출현)와 달리 필드 키는 `***`
  값으로 출현한다. 민감값 비노출이라는 계약의 목적은 충족되며, 키 존재는 마스킹
  집행의 관측 가능 표지로 기능한다.

## 채널 ④ sweep (D1)

| 검사 | 결과 |
|------|------|
| 심은 값 `4111111111111111` grep | **0 hits** |
| 시드 값 `s3cret` grep | 0 hits |
| 네거티브 컨트롤(amountCents) | **4회 출현** (채널이 필드를 싣음을 증명) |
| bearerAuth | securitySchemes에 존재 (오퍼레이션별 적용, 원과 동일한 우수 표면) |
| paths | `/payment-service/approval`, `/payment-service/refund-request` |

F-8 예비 판정: **해소** — 계약과 런타임의 안전 모순 소멸(F-7 해소의 자동 정합,
원 FINDINGS가 예측한 그대로).
