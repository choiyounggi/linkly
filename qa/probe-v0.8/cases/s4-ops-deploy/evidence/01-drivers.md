# 01-drivers — postgres · redis · otel 실연결

## 기동 명령 (1라운드, 재시도 0)

```
$ docker compose -p s4probe -f src/compose.yaml up -d postgres redis otel-collector
... Container s4probe-postgres-1 Started
... Container s4probe-redis-1 Started
... Container s4probe-otel-collector-1 Started

$ docker compose -p s4probe -f src/compose.yaml ps
NAME                        IMAGE                                          STATUS
s4probe-postgres-1          postgres:16                                    Up (healthy)
s4probe-redis-1             redis:7                                        Up (healthy)
s4probe-otel-collector-1    otel/opentelemetry-collector-contrib:latest    Up
```

```
$ OTEL_SERVICE_NAME=s4-linkhub OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:14317 \
  .venv/bin/lnpl serve --host 127.0.0.1 --port 18080 \
    --backend "postgres:postgresql://s4user:s4pw@localhost:15432/s4db" \
    --cache "redis:redis://localhost:16379/0" \
    --trace-exporter otlp --trust-incoming-trace \
    src/linkhub.lnpl
serving src/linkhub.lnpl on http://127.0.0.1:18080 (mode A, backend=postgres, jwt=presence-checked)
$ curl -s -o /dev/null -w "healthz=%{http_code}\n" http://127.0.0.1:18080/-/healthz
healthz=200
```

문서 근거: `docs/backends.md` §8 "postgres = lnpl-postgres" 등록 형태 → `--backend
postgres:<dsn>`; §10 "redis = lnpl-redis" → `--cache redis:<dsn>`; lnpl-otel README
"Usage" → `--trace-exporter otlp` + `OTEL_SERVICE_NAME`(필수, 미설정 시 rc 2로 기동
실패) env. 세 드라이버 모두 **1라운드**에 실연결 성공 — 재시도 없음.

## R1 — postgres 실바인딩

```
$ docker exec s4probe-postgres-1 psql -U s4user -d s4db -c '\dt'
           List of relations
 Schema |    Name     | Type  | Owner
--------+-------------+-------+--------
 public | lnpl_outbox | table | s4user
 public | lnpl_rows   | table | s4user
(2 rows)
```

