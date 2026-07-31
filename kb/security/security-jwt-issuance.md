---
id: security-jwt-issuance
category: Security
triggers:
  - 토큰을 발급·검증할 때
  - `security jwt`를 선언한 workflow를 구현할 때
  - 비밀값이 로그에 나갈까 걱정될 때
  - generate token
  - verify token
  - jwt
  - security jwt
  - mask password secret
version: 0.1.0
status: verified
sources:
  - https://www.rfc-editor.org/rfc/rfc7519
  - https://www.rfc-editor.org/rfc/rfc8725
---
# jwt issuance

`security jwt`는 Security 제약 노드가 되고, 그 노드는 **검증 의무**를 뜻한다 — 발급
로직이 아니라 "이 workflow의 진입은 검증된 토큰을 요구한다"는 선언이다.

토큰을 다룰 때 이렇게 한다:

- **알고리즘을 서버가 고정한다.** 토큰 헤더의 `alg`를 신뢰해 분기하지 않는다. `none`
  수용과 대칭키/비대칭키 혼동이 대표적 취약점이다(RFC 8725 §3.1).
- **`iss`·`aud`·`exp`를 매 요청 검증한다.** 서명 검증만으로는 다른 대상용 토큰이 통과한다.
- **수명은 짧게, 갱신은 회전으로.** access 토큰이 길면 폐기 수단이 사실상 없다.
- **`Password`·secret은 값으로 다루지 않는다.** 런타임이 로그·trace·에러·직렬화에서
  자동 마스킹하지만, 그건 **중앙 1곳**에서 이뤄진다. 콜사이트마다 손으로 가리는 방식은
  언젠가 한 곳을 빠뜨린다.
- **인가는 별개다.** 토큰이 유효한 것과 이 리소스에 권한이 있는 것은 다른 검사다 —
  후자는 `Authorization` Effect다.
