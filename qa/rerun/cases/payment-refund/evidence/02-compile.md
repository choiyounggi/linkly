# 02 — compile·lower·가드 생존 계수 (재측정)

## 컴파일

- `.venv/bin/lnpl compile -o payment-refund.lir.json payment-refund.lnpl` → **rc=0**
  (raw/compile-final-o.err — 경고 2건: 의도적 jwt/encrypt unenforced 프로브)
- `--strict` 컴파일: rc=2 (raw/compile-b4-strict.err — 경고가 게이트로 승격, 원 실측에 없던 옵션)
- lower: **18 nodes** (원: 24 — 원형 표현이 우회 필드·스텝을 제거해 더 작다:
  WorkflowStep 3, RepositoryCall 3, Entity 2, Workflow 2, Guard 2, Capability 2,
  Service 1, Event 1, Policy 1, Security 1)

## 가드 생존 계수 (D2 — 내용 기준, wiki: qa-exploratory-lowered-declaration-survival)

exit 0을 수용으로 읽지 않고 lir.json에서 선언 조건 문자열의 생존을 직접 셌다:

| 소스 선언 조건 | IR 생존 | IR 노드 id / condition 원문 |
|----------------|---------|------------------------------|
| `input.amountCents > 0 and input.amountCents <= 1000000` | **1/1** | `wf.approval.guard.1` :: 동일 문자열 |
| `input.requestedAt - payment.createdAt <= 30d and input.amountCents <= payment.amountCents` | **1/1** | `wf.refund.request.guard.1` :: 동일 문자열 |

**선언 2 → 생존 2, 탈락 0.** 원 F-2의 발생 기제(연쇄 가드 중 첫 번째 무진단 탈락)는
이제 문법 차원에서 봉쇄됨 — 연쇄 가드 자체가 파싱 에러(raw/compile-b2-stacked-guards.err,
"a guard owns exactly one step or block; write the two conditions as one guard joined
by `and`"). 하한(`> 0`)이 `and`로 같은 가드 안에 있어 소실될 개체가 없다.
런타임 프로브(0·-1 승인 여부)는 evidence/04에서 실측.

F-2 예비 판정: **해소** (탈락 무진단 → 파싱 에러 + and 결합 제공).
