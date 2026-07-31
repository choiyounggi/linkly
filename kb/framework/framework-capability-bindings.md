---
id: framework-capability-bindings
category: Framework
triggers:
  - capability를 선언·귀속할 때
  - service가 여러 개인 모듈에서 capability가 어디로 갈지
  - 바인딩 구현체를 고를 때
  - capability
  - database clause
  - binding
  - pool
version: 0.1.0
status: verified
sources:
  - rfcs/0002-syntax.md#부록-a-lowering-매핑 (A.4-⑧ capability 귀속)
---
# capability bindings

`capability postgres`는 **능력 선언**이고 구현체 선택은 컴파일러(Architecture
Optimizer)가 한다. 선언은 무엇이 필요한지만 말한다.

이렇게 한다:

- **service가 하나면 `database` 절을 생략해도 된다.** 모듈의 capability 전체가 그
  service에 귀속된다.
- **service가 둘 이상이면 각 service의 `database` 절로 명시한다.** 명시하지 않으면
  컴파일 오류다 — 어느 service가 어느 capability를 쓰는지 추측하지 않는다.
- **선언하지 않은 이름을 `database` 절에 쓰지 않는다.** dangling 참조로 거부된다.
- **버전을 요구할 때만 적는다.** `capability postgres 16`. 적지 않으면 플랫폼이 고른다 —
  불필요한 핀은 배포 유연성만 깎는다.
- **capability는 pool 계약을 함께 가져온다.** 커넥션 획득은 operation당 1회, 다른 자원
  획득 전 반환. 중첩 획득은 pool 만석 시점에 데드락이다.
