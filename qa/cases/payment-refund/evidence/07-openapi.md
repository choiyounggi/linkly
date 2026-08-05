# evidence/07 — openapi (`lnpl openapi`) (T07)

명령: `.venv/bin/lnpl openapi -o qa/cases/payment-refund/payment-refund.openapi.json qa/cases/payment-refund/payment-refund.lnpl`

```
rc=0
wrote qa/cases/payment-refund/payment-refund.openapi.json (2 path(s))
```

시도 1회, **PASS**. 원본: evidence/raw/openapi.{out,err}

## cardNumber(민감 필드) 문서 표면

```json
"cardNumber": {"type": "string", "format": "password", "writeOnly": true}
```
(components/schemas/Payment/properties)

- `format: password` + `writeOnly: true` — 문서 계약상 응답에 나타나지 않는 필드로 정확히 처리.
- 예시 값 누출 0건: `4111` present: False, `s3cret` present: False, example 키 0개.

## security jwt의 문서 반영 (declared-not-enforced 프로브 확인)

```json
"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}
```
- 두 경로(`/payment-service/approval`, `/payment-service/refund-request` POST) 모두
  `security: [{"bearerAuth": []}]` 적용 — 집행 매트릭스의 "the mechanism reaches the
  OpenAPI document only"를 문서 쪽에서 실측 확인.

## 계약 불일치 발견 (F-기록 참조)

문서 계약은 `writeOnly: true`(응답에 cardNumber 미출현)를 약속하지만, mode A 런타임의
`result.bindings`는 cardNumber **원문을 반환**한다(evidence/04, 30행 인용) —
**문서가 런타임보다 더 안전한 계약을 광고**하는 불일치.
