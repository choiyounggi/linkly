# 03-profiles — R5 설정 프로파일

`src/lnpl.toml` (전문은 파일 참고): `[default]`(backend=fake, log_format=text,
secrets.jwt=LNPL_JWT_SECRET), `[prod]`(backend=postgres:..., log_format=json,
trace_exporter=otlp) — 문서 형식(`docs/serving.md:629-655`) 그대로.

## 비밀 평문 검사

```
$ grep -inE 'secret|password|token' src/lnpl.toml
4:# --metrics/--host/--port/--jwt-issuer/--token-provider/--trust-incoming-trace는
6:# --log-format/--trace-exporter/[*.secrets].jwt/--endpoint만 폴백 있음). 그래서
14:[default.secrets]
15:jwt = "LNPL_JWT_SECRET"
```

4개 매치 전부 (a) 이 파일 자체의 설명 주석 또는 (b) 섹션명 `secrets`/키 이름
`jwt`/**환경변수 이름 문자열** `"LNPL_JWT_SECRET"` — 실제 비밀 **값**은 0건.
(`LNPL_JWT_SECRET`은 이름이지 값이 아니다 — `docs/serving.md:633` "`[*.secrets]`는
그 값을 담은 환경변수의 이름만 받는다"와 일치.) **판정: 값 0건, 충족.**

`lnpl config check`(docs/serving.md "기동 전 완결성 판정")로 기동 전 검증:

```
$ lnpl config check src/linkhub.lnpl --config src/lnpl.toml
ok
$ lnpl config check src/linkhub.lnpl --config src/lnpl.toml --profile prod
ok
```

## `--profile dev`(=`[default]`) 기동

```
$ lnpl serve --host 127.0.0.1 --port 18084 --cache fake \
    --config src/lnpl.toml src/linkhub.lnpl
serving src/linkhub.lnpl on http://127.0.0.1:18084 (mode A, backend=fake, jwt=verified)
$ curl -s -o /dev/null -w "healthz(dev)=%{http_code}\n" http://127.0.0.1:18084/-/healthz
healthz(dev)=200
```

## `--profile prod` 기동

```
$ OTEL_SERVICE_NAME=s4-linkhub OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:14317 \
  lnpl serve --host 127.0.0.1 --port 18085 --cache "redis:redis://localhost:16379/0" \
    --config src/lnpl.toml --profile prod src/linkhub.lnpl
serving src/linkhub.lnpl on http://127.0.0.1:18085 (mode A, backend=postgres, jwt=verified)
$ curl -s -o /dev/null -w "healthz(prod)=%{http_code}\n" http://127.0.0.1:18085/-/healthz
healthz(prod)=200
```

같은 소스(`src/linkhub.lnpl`), 같은 `lnpl.toml`, `--profile`만 바꿔 backend가
fake↔postgres로 전환됨을 기동 로그(`backend=fake` vs `backend=postgres`)로 확인.
**판정: 충족.**

## F-3: 프로파일이 커버하지 못하는 플래그 (축 ops)

`lnpl serve --help` 전수 확인 결과, lnpl.toml 폴백이 **문서화된** 플래그는
`--backend`/`--log-format`/`--trace-exporter`/`--endpoint`/`--jwt-secret-env`
(→`[*.secrets].jwt`) 다섯 뿐이다. `--cache`/`--rate-limit`/`--grace-period`/
`--metrics`/`--host`/`--port`/`--jwt-issuer`/`--token-provider`/
`--trust-incoming-trace`는 toml 키가 없다 — 위 두 기동 명령에서 `--cache`를
dev/prod 모두 CLI로 별도 지정해야 했던 것이 그 증거. 실측으로 확인(`[prod]`
섹션에 `cache = "redis:..."`를 추가한 임시 사본 `.claude/tmp/lnpl-cachetest.toml`):

```
$ lnpl config check src/linkhub.lnpl --config .claude/tmp/lnpl-cachetest.toml --profile prod
error: .claude/tmp/lnpl-cachetest.toml: [prod] has unknown key(s) cache
       — allowed: backend, log_format, trace_exporter, endpoints, secrets
rc=2
```

`lnpl config check`가 **미인식 키를 정확히 거부**한다(허용 키 목록까지 명시) —
이 부분은 조용한 무시가 아니라 명확한 진단이라 우려했던 것보다 안전하다. 다만
근본적으로 `cache`는 toml에 **넣을 수 있는 키 자체가 없다** — dev/prod 두
프로파일을 진짜로 "같은 배치 스크립트, 프로파일만 교체"로 완결하려면 여전히
`--cache` CLI 인자를 프로파일별로 따로 들고 다녀야 한다.

**심각도: minor** — 우회(캐시·경화 플래그를 배포 스크립트/compose command에 항상
명시)로 의미 손실 없이 해소됨, 재시도 0회(첫 실측에서 바로 명확한 rc 2 진단을
받아 원인 확정).
**보완 제안**: `lnpl.toml`의 폴백 대상을 `--cache`까지 포함해 `serve`의 나머지
CLI 표면으로 확장한다 — 진단(`config check`)은 이미 우수하므로 표현력만 넓히면
됨.
