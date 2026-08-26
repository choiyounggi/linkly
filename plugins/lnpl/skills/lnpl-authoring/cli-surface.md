<!-- 수기 문서다(생성물이 아니다). `references/`의 어휘 문서와 달리 이 파일은 손으로
쓰고, `impl/tests/test_cli_surface_doc.py`가 `impl/lnpl/cli.py`를 AST로 읽어
서브커맨드·플래그 누락을 막는다. 플래그를 추가하면 그 테스트가 여기를 고치라고 한다. -->

# CLI 표면 — 서브커맨드·플래그·종료 코드

> 파이프라인 전모. QA 실측(t1 F-12)에서 "공개 문서만으로 개발" 시뮬레이션이
> `impl/lnpl/cli.py`를 직접 열어야 했던 지점이다.

```
lnpl <서브커맨드> <src.lnpl> [옵션]
lnpl --version
```

## 서브커맨드

### `compile` — 파싱 + lowering, Semantic IR 출력

| 플래그 | 뜻 |
|--------|-----|
| `-o` / `--output` | IR을 파일로 쓴다. 없으면 stdout으로 나간다 |
| `--strict[=LEVEL]` | 진단을 종료 코드로 게이팅한다. 무인자면 진단이 하나라도 있으면 rc 2(= `--strict=info`). `--strict=warning`이면 warning 이상만 rc 2 — 의도한 `on schedule`·`performance` 선언(등급 `info`)은 통과시킨다. `error`는 예약이라 오늘 어떤 진단과도 일치하지 않는다. 이슈 #52 |

`-o` 없이 쓰면 IR 문서가 **stdout**으로 나간다. 진단은 항상 stderr다 — 그래서
`-o` 없이 stdout을 파이프해도 산출물이 오염되지 않는다.

### `run` — 컴파일 후 실행 (인터프리터, 모드 A)

| 플래그 | 뜻 |
|--------|-----|
| `--payload` | 실행 입력이 담긴 JSON 파일. 없으면 선언된 타입에서 샘플 payload를 만든다 |
| `--workflow` | 실행할 **워크플로 노드 id**. 없으면 첫 번째 |
| `--json` | 결과와 트레이스를 JSON으로 |
| `--no-row` | 빈 저장소로 시작한다(재시도 경로를 관측할 때) |
| `--backend` | capability 백엔드. `fake`(기본, 인메모리, 실행마다 새로) 또는 `sqlite:<path>`(파일에 남는 실제 저장소). 이슈 #25 |
| `--network` | `NetworkCall` 드라이버. `fake`(기본, 결정적, I/O 없음) 또는 `http`(`http.client`로 실제 요청). RFC-0027, 이슈 #64 |
| `--endpoint` | `NAME=URL` (반복 가능). `--network http`에서 `call`/`request`의 논리명을 실제 URL로 매핑한다. `LNPL_ENDPOINT_<NAME>` 환경변수로도 줄 수 있고, `--endpoint`가 이긴다. 매핑 안 된 논리명이 있으면 기동이 rc 2로 실패한다(요청 중 실패보다 기동 실패). 이슈 #101 |
| `--clock` | 시간 바인딩. `virtual`(기본, 결정적, 프로세스 로컬) 또는 `real`(단조 벽시계 — `CacheAccess` TTL을 실제 경과 시간에 묶는다). `spec`/`diff`에는 없다. RFC-0029, 이슈 #100 |
| `--strict` | 위와 같다 |

`--workflow`는 선언명이 아니라 노드 id를 받는다(`GetReport`가 아니라
`wf.get.report`). 도출 규칙은 [references/naming.md](references/naming.md)에 있고,
잘못된 id를 주면 유효한 id 전부가 에러에 나열된다.

### `trigger` — `on schedule` 이벤트의 연결 워크플로를 실행 (인터프리터, 모드 A, 이슈 #81)

```
lnpl trigger <src>.lnpl --schedule event.daily.rollup
```

