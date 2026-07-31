---
id: testing-workflow-step-coverage
category: Testing
triggers:
  - workflow에 어떤 테스트를 붙일지
  - `spec` 블록에 무엇을 적을지
  - 테스트가 항상 통과하는 것 같을 때
  - spec block
  - test cases
  - expect
version: 0.1.0
status: verified
sources:
  - rfcs/0002-syntax.md (spec 절 → 테스트 스위트 아티팩트, 부록 A.4-②)
---
# workflow step coverage

`spec` 블록은 IR 노드가 아니라 **테스트 매니페스트**가 된다. 그래서 spec에 적는 것은
구현 방법이 아니라 관측 가능한 기대다.

케이스를 고를 때 이렇게 한다:

- **정상 1 + 실패 1 + 경계 1**을 최소로 잡는다. workflow의 실패 경로는 보통 선언에
  이미 적혀 있다 — `retry`가 있으면 재시도가 소진되는 경로, `timeout`이 있으면 데드라인
  초과 경로.
- **기대는 관측 가능한 것으로 쓴다.** `completed`·`steps N`·`attempts N`·`slo met`은
  판정 가능하고, "빠르다"·"안전하다"는 판정 불가다. 평가할 수 없는 기대는 러너가
  **통과시키지 않고 실패**시킨다.
- **검사가 실패할 수 있는지 확인한다.** 기대값을 일부러 틀리게 넣어 red가 나오는지 본다.
  한 번도 빨간불이 된 적 없는 검사는 검사가 아니라 장식이다.
- **`given`은 만들 수 있는 fixture로 쓴다.** `<필드> <값>`과 `no <필드>`만 쓰고, 서술형
  fixture는 러너가 해석할 수 있는 것만 쓴다.
