# 서빙 — `lnpl serve` (이슈 #26)

`lnpl serve`는 컴파일된 모듈의 워크플로를 OpenAPI가 규정한 경로에 바인딩하고,
요청마다 인터프리터(모드 A)를 한 번 실행한다: request body → payload 검증
(워크플로 자신의 `validate` 스텝, #48 계약) → 실행 → 아래 매핑표에 따른 상태코드.

```
lnpl serve <src>.lnpl [--host 127.0.0.1] [--port 8080]
```

각 워크플로는 `POST /<service-slug>/<workflow-slug>`에 붙는다 — `lnpl openapi`가
생성하는 경로와 기동 시 대조되며, 어긋나면 서버는 뜨지 않는다(rc 2).

이슈 #99: 조회 표면도 같은 대조를 받는다. 워크플로가 건드리는 엔티티마다
`GET /<service-slug>/<entity-slug>/{id}`가 자동으로 붙고(선언 불필요, D1),
`service ... expose / list <Entity> by <field>` 절을 쓴 엔티티만
`GET /<service-slug>/<entity-slug>?after=<cursor>&limit=N` 목록도 붙는다(opt-in,
D2). 커서는 정렬키+row_key를 인코딩한 불투명 토큰이며(D3), 목록의 200 본문은
`{"items": [...], "next": <다음 커서 또는 null>}`이다. 인가는 워크플로 경로와
같은 판정을 그대로 재사용한다(M3/M3a, D5) — 조회 전용의 새 401 판정은 없다.

이슈 #103: 실시간 표면도 opt-in 선언에서 유도된다 — ws 문법을 언어에 넣는
대신, 이벤트 선언의 `subscribe` 한 낱말(AppSync형 명시 opt-in)이
`GET /<service-slug>/events/<event-slug>`(`Accept: text/event-stream`)를
연다. 이 경로는 그 이벤트를 실제로 `emit`하는 워크플로가 속한 서비스에만
붙는다(get-single이 엔티티 소유를 유도하는 것과 같은 구조적 규칙 — 새 선언
없이 IR 그래프에서 유도, `subscribe` 없는 이벤트는 표면이 없어 404). 서버는
`lnpl_outbox`(#102)를 그 이벤트로 필터링해 폴링-tail하고, 새 행마다
`id: <seq>`/`data: <마스킹된 payload>` SSE 프레임을 쓴다. `id:`는 t102의
`seq`(단조 저장소 커서)이지 `emission_id`가 아니다 — `emission_id`는 실행
1회의 트레이스 식별자라 재실행마다 재사용될 수 있어 재접속 커서로 쓸 수
없다. 재접속은 `Last-Event-ID` 헤더(SSE 표준 재전송 기제)로 그 seq 초과분만
이어받아 유실이 없다. 인가는 워크플로/조회 경로와 같은 M3/M3a를 그대로
재사용한다. payload는 `EventEmit` 시점에 이미 마스킹된 값이라(#43 계약)
구독 경로가 별도로 마스킹하지 않는다.

```bash
lnpl serve examples/shorten.lnpl &
curl -s http://127.0.0.1:8080/shorten-service/shorten \
  -H "Authorization: Bearer any" \
  -d '{"id":"3f2504e0-4f89-41d3-9a0c-0305e82c3301","slug":"abc-123",
       "target":"https://example.com/a",
       "owner":"3f2504e0-4f89-41d3-9a0c-0305e82c3302",
       "clicks":0,"createdAt":"2026-07-31T09:00:00Z"}'
```

## 상태코드 매핑표 (정본)

판정 순서대로. `impl/tests/test_serve.py`가 행마다 최소 한 케이스를 고정한다.

| # | 관측 조건 | HTTP | error `code` |
|---|-----------|------|--------------|
| M1 | 경로가 라우팅 테이블에 없음 | 404 | `not-found` |
| M2 | 경로는 있으나 메서드 ≠ POST | 405 + `Allow: POST` | `method-not-allowed` |
| M3 | 서비스가 `security jwt` 선언 ∧ `Authorization` 헤더 부재 | 401 | `auth-missing` |
| M3a | 토큰 프로바이더 설정됨(`--jwt-secret-env`) ∧ 토큰 검증 실패 | 401 | `auth-invalid` |
| M4 | `Content-Length` > 1 MiB | 413 | `body-too-large` |
| M5 | body가 JSON 파싱 실패, 또는 object가 아님 | 400 | `body-unreadable` |
| M6 | 실행 실패 ∧ `failure_reason`이 `deadline`으로 시작 | 504 | `deadline-exceeded` |
| M7 | 실행 실패 ∧ 실패 스텝의 효과에 `Validation` 포함 | 400 | `validation-failed` |
| M8 | 실행 실패 (그 외 전부) | 500 | `workflow-failed` |
| M9 | `status == completed` — 가드 거부 포함 | 200 | — |
| M10 | GET 단건: 경로는 있으나 행이 없음(부재 또는 백엔드 미설정) | 404 | `not-found` |
| M11 | GET 목록: `expose` 없는 엔티티(2세그먼트 경로가 라우팅 테이블에 없음) | 404 | `not-found` |
| M12 | GET 목록: `after` 커서가 해독 불가 또는 이 필드 타입과 안 맞음(위조) | 400 | `cursor-invalid` |
| M13 | GET 목록: `limit`이 정수가 아니거나 `[1, 200]` 밖 | 400 | `limit-invalid` |
| M14 | GET(단건·목록) 리포지토리 드라이버 오류 | 500 | `read-failed` |
| M15 | SSE 구독: `subscribe` 없는 이벤트(경로가 라우팅 테이블에 없음) | 404 | `not-found` |
| M16 | SSE 구독: `Last-Event-ID`가 음이 아닌 정수가 아님(위조) | 400 | `cursor-invalid` |

- **가드 거부는 200이다.** RFC-0014가 skipped를 status와 직교하는 신호로 정의한다
  — 가드가 제 역할을 한 실행은 CLI에서 rc 0이고, HTTP만 4xx를 주면 같은 실행이
  두 표면에서 다른 판정을 받는다. 관측 계약은 200 본문의 `skipped[]`가 나른다.
  각 skip 레코드는 `guard`/`mode`/`condition`/`steps`/`rounds`에 더해
  `evaluations[]`(이슈 #83 — 조건이 실제로 비교한 값들, sensitive 필드는
  마스킹 후)를 싣는다.
- 빈 body는 payload `{}`로 실행된다(특례 없음). `validate` 스텝이 있는 워크플로는
  M7로 400이 되고, 없는 워크플로는 그대로 실행된다.
- M6이 M7보다 먼저다: validate 스텝 직전에 데드라인이 소진된 실행은 타임아웃이지
  payload 거부가 아니다.

에러 본문은 전 엔드포인트 단일 형태(RFC 9457 problem+json,
`Content-Type: application/problem+json`): `title`/`status`/`code`/`detail` +
실행이 일어난 경우 `correlation_id`/`failed_step`/`skipped`. 클라이언트는
`detail`(사람용)이 아니라 `code`(안정 계약)로 분기한다. 200 본문은
`lnpl run --json`의 `result`와 같은 dict다 — `bindings`는 마스킹을 거친 값이며
(#43 계약) Password 계열 원문은 어떤 응답에도 실리지 않는다.

어댑터 계약·백엔드 선택·jwt 검증 체크리스트의 정본은 `docs/backends.md`다.

## 계약 한계 (이 서버가 아닌 것)

- **capability 백엔드는 기본이 fake다.** 플래그 없이 띄우면 저장은 요청마다
  시딩되는 인메모리 `FakeRepository`이고 요청 간에 상태가 남지 않는다 — #26이
  출하한 그대로다. `--backend sqlite:<path>`를 주면 요청마다 자기 연결을 열고
  닫는 실제 영속 저장소가 되며, **요청 간에 상태가 남는다**. 계약은
  `docs/backends.md`.
- **401의 뜻은 프로바이더 설정 여부에 달렸다.** `--jwt-secret-env` 없이 띄우면
  `Authorization` 헤더의 **존재 검사만**이다(presence-checked, not verified) —
  아무 값이나 통과한다. 주고 띄우면 M3a가 살아나 서명·`exp`/`nbf`(60초 leeway)·
  `iss`/`aud`/`typ`를 전부 검증하고, 실패는 401 `auth-invalid`다. 어느 검사가
  깨졌는지는 응답에 싣지 않는다 — 위조를 다듬는 쪽이 원하는 피드백이라서,
  correlation id와 함께 서버 stderr로 나간다. 토큰은 `lnpl token`이 발급한다.
- 스케줄 트리거(#49, `x-lnpl-schedules`)는 서빙되지 않는다. 모드 B(네이티브)
  서빙도 없다.
- **WebSocket은 이 이슈(#103)에서 명시 보류한다.** SSE는 단방향 HTTP 스트림이라
  stdlib(`ThreadingHTTPServer`)로 구현 가능하지만, WebSocket은 프로토콜
  업그레이드·프레이밍에 외부 의존이 필요해 stdlib-only 원칙과 맞지 않는다.
  클라이언트→서버 양방향 수요가 실제 이슈로 잡히면, 언어에 ws 문법을 넣기
  전에 외부 게이트웨이 패턴(AWS Step Functions형: API Gateway WebSocket +
  task token 콜백으로 위임)을 먼저 검토한다.
- 요청 `Content-Type` 헤더는 검사하지 않는다 — body 파싱 성공 여부가 판정한다.

## 운영 성질

- 동시성: 스레드-퍼-요청(`ThreadingHTTPServer`). 요청마다 인터프리터와 저장소
  rows를 새로 만들므로 락 없이 격리된다. 공유 상태는 컴파일된 문서와 라우팅
  테이블, 그리고 토큰 프로바이더뿐이며 전부 읽기 전용이다.
- 실제 백엔드를 쓸 때: 요청마다 **자기 연결**을 열고(`sqlite3` 연결은 만든 스레드에
  묶인다) `finally`에서 닫는다 — 응답을 쓴 **다음에** 닫으므로, 클라이언트가 응답을
  받은 시점에 서버가 아직 정리 중일 수 있다.
- 종료: SIGINT(Ctrl-C) → 소켓을 닫고 rc 0. 워커 스레드는 데몬이라 진행 중 요청을
  기다리지 않는다.
- SSE 구독(#103)은 스레드-퍼-요청 모델에서 특히 무겁다 — 연결이 열려 있는 한
  그 스레드를 계속 점유한다. `serve.SSE_POLL_INTERVAL_S`(기본 0.2s)로
  `lnpl_outbox`를 폴링하고, `serve.SSE_IDLE_TIMEOUT_S`(기본 30s) 동안 새 행이
  없으면 연결을 스스로 닫는다 — 느리거나 죽은 구독자가 워커 스레드를 무한정
  묶어 두지 못하게 하는 상한이다(WSGI/graceful shutdown은 #80 별도 이슈).
- 요청별 진단(가드 스킵 등)은 CLI와 같은 채널인 stderr로 나간다.
