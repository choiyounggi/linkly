---
id: performance-response-budget-caching
category: Performance
triggers:
  - response 예산을 정할 때
  - cache TTL을 정할 때
  - SLO 위반이 실패로 처리되는지 헷갈릴 때
  - response budget
  - cache ttl
  - slo
version: 0.1.0
status: verified
sources:
  - https://sre.google/sre-book/service-level-objectives/
  - rfcs/0003-runtime.md#policy-enforcement
---
# response budget caching

`response < 50ms`는 **SLO 선언이지 집행 장치가 아니다.** 런타임은 초과를 측정·경보할
뿐 요청을 차단하지 않는다(RFC-0003). 유효한 요청을 예산 때문에 실패시키면 그건 가용성을
스스로 깎는 것이다. 실패시키고 싶다면 그건 `timeout`이고, 둘은 다른 선언이다.

예산을 정할 때 이렇게 한다:

- **백분위로 생각한다.** 평균은 꼬리를 감춘다. SLO는 p95/p99로 판정하고, 참조 구현도
  step duration histogram을 그 용도로 낸다.
- **`timeout`은 `response`보다 넉넉하게.** `response`는 "이 정도면 좋다"이고 `timeout`은
  "이 이상은 무의미하다"다. 같은 값을 주면 SLO를 스치는 요청이 전부 죽는다.
- **`cache T`는 CacheAccess의 TTL 예산이다.** TTL 없는 캐시 쓰기는 런타임이 거부한다 —
  만료 없는 키는 메모리 누수를 유예한 것일 뿐이다.
- **retry 예산을 데드라인 안에 넣는다.** 재시도 백오프의 합이 `timeout`을 넘으면 재시도는
  데드라인에 잡아먹힌다. 참조 구현이 그 경계를 강제한다.
