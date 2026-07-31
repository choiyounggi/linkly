---
id: database-postgres-index-selection
category: Database
triggers:
  - RepositoryCall이 느릴 때
  - 인덱스를 추가할지 결정할 때
  - 조회 조건이 늘어날 때
  - repository call slow
  - index
  - query plan
  - read find load
version: 0.1.0
status: verified
sources:
  - https://use-the-index-luke.com/sql/where-clause
  - https://www.postgresql.org/docs/current/indexes-multicolumn.html
---
# postgres index selection

`RepositoryCall`은 capability pool 커넥션으로 실행되는 await 지점이다. 느린 조회는
`response` 예산을 직접 먹는다.

인덱스를 정할 때 이렇게 한다:

- **조건 컬럼의 순서가 인덱스 순서다.** 복합 인덱스는 선두 컬럼부터 좌측 접두사만
  쓰인다 — `(a, b)` 인덱스는 `b`만으로 조회할 때 쓰이지 않는다.
- **선택도 높은 컬럼을 앞에 둔다.** 단, 등가 조건 컬럼을 범위 조건 컬럼보다 앞에 두는
  것이 우선이다.
- **인덱스는 쓰기 비용이다.** `create`/`update`가 잦은 entity에 인덱스를 늘리면 읽기를
  위해 쓰기를 느리게 한다. 그 교환이 이 workflow의 예산에서 이득인지 본다.
- **실행 계획으로 확인한다.** 추측으로 인덱스를 추가하지 않는다 — 계획이 그 인덱스를
  실제로 선택하는지 본 뒤에 남긴다.
- **soft delete가 있으면 조건에 포함한다.** 삭제 필터가 빠진 조회는 조용히 틀린 결과를
  낸다.
