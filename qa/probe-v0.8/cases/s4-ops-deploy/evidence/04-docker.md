# 04-docker — R6 이미지·compose 통합

## 빌드

`src/Dockerfile`은 `examples/deploy/Dockerfile`을 파생(builder에서 wheel 빌드 →
runtime에 wheel 설치, `--build-context repo=.` 패턴 동일). D16대로 CMD는
`lnpl serve`(gunicorn 아님).

```
$ time docker compose -p s4probe -f src/compose.yaml build app
...
real 0m6.7s (2라운드 캐시 히트 후 재현 시간; 최초 클린 빌드는 두 마찰 해소 포함 ~40s)
rc=0

$ docker image ls s4probe-app --format "{{.Repository}}:{{.Tag}}  {{.Size}}"
s4probe-app:latest  330MB
```

**빌드 라운드 2회, 재시도 2회:**

1. **1라운드 실패** — builder 스테이지에 `git`이 없어 `pip wheel
   git+https://github.com/choiyounggi/lnpl-{postgres,redis,otel}@main`이
   `ERROR: Cannot find command 'git'`로 실패. `examples/deploy/Dockerfile`은
   외부 git 드라이버 설치를 상정하지 않은 원본이라 이 저장소 문서의 갭이 아니라
   이 케이스가 처음 부딪힌 것 — `apt-get install git`을 builder 스테이지에 추가.
