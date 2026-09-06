# FINDINGS — s4-ops-deploy

환경: 커밋 264e3442d653e5534d827687ebac5ede956e801, lnpl 0.8.0, python 3.13.1,
드라이버 lnpl-postgres 0.1.0/lnpl-redis 0.1.0/lnpl-otel 0.1.0, dev_doctor rc=1
(Mode B 미사용, 환경 문제이지 회귀 아님 — evidence/00-env.md)
조건: 블랙박스(requirements/README.md §2), impl/ 열람 0회, impl/ 수정 0건
(evidence/09-purity.md)

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| env(설치·서비스 선택) | PASS | evidence/00-env.md | 0 |
| drivers(postgres/redis/otel 실연결) | PASS | evidence/01-drivers.md | 0 |
| hardening(경화 옵션 6종) | PASS | evidence/02-hardening.md | 1(jwt secret 최소길이) |
| profiles(dev/prod 설정) | PASS | evidence/03-profiles.md | 0 |
| docker(이미지·compose 통합) | PASS | evidence/04-docker.md | 2(git 누락, driver wheel 재해석) |
| load(100rps fake/postgres) | PASS(측정 자체) — 결과가 F-6 노출 | evidence/05-load.md | 0 |
| drain(SIGTERM 그레이스풀) | PASS(측정) — F-7 노출 | evidence/06-drain.md | 0 |
| health(liveness/readiness) | PASS | evidence/08-health.md | 0 |
| migration(expand-migrate-restore) | PASS | evidence/07-migration.md | 0 |

## 요구사항 커버리지

| R | 요구 | 판정 | 근거(evidence 경로 + 실행 출력 인용) |
|---|------|------|--------------------------------------|
| R1 | postgres 실바인딩 | **충족** | evidence/01-drivers.md — `\dt` 2테이블 자동생성, `lnpl db check` rc0 |
| R2 | redis 실바인딩(캐시) | **부분** | evidence/01-drivers.md §R2 — SET 실증(MONITOR), 캐시 **읽기(hit)**는 어휘 부재로 증명 불가(F-2) |
| R3 | OTel 실수신 | **충족** | evidence/01-drivers.md §R3 — trace id 전파(`--trust-incoming-trace`), service.name 확인 |
| R4 | 경화 옵션 6종 | **충족** | evidence/02-hardening.md — 429/metrics/401·200/JSON로그/0.0.0.0 전부 curl로 실증 |
| R5 | 설정 프로파일 | **충족** | evidence/03-profiles.md — 같은 소스 dev/prod 전환, 비밀 값 0건; 단 cache 등 일부 플래그는 toml 미지원(F-3, minor) |
| R6 | Docker 이미지 | **충족** | evidence/04-docker.md — 330MB, 비-editable 확인, compose 4서비스 healthy; gunicorn 대조에서 R4의 절반 소실(F-5, major) |
| R7 | 부하(100rps×60s) | **충족**(측정 완료) | evidence/05-load.md — fake 안정(p99 6.78ms), postgres **~40s 지점부터 붕괴**(p99 5.87s, F-6, blocker) |
| R8 | 드레인 | **부분** | evidence/06-drain.md — 종료시간≤grace 충족이나 손실 0 미달(양쪽 grace 모두 1/6000건, F-7, minor) |
| R9 | 스키마 변경 무중단 | **충족** | evidence/07-migration.md — 5단계 전부 행손실 0, v1/v2 병행 확인, 복원 값 일치 |
| R10 | 헬스·준비 | **충족** | evidence/08-health.md — 200→503→200 전이, healthz 불변, 재시작 0회 |

집계: 충족 7 / 부분 2 / 불가 0 / 우회 0 (10건)

## Frictions

### F-1: `--jwt-secret-env` 최소 시크릿 길이(32바이트) 미문서화
- 단계: hardening | 심각도: minor | 축: doc
- 재현: `--jwt-secret-env LNPL_JWT_SECRET`에 30바이트 값 → `error: the JWT
  signing secret must be at least 32 bytes, got 30 (from LNPL_JWT_SECRET)`
- 기대 vs 실제: `lnpl serve --help`의 해당 플래그 설명에 최소 길이 언급 없음 →
  실제로는 기동 시점에 32B 미만이면 rc 2로 거부
- 재시도: 1 | 우회: 성공 — 32B+ 값으로 재시도, 의미 손실 없음
- 보완 제안: `--help` 텍스트와 `docs/serving.md`에 HS256 최소 시크릿 길이(32B)
  명시

### F-2: 캐시 **읽기(get)** 를 표현할 수 있는 표면 동사가 어휘에 없다
- 단계: drivers(R2) | 심각도: major | 축: expr
- 재현: `plugins/lnpl/skills/lnpl-authoring/references/verbs.md:22-23` — `cache`→
  CacheAccess(set만), `invalidate`→CacheAccess(invalidate); `find`/`read`/`load`는
  전부 RepositoryCall(read)로 내려간다(`rfcs/0002-syntax.md:578`). `redis
  MONITOR`로 SaveBookmark 2회 + GetBookmark 반복 호출을 캡처해도 `GET`류
  명령이 한 번도 나타나지 않음(evidence/01-drivers.md)
