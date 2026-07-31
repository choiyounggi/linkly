---
id: cloud-redis-cache-provisioning
category: Cloud
triggers:
  - `capability redis`를 프로비저닝할 때
  - 캐시 용량·축출 정책을 정할 때
  - 캐시 장애 시 동작을 정할 때
  - capability redis
  - cache eviction
  - provisioning
version: 0.1.0
status: verified
sources:
  - https://redis.io/docs/latest/develop/reference/eviction/
---
# redis cache provisioning

`capability redis`는 선언이고, 어떤 인스턴스가 그것을 만족할지는 컴파일러·플랫폼이
정한다. 프로비저닝 결정은 그 계약을 깨지 않는 범위에서 한다.

이렇게 한다:

- **축출 정책을 명시한다.** 기본값에 맡기면 메모리가 차는 순간의 동작이 환경마다 달라진다.
  캐시 용도라면 `allkeys-lru`류가 맞고, 세션·큐를 같은 인스턴스에 두면 축출이 그것들을
  지운다 — **용도가 다른 데이터는 인스턴스를 분리한다.**
- **모든 키에 TTL을 준다.** 런타임이 TTL 없는 쓰기를 거부하지만, 프로비저닝 쪽에서도
  만료 없는 키가 쌓이지 않는지 본다.
- **캐시는 정합성 장치가 아니다.** 캐시 불가용 시 원천으로 폴백하되 동시성 상한을 둔다 —
  상한 없는 폴백은 캐시 장애를 원천 장애로 증폭시킨다.
- **키에 테넌트·로케일·버전 차원을 넣는다.** 차원이 빠진 키는 교차 노출을 만든다.