2. **2라운드 실패** — runtime 스테이지 `pip install /tmp/*.whl`이 여전히
   `git+https://github.com/choiyounggi/linkly@ecfa408...`를 재요청(드라이버
   wheel의 METADATA가 `lnpl`을 PEP 508 **direct URL**로 커밋 SHA 고정 참조하기
   때문 — `lnpl-otel`/`lnpl-postgres`/`lnpl-redis` README "Bumping the pinned
   lnpl commit" 절 그대로). runtime 스테이지엔 git이 없어 같은 에러. `pip
   install --no-deps /tmp/*.whl`로 전환(전이 의존성 wheel은 이미 builder의
   `pip wheel`이 전부 `/wheels`에 받아둔 상태라 `--no-deps`는 재해석을 막을 뿐
   빠뜨리는 게 없음) — 해소, rc 0.

**F-4(축 doc/ops, minor):** 외부 드라이버 3종이 `lnpl`을 PEP 508 direct URL(커밋
SHA)로 고정 참조하는 설계(`docs/backends.md` §8 "Bumping the pinned lnpl commit"
관행) 때문에, 로컬에서 이미 빌드한 `lnpl` wheel이 있어도 `pip install`이
그 사실을 신뢰하지 않고 git 재요청을 시도한다 — 멀티스테이지 빌드에서 runtime
이미지에 git/네트워크가 없으면 조용히 막힌다(`--no-deps`로 우회, 의미 손실
없음: 필요한 wheel이 전부 이미 로컬에 있으므로). **보완 제안**: 드라이버
README의 "Local testing"/"Bumping" 절에, 멀티스테이지 프로덕션 빌드에서는
`--no-deps` 설치가 필요하다는 안내를 추가.

## compose 통합

```
$ docker compose -p s4probe -f src/compose.yaml up -d
$ docker compose -p s4probe -f src/compose.yaml ps
NAME                       SERVICE          STATUS
s4probe-app-1              app              Up (healthy)
s4probe-otel-collector-1   otel-collector   Up
s4probe-postgres-1         postgres         Up (healthy)
s4probe-redis-1            redis            Up (healthy)
```

4개 서비스 모두 running, app healthcheck(healthz curl) healthy. `depends_on:
condition: service_healthy`로 postgres/redis가 준비된 후에만 app이 뜬다.

```
$ curl -s -o /dev/null -w "healthz=%{http_code}\n" http://127.0.0.1:18080/-/healthz
healthz=200
$ curl -s -X POST http://127.0.0.1:18080/link-hub-service/save-bookmark -d '{...}'
{"status": "completed", ...} status=200
```

## 비-editable 확인

```
$ docker compose -p s4probe exec app lnpl --version
lnpl 0.8.0
$ docker compose -p s4probe exec app pip show lnpl | grep -E "Name|Version|Location"
Name: lnpl
Version: 0.8.0
Location: /usr/local/lib/python3.13/site-packages
```

`Location`이 site-packages(런타임 스테이지에서 `pip install`한 wheel 경로)이고
`Editable project location` 필드가 없음 — 소스 마운트/`-e` 없이 wheel 설치로
정상 동작. **CMD 원문**(compose가 실제로 실행한 커맨드):

```
lnpl serve --host 0.0.0.0 --port 8080 --config /app/lnpl.toml --profile prod
  --backend postgres:postgresql://s4user:s4pw@postgres:5432/s4db
  --cache redis:redis://redis:6379/0 --trace-exporter otlp --trust-incoming-trace
  --rate-limit 50 --grace-period 15 --metrics
  --jwt-secret-env LNPL_JWT_SECRET --jwt-issuer s4-issuer /app/linkhub.lnpl
```

**판정: 충족.**

## gunicorn 대조 (D16 — 별도 1회, 컨테이너 밖 포트 18082, 종료 후 폐기)

문서 근거: `docs/serving.md:700-732` "운영 배치 — WSGI 호스트(gunicorn)" — 환경
변수 표가 `LNPL_SOURCE`/`LNPL_BACKEND`/`LNPL_JWT_SECRET_ENV`/`LNPL_CLOCK`/
`LNPL_ENDPOINT_<NAME>`/`LNPL_LOG_FORMAT`/`LNPL_TRACE_EXPORTER` 7개뿐이고,
`--cache`/`--rate-limit`/`--grace-period`/`--metrics`/`--jwt-issuer`/
`--trust-incoming-trace`/`--host`/`--port`(gunicorn 자체 `--bind`가 대신함)에
대응하는 env var가 **없다**(`docs/serving.md:448-453` "`lnpl serve`/`serve.serve()`
전용" 문구와 정확히 일치).

```
$ .venv/bin/pip install gunicorn -q   # 프로젝트 의존성 아님, 이 대조 전용 1회 설치
$ LNPL_SOURCE=src/linkhub.lnpl \
  LNPL_BACKEND="postgres:postgresql://s4user:s4pw@localhost:15432/s4db" \
  LNPL_JWT_SECRET_ENV=LNPL_JWT_SECRET LNPL_LOG_FORMAT=json \
  LNPL_JWT_SECRET=<32B+> \
  .venv/bin/gunicorn "lnpl.wsgi:build_app()" --bind 127.0.0.1:18082 --workers 1
[INFO] Listening at: http://127.0.0.1:18082

$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18082/-/healthz
200
$ curl -s -i http://127.0.0.1:18082/-/metrics | head -1
HTTP/1.1 404 Not Found
$ .venv/bin/python src/burst.py --url http://127.0.0.1:18082/link-hub-service/get-bookmark \
    --requests 100 --concurrency 10 --method POST --body '{}'
total=100
  400: 100          # 429 전혀 없음 — rate-limit 미적용
$ kill -TERM <pid>  # gunicorn 자신의 graceful shutdown, 이 프로젝트 코드 아님
```

### 대조 표

| R4 옵션 | `lnpl serve` (compose app) | gunicorn(`build_app()`) |
|---------|---------------------------|--------------------------|
| `--rate-limit` | 429 실측(02-hardening §1) | **미적용** — 100 req 버스트에도 429 0건 |
| `--metrics` | `/-/metrics` 200 + RED 지표 | **404** — 라우팅 자체에 없음 |
| `--jwt-secret-env`+`--jwt-issuer` | 둘 다 지원 | `LNPL_JWT_SECRET_ENV`만 있음(issuer 지정 불가 — 항상 내장 발급자 `lnpl`) |
| `--log-format json` | 지원 | `LNPL_LOG_FORMAT=json` 지원(env 대응 있음) |
| `--host 0.0.0.0` | 지원 | gunicorn 자체 `--bind`로 대체(동등) |
| `--grace-period` | 앱이 직접 드레인(D6) | gunicorn `--graceful-timeout`(기본 30s, 앱 코드 무관) |
| `--cache redis:...` | 지원 | **env 대응 없음** — `build_app()`은 캐시 드라이버 선택 통로가 없다(`fake`로 고정 추정, 문서에 명시 없음) |

**F-5(축 ops, major):** 프로덕션 WSGI 경로(`lnpl.wsgi:build_app()` + gunicorn)에서
R4 경화 옵션 6종 중 **rate-limit·metrics 2종이 완전히 적용 불가**이고, jwt-issuer는
부분(고정), cache 드라이버 선택 통로 자체가 없어 redis 실사용도 불가해 보인다
(문서에 대응 env var 없음 — `fake`로 남는지, 에러가 나는지는 미확인: 이 케이스는
`--backend`만 postgres로 바꿔 실행했고 캐시 관련 env를 넘겨도 무시되는지까지는
검증하지 않음, 4h 예산 내 우선순위상 스킵). SRE 관점에서 "진짜 프로덕션(gunicorn+
nginx TLS)으로 가면 R4의 절반이 사라진다"는 것이 이 케이스의 가장 큰 배치 리스크.
**보완 제안**: `impl/lnpl/wsgi.py`의 `build_app()` env-var 표면을 `lnpl serve`
CLI 표면과 동등하게 확장하거나(각 옵션에 `LNPL_RATE_LIMIT`/`LNPL_METRICS`/
`LNPL_CACHE`/`LNPL_JWT_ISSUER` 등 추가), 최소한 gunicorn 앞단 nginx에서
rate-limit/metrics를 대신 구현하는 참조 설정을 `examples/deploy/nginx.conf`에
문서화한다(현재는 TLS 종단만 있음).

## 정리 메모

compose 스택은 05(부하)가 이어 사용한다 — 이 태스크 끝에 down하지 않음.