`event ... on schedule`은 내장 크론이 없다(RFC-0016) — `serve` 소켓 없이 외부
스케줄러(cron/systemd)가 직접 부르는 일회성 진입점이 이 서브커맨드다.
실행 자체는 `run`과 같은 모드 A다.

| 플래그 | 뜻 |
|--------|-----|
| `--schedule` | 필수. **스케줄 이벤트 노드 id**(`GetReport`가 아니라 `event.daily.rollup`). 이 모듈이 선언한 `on schedule` 이벤트가 아니면 유효한 id 전부와 함께 rc 2로 거부된다 |
| `--payload` | `run`과 같다 |
| `--backend` | `run`과 같다 |
| `--network` | `run`과 같다 |
| `--endpoint` | `run`과 같다 |
| `--clock` | `run`과 같다 |
| `--strict` | `run`과 같다 |

**연결 규칙.** 스케줄 이벤트는 IR에서 어떤 워크플로에도 속하지 않는다 —
워크플로가 이미 쓰는 "가장 가까이 앞선 `service` 선언" 규칙(RFC-0002 A.2 R2)을
그대로 적용해, 그 서비스의 워크플로 자식 하나를 target으로 고른다. 정확히
하나가 아니면(0개 또는 2개 이상) rc 2로 거부된다 — 추측하지 않는다. 실행
성공은 rc 0, 실패(`status != completed` 또는 런타임 에러)는 rc ≠ 0 — cron이
그대로 판정에 쓸 수 있다. `lnpl serve`도 같은 연결로 `POST
/-/schedules/<event-slug>` 라우트를 만든다 — 정본은 `docs/serving.md`.

### `schedules` — `on schedule` 이벤트를 외부 스케줄러 스니펫으로 (이슈 #81)

```
lnpl schedules <src>.lnpl --format crontab
lnpl schedules <src>.lnpl --format systemd
```

| 플래그 | 뜻 |
|--------|-----|
| `--format` | `crontab`(기본, 5필드 한 줄) 또는 `systemd`(`.timer`+`.service` 쌍) |
| `-o` / `--output` | 스니펫을 파일로 |

OpenAPI `x-lnpl-schedules` 메타데이터(기존 생성물)를 소비해 `lnpl trigger`를
부르는 스니펫을 만든다 — 스니펫 자체도 생성물이고, 출력 헤더가 손편집
대상이 아님을 밝힌다. 선언된 `on schedule` 이벤트가 없으면 rc 1.

### `spec` — `spec` 블록을 테스트 매니페스트로

| 플래그 | 뜻 |
|--------|-----|
| `-o` / `--output` | 매니페스트를 파일로 |
| `--run` | 매니페스트를 실행한다 |
| `--strict` | 위와 같다 |

### `openapi` — IR에서 OpenAPI 3.1 문서 생성

| 플래그 | 뜻 |
|--------|-----|
| `-o` / `--output` | 문서를 파일로 |

### `serve` — OpenAPI 경로에 워크플로를 HTTP로 바인딩 (모드 A, 이슈 #26)

```
lnpl serve <src>.lnpl [--host 127.0.0.1] [--port 8080]
```

