# evidence/08 — spec (`lnpl spec --run`) (T08)

명령: `.venv/bin/lnpl spec qa/cases/payment-refund/payment-refund.lnpl --run`
최종 출력(원문):

```
PASS Approval spec — completed (status=completed)
PASS Approval spec — steps 3 (steps=3 want=3)
PASS RefundRequest spec — failed (status=failed)
PASS RefundRequest spec — attempts 3 (max attempts=3 want=3)
spec: 4 passed, 0 failed
```

rc=0. **시도 6회** (원본: evidence/raw/spec-run*.{out,err}). 매니페스트: payment-refund.spec.json.

## 시도별 발견

| 시도 | 프로브 | 결과(원문 인용) | 발견 |
|------|--------|------------------|------|
| 1 | `stored Payment ageDays 31` | `compile error: given 'stored Payment ageDays 31' names 'Payment', which is not a declared entity` | Payment는 선언돼 있음 — **오도적 진단**(소문자 바인딩명 `payment` 요구를 "not a declared entity"로 보고) (F) |
| 2 | 워크플로당 spec 블록 3개(정상/에러/경계) | `compile error: 'empty repository' and 'stored ...' contradict each other: there is no row to store into an empty store. Drop one.` | **블록 간 given 병합의 첫 징후** |
| 3 | stored 제거 후 3블록 | `spec: 4 passed, 6 failed` — 정상·경계 블록이 `status=failed`·`steps=1`로 평가됨(빈 저장소 given이 전 블록 오염) | **워크플로당 시나리오 1개만 가능** — 모든 spec 블록의 given이 병합돼 단일 실행에 전 expect를 평가(F-major: 정상+에러+경계 공존 불가) |
| 4 | 경계 given에 전체 필드(`amount {'amount': …}` 포함) | `compile error: unsupported given: "amount {'amount': '10000.01', 'currency': 'USD'}" …` | **Money 값은 given으로 표현 불가**(F) |
| 5 | amount 줄 제거한 전체 given | `FAIL Approval spec — completed (status=failed)`, `steps=1` | given은 payload를 **통째 대체**(병합 아님) → 필수 Money 필드를 못 채워 validate에서 실패 — **경계 시나리오는 spec으로 표현 불가 확정** |
| 6 | Approval=정상(도출 표), RefundRequest=에러(retry 도출) | `spec: 4 passed, 0 failed` | 통과 |

## DoD 매핑 (spec 블록: 정상 ≥1 + 에러 ≥1 + 경계값 ≥1)

- 정상 1: Approval — `completed` + `steps 3` ✓ (도출 표의 항상-케이스)
- 에러 1: RefundRequest — `failed` + `attempts 3` ✓ (`policy retry 2` → N+1 도출)
- 경계값: **표현 불가 → F-기록 대체**(brief 허용). 근거: 워크플로당 1시나리오 제한(시도 3) +
  given의 payload 통째 대체 + Money 값 표현 수단 부재(시도 4·5). 경계 실측 자체는
  mode A payload 실행으로 완료(evidence/04 — 0/-1/1000000/1000001 매트릭스; CLI payload는
  JSON이라 Money 표현 가능).

재컴파일 재확인: compile rc=0(경고 2건 — 의도 프로브 그대로), validate_ir PASS.
