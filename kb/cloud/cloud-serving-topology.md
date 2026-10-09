---
id: cloud-serving-topology
category: Cloud
triggers:
  - 운영 호스트로 `lnpl serve`와 gunicorn 중 하나를 고를지
  - gunicorn 워커 수·워커 클래스
  - 인스턴스 수와 TLS 종단 프록시
  - lnpl serve
  - gunicorn workers
  - worker class
  - reverse proxy
  - tls
  - nginx
version: 0.1.0
status: draft
sources:
  - docs/serving.md
  - docs/gunicorn-load-measurement.md
  - docs/backends.md
  - docs/RELEASING.md
  - examples/deploy/README.md
  - examples/deploy/nginx.conf
---
# serving topology

`lnpl serve`와 운영 WSGI 호스트는 같은 요청 처리 코어(`impl/lnpl/wsgi.py`의
`build_app()`)를 다른 전제로 돌린다(근거: docs/serving.md "운영 배치 —
WSGI 호스트(gunicorn) (이슈 #80)") — 어느 쪽을 쓸지, 워커를 몇 개 둘지,
앞에 뭘 세울지는 측정과 계약으로 정한다.

이렇게 한다:

## lnpl serve와 gunicorn

- `lnpl serve`의 dev 서버는 TLS도 다중 프로세스 워커 풀도 일부러 갖지
  않는다. graceful shutdown만 예외로, 서버 자신이 SIGTERM 그레이스풀 드레인을
  한다(근거: docs/serving.md "운영 배치 — WSGI 호스트(gunicorn) (이슈
  #80)").
- 운영에서는 `impl/lnpl/wsgi.py`의 `build_app()` 팩토리를 표준 WSGI
  호스트(예: gunicorn, 이 저장소의 의존성은 아니다)에 넘긴다 — 모든 설정은
  환경 변수로 온다(근거: docs/serving.md "운영 배치 — WSGI 호스트(gunicorn)
  (이슈 #80)").
- WebSocket은 이 이슈(#103)에서 명시 보류다 — SSE는 WSGI 이터레이터로
  구현 가능하지만 WebSocket은 외부 의존이 필요해 stdlib-only 원칙과 맞지
  않는다. 내장 스케줄러(크론 루프)도 없다 — 외부 스케줄러(cron/systemd)가
  여전히 필요하다. 모드 B(네이티브) 서빙도 없다(근거: docs/serving.md
  "계약 한계 (이 서버가 아닌 것)").

## 워커 수와 워커 클래스

- gunicorn 아래 postgres 백엔드는 워커 1개 sync에서 100 rps, 워커 1개
  gthread에서 50 rps, 워커 4개 sync에서 100 rps까지 STABLE이었다. 워커 2개
  gthread와 워커 4개 gthread는 400 rps까지 STABLE했다(근거:
  docs/gunicorn-load-measurement.md "Results"). 워커 2개 sync도 표에는
  400 rps STABLE로 적혀 있지만 그 행은 깨끗하지 않다 — 첫 구간부터
  느려서(p95 1493.78ms, p99 1566.89ms) STABLE 규칙이 그것을 잡지 못했을
  뿐이다(근거: docs/gunicorn-load-measurement.md "Reading the table").
  fake·sqlite는 워커·클래스 조합 전부 400 rps까지 병목이 되지 않았다(근거:
  docs/gunicorn-load-measurement.md "Results").
- 100 rps 목표에는 postgres 워커 1개 sync(상한 100, p99 6.74ms)가 이 표가
  뒷받침하는 조합이다. 100 rps를 넘는 목표에는 워커 2개 gthread(상한 400,
  p99 10.98ms)가 가장 작은 깨끗한 행이다. 상한이 워커 수에 단조롭게
  비례하지 않는다 — 점마다 1회 측정이라 워커 수 효과와 실행 잡음을 가를 수
  없다(근거: docs/serving.md "워커 수와 워커 클래스 (이슈 #195)").
- gunicorn 공식 권고 `(2 × 코어 수) + 1`이나 "2-4 x 코어 수"는 출발점일 뿐,
  측정이 그것을 대체한다(근거: docs/serving.md "워커 수와 워커 클래스
  (이슈 #195)").
- 새 postgres DB에서 `--workers 2` 이상으로 처음 띄우면 모든 워커의 기동
  점검이 같은 순간 `CREATE TABLE IF NOT EXISTS`를 돌려 서로 부딪칠 수 있다 —
  테이블을 먼저 한 번 만들고 K개 워커를 띄우는 수동 우회가 지금은 전부다
  (근거: docs/serving.md "워커 수와 워커 클래스 (이슈 #195)"); 아래
  "집행 등급" 참조.

## 워커마다 따로인 상태

- `--rate-limit`의 토큰 버킷은 프로세스 전역이다. gunicorn이 워커 K개를
  띄우면 각 워커가 독립된 OS 프로세스라 토큰 버킷도 워커마다 따로 생긴다 —
  합산 허용량은 N × K다(근거: docs/serving.md "운영 배치 — WSGI
  호스트(gunicorn) (이슈 #80)").
- 레이트 리밋 버킷만이 아니다 — 메트릭 레지스트리를 포함해 요청 사이에
  살아남는 프로세스-로컬 상태는 전부 워커마다 하나씩이다. 워커 2개에
  get-bookmark 요청 100건을 보낸 뒤 열 번 스크레이프하면 실행 수가 53건과
  48건으로 나뉘어 나왔다(합 101 = 100건 + 시드 1건)(근거: docs/serving.md
  "운영 배치 — WSGI 호스트(gunicorn) (이슈 #80)").
- `build_app()` 경로가 기존 gunicorn 배치에서 바꾸는 동작은 정확히 둘뿐이다
  — readyz 검사 ③이 추가로 돌고, 알 수 없는 `LNPL_BACKEND` 값의 기동 실패
  메시지가 값을 담지 않게 됐다(근거: docs/serving.md "기존 배치에 생기는
  변화 — 정확히 둘 (이슈 #187)").

## 앞단 프록시 — TLS와 한도

- `examples/deploy/nginx.conf`는 TLS 종단(Mozilla intermediate, TLS
  1.2+1.3), http→https 리다이렉트, gunicorn으로의 리버스 프록시, `/-/` ops
  경로 패스스루를 담는 참조 설정이다 — 공식 릴리스 이미지는 TLS 종단을
  담지 않는다(근거: examples/deploy/README.md "TLS 종단 — `nginx.conf`
  (이슈 #148)").
- TLS 종단과 워커 풀 관리는 dev 서버의 책임이 아니다 — 운영 배치의 WSGI
  호스트+nginx가 가진다(근거: docs/serving.md "운영 성질").
- 전역 레이트 리밋도 같은 파일에 들어간다 — `limit_req_zone`(파일 상단)과
  `location /`의 `limit_req`가 게이트웨이 수준에서 합산 한도를 건다(근거:
  examples/deploy/nginx.conf). 이 파일의 `rate=20r/s`/`burst=10`은 묶음
  스모크 테스트가 결정적으로 끝나도록 맞춘 데모 기본값이고, 키는
  `$server_name`이라 클라이언트별이 아니라 이 가상 서버 하나에 버킷
  하나다 — 실제 배포에서는 측정한 값으로 바꾼다(근거:
  examples/deploy/nginx.conf).

## 배포 산출물

- `lnpl generate compose <src.lnpl> --out <dir>`는 `compose.yaml` 하나를
  결정적으로(같은 입력이면 바이트가 같음) 쓴다 — 이미지 태그·소스 경로는
  자리표시자로 남는다(근거: docs/backends.md "`compose` — 내장 배포 생성기
  (이슈 #189)").
- `lnpl generate k8s <src.lnpl> --out <dir>`는 ConfigMap·Deployment·Service가
  든 `k8s.yaml` 하나를 쓴다 — Secret 오브젝트는 만들지 않는다(근거:
  docs/backends.md "`k8s` — 내장 배포 생성기 (이슈 #189)").
- 공식 릴리스 이미지는 `vX.Y.Z`와 `X.Y` 두 태그로 ghcr에 올라가고(`latest`는
  올리지 않는다), postgres·redis·otel 드라이버는 기본 이미지에 없다 — 파생
  이미지로 얹는 방식을 권장한다(근거: docs/RELEASING.md "절차").

## 종료와 드레인

- SIGTERM이 오면 즉시 `/-/readyz`가 503이 되고, `/-/`가 아닌 새 요청은
  `503`+`Retry-After: 1`로 거부되며, 진행 중 요청은 `--grace-period`(기본
  30초) 안에서 계속 처리된다(근거: docs/serving.md "SIGTERM 그레이스풀
  드레인 — `--grace-period` (이슈 #148)").
- gunicorn 배치에서는 코드가 바뀌지 않는다 — `graceful_timeout`(기본
  30초)이 이미 그 시간을 준다(근거: docs/serving.md "SIGTERM 그레이스풀
  드레인 — `--grace-period` (이슈 #148)").
- SSE 구독은 스레드-퍼-요청/워커 모델에서 특히 무겁다 — 연결이 열려 있는
  한 그 워커를 계속 점유한다(근거: docs/serving.md "운영 성질").

## 집행 등급

- 미구현 — 워커·인스턴스 사이에서 공유되는 상태. 토큰 버킷은 워커마다
  따로다(근거: docs/serving.md "Rate limit — `--rate-limit` (이슈
  #148)"). 메트릭 레지스트리를 포함해 요청 사이에 살아남는 프로세스-로컬
  상태는 전부 워커마다 하나씩이다(근거: docs/serving.md "운영 배치 —
  WSGI 호스트(gunicorn) (이슈 #80)"). 위 권고는 설계 방향의 서술이지
  지금 집행되는 제약이 아니다.
- 미구현 — `lnpl serve` 안에서의 TLS 종단. 위 권고는 설계 방향의 서술이지
  지금 집행되는 제약이 아니다(근거: docs/serving.md "운영 배치 — WSGI
  호스트(gunicorn) (이슈 #80)").
- 구현됨 — `build_app()`을 통한 gunicorn 호스팅(근거: docs/serving.md
  "운영 배치 — WSGI 호스트(gunicorn) (이슈 #80)").
- 구현됨 — `compose`·`k8s` 배포 생성기(근거: docs/backends.md "`compose` —
  내장 배포 생성기 (이슈 #189)").
