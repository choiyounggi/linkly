---
id: antipatterns-unbounded-retry
category: AntiPatterns
triggers:
  - 재시도가 멈추지 않을 때
  - `retry`를 늘려 문제를 덮으려 할 때
  - 데드라인과 재시도가 겹칠 때
  - retry
  - unbounded retry
  - backoff
  - deadline
version: 0.1.0
status: verified
sources:
  - rfcs/0003-runtime.md#policy-enforcement
  - https://sre.google/sre-book/handling-overload/
---
# unbounded retry

**상한 없는 재시도는 장애를 증폭한다.** 다운스트림이 느려서 실패하는 상황에서 재시도는
그 다운스트림에 부하를 더한다 — 회복을 돕는 게 아니라 방해한다.

회피 방법:

- **`retry N`은 상한이고, 데드라인이 두 번째 상한이다.** 백오프의 합이 `timeout`을 넘으면
  재시도는 데드라인에 잡아먹혀야 한다. 상한이 하나뿐인 재시도 루프는 그 하나를 잃는 순간
  실패가 아니라 무한 루프가 된다(참조 구현에서 실제로 발생했고, 뮤테이션 검사가 잡았다).
- **재시도 가능 여부를 실패 유형으로 가른다.** 도달 전 실패는 재시도, 전송 후 무응답은
  멱등일 때만, 요청 자체가 잘못된 실패(인가 거부 등)는 재시도 금지.
- **`retry`를 늘려 해결하지 않는다.** 재시도가 필요한 빈도가 올라간다는 것은 다운스트림
  용량이나 예산이 틀렸다는 신호다.
- **비멱등 Effect를 재시도하지 않는다.** `create`를 재시도하면 중복이 생긴다.
