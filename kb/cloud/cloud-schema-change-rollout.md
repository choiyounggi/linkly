---
id: cloud-schema-change-rollout
category: Cloud
triggers:
  - 무중단 스키마 변경 순서
  - 스키마 변경 배포
  - 백업·복원
  - schema change rollout
  - expand migrate contract
  - zero-downtime
  - backup restore
  - pitr
version: 0.1.0
status: draft
sources:
  - docs/migration.md
  - docs/backends.md
---
# schema change rollout

entity에 필드를 추가하거나 타입을 바꾸는 순간, 그 전에 쓰인 행은 옛 모양
그대로 저장소에 남는다 — 배포와 백필을 한 순간에 맞추는 것은 무중단
배포에서 불가능하므로 그 사이를 견디는 절차가 필요하다(근거:
docs/migration.md "1. 왜 세 단계인가").

이렇게 한다:

## 왜 세 단계인가

- 새 필드를 참조하는 워크플로가 배포되는 순간과 옛 행이 백필되는 순간을
  한 번에 맞출 수 없다 — `stored-row-shape-mismatch`(이슈 #85)는 이
  어긋남을 **경고로만** 잡는다. 그 사이를 안전하게 건너기 위해 세 단계
  (expand → migrate → contract)를 쓴다(근거: docs/migration.md "1. 왜 세
  단계인가").

## 순서 — expand, migrate, contract

- **expand**는 코드 변경(entity 선언)만이다 — 저장소를 건드리지 않는다.
  새 필드를 `optional`로 선언하거나, 아직 어떤 스텝도 그 필드를 참조하지
  않게 하거나, 배포 전에 `lnpl migrate`로 기본값을 먼저 채우는 셋 중
  하나로 "관용"을 만든다(근거: docs/migration.md "expand — 관용하는 새
  필드를 먼저 연다").
- **migrate**는 `lnpl migrate <source...> --entity <E> --set
  <field>=<value> --backend sqlite:<path>`로 그 필드가 **없는** 행에만
  값을 채운다 — 이미 값이 있는 행은 절대 덮어쓰지 않는다. 한 번에 한
  필드이고, 실제로 값을 쓴 행마다 `_schema_gen`을 재스탬프한다. 전체
  배치는 단일 트랜잭션이다. `fake` 백엔드는 거부된다(근거:
  docs/migration.md "migrate — `lnpl migrate`로 배치 백필").
- **contract**는 컴파일러가 강제한다 — entity 선언에서 필드를 지우고
  `lnpl compile`이 통과하면 끝이다. 참조가 남아 있으면 컴파일이
  실패한다. `lnpl db check`로 저장된 행이 새 선언과 정합하는지 마지막
  확인한다(근거: docs/migration.md "contract — 옛 참조가 사라진 뒤에
  제거").

## _schema_gen

- `lnpl migrate`가 실제로 쓴 행과 `lnpl run`이 `create`/`set`으로 쓰는
  모든 행은 그 entity 선언 필드 이름·타입 목록의 sha256 12자리 digest를
  `_schema_gen` 키로 payload 안에 함께 갖는다 — 같은 선언이면 언제
  계산해도 같은 값이다(근거: docs/migration.md "3. `_schema_gen` —
  payload 내부 스키마 세대 스탬프").
- 이 키는 새 컬럼이 아니라 기존 `payload` TEXT 컬럼 안의 JSON 키다 —
  `RepositoryDriver` SPI는 이 키를 모르고, 저장된 행을 읽는 모든 경로가
  역직렬화 직후 이 키를 벗긴다(근거: docs/migration.md "3. `_schema_gen`
  — payload 내부 스키마 세대 스탬프").

## 백업 — 수동 절차

- sqlite는 WAL 모드라 메인 `.db` 파일만 복사하면 최근 커밋이 빠지거나
  일관되지 않은 스냅샷이 된다. 정본은 `sqlite3 store.db ".backup
  backup.db"`(온라인 백업 API) 또는 `VACUUM INTO 'backup.db'` 둘 중
  하나이고, 둘 다 드라이버가 여는 연결과는 별개의 연결·프로세스로
  실행한다(근거: docs/backends.md "sqlite — 파일 복사는 무효,
  `.backup`/`VACUUM INTO`가 정본").
- 한 번의 스냅샷이 아니라 지속적인 재해복구가 필요하면 Litestream을
  쓴다 — WAL 체크포인트를 가로채 새 WAL 페이지를 오브젝트 스토리지로
  증분 스트리밍하는 백그라운드 프로세스이고, `lnpl` 쪽 코드 변경은 없다
  (근거: docs/backends.md "연속 복제·PITR — Litestream").
- postgres 백엔드는 백업을 postgres 자신의 도구에 맡긴다 — 논리 백업은
  `pg_dump`/`pg_dumpall`, 연속 아카이빙과 PITR은 WAL 아카이빙 기반의
  별도 절차다(근거: docs/backends.md "postgres 드라이버 —
  `pg_dump`/PITR에 위임").

## 집행 등급

- 미구현 — linkly 안에서의 postgres 백업·복원. postgres 백엔드를 쓰는
  배포는 백업을 postgres 자신의 도구(`pg_dump`/`pg_dumpall`, WAL
  아카이빙 기반 PITR)에 위임한다 — 이 레포는 그 드라이버를 구현하지
  않는다. 위 권고는 설계 방향의 서술이지 지금 집행되는 제약이 아니다
  (근거: docs/backends.md "postgres 드라이버 — `pg_dump`/PITR에 위임").
- 미구현 — sqlite 백업·연속 복제의 자동 실행. `.backup`/`VACUUM INTO`나
  Litestream은 이 드라이버가 노출하는 API가 아니라 별도 연결·프로세스로
  수동 실행하는 절차다. 위 권고는 설계 방향의 서술이지 지금 집행되는
  제약이 아니다(근거: docs/backends.md "sqlite — 파일 복사는 무효,
  `.backup`/`VACUUM INTO`가 정본").
- 구현됨 — `lnpl migrate` 배치 백필(근거: docs/migration.md
  "migrate — `lnpl migrate`로 배치 백필").
- 구현됨 — `_schema_gen` 스탬프(근거: docs/migration.md "3.
  `_schema_gen` — payload 내부 스키마 세대 스탬프").
