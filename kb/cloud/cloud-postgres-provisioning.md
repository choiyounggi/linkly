---
id: cloud-postgres-provisioning
category: Cloud
triggers:
  - postgres 백엔드를 붙일 때
  - postgres 백엔드에 rate limit을 얼마로
  - 처리량 상한·커넥션 수·max_connections를 잡을 때
  - attach postgres
  - postgres backend
  - throughput ceiling
  - hold
  - rate limit
  - max_connections
version: 0.1.0
status: draft
sources:
  - docs/postgres-load-ceiling.md
  - docs/serving.md
  - docs/backends.md
  - docs/gunicorn-load-measurement.md
  - examples/deploy/nginx.conf
---
# postgres backend provisioning

이 문서는 postgres 백엔드가 얼마나 받을 수 있는지를 측정으로만 답한다 —
추측하지 않는다.

이렇게 한다:

## 처리량 상한과 --rate-limit 값

- **`--rate-limit 100`을 postgres 백엔드 `lnpl serve`에 건다.** lnpl-postgres
  드라이버가 커넥션 풀을 갖추기 전까지의 권고다(근거: docs/postgres-load-ceiling.md
  "Deployment guidance").
- 100은 이 측정이 돌았던 머신의 숫자다 — 배포 호스트에서 같은 스윕
  (`scripts/load_probe.py`)을 다시 돌려 그 호스트에서 STABLE로 남는 가장
  높은 값을 한도로 쓴다. 그렇게 하기 전까지는 더 낮은 값(예: 이전 감사의
  `--rate-limit 50`)이 안전한 선택이다(근거: docs/postgres-load-ceiling.md
  "Deployment guidance").
- 매 요청이 자기 커넥션을 여는 지금 구현에서, 호스트 측 측정은 100 rps까지
  STABLE이었고 150 rps에서 멈췄다(오류율 0.16%, p99 2028.38ms)(근거:
  docs/postgres-load-ceiling.md "Ceiling sweep").
- `--rate-limit`은 한도를 넘는 요청에 `429`+`Retry-After`를 돌려준다(근거:
  docs/serving.md "Rate limit — `--rate-limit` (이슈 #148)"). 그래서
  과부하가 와도 큐에 쌓이지 않고 바로 실패한다(근거:
  docs/postgres-load-ceiling.md "Deployment guidance").

## 인스턴스·워커가 K개일 때 — 합산 한도는 게이트웨이