- 기대 vs 실제: `rfcs/0003-runtime.md:93`는 IR 실행 의미로 CacheAccess `get`을
  정의("miss가 정상 경로")하지만, 그 노드를 만드는 표면 동사가 닫힌 사전에 없어
  워크플로 저자가 "캐시를 먼저 보고 없으면 저장소로" 같은 read-through를
  **아예 쓸 수 없다**
- 재시도: 0 | 우회: 시도 안 함 — 언어 표현 불가능한 것을 셸/우회로 만드는 것은
  측정 오염(D13)
- 보완 제안: `cache`(set)/`invalidate` 옆에 `check`/`peek` 같은 CacheAccess(get)
  표면 동사를 추가하거나, `find` 앞에 선언적으로 캐시를 경유시키는 구문
  (`find bookmark via cache`류)을 열어 RFC로 검토

### F-3: `lnpl.toml` 프로파일이 `--cache`/`--rate-limit` 등 절반의 CLI 표면을 커버하지 않음
- 단계: profiles(R5) | 심각도: minor | 축: ops
- 재현: `[prod]`에 `cache = "redis:..."`를 추가한 사본으로 `lnpl config check` →
  `error: [prod] has unknown key(s) cache — allowed: backend, log_format,
  trace_exporter, endpoints, secrets`(evidence/03-profiles.md)
- 기대 vs 실제: `lnpl serve --help`가 toml 폴백을 문서화한 플래그는 5개
  (`--backend`/`--log-format`/`--trace-exporter`/`--endpoint`/
  `--jwt-secret-env`)뿐 — `--cache`/`--rate-limit`/`--grace-period`/`--metrics`/
  `--host`/`--jwt-issuer` 등은 프로파일 전환에서 제외돼 CLI로 매번 따로
  들고 다녀야 함
- 재시도: 0(진단이 명확해 바로 원인 확정) | 우회: 성공 — compose CMD/배포
  스크립트에 상시 명시, 의미 손실 없음
- 보완 제안: toml 폴백 대상을 `serve`의 나머지 CLI 표면으로 확장

### F-4: 외부 드라이버의 `lnpl` 커밋 SHA 직접 참조가 멀티스테이지 빌드에서 git 재요청을 유발
- 단계: docker(R6) | 심각도: minor | 축: doc
- 재현: builder에서 `pip wheel`로 lnpl+드라이버 3종 wheel을 전부 만들어도,
  runtime 스테이지의 `pip install /tmp/*.whl`이 드라이버 wheel의 METADATA에
  박힌 `lnpl @ git+https://.../linkly@<sha>`(PEP 508 direct URL, 드라이버
  README "Bumping the pinned lnpl commit" 관행)를 재해석하려 git을 호출 →
  runtime에 git 없음 → 실패(evidence/04-docker.md)
- 기대 vs 실제: 로컬에 동일 버전 lnpl wheel이 이미 있으면 재사용될 것으로
  기대했으나, direct URL 의존성은 그렇게 만족되지 않음
- 재시도: 2(builder에 git 추가 → 1차 실패, runtime install에 `--no-deps` →
  해소) | 우회: 성공, 의미 손실 없음(전이 의존성 wheel이 이미 로컬에 전부 있음)
- 보완 제안: 드라이버 README에 멀티스테이지 프로덕션 빌드 시 `--no-deps` 필요성
  명시

### F-5: 프로덕션 WSGI 경로(gunicorn)에서 R4 경화 옵션 절반이 적용 불가
- 단계: docker(R6) | 심각도: major | 축: ops
- 재현: `LNPL_SOURCE=...  gunicorn "lnpl.wsgi:build_app()"`로 띄운 뒤 동일
  버스트·`/-/metrics` 조회 → `/-/metrics` 404(라우팅에 없음), 100건 버스트에
  429 0건(rate-limit 미적용). `docs/serving.md:700-732` env-var 표에
  `LNPL_RATE_LIMIT`/`LNPL_METRICS`/`LNPL_CACHE`/`LNPL_JWT_ISSUER`가 없음
  (evidence/04-docker.md 대조 표)
- 기대 vs 실제: 문서(`docs/serving.md:448-453`)가 이미 "`lnpl serve` 전용"이라고
  경고하지만, 실제 배치 시 어느 옵션이 없는지 대조해 보니 rate-limit·metrics
  2종 완전 소실 + jwt-issuer 고정 + cache(redis) 선택 통로 자체 부재로,
  R4 절반이 "프로덕션다운 프로덕션"(gunicorn+nginx)에서 사라짐
- 재시도: 0 | 우회: 안 함(설계상 부재, D13)
- 보완 제안: `build_app()`의 env-var 표면을 `serve` CLI와 동등하게 확장하거나,
  최소한 nginx 앞단에서 rate-limit/metrics 대체 참조 설정을 문서화

