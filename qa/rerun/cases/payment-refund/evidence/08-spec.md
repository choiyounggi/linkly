# 08 — spec 시나리오 (재측정)

최종 spec 구성(payment-refund.lnpl): Approval 3블록(정상 / 경계 상한 1000001 / 경계
하한 0) + RefundRequest 2블록(정상 가드-참 / 에러 empty repository). 파일 전체로
정상·에러·경계 3종이 모두 선언됨 — 원 실측(F-10·11로 워크플로당 1개, 경계 불가)과
대조.

## 실행 결과 (raw/spec-run4.out — 최종)

```
spec: 10 passed, 1 failed   (rc=1)
```

| 블록 | 시나리오 | 결과 |
|------|----------|------|
| Approval 1 | 정상: valid → completed·steps 1·rows Payment 1 | **PASS** (3단언 전부) |
| Approval 2 | 경계 상한: `given amountCents 1000001` → steps 0 | **PASS** |
| Approval 3 | 경계 하한: `given amountCents 0` → steps 0 | **PASS** |
| RefundRequest 1 | 정상(가드 참): stored 행 + 부분 환불 → steps 2 | **FAIL** — steps=1 (create 스킵) |
| RefundRequest 2 | 에러: empty repository → failed·attempts 3 | **PASS** (retry 2 → attempts=3 기계 도출) |

## 원 F-10·11·12 재검

- **F-10 (블록 간 given 병합)**: **해소** — 한 워크플로에 3블록이 각자의 given으로
  독립 평가됨(블록 2의 1000001이 블록 1을 오염시키지 않음; 원 실측은 `empty
  repository` 모순 컴파일 에러 + 병합 오염). spec.md도 "블록마다 독립 케이스"를
  명시(issue #46).
- **F-11 (given 통째 대체·경계 불가)**: **해소** — `given amountCents 1000001` 필드
  하나만 덮어쓰는 경계 블록이 선언·통과. Money 리터럴 문제는 소멸(금액이 Integer
  센트 모델링 — 단 그 모델링 강제는 F-4 잔존 제약의 그림자).
- **F-12 (stored 오도 진단)**: **해소** — `stored Payment id …`(선언명 대문자)가
  컴파일·실행 모두 수용됨(raw/spec-run2.out 시도에서 에러 없이 평가). spec.md 명시:
  "엔티티는 선언명(Product)과 바인딩명(product) 둘 다 받는다(issue #46)".

## 시도 이력 (재시도 3회 — 한도 소진)

| 시도 | 변경 | 결과 | raw |
|------|------|------|-----|
| 1 | 초안: A3=`no id`→failed 기대, R1=`valid refund`→steps 2 | 8P/2F — `no id`여도 completed(원 "missing required field" 거동 소멸의 이면), R1 steps=1 | spec-run.out |
| 2 | A3=`stored Payment id <uuid>`(중복 결제 충돌 기대), R1에 stored amountCents+입력 3 | 8P/3F — stored 같은 id에도 create 충돌 미발생(attempts=1 completed), R1 여전히 steps=1 | spec-run2.out |
| 3 | A3=하한 경계로 교체, R1 stored에 createdAt 추가 | 10P/1F | spec-run3.out |
| 4 | R1 stored에 행 키 id 추가(examples "행 키" 근거) | **10P/1F — 동일** | spec-run4.out |

## 신규 마찰 (FINDINGS N-2·N-3으로 승격)

- **N-2**: read된 행을 참조하는 가드(payment.*)를 spec에서 참으로 만들 수 없다 —
  stored로 행 키 id·필드를 명시해도 create가 스킵된다(steps=1). 같은 가드가 CLI
  `run`(payload 시드)에서는 참(evidence/04 §2). spec 러너의 시드 의미가 run과 다르며,
  가드-참 정상 경로의 spec 계약화가 불가. FAIL 행은 어느 항이 거짓이었는지·바인딩이
  무엇이었는지 보여주지 않아(진단 채널 부재) 문서 표면만으로는 원인 확정도 불가.
- **N-3**: 승인 워크플로의 도메인 에러(중복 결제)를 유도할 수단 부재 — `stored
  Payment id <같은 uuid>` 후 create가 충돌 없이 completed(attempts=1). create-only
  엔티티의 충돌 의미가 관측 불가.

원형 기대(steps 2)는 약화하지 않고 그대로 남긴다 — **spec 단계 rc=1이 이 케이스의
정직한 측정값이다.** (가드-참 경로 자체는 mode A run·mode B build에서 실증 완료 —
evidence/04·05.)
