---
id: architecture-service-boundaries
category: Architecture
triggers:
  - 서비스 경계를 어디에 그을지 결정할 때
  - 하나의 service 선언에 workflow를 몇 개 둘지
  - 모듈을 쪼갤지 합칠지
  - service boundary
  - workflow ownership
  - module split
version: 0.1.0
status: verified
sources:
  - https://martinfowler.com/bliki/BoundedContext.html
---
# service boundaries

한 `service` 선언은 **하나의 소유 결정 집합**을 가진다. 같은 `policy`·`security`·
`performance` 제약을 공유하는 workflow들이 한 service에 모이고, 제약이 달라지면 그것이
경계 신호다.

경계를 정할 때 이렇게 한다:

- **제약이 같은 것끼리 묶는다.** `timeout 3s`가 맞는 workflow와 `timeout 30s`가 필요한
  workflow는 다른 service다 — 한쪽을 다른 쪽에 맞추면 둘 중 하나가 틀린 예산으로 돈다.
- **capability 소유로 검산한다.** 한 service의 `database` 절이 무관한 capability를 여럿
  나열하기 시작하면 그 service는 이미 두 일을 하고 있다.
- **entity 하나에 service 하나를 강제하지 않는다.** 같은 entity를 읽는 두 service가
  서로 다른 제약을 가지는 것은 정상이다(읽기 경로와 쓰기 경로의 예산은 보통 다르다).

경계를 옮기는 변경은 IR에서 Service 노드의 `children`·`constraints`·`requires`가 함께
움직인다. 세 필드 중 하나만 바뀌는 경계 변경은 대개 잘못 그은 경계다.