| 플래그 | 뜻 |
|--------|-----|
| `--host` | 바인드 주소 (기본 `127.0.0.1` — 루프백 전용) |
| `--port` | TCP 포트, `0`이면 임시 포트 (기본 `8080`) |
| `--backend` | `run`과 같다. `sqlite:<path>`를 주면 요청 사이에 상태가 남는다 |
| `--network` | `run`과 같다. 이슈 #101 전에는 `serve`에 이 플래그 자체가 없어서 모든 요청이 `fake` 드라이버로 나갔다 |
| `--endpoint` | `run`과 같다 — `--network http`에서 소켓을 바인드하기 전에 검사한다(백엔드·jwt 시크릿과 같은 자리). 이슈 #101 |
| `--jwt-secret-env` | HS256 서명 시크릿이 담긴 **환경변수 이름**. 주면 `security jwt` 서비스가 베어러 토큰을 실제로 검증하고(401 `auth-invalid`), 안 주면 헤더 존재 검사만 한다. 시크릿 **값**은 명령줄로 받지 않는다 |
| `--jwt-issuer` | 검증된 토큰이 실려야 할 기대 `iss` 클레임. 안 주면 기존 `"lnpl"`(이슈 #119b 이전과 바이트 단위로 동일). `--jwt-secret-env`와 함께일 때만 의미가 있다 |
| `--token-provider` | `security jwt` 검증기를 고른다(이슈 #119b): 내장 `hmac`(기본 — `--jwt-secret-env`/`--jwt-issuer`를 그대로 읽는다) 또는 `lnpl.tokens` entry-points 그룹에 등록된 이름(실제 외부 IdP를 RS256/ES256으로 검증). 등록된 이름이 `hmac`을 가리키면 거부된다(`docs/backends.md`) |
| `--log-format` | 접속 로그 형태. `text`(기본, 무음 — 접속 로그 없음) 또는 `json`(요청당 stderr에 JSON 1행: correlation_id/method/path/workflow/status/duration_ms/skipped/diagnostics). 이슈 #78 |
| `--trace-exporter` | 완료된 요청의 Trace를 내보낼 대상. 내장 `stderr-json`, 또는 `lnpl.exporters` entry-points 그룹에 등록된 이름. 안 주면 아무것도 내보내지 않음 — `--log-format`과 독립. 이슈 #78 |
| `--trust-incoming-trace` | 인바운드 `traceparent` 헤더의 trace-id를 이 요청의 trace-id로 채택할지. 기본 꺼짐 — 꺼져 있으면 형식이 깨졌든 신뢰하지 않든 항상 새 trace-id를 채번하고, 받은 값은 link로만 기록한다. 이슈 #107 |

각 워크플로가 `POST /<service-slug>/<workflow-slug>`에서 실행된다. 상태코드
매핑표(200/400/401/404/405/413/500/504)의 정본과 계약 한계(Fake 백엔드,
Authorization 존재 검사만)는 `docs/serving.md`. SIGINT로 정상 종료(rc 0).

### `token` — 서빙 경로 하나에 대한 베어러 토큰 발급 (이슈 #25)

```
lnpl token <src>.lnpl --path /<service>/<workflow> --subject alice \
           --secret-env LNPL_JWT_SECRET [--ttl 15m]
```

| 플래그 | 뜻 |
|--------|-----|
| `--path` | 토큰이 향하는 **서빙 경로**. `serve`가 서빙하지 않는 경로면 유효한 경로 전부와 함께 거부된다 |
| `--subject` | `sub` 클레임 — 토큰이 누구를 대변하는가 |
| `--secret-env` | HS256 서명 시크릿이 담긴 **환경변수 이름**(시크릿 자체가 아니다) |
| `--jwt-issuer` | 토큰에 실을 `iss` 클레임(이슈 #119b). 안 주면 `"lnpl"` — `serve --jwt-issuer`로 검증할 값과 맞춰야 한다 |
| `--ttl` | 액세스 토큰 수명 (기본 `15m`) |

토큰은 stdout 한 줄로 나온다. `aud`는 경로의 서비스 슬러그에서 유도되므로
발급과 검증이 같은 함수를 읽는다 — 이웃 서비스용 토큰은 통하지 않는다.
서명 알고리즘은 HS256 고정이고 검증은 서버 측 allowlist로 한다(`alg: none` 거부).
자세한 계약은 `docs/backends.md`.

### `outbox drain` / `outbox ack` — `lnpl_outbox` 드레인/ack (이슈 #102)

```
lnpl outbox drain --backend sqlite:<path> [--limit N]
lnpl outbox ack --backend sqlite:<path> <seq> [<seq>...]
```

`--backend sqlite:...`로 실행한 `emit`은 `lnpl_outbox`에 영속된다(`run`과 같은
`--backend` 규칙). `fake`는 프로세스 밖 저장소가 없으므로 두 서브커맨드 모두 이
값을 거부한다(rc 2).

| 서브커맨드 | 플래그 | 뜻 |
|-----------|--------|-----|
| `drain` | `--backend` | 필수. `sqlite:<path>`만 유효 |
| `drain` | `--limit` | 출력할 최대 개수 (기본 무제한) |
| `ack` | `--backend` | 필수. `sqlite:<path>`만 유효 |
| `ack` | (위치 인자) `<seq>` | delivered로 마킹할 `seq` 값(들). `drain` 출력의 첫 필드 |

`drain`은 아직 delivered로 마킹되지 않은 모든 행을 `seq` 오름차순(삽입 순서)
JSON Lines로 stdout에 찍는다. 한 줄이 `{"seq", "emission_id", "event", "payload",
"created_at"}`.

**행의 정체성은 `seq`이지 `emission_id`가 아니다.** `emission_id`는
`interp.py`의 프로세스-로컬 카운터라, 같은 문서를 같은 저장소에 대해 두 번
따로 실행하면 첫 emit끼리 같은 `emission_id`를 재현한다 — 그건 재전송이 아니라
서로 다른 두 emission이므로, 두 번째 실행이 실패해서는 안 된다(2026-08-24 실측).
그래서 저장소가 소유하는 대리키 `seq`(sqlite `AUTOINCREMENT`)가 행을 구분하고,
`ack`도 `seq`로 받는다. 같은 `seq` 재-ack는 멱등(성공, 상태 불변). 배치에 모르는
`seq`가 하나라도 있으면 **아무것도 쓰지 않고** 그 `seq`를 이름과 함께 rc 1로
거부한다 — 나머지가 조용히 acked되는 일은 없다.

스키마·drain/ack 의미론의 정본과 외부 릴레이(cron/systemd/k8s CronJob이
drain→publish→ack 루프를 소유) 위임 구도는 `docs/backends.md`.

### `db check` — 저장된 행을 선언과 대조 (이슈 #85)

```
lnpl db check <source...> --backend sqlite:<path>
```

일반 JSON blob 테이블은 스키마를 검증하지 않는다 — entity 선언이 필드를
추가하거나 타입을 바꾼 뒤에도 그 전에 쓰인 행은 조용히 옛 모양 그대로
읽힌다. `db check`는 선언된 모든 entity의 저장된 모든 행을 훑어 그 정합을
확인한다: 선언 필드가 행에 없으면(missing) 또는 있어도 타입이 안 맞으면
(type), stdout에 JSON 배열로 나열한다. 값은 절대 싣지 않는다 — 항목마다
`entity`/`row_key`/`field`/`expected_type`/`kind`뿐이다.

| 플래그 | 뜻 |
|--------|-----|
| `--backend` | 필수. `sqlite:<path>`만 유효 — `fake`는 영속 저장소가 없어 거부(rc 2) |

정합한 DB는 `[]`와 rc 0. 불일치가 하나라도 있으면 rc 1. 백필 자체는 이
커맨드의 일이 아니다 — 이 JSON을 소비해 실제로 고치는 것은 외부 도구고,
고침이 끝났는지는 `db check`를 다시 돌려 확인한다.

`read`/`find`가 돌려주는 행에도 같은 판단이 실시간으로 걸린다 —
`stored-row-shape-mismatch`(warning), 아래 "진단은 어디를 가리키나" 참고.
`db check`는 그 실시간 진단과 같은 판단 로직(`interp.row_shape_mismatches`,
`check_semantic_type` 재사용)을 전체 저장소에 훑어 적용한 것뿐이다.

### `build` — 네이티브 바이너리로 컴파일 (모드 B)

| 플래그 | 뜻 |
|--------|-----|
| `--workflow` | 대상 워크플로 노드 id |
| `--workdir` | 빌드 작업 디렉터리 (기본 `.claude/tmp/lnpl-build`) |
| `--run` | 빌드 후 실행. 거짓 가드로 실행되지 않은 스텝을 복원해 함께 보고한다(아래) |
| `--field` | `NAME=VALUE`. 비교 가드 필드의 값을 준다(반복 가능). 이름은 그 워크플로의 비교 가드 필드여야 하고, 아니면 유효한 이름과 함께 거부된다. 생략한 필드는 0. **비교 가드 전용** — refinement/검증 값은 이 레버로 주입되지 않는다(아래) |
| `--skip` | Presence `when` 가드의 플래그를 세워 존재 검사로 가드된 스텝을 건너뛴다. 비교 가드는 이 플래그가 아니라 `--field`가 몬다 |

MLIR/LLVM 툴체인이 필요하다. 없으면 `bash scripts/dev_doctor.sh`가 알려준다.

**스킵 관측(이슈 #55).** 가드가 거짓이면 바이너리는 그 스텝의 줄을 아예 찍지 않는다.
`--run`은 컴파일된 스텝 계획과 대조해 그 부재를 복원하고 stdout에 이름을 붙여 적으며,
stderr로 `guard-skipped-steps`(warning)를 낸다. mode A와 두 가지가 다르다 — 진단이
**스텝당 한 건**이고(mode A는 가드당 한 건), 위치가 가드 노드 id가 아니라 워크플로
id다. mode B의 관측 표면에 가드가 없기 때문이다.

```
status completed
  (1 step(s) skipped by guard, restored from the compiled plan)
  skipped by `when token.retryBudget > 0`: call token
```

**`--field`의 도달 범위.** 비교 가드의 파라미터만 몬다. refinement 검증은 mode B에서
빌드 시점에 파생 sample payload로 확정되므로 어떤 `--field` 값도 refinement를
실패시키지 못한다. `build`는 Validation effect가 있는 워크플로마다
`validation-sample-derived`(info)로 그 사실을 말한다. refinement 집행을 실측하려면
`lnpl run --payload`(mode A)를 쓴다.

`build`에는 `--strict`도 `--json`도 없다 — mode B 스킵은 사람이 읽는 채널로만
나가고, rc는 스킵이 있어도 0이다. 정본과 잔여 목록은
`rfcs/0022-mode-b-observation-surface.md`.

### `diff` — 차등 검사: 모드 A vs 모드 B

| 플래그 | 뜻 |
|--------|-----|
| `--workflow` | 대상 워크플로 노드 id |
| `--workdir` | 기본 `.claude/tmp/lnpl-diff` |
| `--payload` | 실행 입력 JSON |
| `--no-row` | 양쪽 모두 빈 저장소로 |

### `kb` — 지식 베이스 조회 (RFC-0005)

| 플래그 | 뜻 |
|--------|-----|
| `--root` | KB 루트 경로 |
| `--lint` | RFC-0005 적합성 검사 |
| `--route` | `TASK` 서술을 문서 id 목록으로 |
| `--load` | `DOC_ID`의 본문을 로드 |

### `agents` — RFC-0006 에이전트 사이클

| 플래그 | 뜻 |
|--------|-----|
| `--root` | KB 루트 |
| `-o` / `--output` | 결과 IR을 파일로 |

## 종료 코드

| rc | 뜻 |
|----|-----|
| 0 | 성공 |
| 1 | 실행이 실패했다(워크플로 status가 completed가 아니다), 또는 대상 워크플로가 없다 |
| 2 | 컴파일 에러, 또는 조작 실수 — `--strict` 게이트, 잘못된 `--field`, 잘못된 `--workflow` |
| 3 | 런타임 에러 |
| 4 | 백엔드/차등 검사 에러 |

## 진단은 어디를 가리키나

진단은 **stderr로 나가고 종료 코드는 0**이다. `--strict`를 줘야 rc 2로 올라간다.

진단에는 등급이 있다(이슈 #52). `warning`은 프로그램을 고치면 사라지는 것이고
(`unknown-verb`, `unknown-entity`, `guard-skipped-steps`, `guard-orphaned-steps`,
`aggregation-orphaned-list`, `event-source-mismatch`, `derived-never-assigned`,
`stored-row-shape-mismatch`(이 하나는 프로그램이 아니라 데이터를 고치면
사라진다 — 이슈 #85), `rollback-escapes-network`(호출을 경계 밖으로 옮기거나
`rollback`을 떼면 사라진다 — 이슈 #112)), `info`는 고쳐도 사라지지 않는
플랫폼 상태의 진술이다(`declared-not-enforced`, `declared-measured-only`,
`authorization-not-verified`, `validation-sample-derived`, `event-source-orphaned`,
`declared-not-bound`).
등급별 표는
`references/declarations.md`에 생성되어 있다 — 등급을 정하는 것은 그 표가 아니라
`diagnostics.SEVERITY_OF`이고, 문서는 그것의 사본이다. CI에서 의도한 선언을
통과시키려면 `--strict=warning`을 쓴다.

위치 정보는 네 종류다:

- **파싱·lowering 에러**와 **`unknown-verb`/`unknown-entity`**는 `line N`만
  갖는다 — 소스 줄을 바로 가리킨다(`unknown-entity`는 이슈 #91, 형식은
  `unknown-verb`와 동일).
- **집행 진단** 3종(`declared-not-enforced`, `declared-measured-only`,
  `authorization-not-verified`)은 **노드 id와 `(line N)` 둘 다** 갖는다
  (`[security.shorten] (line 46)`, RFC-0024). `line`은 IR 노드의 선택 필드라
  lowering이 그 노드의 줄을 아는 경우에만 실린다. `authorization-not-verified`는
  런타임(`interp.py`) 진단이라 `lnpl compile`에는 나오지 않고 `lnpl run`(또는
  인터프리터를 직접 돈 경로)에서만 관측된다 — `compile`이 인터프리터를 돌리지
  않는 것은 RFC-0024가 바꾸지 않았다.
- `stored-row-shape-mismatch`도 같은 모양(노드 id + `(line N)`)이지만 노드
  id가 선언이 아니라 그 `RepositoryCall` Effect의 id다 — `authorization-not-
  verified`와 마찬가지로 런타임 진단이라 `lnpl run`에서만 관측되고, `lnpl
  compile`에는 나오지 않는다 (이슈 #85).
- **mode B 두 진단**(`guard-skipped-steps`, `validation-sample-derived`)은
  **워크플로 id**만 갖는다 — 그 표면에는 가드 노드 id가 없다(rfcs/0022 표 1).
  RFC-0024가 손대지 않은 범위다.
- **`guard-orphaned-steps`는 예외로 `line N`만 갖는다.** 저자가 옮겨야 하는 것이
  그 스텝이라, 노드 id를 되짚게 하는 대신 줄을 바로 가리킨다(RFC-0023 §5,
  RFC-0024가 손대지 않은 범위다).
- **`aggregation-orphaned-list`도 `line N`만 갖는다** — 같은 이유다: 저자가
  고쳐야 하는 것은 그 `set` 줄(또는 그 앞에 `list`를 추가하는 것)이라, 줄을
  바로 가리킨다(RFC-0025 §4).
- **`event-source-mismatch`/`event-source-orphaned`도 `line N`만 갖는다** — 저자가
  보거나 옮겨야 하는 것은 그 `emit` 줄이라, 줄을 바로 가리킨다(issue #98).
- **`derived-never-assigned`도 `line N`만 갖는다** — 저자가 고쳐야 하는 것은 그
  `create` 줄(또는 그 앞뒤에 `set`/`format`을 추가하는 것)이라, 줄을 바로
  가리킨다(issue #95).

노드 id에서 선언명을 되짚는 규칙은
[references/naming.md](references/naming.md)에 있다.
