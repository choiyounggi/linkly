# 02-hardening — R4 경화 옵션 6종

기동 명령(모두 동시에 켬, `lnpl serve --help` 그대로):

```
$ set -a; source .claude/tmp/s4.env; set +a   # LNPL_JWT_SECRET (32B+) — .env 파일, 커맨드라인에 값 없음
$ OTEL_SERVICE_NAME=s4-linkhub OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:14317 \
  .venv/bin/lnpl serve --host 0.0.0.0 --port 18080 \
    --backend "postgres:postgresql://s4user:s4pw@localhost:15432/s4db" \
    --cache "redis:redis://localhost:16379/0" \
    --trace-exporter otlp --trust-incoming-trace \
    --rate-limit 50 --metrics --log-format json \
    --jwt-secret-env LNPL_JWT_SECRET --jwt-issuer s4-issuer \
    --grace-period 15 \
    src/linkhub.lnpl
serving src/linkhub.lnpl on http://0.0.0.0:18080 (mode A, backend=postgres, jwt=verified)
```

(비밀 취급: `LNPL_JWT_SECRET` 값을 커맨드라인 인자로 절대 넘기지 않음 — env로만,
`.claude/tmp/s4.env`에서 `source`. 최초 30바이트 값으로 시도했을 때 서버가
`error: the JWT signing secret must be at least 32 bytes, got 30`으로 즉시 거부 —
`--jwt-secret-env` 문서화되지 않은 하한(32B)을 실측으로 발견, 32B+ 값으로 재시도해
해결. 1회 재시도.)

## 1) `--rate-limit 50` (docs/serving.md:459 "프로세스 전역 토큰 버킷 하나, rate ==
capacity == N")

```
$ .venv/bin/python src/burst.py --url http://127.0.0.1:18080/link-hub-service/get-bookmark \
    --requests 200 --concurrency 20 --method POST --body '{}'
total=200
  400: 85
  429: 115
sample 429 body: {"title": "rate limit exceeded", "status": 429, "code": "rate-limited",
                  "detail": "rate limit exceeded, retry after 1s"}
```

200 req 버스트 중 115건이 429(`code: rate-limited`, `Retry-After` 의미 포함) — 나머지
85건은 payload 검증 실패(400, `{}` 바디라 의도된 것). **판정: 충족.**

## 2) `--metrics` (docs/serving.md:418 "`/-/metrics` — RED 시그널")

```
$ curl -s http://127.0.0.1:18080/-/metrics | head -3
# HELP lnpl_workflow_runs_total Total workflow runs, by outcome.
# TYPE lnpl_workflow_runs_total counter
lnpl_workflow_runs_total{service="LinkHubService",workflow="GetBookmark",status="failed"} 237
```

버스트 트래픽이 실제로 카운터에 반영됨(237 = burst.py 200건 중 400/429 처리된 run
수 누계 + 이전 시험 트래픽). histogram 버킷도 non-zero. **판정: 충족.**

## 3) `--jwt-secret-env` + `--jwt-issuer` (docs/serving.md:66-68 M3/M3a)

**주의(마찰 아님, 계약대로):** M3(401)는 "서비스가 `security jwt`를 **선언**"한
경우에만 발동한다(`docs/serving.md:66`). linkhub.lnpl은 `security` 블록을 선언하지
않으므로 `--jwt-secret-env`를 켜도 linkhub 경로는 토큰 없이 200/400을 낸다(아래).
이는 문서 그대로의 동작 — F-항목 아님, 다음 절에서 `security jwt`를 선언한
`examples/shorten.lnpl`(읽기 전용 원본을 `src/shorten.lnpl`로 복사, R4 플래그 검증
전용 — s4의 측정 대상 서비스는 여전히 linkhub)로 401/200을 실제로 증명.

```
$ curl -s -i -X POST http://127.0.0.1:18080/link-hub-service/get-bookmark -d '{"id":"..."}'
HTTP/1.0 400 Bad Request   # security jwt 미선언 — 토큰 유무와 무관하게 검증만 발동
```

```
$ .venv/bin/lnpl compile src/shorten.lnpl --strict=warning   # rc=0
$ .venv/bin/lnpl serve --host 127.0.0.1 --port 18083 --backend fake --cache fake \
    --jwt-secret-env LNPL_JWT_SECRET --jwt-issuer s4-issuer src/shorten.lnpl
serving src/shorten.lnpl ... (jwt=verified)

$ curl -s -i -X POST http://127.0.0.1:18083/shorten-service/shorten -d '{}'
HTTP/1.0 401 Unauthorized
{"title": "authorization required", "status": 401, "code": "auth-missing",
 "detail": "the service declares `security jwt`; send an Authorization header"}

$ TOKEN=$(.venv/bin/lnpl token --path /shorten-service/shorten --subject test-user \
    --secret-env LNPL_JWT_SECRET --jwt-issuer s4-issuer src/shorten.lnpl)
$ curl -s -i -X POST http://127.0.0.1:18083/shorten-service/shorten \
    -H "Authorization: Bearer $TOKEN" -d '{"id":"4444...","slug":"abc123", ...}'
HTTP/1.0 200 OK
{"status": "completed", "steps": [..., {"step":"authorize owner", ...}], ...}
```

**판정: 충족** (`--jwt-secret-env`/`--jwt-issuer` 자체는 정상 동작; 발동 조건은
서비스의 `security jwt` 선언 — linkhub는 미선언이라 이 플래그가 무의미하다는
점은 R5/프로파일 설계에서 인지해야 할 사실로 evidence/03에도 표기).

## 4) `--log-format json` (docs/serving.md:526 "접속 로그 — `--log-format`")

```
$ curl -s -o /dev/null http://127.0.0.1:18080/-/healthz
$ tail -1 .claude/tmp/serve02.log
{"correlation_id": "req-ea62a46988df", "method": "GET", "path": "/-/healthz",
 "workflow": null, "status": 200, "duration_ms": 0.05, "skipped": [], "diagnostics": [],
 "trace_id": "522c649fac8640788442e73aaef3b11e", "span_id": "dd956a28d5bf4cc6"}
```

요청 1건당 JSON Lines 1줄, 문서가 약속한 필드(correlation_id/method/path/workflow/
status/duration_ms/skipped/diagnostics) 전부 존재. **판정: 충족.**

## 5) `--host 0.0.0.0`

```
$ lsof -i :18080 -P
COMMAND   PID         USER   FD   TYPE  ... NAME
Python  64705 choeyeong-gi    8u  IPv4  ... TCP *:18080 (LISTEN)
```

`*:18080` — 모든 인터페이스에 바인딩(기본 `127.0.0.1`이 아님). **판정: 충족.**

## 6) `--grace-period` (드레인)

`kill -TERM` 실측은 부하 중 손실 여부와 함께 D6대로 evidence/06-drain.md에서
측정한다(이 절에서는 기동 파라미터 수용만 확인 — 기동 로그에 에러 없음).

## Scorecard 발췌

| 옵션 | 결과 | 근거 |
|------|------|------|
| --rate-limit | PASS | 위 §1, 429 115/200 |
| --metrics | PASS | 위 §2, RED counter 반영 |
| --jwt-secret-env/--jwt-issuer | PASS (조건부: security jwt 선언 서비스 필요) | 위 §3 |
| --log-format json | PASS | 위 §4 |
| --host 0.0.0.0 | PASS | 위 §5 |
| --grace-period | 06-drain.md로 이월 | — |

재시도: JWT 시크릿 최소 길이(32B) 미문서화로 1회 재시도(§ jwt secret error). 그 외
0회.
