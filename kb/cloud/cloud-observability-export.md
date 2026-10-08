---
id: cloud-observability-export
category: Cloud
triggers:
  - 관측 신호(trace·메트릭·접속로그)를 내보낼 때
  - 메트릭 수집·헬스 프로브
  - traces
  - trace exporter
  - otlp
  - access log
  - --log-format
  - metrics scrape
  - prometheus
  - healthz
  - readyz
version: 0.1.0
status: draft
sources:
  - docs/serving.md
  - docs/backends.md
---
# observability export

관측 신호는 접속 로그, trace, 메트릭, liveness/readiness 프로브 넷이다.
접속 로그(`--log-format`)·trace exporter(`--trace-exporter`)·메트릭
(`--metrics`)은 각각 독립적으로 켤 수 있다 — 프로브는 어떻게 뜨는지 아래
"프로브" 절에서 다룬다.

이렇게 한다:

## 접속 로그 형식

- 기본(`text`)은 접속 로그가 없다 — 이슈 #78 이전과 바이트 단위로 동일하다.
  `--log-format json`을 주면 요청 1건마다 stderr에 JSON 1행이 나간다(근거:
  docs/serving.md "접속 로그 — `--log-format`").
- JSON 행은 `correlation_id`, `method`/`path`, `workflow`, `status`,
  `duration_ms`, `skipped`, `diagnostics`, `trace_id`/`span_id`를 담는다.
  payload·필드 값이 실릴 채널은 전부 기존 `mask_payload` 체크포인트를 이미
  통과한 값만 받는다(근거: docs/serving.md "접속 로그 — `--log-format`").

## Trace 내보내기

- `--trace-exporter`는 `--log-format`과 독립이다 — 접속 로그를 켜지 않고도
  워크플로가 완료될 때마다 `Trace.to_dict()`를 내보낼 수 있다. 내장
  구현은 `stderr-json` 하나뿐이다(근거: docs/serving.md "`TraceExporter` —
  완료된 요청의 Trace 내보내기").
- built-in 밖의 이름은 `lnpl.exporters` entry-points 그룹에서 찾는다 —
  `lnpl-otel`(이슈 #144)이 `otlp = "lnpl_otel:make_exporter"`로 등록하는
  실사례다(근거: docs/serving.md "`TraceExporter` — 완료된 요청의 Trace
  내보내기").
- `stderr-json`은 entry-points 조회보다 먼저 문자열 비교로 매칭돼, 외부
  패키지가 같은 이름을 등록해도 절대 실행되지 않는다(근거: docs/serving.md
  "내장 스킴은 절대 가려지지 않는다").

## 메트릭 스크레이프

- `--metrics` 없이 띄우면 `/-/metrics`는 라우팅 테이블에 아예 없다 — 404다.
  켜면 `lnpl_workflow_runs_total`, `lnpl_workflow_duration_seconds`,
  `lnpl_step_failures_total` 세 가지를 Prometheus 텍스트 노출 형식으로
  낸다(근거: docs/serving.md "`/-/metrics` — RED 시그널 (`--metrics`, 기본
  off)").
- 라벨 값은 전부 컴파일 시점에 알려진 작고 닫힌 집합이다 —
  `correlation_id`·엔티티 id·payload 값은 라벨이 될 수 없다(근거:
  docs/serving.md "`/-/metrics` — RED 시그널 (`--metrics`, 기본 off)").

## 프로브

- `/-/healthz`(liveness)는 프로세스가 살아 있고 문서가 로드됐는지만 본다 —
  저장소도 네트워크도 만지지 않는다. SIGTERM을 받아도 영향받지 않는다(근거:
  docs/serving.md "`/-/healthz` — liveness").
- `/-/readyz`(readiness)는 닫힌 목록 다섯만 본다: 라우팅↔OpenAPI 대조, 영속
  백엔드 커넥션 1회 획득, `--jwt-secret-env` 생존 확인, network endpoint
  매핑 해소, 그리고 JWT 시크릿이 프로바이더 원천일 때의 `secret-provider`
  재조회다. 다섯 모두 통과하면 200, 하나라도 깨지면 503에 깨진 검사 이름을
  싣는다(근거: docs/serving.md "`/-/readyz` — readiness").
- `/-/healthz`/`/-/readyz`는 끄는 스위치가 없다 — `build_app()`(gunicorn)
  경로에서도 그대로 뜬다. 둘 다 `make_wsgi_app()` 안에서 무조건 합류하는
  `build_ops_routes`가 만들기 때문이다(근거: docs/serving.md "`/-/metrics`
  — RED 시그널 (`--metrics`, 기본 off)").

## build_app 환경 변수

- `build_app()`(gunicorn) 경로는 `LNPL_LOG_FORMAT`, `LNPL_TRACE_EXPORTER`
  두 환경 변수로 접속 로그 형식과 trace exporter를 받는다 — `lnpl serve`의
  `--log-format`/`--trace-exporter`와 같은 자리다(근거: docs/serving.md
  "환경 변수 (`build_app()` 경유)").

## 집행 등급

- 미구현 — 코어 안의 OTLP 또는 그 외 non-stderr exporter. 내장은
  `stderr-json` 하나뿐이고, 다른 형식은 `lnpl.exporters` entry-point로
  외부 패키지(lnpl-otel 등)가 들여온다. 위 권고는 설계 방향의 서술이지
  지금 집행되는 제약이 아니다(근거: docs/serving.md "`TraceExporter` —
  완료된 요청의 Trace 내보내기").
- 구현됨 — `--log-format json` 접속 로그(근거: docs/serving.md "접속 로그
  — `--log-format`").
- 구현됨 — `stderr-json` trace exporter(근거: docs/serving.md
  "`TraceExporter` — 완료된 요청의 Trace 내보내기").
- 구현됨 — `--metrics` 뒤의 `/-/metrics`(근거: docs/serving.md
  "`/-/metrics` — RED 시그널 (`--metrics`, 기본 off)").
- 구현됨 — `/-/healthz`·`/-/readyz`(근거: docs/serving.md "`/-/readyz` —
  readiness").
