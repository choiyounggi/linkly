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
| `--strict` | 진단이 하나라도 있으면 rc 2 |

`-o` 없이 쓰면 IR 문서가 **stdout**으로 나간다. 진단은 항상 stderr다 — 그래서
`-o` 없이 stdout을 파이프해도 산출물이 오염되지 않는다.

### `run` — 컴파일 후 실행 (인터프리터, 모드 A)

| 플래그 | 뜻 |
|--------|-----|
| `--payload` | 실행 입력이 담긴 JSON 파일. 없으면 선언된 타입에서 샘플 payload를 만든다 |
| `--workflow` | 실행할 **워크플로 노드 id**. 없으면 첫 번째 |
| `--json` | 결과와 트레이스를 JSON으로 |
| `--no-row` | 빈 저장소로 시작한다(재시도 경로를 관측할 때) |
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

위치 정보는 두 종류다:

- **파싱·lowering 에러**는 `line N`을 갖는다 — 소스 줄을 바로 가리킨다.
- **집행 진단**(`declared-not-enforced`, `declared-measured-only`,
  `unknown-verb`, `authorization-not-verified`, `guard-skipped-steps`)은
  **노드 id**만 갖는다(`[perf.rate.notify]`). 파일:라인이 아니다.

집행 진단이 어느 줄에서 왔는지 알아야 하면 `compile -o`로 IR을 뽑아 그 노드 id를
찾는다. 노드 id에서 선언명을 되짚는 규칙은
[references/naming.md](references/naming.md)에 있다.