- `--rate-limit N`은 프로세스 전역 토큰 버킷 하나다. 인스턴스(또는 gunicorn
  워커)가 K개면 합산 허용량은 N × K로 느슨해지고, linkly 안에는 클라이언트별
  한도가 전혀 없다(근거: docs/serving.md "Rate limit — `--rate-limit` (이슈
  #148)").
- 100 rps 권고도 "`lnpl serve` 프로세스당" 숫자다 — K개를 두면 합산 상한도
  100 × K다(근거: docs/postgres-load-ceiling.md "Deployment guidance").
- 전역·클라이언트별 합산 한도는 게이트웨이에 둔다(근거: docs/serving.md
  "Rate limit — `--rate-limit` (이슈 #148)"). 참조 설정의
  `limit_req_zone`(파일 상단)과 `location /`의 `limit_req`가 그 자리다(근거:
  examples/deploy/nginx.conf).

## 커넥션과 풀

- `RepositoryDriver` SPI는 풀링을 규정하지 않는다 — 커넥션을 매 호출 새로
  열지 재사용할지는 드라이버 구현체 자신의 책임이다(근거: docs/backends.md
  "커넥션 풀은 드라이버가 소유한다 (이슈 #148)").
- postgres 실 드라이버는 코어가 소유하지 않는다 — 계약과 TCK만 코어에 있고,
  실 바인딩은 외부 패키지가 자기 CI에서 실 서버로 검증한다(근거:
  docs/backends.md "8. SPI: 외부 드라이버 등록 (이슈 #75)").
- 지금 쓰이는 lnpl-postgres 드라이버는 요청마다 `psycopg.connect(dsn)`로 새
  커넥션을 연다 — 이것이 150 rps 스톨의 근인이다(근거:
  docs/postgres-load-ceiling.md "Root cause"). 커넥션 풀을 드라이버에 두는
  일은 지금은 없다 — 아래 "집행 등급" 참조.

## max_connections

- stock postgres 이미지의 `max_connections`는 100이다. 150 rps 스톨 중 20건이
  `sorry, too many clients already`로 거부됐다 — 동시에 열린 커넥션 수가 이
  한도를 넘었다는 뜻이다(근거: docs/postgres-load-ceiling.md "Ceiling
  sweep").
- "동시 열린 커넥션 수가 무한정 늘어난다"는 가설(H2')은 확인됐다 — 스톨
  샘플에서 82개 postgres backend가 동시에 열려 있었다(근거:
  docs/postgres-load-ceiling.md "Hypothesis table").
- gunicorn 아래에서 동시에 열리는 커넥션 수의 상한은 sync 워커면 워커 수(K),
  gthread면 K × 스레드 수다 — 이를 `max_connections` 100보다 한참 아래로
  둔다(근거: docs/serving.md "워커 수와 워커 클래스 (이슈 #195)").

## gunicorn 위에서의 수치

- gunicorn 아래 postgres 백엔드는 워커 1개 sync에서 상한 100 rps(p99
  6.74ms), 워커 1개 gthread에서 상한 50 rps(p99 7.54ms), 워커 4개 sync에서
  상한 100 rps(p99 22.28ms)였다. 워커 2개 gthread와 워커 4개 gthread는
  사다리 끝인 400 rps까지 STABLE했다(근거: docs/gunicorn-load-measurement.md
  "Results"). 워커 2개 sync도 표에는 400 rps STABLE로 적혀 있지만 그 행은
  깨끗하지 않다 — 첫 구간부터 느려서(p95 1493.78ms, p99 1566.89ms) STABLE
  규칙이 그것을 잡지 못했을 뿐이다(근거: docs/gunicorn-load-measurement.md
  "Reading the table").
- 상한은 워커 수에 단조롭게 비례하지 않았다(워커 4개 sync는 100, 워커 2개
  sync는 400) — 점마다 1회 측정이라 워커 수 효과와 실행 잡음을 이 표만으로는
  가를 수 없다(근거: docs/gunicorn-load-measurement.md "Reading the table").
- 측정은 한 대의 Docker Linux 컨테이너, 점마다 1회, 50초 측정 창으로
  이루어졌다 — #180처럼 70-80초대에 나타나는 늦은 스톨은 이 측정으로는 놓칠
  수 있다(근거: docs/gunicorn-load-measurement.md "Limits").

## 집행 등급

- 미구현 — lnpl-postgres 드라이버의 커넥션 풀링(`psycopg_pool.ConnectionPool`
  제안, 아직 미채택). 위 권고는 설계 방향의 서술이지 지금 집행되는 제약이
  아니다(근거: docs/postgres-load-ceiling.md "Deployment guidance").
- 미구현 — 공유 저장소 기반의 분산 rate limit(레디스 카운터 방식은 검토했지만
  채택하지 않았다). 위 권고는 설계 방향의 서술이지 지금 집행되는 제약이
  아니다(근거: docs/serving.md "Rate limit — `--rate-limit` (이슈 #148)").
- 미구현 — linkly 내부의 클라이언트별 rate limit(전역 토큰 버킷 하나뿐). 위
  권고는 설계 방향의 서술이지 지금 집행되는 제약이 아니다(근거:
  docs/serving.md "Rate limit — `--rate-limit` (이슈 #148)").
- 구현됨 — 프로세스-로컬 `--rate-limit`과 한도 초과 시 `429`+`Retry-After`(근거:
  docs/serving.md "Rate limit — `--rate-limit` (이슈 #148)").
- 구현됨 — 게이트웨이의 `limit_req_zone`/`limit_req` 참조 설정(근거:
  examples/deploy/nginx.conf).
