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
| `--strict` | 위와 같다 |

`--workflow`는 선언명이 아니라 노드 id를 받는다(`GetReport`가 아니라
`wf.get.report`). 도출 규칙은 [references/naming.md](references/naming.md)에 있고,
잘못된 id를 주면 유효한 id 전부가 에러에 나열된다.

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
| `--jwt-secret-env` | HS256 서명 시크릿이 담긴 **환경변수 이름**. 주면 `security jwt` 서비스가 베어러 토큰을 실제로 검증하고(401 `auth-invalid`), 안 주면 헤더 존재 검사만 한다. 시크릿 **값**은 명령줄로 받지 않는다 |

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
| `--ttl` | 액세스 토큰 수명 (기본 `15m`) |

토큰은 stdout 한 줄로 나온다. `aud`는 경로의 서비스 슬러그에서 유도되므로
발급과 검증이 같은 함수를 읽는다 — 이웃 서비스용 토큰은 통하지 않는다.
서명 알고리즘은 HS256 고정이고 검증은 서버 측 allowlist로 한다(`alg: none` 거부).
자세한 계약은 `docs/backends.md`.

### `build` — 네이티브 바이너리로 컴파일 (모드 B)

| 플래그 | 뜻 |
|--------|-----|
| `--workflow` | 대상 워크플로 노드 id |
| `--workdir` | 빌드 작업 디렉터리 (기본 `.claude/tmp/lnpl-build`) |
| `--run` | 빌드 후 실행 |
| `--field` | `NAME=VALUE`. 비교 가드 필드의 값을 준다(반복 가능). 이름은 그 워크플로의 비교 가드 필드여야 하고, 아니면 유효한 이름과 함께 거부된다. 생략한 필드는 0 |
| `--skip` | Presence `when` 가드의 플래그를 세워 존재 검사로 가드된 스텝을 건너뛴다. 비교 가드는 이 플래그가 아니라 `--field`가 몬다 |

MLIR/LLVM 툴체인이 필요하다. 없으면 `bash scripts/dev_doctor.sh`가 알려준다.

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
(`unknown-verb`, `guard-skipped-steps`), `info`는 고쳐도 사라지지 않는 플랫폼
상태의 진술이다(`declared-not-enforced`, `declared-measured-only`,
`authorization-not-verified`). 등급별 표는 `references/declarations.md`에
생성되어 있다. CI에서 의도한 선언을 통과시키려면 `--strict=warning`을 쓴다.

위치 정보는 두 종류다:

- **파싱·lowering 에러**는 `line N`을 갖는다 — 소스 줄을 바로 가리킨다.
- **집행 진단**(`declared-not-enforced`, `declared-measured-only`,
  `unknown-verb`, `authorization-not-verified`, `guard-skipped-steps`)은
  **노드 id**만 갖는다(`[perf.rate.notify]`). 파일:라인이 아니다.

집행 진단이 어느 줄에서 왔는지 알아야 하면 `compile -o`로 IR을 뽑아 그 노드 id를
찾는다. 노드 id에서 선언명을 되짚는 규칙은
[references/naming.md](references/naming.md)에 있다.
