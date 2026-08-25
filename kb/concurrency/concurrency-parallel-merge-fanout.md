---
id: concurrency-parallel-merge-fanout
category: Concurrency
triggers:
  - `parallel` 블록을 쓸 때
  - 병렬 분기의 실패를 어떻게 다룰지
  - 여러 조회를 동시에 하려 할 때
  - parallel merge
  - fan out
  - concurrent read
version: 0.1.0
status: verified
sources:
  - rfcs/0003-runtime.md#execution-model
  - https://250bpm.com/blog:71/
---
# parallel merge fanout

`parallel` 블록은 Concurrency 노드가 되고, 런타임은 그것을 **structured concurrency**로
집행한다: 전 분기 완료 시 join, 한 분기 실패 시 형제 취소 후 부모로 전파, 부모 취소는 전
분기로 전파. 개발자는 thread를 다루지 않는다.

병렬을 쓸 때 이렇게 한다:

- **독립적인 조회에만 쓴다.** 분기 사이에 데이터 의존이 있으면 그건 순차이며, 병렬로
  적으면 순서가 사라져 결과가 불확정해진다.
- **`merge`로 닫는다.** 명시 종결 키워드를 가진 블록은 `parallel`뿐이다 — 열고 닫지 않으면
  문법 오류다.
- **fire-and-forget을 만들지 않는다.** 부모가 기다리지 않는 분기는 실패가 유실된다.
  구조적 병렬은 그것을 문법적으로 불가능하게 한다.
- **같은 capability pool을 여러 분기가 동시에 잡지 않는지 본다.** pool은 bounded이고
  고갈 시 fail-fast다 — 분기 수가 pool 크기를 넘으면 병렬화가 오히려 실패를 만든다.
  이 pool 계약은 RFC-0003(`rfcs/0003-runtime.md`)의 설계 계약이며, Phase 1 런타임은
  이를 강제하지 않는다(unenforced) — `docs/ENFORCEMENT-MATRIX.md` 참조. 현재
  드라이버(`impl/lnpl/drivers.py`)에는 bounded pool도 fail-fast도 없다 — 위 점검은
  설계 방향의 서술이지 지금 집행되는 제약이 아니다.
