---
id: patterns-repository-call
category: Patterns
triggers:
  - 저장소 접근 step을 쓸 때
  - 어떤 동사가 어떤 operation이 되는지 확인할 때
  - repository call
  - authenticate load find read create update delete
version: 0.1.0
status: verified
sources:
  - rfcs/0002-syntax.md#부록-a-lowering-매핑 (A.4-③ 동사 사전)
---
# repository call

저장소 접근은 step의 **동사**로 표현한다. 동사 사전이 Effect를 결정적으로 도출한다 —
`authenticate`·`load`·`find`·`read`는 `RepositoryCall(read)`, `create`·`insert`는
`(create)`, `update`는 `(update)`, `delete`는 `(delete)`다.

이렇게 한다:

- **동사를 사전에서 고른다.** 사전에 없는 동사는 Effect를 만들지 않는다 — 조용히
  추측하지 않는 것이 설계이지만, 저장소 접근을 의도했다면 아무 일도 일어나지 않는다.
- **한 step에 한 저장소 접근.** 두 접근이 필요하면 두 step이다. step은 재시도·span의
  단위이므로 접근을 묶으면 재시도가 둘을 함께 반복한다.
- **멱등성을 의식한다.** `read`·`update`(절대값 쓰기)·`delete`는 멱등이라 재시도되고,
  `create`는 아니라 재시도되지 않는다. `retry`를 선언했는데 재시도가 안 보이면 대개
  이 이유다.
- **entity는 스코프에서 온다.** 목적어를 생략하면 모듈의 entity가 대상이다.
