# evidence/02 — authoring·parse·lower (`lnpl compile`) (T03)

명령(최종): `.venv/bin/lnpl compile -o qa/cases/payment-refund/payment-refund.lir.json qa/cases/payment-refund/payment-refund.lnpl`
최종 rc=0, stdout: `wrote qa/cases/payment-refund/payment-refund.lir.json (24 nodes)`
**시도 4회** (원본: evidence/raw/compile-a{1..4}.{out,err})

## 시도별 기록 (진단 원문 인용)

| 시도 | 프로브 | rc | stderr 원문(발췌) | 판정 |
|------|--------|----|-------------------|------|
| 1 | 기간 산술 `refund.requestedAt - payment.createdAt <= 30d` + 필드 간 비교 `refund.amount <= payment.amount` | 2 | `compile error: line 46: invalid condition: unsupported condition form: … (RFC-0008 supports only `<field> exists\|missing` and `<field> <op> <value>`, where <value> is Integer or Duration)` | **표현 불가 확정(F)**: 필드 간 산술·비교 미지원. 진단 품질 높음 — 행 번호+지원 형식+근거 RFC 명시 |
| 2 | 진단이 안내한 Duration 값 형태 `refund.requestedAt <= 30d` | 2 | `compile error: line 48: invalid condition: invalid value '30d'` | **일(day) 단위 없음(F)**: 기간 단위는 ms/s/m뿐(grammar.md) — 30일은 43200m으로 수동 환산해야 |
| 3 | `43200m` + 입력 엔티티 가드 `payment.amount <= 10000` (Approval에 read 없음) | 2 | `compile error: workflow Approval: guard condition 'payment.amount <= 10000' reads entity.payment, but this workflow never reads it — no binding can ever exist, so the guard would be false forever` | **입력값 검증 표현 불가 확정(F-major)**: 가드는 read된 저장 행만 참조(RFC-0012 실행 스코프). 진단 품질 매우 높음 — 원인·귀결("false forever")까지 설명 |
| 4 | 우회 반영: Approval=find→guards→update("기존 결제 승인" 재해석), 창 가드를 `payment.createdAt <= 43200m`로 | 0 | 하단 경고 2건만 | 통과 |

## 남은 진단(시도 4)과 의도 판정 — 전부 의도됨

```
warning: declared-not-enforced [security.payment] security jwt — declared but unenforced: no token is issued or verified; the mechanism reaches the OpenAPI document only
warning: declared-not-enforced [security.payment] security encrypt — declared but unenforced: the field is not encrypted (Password masking is a separate, type-driven behaviour)
2 warning(s), 0 error(s)
```

- `security jwt`: 의도 — OpenAPI 반영 여부를 T07에서 실측하기 위한 프로브(D6).
- `security encrypt`: 의도 — "마스킹은 Password 타입 주도"의 진단 확인 프로브(D6). 메시지가 집행 매트릭스 문구와 일치.
- `policy timeout 3s`·`retry 2`: 진단 없음 — enforced이므로 무경고가 기대 동작과 일치.
- 참고: 진단은 stderr, 성공 시 exit 0 — 문서(lnpl-authoring SKILL.md) 그대로 실측 확인.

## Money 비교 관련

`payment.amount > 0`·`<= 10000`(Money 필드 vs Integer 리터럴)은 시도 4에서 파싱·바인딩 통과 —
폴백 1(amountCents) 불필요. 런타임 비교 의미는 T05에서 실측.

## verbs 검사 (Verify)

스텝 첫 낱말: validate, find, update, create — 전부 verbs.md 표 내(no-op 동사 0개).
`grep -E '^\s{4}(validate|find|update|create|when|#|spec)' + 수동 대조`로 확인.
