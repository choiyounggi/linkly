# 서빙 — `lnpl serve` / WSGI (이슈 #26, #80)

`lnpl serve`는 컴파일된 모듈의 워크플로를 OpenAPI가 규정한 경로에 바인딩하고,
요청마다 인터프리터(모드 A)를 한 번 실행한다: request body → payload 검증
(워크플로 자신의 `validate` 스텝, #48 계약) → 실행 → 아래 매핑표에 따른 상태코드.

이 요청 처리 코어는 `impl/lnpl/wsgi.py`에 표준 WSGI callable(PEP 3333,
`environ`/`start_response`)로 산다(이슈 #80). `lnpl serve`는 그 callable을
`wsgiref.simple_server` + `ThreadingMixIn`으로 감싼 dev 서버이고, 운영 배치는
그 SAME callable을 진짜 WSGI 호스트(gunicorn)에 넘긴다 — 두 경로가 실행하는
코드는 하나뿐이라 서로 어긋날 수 없다(아래 "공유 계약" 절). TLS 종단·graceful
shutdown·워커 관리는 이 모듈이 아니라 그 호스트(+ nginx 같은 리버스 프록시)의
책임이다 — 이슈 #110부터 `lnpl serve`(`serve.serve()`)가 SIGTERM 핸들러
하나를 둔다(아래 "운영 표면" 절), 그러나 그 핸들러가 하는 일은 `/-/readyz`를
503으로 뒤집는 것뿐이다. 연결 드레이닝·실제 종료는 여전히 이 모듈의 책임이
아니다 — `build_app()`/gunicorn 경로는 이 핸들러가 없고 그대로다.

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
| M3b | 토큰 검증 성공(M3a 통과) ∧ 서비스가 `security role <r>` 선언 ∧ 검증된 역할이 `<r>`과 불일치(또는 부재) | 403 | `forbidden` |
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

### 인가 — 신뢰 모델과 게이트 범위 (이슈 #119)

토큰 검증(M3/M3a)을 통과했어도 검증된 역할이 `security role <r>`과 다르면
403 `forbidden`이다(매핑표 M3b, Task 04) — 401은 "너를 모르겠다", 403은
"너를 알지만 안 된다"는 서로 다른 판정이므로 순서도 M3a 다음으로 고정된다.
403 본문에는 어느 역할이 필요했는지 싣지 않는다 — 그 정보는 correlation id와
함께 서버 stderr로만 나간다(M3a가 이미 쓰는 것과 같은 판단).

**신뢰 모델.** `security role <r>`이 집행하는 역할은 이 서버가 검증한 토큰의
`role`(또는 원소 1개짜리 `roles`) 클레임에서 읽는다. 그 토큰은 지금은
`lnpl token`이 **자기 발급**한다 — 외부 IdP(issuer)가 서명한 것이 아니라,
같은 서비스가 발급과 검증을 모두 하는 자기 주장(self-asserted)이다. 그래서
이 집행은 t119b(외부 IdP: `--jwt-issuer`, RS256/ES256, `lnpl.tokens` SPI)가
들어오기 전까지는 **dev/테스트 신뢰 모델**이다 — "이 역할 클레임을 누가 왜
믿어도 되는가"라는 질문에 아직 제3자의 답이 없다. 프로덕션에서 이 신뢰
경계를 넘기려면 t119b가 필요하다.

**게이트 범위 — 행위(action) 대 객체(object).** `security role <r>`은
**행위 게이트**다: "이 역할을 가진 호출자가 이 라우트를 실행해도 되는가"만
묻는다. "42번 주문이 이 호출자의 것인가" 같은 **객체(소유권/테넌시) 게이트**는
linkly에 **없다** — 행위 게이트를 통과했다고 객체 게이트까지 통과한 것이
아니다(둘은 서로를 함의하지 않는다). 소유권이 필요한 워크플로(예: "본인
주문만 취소")는 이 서비스 수준 역할 게이트만으로는 안전하지 않다 — 워크플로
자체가 가드로 그 조건을 검사해야 한다.

어댑터 계약·백엔드 선택·jwt 검증 체크리스트의 정본은 `docs/backends.md`다.

## 스케줄 트리거 (이슈 #81)

`event ... on schedule`은 IR과 OpenAPI `x-lnpl-schedules`까지만 도달하고 실행기가
없다(RFC-0016). 내장 크론은 설계상 기각했다 — 대신 외부 스케줄러(cron/systemd)가
직접 부르는 트리거 표면을 세 가지 낸다:

- **트리거 라우트** — `POST /-/schedules/<event-slug>`. OpenAPI 계약에는 실리지
  않는다(스케줄은 오퍼레이션이 아니라 `x-lnpl-schedules` 메타데이터다) — 대신
  `build_routes`가 만드는 워크플로 라우트와 **완전히 같은 코드 경로**로
  실행된다: 같은 M1–M9 매핑, 같은 `_check_auth`(그 이벤트가 속한 서비스가
  `security jwt`를 선언했으면 M3/M3a 그대로), 같은 `skipped[]` 관측, 같은
  JSON 접근 로그(#78) — 새 판정을 하나도 만들지 않는다.
- **`lnpl trigger <src>... --schedule <event-id>`** — 소켓을 열지 않는
  일회성 CLI 경로. `lnpl run`과 같은 모드 A 실행이고, 워크플로 선택만
  `--workflow` 대신 스케줄 이벤트의 연결로 갈린다. 성공은 rc 0, 실행 실패는
  rc ≠ 0 — cron이 그대로 판정에 쓸 수 있다.
- **`lnpl schedules <src>... --format crontab|systemd`** — `x-lnpl-schedules`
  메타데이터로부터 crontab 한 줄 또는 systemd `.timer`+`.service` 쌍을
  만든다. 출력은 생성물이고 손으로 고치는 대상이 아니다(헤더에 명시).

**이벤트→워크플로 연결.** 스케줄 이벤트는 IR에서 어떤 워크플로에도 속하지
않는다(`lower.py`의 `owner_of`는 워크플로 전용이다). 트리거 표면은 워크플로가
이미 쓰는 것과 같은 규칙 — "가장 가까이 앞선 `service` 선언"(RFC-0002 A.2 R2)
— 을 컴파일된 문서의 `line` 필드 위에서 그대로 적용해, 그 서비스의 워크플로
자식 하나를 target으로 고른다. **정확히 하나가 아니면**(앞선 서비스가 없거나,
그 서비스에 워크플로가 0개거나 2개 이상이면) `ServeError`로 **기동 시점에**
거부한다 — 추측하지 않는다. `lnpl serve`는 문서의 모든 스케줄 이벤트를 한
번에 검증하고, `lnpl trigger`는 그중 요청한 하나만 검증한다.

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
- **내장 스케줄러(크론 루프)는 없다** — 이 서버는 어떤 타이머도 자체적으로
  돌리지 않는다. `event ... on schedule`이 선언한 시각/주기를 실제로 지키는
  것은 여전히 운영자가 붙이는 외부 스케줄러(cron/systemd)의 몫이다 — 아래
  "스케줄 트리거" 절, 이슈 #81. 모드 B(네이티브) 서빙도 없다.
- **WebSocket은 이 이슈(#103)에서 명시 보류한다.** SSE는 단방향 HTTP 스트림이라
  stdlib(WSGI 이터레이터 — dev 서버는 `wsgiref`, 운영은 gunicorn 등 아무 WSGI
  호스트나)로 구현 가능하지만, WebSocket은 프로토콜 업그레이드·프레이밍에
  외부 의존이 필요해 stdlib-only 원칙과 맞지 않는다.
  클라이언트→서버 양방향 수요가 실제 이슈로 잡히면, 언어에 ws 문법을 넣기
  전에 외부 게이트웨이 패턴(AWS Step Functions형: API Gateway WebSocket +
  task token 콜백으로 위임)을 먼저 검토한다.
- 요청 `Content-Type` 헤더는 검사하지 않는다 — body 파싱 성공 여부가 판정한다.

## 운영 성질

- 동시성(dev 서버): 스레드-퍼-요청(`wsgiref.simple_server` + `ThreadingMixIn`,
  `http.server.ThreadingHTTPServer`와 같은 조합을 `HTTPServer` 자리에
  `WSGIServer`를 넣어 그대로 미러링). 요청마다 인터프리터와 저장소 rows를
  새로 만들므로 락 없이 격리된다. 공유 상태는 컴파일된 문서와 라우팅 테이블,
  그리고 토큰 프로바이더뿐이며 전부 읽기 전용이다 — 이 성질은 이슈 #80 이전과
  바이트 단위로 동일하다(재구성이지 재설계가 아니다).
- 실제 백엔드를 쓸 때: 요청마다 **자기 연결**을 열고(`sqlite3` 연결은 만든 스레드에
  묶인다) `finally`에서 닫는다 — 응답을 쓴 **다음에** 닫으므로, 클라이언트가 응답을
  받은 시점에 서버가 아직 정리 중일 수 있다.
- 종료(dev 서버): SIGINT(Ctrl-C) → 소켓을 닫고 rc 0. 워커 스레드는 데몬이라
  진행 중 요청을 기다리지 않는다. **graceful shutdown·TLS 종단·워커 풀
  관리는 dev 서버의 책임이 아니다** — 아래 "운영 배치" 절의 WSGI 호스트가
  가진다(D4). 이슈 #110: SIGTERM은 `/-/readyz`를 즉시 503으로 뒤집을 뿐,
  이 판단을 바꾸지 않는다 — 아래 "운영 표면" 절.
- SSE 구독(#103)은 스레드-퍼-요청/워커 모델에서 특히 무겁다 — 연결이 열려
  있는 한 그 워커를 계속 점유한다. `wsgi.SSE_POLL_INTERVAL_S`(기본 0.2s)로
  `lnpl_outbox`를 폴링하고, `wsgi.SSE_IDLE_TIMEOUT_S`(기본 30s) 동안 새 행이
  없으면 그 WSGI 이터레이터를 스스로 끝낸다(`StopIteration`) — 느리거나 죽은
  구독자가 워커를 무한정 묶어 두지 못하게 하는 상한이다. (`lnpl.serve`도 같은
  이름을 재수출하지만, 실제로 루프가 읽는 모듈 전역은 `lnpl.wsgi`의 것이다 —
  테스트에서 값을 줄이려면 `wsgi.SSE_POLL_INTERVAL_S`를 패치해야 한다.)
- 요청별 진단(가드 스킵 등)은 CLI와 같은 채널인 stderr로 나간다.

## 운영 표면 — `/-/healthz` / `/-/readyz` / `/-/metrics` (이슈 #110)

이슈 #87이 컨테이너(`examples/deploy/Dockerfile`)까지 만들어 뒀지만 붙일
k8s 프로브가 없었다 — 롤링 업데이트 중 아직 준비되지 않은 파드로 트래픽이
갔다. 세 경로 모두 `impl/lnpl/wsgi.py`의 `build_ops_routes`/
`build_metrics_route`가 만들고, `make_wsgi_app`이 `build_routes`의
집합-동일성 대조(위 "상태코드 매핑표" 절 D1과 같은 종류의 계약, `set(routes)
== contract`) **뒤에** `routes.update(...)`로 합류시킨다 — `/-/schedules/...`
(이슈 #81)가 이미 세운 바로 그 자리, 그 방식이다. **`/-/` 경로는 그
대조에서 제외된다**(테스트로 고정, `impl/tests/test_ops_surface.py`) —
OpenAPI가 규정하는 경로 집합에 들어간 적이 없으니 대조가 "빠뜨렸다"고
읽으면 안 되고, 애초에 이 대조가 보는 대상이 아니라는 뜻이다.

**셋 다 인증이 면제된다** — 어느 서비스가 `security jwt`/`security role`을
선언했더라도 토큰 없이 접근 가능하다. kubelet의 liveness/readiness 프로브는
`Authorization` 헤더를 들고 오지 않으므로, 여기 401/403을 물리면 그
서비스가 있는 파드는 영원히 unready가 된다.

### `/-/healthz` — liveness

프로세스가 살아 있고 이 문서가 로드됐는지만 본다. **저장소도 네트워크도
만지지 않는다** — 검사가 100 자체로 끝나며, `repository_factory`를 단 한
번도 호출하지 않는다(`impl/tests/test_ops_surface.py`가 기록형 드라이버로
호출 카운트 0을 단언한다). liveness에 백엔드 검사를 넣지 않는 이유는
검색 자료가 반복해 경고하는 실패 모드다: DB가 30초 죽으면 liveness가 그때
같이 죽고, k8s는 그 파드를 재시작한다 — 그러나 재시작은 DB를 못 고치고
다운타임만 하나 더 만든다. 백엔드 가용성은 아래 readyz의 몫이다.

SIGTERM을 받아도 `/-/healthz`는 **영향받지 않는다** — 종료 중인 파드를
liveness가 재시작시키면 롤링 업데이트/드레이닝이 깨진다.

### `/-/readyz` — readiness

닫힌 목록 넷만 본다(임의로 늘리지 않는다):

1. 라우팅↔OpenAPI 대조 통과 여부 — `build_routes`가 기동 시 이미 판정했다
   (실패했다면 `ServeError`로 애초에 뜨지 못했으므로, 이 앱이 존재한다는
   사실 자체가 통과의 증거다).
2. 영속 백엔드(`--backend sqlite:...`)가 설정돼 있으면 커넥션을 1회
   획득·해제한다.
3. `--jwt-secret-env`가 지정돼 있으면 그 환경변수가 **지금도** 설정돼
   있는지 — 기동 시 검증(`cli.cmd_serve`)과 별개로, 매 프로브마다 다시
   읽는다(프로세스가 떠 있는 동안 그 변수가 사라지는 드문 드리프트도
   다음 프로브가 잡는다).
4. `--network http`를 썼으면 논리명 endpoint 매핑이 전부 해소돼 있는지 —
   (1)과 같은 이유로, 기동 시 이미 판정된 사실을 노출한다.

SIGTERM은 이 넷보다 **먼저** 본다 — 받는 즉시 나머지 검사 없이 503이다.
전부 통과하면 200 `{"status": "ok"}`; 하나라도 깨졌으면 503 +
`application/problem+json`(`code: "not-ready"`)에 **깨진 검사 이름**을
`checks`로 싣는다. 401/403(위 M3/M3a/M3b)과 반대 판단이다 — readyz는
운영자용이지 공격면이 아니므로, 어느 검사가 깨졌는지 감추지 않는다.

```jsonc
// 예: 백엔드 커넥션 획득 실패 + jwt-secret-env 미설정, 둘 다
{"title": "the server is not ready to receive traffic", "status": 503,
 "code": "not-ready",
 "detail": "readiness check(s) failed: repository, jwt-secret-env",
 "checks": ["repository", "jwt-secret-env"]}
```

**liveness와 readiness를 절대 섞지 않는다.** 재시작이 답인 실패(프로세스가
망가짐)는 healthz로, 트래픽만 끊으면 되는 실패(백엔드/설정 드리프트)는
readyz로 간다 — 둘을 하나로 합치면 트래픽 차단이면 충분한 상황에서
재시작이 나가거나, 재시작이 필요한 상황에서 트래픽만 계속 흘러들어간다.

### `/-/metrics` — RED 시그널 (`--metrics`, 기본 off)

`--metrics` 없이 띄우면 `/-/metrics`는 라우팅 테이블에 아예 없다 — **404다,
"비활성" 본문이 아니다**. 켜면 Prometheus 텍스트 노출 형식(`# HELP`/`# TYPE`
포함)으로 RED 3종을 낸다:

| 메트릭 | 종류 | 라벨 |
|---|---|---|
| `lnpl_workflow_runs_total` | counter | `service`, `workflow`, `status` |
| `lnpl_workflow_duration_seconds` | histogram | `service`, `workflow` |
| `lnpl_step_failures_total` | counter | `service`, `workflow`, `step`, `kind` |

**카디널리티 계약(D8).** 위 라벨 값은 전부 컴파일 시점에 알려진, 작고 닫힌
집합의 이름이다 — 서비스/워크플로/스텝 선언 이름, 그리고 `completed`/
`failed`나 매핑표의 `code`처럼 작은 고정 열거값. **`correlation_id`,
엔티티 id, payload 값은 라벨이 될 수 없다** — 무한 카디널리티는 Prometheus
자체를 무너뜨린다. 이건 새 규칙이 아니라 이미 있던 것의 승격이다:
`interp.Trace.metric`의 라벨 allowlist(`{module, service, workflow, step,
kind}`, RFC-0003)가 소스에서부터 이 계약을 막아 왔고, 이 issue의 세 지표는
전부 그 allowlist 안의 라벨만 쓴다(새 라벨 축 없음). allowlist를 벗어난
라벨은 여전히 `RunError`다 — 이 issue가 그 판단을 바꾸지 않는다.

**적재 위치(D9).** `interp.Trace.metrics`(요청마다 새로 생기는 배열,
`--trace-exporter`/이슈 #78 계약)는 건드리지 않는다. 그 옆에서, 요청이
끝날 때(`LnplWsgiApp._respond`) 이미 계산된 `result`를 읽어 **프로세스
수준**(`wsgi.MetricsRegistry`, 요청 간에 살아남는다)에 더한다 — 두 채널은
서로 독립이라 한쪽을 껐다고 다른 쪽이 달라지지 않는다. 갱신은
`threading.Lock`으로 보호한다(D10) — dev 서버는 스레드-퍼-요청이라 락 없는
`+=`는 동시 요청 아래서 갱신을 잃는다.

**`lnpl serve`/`serve.serve()` 전용.** `--metrics`와 readyz 검사 ③(살아있는
`--jwt-secret-env` 재확인)은 지금은 `lnpl serve` 경로에만 있다 —
`build_app()`(운영 배치, gunicorn)의 환경 변수 표(아래 "운영 배치" 절)에는
아직 대응 항목이 없다. `--trust-incoming-trace`(이슈 #107)가 이미 세운
같은 전례다: `serve()`에 새 플래그가 늘 때마다 자동으로 `build_app()`의
env-var 표면까지 넓히지 않는다. `/-/healthz`/`/-/readyz` 자체는 `build_app()`
경로에서도 그대로 뜬다 — 둘 다 `make_wsgi_app()` 안에서 무조건 합류하는
`build_ops_routes`가 만들기 때문이다(위).

## 관측 — `--log-format` / `TraceExporter` (이슈 #78)

사람용 stderr 텍스트만 있으면 수집기가 `correlation_id`를 필드로 뽑을 수
없다(`format_lines`가 만드는 텍스트 진단은 grep 대상이지 파싱 대상이 아니다).
이 절은 그 통로를 연다 — 기본 `text` 출력의 바이트는 그대로 두고.

### 접속 로그 — `--log-format`

- `text`(기본): 접속 로그 없음. 이슈 #78 이전과 바이트 단위로 동일 — 가드
  스킵 등 요청별 진단은 여전히 `format_lines`를 통해 stderr로 나간다(위
  "운영 성질" 절, 변경 없음).
- `json`: 요청 1건마다 stderr에 JSON 1행(`json.dumps(..., ensure_ascii=False)`).
  필드:

  | 필드 | 뜻 |
  |------|-----|
  | `correlation_id` | 워크플로가 실행된 요청은 응답 본문과 **같은** id(외부에서 새로 채번하지 않는다); 실행 전 거절(404/405/401/413/400)은 이 요청 전용으로 채번한 id |
  | `method` / `path` | `REQUEST_METHOD` / `PATH_INFO` |
  | `workflow` | POST 워크플로 요청이면 워크플로 노드 id, 아니면 `null`(GET 단건/목록/SSE/거절) |
  | `status` | 응답으로 나간 HTTP 상태 — 위 매핑표(M1–M16)와 같은 값 |
  | `duration_ms` | 요청 처리 전체 걸린 시간(반올림 3자리) |
  | `skipped` | `result["skipped"]` 그대로(워크플로 요청이 아니면 `[]`) |
  | `diagnostics` | `diagnostics.to_records(interp.diagnostics)`(기존 진단 레코드 재사용 — 새 직렬화를 발명하지 않는다; 워크플로 요청이 아니면 `[]`) |

  SSE 구독은 스트림이라 `duration_ms`가 연결이 열려 있던 시간 전체를
  가리켜야 하므로, 접속 시점이 아니라 **스트림이 끝날 때**(정상 소진,
  idle timeout, 또는 클라이언트 연결 종료로 인한 `GeneratorExit`) 1행이
  나간다.
- payload/필드 값이 로그 줄에 실릴 일이 있는 채널은 전부 기존
  `mask_payload` 체크포인트를 이미 통과한 값만 받는다 — 두 번째 마스킹
  규칙을 새로 만들지 않는다(위 항목들 자체는 correlation_id/상태/시간처럼
  민감하지 않은 메타데이터이고, `skipped[].evaluations`는 `interp.py`가
  이미 마스킹한 값만 담는다).

### `TraceExporter` — 완료된 요청의 Trace 내보내기

`--trace-exporter`는 `--log-format`과 **독립**이다 — 접속 로그를 켜지 않고도
Trace만 내보낼 수 있다. 워크플로가 완료(성공이든 실패든)될 때마다
`interp.Trace.to_dict()`(`{"correlation_id", "span", "metrics", "logs"}`,
스텝 span 트리는 이미 존재하던 것)를 딱 하나의 훅으로 넘긴다:

```python
class TraceExporter:
    def export(self, trace_dict):
        raise NotImplementedError
```

내장 구현은 `stderr-json` 하나 — `export()`가 받은 그대로 `json.dumps`해
stderr에 한 줄 쓴다. GET 단건/목록/SSE 요청은 `Interpreter`/`Trace`를 아예
만들지 않으므로 exporter는 워크플로 요청에만 반응한다.

#### 등록

built-in 밖의 이름은 `lnpl.exporters` entry-points 그룹에서 찾는다 —
`lnpl.drivers`(이슈 #75, `docs/backends.md` §8)와 같은 모양:

```toml
# 외부 패키지 자신의 pyproject.toml
[project.entry-points."lnpl.exporters"]
otlp = "my_otlp_exporter:OtlpExporter"
```

`OtlpExporter`는 인자 없이 호출되는 팩토리(클래스면 생성자가 인자를 받지
않는다)여야 하고, 반환값은 `TraceExporter`를 상속해 `export(trace_dict)`를
구현해야 한다.

#### 내장 스킴은 절대 가려지지 않는다

`stderr-json`은 entry-points 조회보다 먼저 문자열 비교로 매칭된다 —
외부 패키지가 같은 이름을 등록해도 절대 실행되지 않는다(`open_repository`가
`fake`/`sqlite`를 지키는 것과 같은 순서).

#### 미등록 이름의 진단

`--trace-exporter otlp`인데 아무 패키지도 그 이름을 등록하지 않았으면
`ValueError`가 받은 값과 내장/등록된 이름 전체를 담아 나가고, CLI 경로는
이를 rc 2로 번역한다(`cli._open_trace_exporter`).

#### entry-point 로드 실패

등록은 됐는데 `entry_point.load()`가 실패하면(모듈 없음, import 에러 등)
`lnpl.wsgi.ExporterError` 하나로 번역되어 나간다 — 원인 예외는 `__cause__`로
붙어 있다(드라이버 경로의 `DriverError`와 같은 "에러는 한 종류로 나간다"
원칙).

### 환경 변수 (`build_app()` 경유)

아래 "운영 배치" 절 표에 두 행이 더 있다: `LNPL_LOG_FORMAT`,
`LNPL_TRACE_EXPORTER`.

## 운영 배치 — WSGI 호스트(gunicorn) (이슈 #80)

`lnpl serve`의 dev 서버는 TLS도, graceful shutdown도, 다중 프로세스 워커
풀도 없다(D4 — 일부러 만들지 않았다). 운영에서는 요청 처리 코어를 노출하는
`impl/lnpl/wsgi.py`의 `build_app()` 팩토리를 표준 WSGI 호스트에 넘긴다 —
여기서는 stdlib 밖 도구인 gunicorn을 예로 쓴다(프로젝트 의존성으로 추가하지
않는다; stdlib-only 원칙은 `impl/lnpl` 자체에 대한 것이지, 그것을 호스팅하는
별도 프로세스에 대한 것이 아니다).

```bash
pip install gunicorn   # 이 저장소의 의존성이 아니다 — 배치 환경에서 설치

LNPL_SOURCE=examples/shorten.lnpl \
  gunicorn "lnpl.wsgi:build_app()" --bind 0.0.0.0:8000
```

`build_app()`은 인자를 하나도 받지 않는 팩토리로 호출되므로(그것이 gunicorn이
factory 문자열을 호출하는 방식), 모든 설정은 환경 변수로 온다 — CLI 플래그의
env-var 대응:

| 환경 변수 | CLI 대응 | 기본값 |
|-----------|----------|--------|
| `LNPL_SOURCE` | `lnpl serve <src>` | (필수) — 파일들(`os.pathsep` 구분) 또는 디렉터리 1개, t77 `load_sources` 그대로 소비 |
| `LNPL_BACKEND` | `--backend` | `fake` |
| `LNPL_JWT_SECRET_ENV` | `--jwt-secret-env` | (미설정 — presence-checked, not verified) |
| `LNPL_CLOCK` | `--clock` | `virtual` |
| `LNPL_ENDPOINT_<NAME>` | `--endpoint NAME=URL` | (이슈 #101 계약 그대로 재사용 — `build_app()`이 새로 발명하지 않는다) |
| `LNPL_LOG_FORMAT` | `--log-format` | `text` (이슈 #78) |
| `LNPL_TRACE_EXPORTER` | `--trace-exporter` | (미설정 — 아무것도 내보내지 않음, 이슈 #78) |

해석 실패(존재하지 않는 소스, 알 수 없는 backend/clock 선택자, 미설정
JWT secret, 매핑되지 않은 network target)는 `lnpl.wsgi.WsgiConfigError`를
내며 **요청이 아니라 기동이 실패한다** — `cli.cmd_serve`가 이미 CLI 경로에서
세운 것과 같은 원칙(첫 요청에서야 발견되는 게 아니라 뜨지 않는다).

이 머신에는 gunicorn이 설치되어 있지 않을 수 있다 — 그 경우를 위해 D5는
`wsgiref.validate`로 대체 증거를 요구한다: `impl/tests/test_wsgi.py`의
`test_boundary_wsgiref_validate_accepts_the_built_callable`가 `build_app()`이
내놓는 callable을 PEP 3333 검증 래퍼(`wsgiref.validate.validator`)에 태워
매 스위트 실행마다 확인한다. 아래는 이 저장소를 검증하는 동안 로컬에 gunicorn
을 설치해 실측한 기동·요청·SIGTERM 종료 로그다(재현: `pip install gunicorn`
후 위 커맨드, 다른 터미널에서 curl):

```
$ LNPL_SOURCE=examples/shorten.lnpl gunicorn "lnpl.wsgi:build_app()" --bind 127.0.0.1:8099 --workers 1
[INFO] Starting gunicorn 26.1.0
[INFO] Listening at: http://127.0.0.1:8099 (13187)
[INFO] Using worker: sync
[INFO] Booting worker with pid: 13189

$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8099/shorten-service/shorten \
    -H "Authorization: Bearer any" -d '{"id":"3f2504e0-...","slug":"abc-123", ...}'
200

$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8099/no/such/path
404

$ kill -TERM 13187   # gunicorn's own graceful shutdown, not this project's code
[INFO] Handling signal: term
[INFO] Worker exiting (pid: 13189)
[INFO] Shutting down: Master
```

두 상태코드(200/404)는 위 매핑표의 M9/M1과 같다 — gunicorn 아래에서도
`impl/tests/test_wsgi_contract.py`의 공유 계약 테스트가 socket 경로(내장
`lnpl serve`)와 직접 구동한 WSGI callable 양쪽에 대해 이미 고정한 것과
동일한 판정이다. nginx를 앞에 두는 경우 TLS 종단·정적 헤더 정책은 nginx가
갖고, gunicorn은 이 WSGI callable을 서빙하는 역할만 한다 — 둘 다 이 저장소
바깥의 배치 관심사다.

컨테이너로 이 절차를 그대로 실행하는 참조 Dockerfile과 실측 빌드/기동
로그는 [examples/deploy/README.md](../examples/deploy/README.md)에 있다
(issue #87).

## 공유 계약

내장 dev 서버(소켓)와 `build_app()`/`make_wsgi_app()`이 만드는 WSGI callable은
**같은 코드**를 실행한다(`impl/lnpl/wsgi.py`의 `LnplWsgiApp`) — `lnpl.serve`는
그 위에 `wsgiref.simple_server`를 씌우는 얇은 래퍼일 뿐, 두 번째 구현이
아니다. `impl/tests/test_wsgi_contract.py`가 이것을 코드를 읽어서가 아니라
실행해서 증명한다: POST 워크플로 완료, GET 단건/목록, 401(인가 누락), 404
(미등록 경로)를 소켓 경로와 WSGI callable 직접 호출 양쪽에 똑같이 돌려
(`correlation_id`처럼 요청마다 무작위인 필드만 제외하고) 응답이 바이트
단위로 같음을 단언한다. SSE는 별도로 — 소켓 위에서의 실시간 도착·재접속·
유휴 종료는 `test_serve_sse.py`가 이미 고정하므로, `test_wsgi_contract.py`는
그 위에 없던 것 하나만 더 본다: SSE가 소켓 전혀 없이 **순수 WSGI 이터레이터**
로 동작한다는 것 — `next()`를 반복 호출해 프레임을 받고, idle 타임아웃에서
이터레이터가 스스로 끝난다(`StopIteration`).