### F-6: 100 rps 지속 부하 아래 postgres 백엔드가 ~40초 지점부터 붕괴(p99 5.9초)
- 단계: load(R7) | 심각도: **blocker** | 축: perf
- 재현: `python src/load.py --url <postgres-backed lnpl serve>/... --rps 100
  --seconds 60 --body <valid Bookmark>` — 0-40s 구간 평균 10ms대 안정, 40-50s
  평균 95.9ms(최대 3968ms), 50-60s 평균 1161.9ms(최대 5876ms).
  postgres 컨테이너 자체는 CPU 6%/메모리 29MB로 무관함을 확인(정상 체크포인트
  로그만, 에러 0) — 병목이 postgres 서버가 아니라 `lnpl serve`↔`lnpl-postgres`
  드라이버 경로임을 시사(evidence/05-load.md)
- 기대 vs 실제: R7이 요구한 100rps×60s를 postgres 백엔드로 실행하면 요구
  처리량을 안정적으로 감당하지 못하고 큐가 누적돼 tail latency가 시간에
  비례해 폭증 — 짧은 15초 재현에서는 나타나지 않음(지속 시간 의존적)
- 재시도: 0 | 우회: 시도 안 함(D13 — 성능 결함은 우회 대상 아님). **완화책은
  있음**: `--rate-limit`으로 처리량을 안전 한도 아래로 제한하면(evidence/05
  ①의 rate-limit 50 케이스는 60초 내내 안정) 붕괴를 피할 수 있다 — 다만 그
  안전 한도가 얼마인지는 이 케이스에서 확정하지 못함
- 근인(impl 열람): 안 함 — 블랙박스 조건 유지, postgres 서버 지표로만 배제
- 보완 제안: `lnpl serve`(dev 서버)의 postgres 백엔드 지속 부하 상한을
  공식적으로 측정·문서화하고, 그 상한을 넘는 배치에는 gunicorn 경로(단
  F-5의 한계 인지) 또는 `--rate-limit`을 그 상한 아래로 강제하도록 배포
  가이드에 명시. 근인(드라이버 커넥션 재사용 정책 vs dev 서버 스레드 모델)은
  플랫폼팀의 impl/ 조사가 필요.

### F-7: SIGTERM 드레인 경계에서 매 라운드 1건이 손실됨(grace-period 값 무관)
- 단계: drain(R8) | 심각도: minor | 축: ops
- 재현: fake 백엔드, `--grace-period 1`과 `--grace-period 10` 각각에서 100rps
  부하 중 t=20s SIGTERM → 6000행 중 completed 1999/1998, refused(ECONNREFUSED)
  4000/4001, **lost(ConnectionResetError) 1/1** — 손실 건의 `t_start`가 SIGTERM
  시점과 0.006s 차이(evidence/06-drain.md)
- 기대 vs 실제: s4.md D4는 "손실 0"을 기대하지만 grace-period 값과 무관하게
  상수 1건이 관측됨 — 종료 자체는 grace-period 이내(0.1s 안팎)로 훨씬 빠르게
  끝나 유예 초과가 원인이 아니라, 신규 연결 거부 전환 순간과 정확히 겹친
  TCP accept-vs-close 레이스로 보임
- 재시도: 0 | 우회: 시도 안 함 — 이 레이스는 애플리케이션 레벨에서 일반적으로
  닫을 수 없는 창(로드밸런서가 헬스체크로 먼저 트래픽을 빼는 것이 정석 완화책)
- 보완 제안: `docs/serving.md` 드레인 절에 이 경계 레이스를 알려진 한계로 명시

## 케이스 판정

**Ship-with-known-issues** — R1/R3/R4/R5/R6/R9/R10 7건은 문서 그대로거나 사소한
우회로 충족했고, 특히 R9(무중단 스키마 변경)·R10(헬스·준비)은 마찰 없이 완전히
증명됐다. 다만 세 조건을 소유자가 명시적으로 수용해야 "Ship":

1. **F-6(blocker)**: postgres 백엔드로 `lnpl serve`를 지속 고부하(≥100rps,
   ≥40초)로 운영하지 않는다 — 안전 처리량 상한을 별도로 측정하거나
   `--rate-limit`을 보수적으로 설정한다(이 케이스의 rate-limit=50 조합은
   60초 내내 안정이었다).
2. **F-2(major)**: 캐시가 실제로 읽기 부하를 흡수하는지(hit rate)는 오늘의
   어휘로 워크플로 안에서 증명할 방법이 없다 — 캐시 도입 효과를 스펙/워크플로
   레벨로 검증해야 하는 팀은 이 갭을 감수하거나 별도 도구(redis 자체 지표)에
   의존해야 한다.
3. **F-5(major)**: gunicorn 프로덕션 경로를 선택하면 R4 경화 옵션 절반(특히
   rate-limit·metrics)을 잃는다 — `lnpl serve`(F-6의 한계 인지)와 gunicorn(F-5의
   한계 인지) 중 하나를 배치마다 명시적으로 골라야 하며 "둘 다 완전하다"고
   가정하면 안 된다.

F-1/F-3/F-4/F-7은 minor로 문서·배포 스크립트 수준의 조정으로 흡수 가능해
Block 사유가 되지 않는다.