스키마는 **자동** 생성 — 별도 마이그레이션/DDL 명령 없이 첫 요청에서 `lnpl_rows`/
`lnpl_outbox` 두 테이블이 만들어졌다(`docs/backends.md` §3의 "엔티티별 테이블이
아니다" 설계가 postgres 드라이버에도 그대로 적용됨을 실측 확인).

```
$ .venv/bin/lnpl db check --backend "postgres:postgresql://s4user:s4pw@localhost:15432/s4db" src/linkhub.lnpl
[]
rc=0
```

**판정: 충족.**

## R2 — redis 실바인딩 (캐시)

SaveBookmark 워크플로의 `cache bookmark` 스텝(linkhub.lnpl:64)이 캐시를 쓴다.
2회 호출하며 redis MONITOR로 캡처:

```
$ timeout 10 docker exec s4probe-redis-1 redis-cli MONITOR &
$ curl -X POST http://127.0.0.1:18080/link-hub-service/save-bookmark -d @bookmark1.json
{"status":"completed", ...}  status=200
$ curl -X POST http://127.0.0.1:18080/link-hub-service/save-bookmark -d @bookmark2.json
{"status":"completed", ...}  status=200

MONITOR 발췌:
1788626160.217617 [0 192.168.0.1:...] "SET" "bookmark:1111...1111" "{...}" "PX" "300000"
1788626160.247006 [0 192.168.0.1:...] "SET" "bookmark:3333...3333" "{...}" "PX" "300000"

$ docker exec s4probe-redis-1 redis-cli DBSIZE
2
$ docker exec s4probe-redis-1 redis-cli GET bookmark:1111...1111
{"id": "1111...1111", "owner": "...", "savedAt": "...", "title": "A", "url": "...", "visits": 0}
```

`PX 300000`은 서비스 선언 `performance { cache 5m }`(linkhub.lnpl:58)의 TTL과 정확히
일치 — `performance cache`가 CacheAccess set의 TTL 예산을 소유한다는
`plugins/lnpl/skills/lnpl-authoring/references/declarations.md:29`의 계약대로.

**중요 마찰 (F-후보, 축 expr):** 위 SET은 **실제 redis 쓰기**임이 증명됐지만, "캐시
**히트**가 실제로 일어남"(R2 요구 문구)은 증명할 수 없었다. 이유: 어휘 사전
(`plugins/lnpl/skills/lnpl-authoring/references/verbs.md:22-23`)에 `cache`→
CacheAccess(**operation=set만**), `invalidate`→CacheAccess(invalidate) 두 동사뿐이고,
CacheAccess(**get**)로 내려가는 표면 동사가 **하나도 없다** — `find`/`read`/`load`는
전부 RepositoryCall(read)로 내려간다(`rfcs/0002-syntax.md:578`). `rfcs/0003-runtime.md:93`은
IR 실행 의미로 "`get` = miss가 오류가 아닌 정상 조회"를 규정하지만, 그 IR 노드를
만들어 내는 표면 동사가 닫힌 사전에 없다. 즉 **.lnpl 워크플로로는 캐시를 읽는 스텝을
아예 쓸 수 없다** — GetBookmark의 `find bookmark`는 항상 postgres를 읽지, redis를
먼저 보지 않는다. 실측: GetBookmark를 반복 호출하는 동안 MONITOR에 `GET`/`HGET` 등
조회 커맨드가 한 번도 나타나지 않음(SET 두 건만 관측). SRE 관점에서 "캐시가 실제로
읽기 부하를 흡수하는가"를 증명할 방법이 플랫폼에 없다 — FINDINGS.md F-2로 상세 기록.

**판정: 부분** — 쓰기 경로는 실증(우회 없음), 읽기(hit) 경로는 언어 표현력 부재로
증명 불가(우회 시도 안 함 — 표현 불가능한 것을 우회하면 의미가 없음, D13).

## R3 — OTel 실수신

```
$ TRACE_ID=5be92f3577b34da6a3ce929d0e0e5847
$ curl -X POST http://127.0.0.1:18080/link-hub-service/get-bookmark \
    -H "traceparent: 00-${TRACE_ID}-11f067aa0ba902c8-01" \
    -d '{"id":"1111...1111"}'
{"title":"payload validation failed", ..., "correlation_id":"req-4cda6c863be2", "failed_step":"validate input"} status=400
```

(GetBookmark의 워크플로 POST 엔드포인트는 Bookmark 전체 스키마로 입력을 검증하므로
id만 보내면 400 — validation 실패도 정상 실행 경로이자 트레이스 대상.)

```
$ grep "$TRACE_ID" src/otel-out/spans.json | jq .
{
  "resourceSpans": [{
    "resource": {"attributes": [..., {"key":"service.name","value":{"stringValue":"s4-linkhub"}}]},
    "scopeSpans": [{"scope": {"name":"lnpl_otel"}, "spans": [
      {"traceId":"5be92f3577b34da6a3ce929d0e0e5847","spanId":"1456cf2b4fba4870","name":"GetBookmark", ...},
      {"traceId":"5be92f3577b34da6a3ce929d0e0e5847","spanId":"6070ea51182df10d","parentSpanId":"1456cf2b4fba4870","name":"validate input", ...},
      ...
    ]}]
  }]
}
```

collector `debug` exporter 로그(컨테이너 쪽)에도 동일 trace id·`service.name:
s4-linkhub`가 찍힘 (`docker compose -p s4probe logs otel-collector` 발췌, 전체는
길어 trace id로 grep). 주입한 `traceparent`의 trace-id(`5be92f...5847`)가 그대로
root span의 `traceId`로 채택됨 — `--trust-incoming-trace`가 문서(`lnpl serve
--help`: "adopt an inbound traceparent header's trace-id for this request")대로
동작.

**판정: 충족.**

## 컨테이너 상태

01 종료 시점에 postgres·redis·otel-collector 컨테이너는 **유지**한다 — 03(경화
옵션)이 이어서 쓴다. `docker compose -p s4probe down -v`는 05/06에서 수행.
