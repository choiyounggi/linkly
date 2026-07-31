---
id: naming-entity-field-conventions
category: Naming
triggers:
  - entity·필드·workflow·capability 이름을 정할 때
  - 노드 id가 예상과 다르게 나올 때
  - entity name
  - field name
  - node id derivation
version: 0.1.0
status: verified
sources:
  - rfcs/0002-syntax.md#부록-a-lowering-매핑 (A.4-⑦ id 도출 규칙)
---
# entity field conventions

이름은 곧 노드 id다. `LoginService`는 `svc.login`이 되고 `UserCreated`는
`event.user.created`가 된다 — id 도출 규칙이 **kind를 중복하는 후행 세그먼트를 제거**하기
때문이다(RFC-0002 부록 A.4-⑦).

그래서 이렇게 한다:

- **kind를 이름에 반복하려면 후행에 둔다.** `LoginService`(→`svc.login`)는 좋고
  `ServiceLogin`(→`svc.service.login`)은 나쁘다.
- **entity는 단수 명사.** `User`(→`entity.user`). 복수형은 컬렉션을 뜻하는 것으로 읽혀
  단일 레코드 스키마와 어긋난다.
- **workflow는 동작 명사.** `Login`·`Checkout`. 동사구(`DoLogin`)는 step 이름의 문법이고
  선언 이름의 문법이 아니다.
- **필드는 camelCase.** `createdAt`. 문법이 `CamelName`을 요구한다.
- **capability는 소문자 단일 토큰.** `postgres`·`redis`·`jwt`. 이름이 곧 바인딩 키다.

이름을 바꾸면 id가 바뀌고, id는 IR 조각 교환·진단·trace 상관에 쓰인다. 이름 변경은
리팩터가 아니라 **계약 변경**으로 다룬다.
