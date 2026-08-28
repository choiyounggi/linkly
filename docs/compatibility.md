# 호환성 정책 (0.x)

linkly는 아직 0.x다 — [Semantic Versioning](https://semver.org/)의 "무엇이든
바뀔 수 있다"는 0.x 규칙을 그대로 따른다. 이 문서는 그 안에서도 **어느
표면이 계약이고, 무엇이 바뀌면 [CHANGELOG.md](../CHANGELOG.md)의 `Changed`
절에 breaking으로 고지되는지**를 명시한다 — "0.x니까 아무거나 바뀔 수 있다"를
운영자가 실무에서 쓸 수 있는 목록으로 좁힌다.

breaking change의 고지 방식은 전부 동일하다: 릴리스 태그의
[CHANGELOG.md](../CHANGELOG.md) 항목에 `Changed`로 기록하고, 그 항목이
아래 계약 중 무엇을 바꿨는지 이름을 댄다. 릴리스 절차는
[docs/RELEASING.md](RELEASING.md)를 본다.

## 계약 목록

### 1. 진단 `code` / `severity`

컴파일 진단은 `code` / `severity` / `where` / `subject` / `message` 다섯
키로 이루어진 레코드다(RFC-0021 §Diagnostic 레코드 형태). `severity`는
`code`에서 파생된다(`SEVERITY_OF[code]`) — 같은 `code`가 릴리스 사이에
다른 severity로 재분류되면 breaking이다.

- **보장**: 기존 `code` 값의 의미·severity 매핑은 유지된다. 새 진단
  `code` 추가는 breaking이 아니다.
- **breaking**: 기존 `code`를 삭제·재의미부여, 또는 severity 매핑 변경.
- 검증: `lnpl compile <file> --strict=warning` — `warning` 등급 이상이면
  rc≠0 (issue #62, v0.5.0에서 기본 게이트로 승격).
- **확장 code**: RFC-0042가 `code`에 네임스페이스 축(`<prefix>/<code>`)을
  연다. 위 보장·breaking 규칙은 bare(무슬래시) `code`에만 적용된다 — bare는
  코어 전용 영구 예약이다(RFC-0042 §Reference-level Specification/코드 →
  등급). **`<prefix>/<code>`의 존속·재의미부여·severity는 코어가 아니라 그
  확장 자신의 보증이다.** 코어가 보증하는 것은 다섯 키 봉투 형태
  (`code`/`severity`/`where`/`subject`/`message`)뿐이다.

**기계 채널 — `lnpl compile --json` (issue #133)**: `--json`은 사람용
`format_lines` 출력 대신 stdout에 결합 JSON 문서 하나만 낸다 —
`{"lir_version", "module", "nodes", "diagnostics"}`. `diagnostics`의 각
레코드는 `code` / `severity` / `where` / `subject` / `message` / `line`
여섯 키로 고정된다(위 다섯 키 + RFC-0024 `line`) — 키 생략은 없다.

- 진단이 0건이면 `"diagnostics": []`(`null` 금지). 컴파일이 문서를 만들지
  못하는 실패(파스/lower 에러)에서는 `lir_version` / `module` / `nodes`가
  `null`이고 `diagnostics`는 같은 형태로 `[]`다 — 빈 모듈이 성공적으로
  내는 `"nodes": []`와는 구별된다. 하드 에러 메시지는 stderr로만 간다.
- `--json` 유무는 채널만 바꾼다: exit code 의미는 동일하고, `--strict`와도
  직교한다(`--json --strict`의 rc는 `--strict`만 준 경우와 같다).
- 이 6키·null 규칙은 계약이다 — 키 추가는 breaking이 아니지만 키 삭제나
  `null` 규칙 변경은 breaking이다.

### 2. Semantic IR 스키마 (`schemas/lir.schema.json`)

`lnpl compile`이 내는 IR JSON의 정본 스키마. `lir_version` 필드가 스키마
세대를 표시한다.

- **보장**: 같은 `lir_version` 내에서 기존 노드 `kind`의 필수 필드는
  유지된다. 새 `kind`나 선택 필드(예: v0.5.0의 `line`, RFC-0024) 추가는
  breaking이 아니다.
- **breaking**: 기존 필수 필드 제거·타입 변경, 또는 `lir_version` 상향
  (하위 소비자가 재검증 없이 파싱하면 깨질 수 있는 변경).

**`provenance` 블록 (issue #136)**: `to_document()`가 내는 모든 문서의
최상위 `provenance` 키 — `compiler` / `vocabulary_digest` /
`enforcement_digest` / `extensions` 네 키로 고정된다. 위 "새 `kind`나
선택 필드 추가는 breaking이 아니다" 보장 그대로 additive·optional이다 —
`lir_version`은 올라가지 않았고, 이 키가 없는 구세대 문서도 여전히
유효하다(`lnpl.provenance.check()`가 그 경우 보고를 `None`으로 채운다).
`vocabulary_digest` / `enforcement_digest`는 정규화 직렬화(`sort_keys=True`,
compact separators)의 sha256이며 `"sha256:"` 접두가 계약이다 — 접두·해시
알고리즘의 변경은 breaking. 값 자체(다이제스트의 실제 16진수)는 계약이
아니다: 어휘·집행 상수가 바뀌는 정상적인 커밋마다 달라진다. 서명이나
증명(attestation)은 이 블록의 범위 밖이다 — 의미 세대 식별이 목적이지
빌드 플랫폼 신뢰가 목적이 아니다.

### 3. sqlite 저장소 스키마 (`lnpl_rows` / `lnpl_outbox`)

`--backend sqlite:<path>`가 여는 두 테이블. 정본은
[docs/backends.md](backends.md).

- `lnpl_rows`: `entity_id, row_key, payload, _version`. `_version`은
  낙관적 동시성 조건부 쓰기 전용 내부 컬럼이다(issue #92) —
  `UPDATE ... SET payload = ?, _version = _version + 1 WHERE ... AND
  _version = ?`.
- `lnpl_outbox`: PK는 `seq`(sqlite `AUTOINCREMENT`)이지 `emission_id`가
  아니다 — 같은 DB에 대한 재실행에서 `emission_id`가 PK 충돌을 일으키는
  것이 issue #102에서 실측되어, 행 정체성을 저장소가 소유하는 대리키
  `seq`로 옮겼다. `lnpl outbox ack`는 같은 `seq` 재-ack가 멱등이다.
- **보장**: 기존 컬럼의 이름·의미는 유지된다. 기존 DB 파일에 대해
  `ALTER TABLE ... ADD COLUMN ... DEFAULT ...`로 흡수 가능한 컬럼 추가는
  breaking이 아니다(예: `_version` 자체가 이 방식으로 도입됨).
- **breaking**: 기존 컬럼 제거·의미 변경, PK 정의 변경(예: 다시
  `emission_id`를 PK로), 또는 마이그레이션 없는 컬럼 타입 변경.

### 4. `spec` 블록 어휘 — `given` / `expect`

`given`이 받는 형식(`valid`, `empty repository`, `input.<field>`,
`stored`, `stored <entity>[<i>]`, `call ... returns ...` 등)과 `expect`가
받는 키(`completed`/`failed`/`steps`/`rows`/`emitted`/`effects`/...)의
정본은 `lnpl-spec` 스킬 참조(`references/spec.md`, 컴파일러 docstring
상수에서 생성됨 — 손으로 고치면 `test_plugin_references.py`가 실패한다).

- **보장**: 기존 `given` 형식·`expect` 키의 파싱과 의미는 유지된다. 새
  키/형식 추가(v0.5.0의 `call ... returns ...`, RFC-0027)는 breaking이
  아니다. 미문서화 키는 생성기가 fail-closed로 거부한다(issue #61).
- **breaking**: 기존 키·형식 제거 또는 의미 변경.

### 5. CLI 표면

`lnpl --help`가 나열하는 서브커맨드 집합과 각 커맨드의 관측 가능한
동작(입력 인자, 종료 코드, stdout/stderr 계약):

```
compile   parse and lower to Semantic IR
run       compile then execute (interpreter mode A)
spec      extract `spec` blocks as a test manifest
openapi   generate an OpenAPI 3.1 document from the IR
serve     serve workflows over HTTP at the OpenAPI paths (mode A, fake backend)
token     issue a bearer token for one served path (#25)
outbox    drain/ack the lnpl_outbox — at-least-once emit delivery (issue #102)
build     compile to a native binary (mode B)
diff      differential check: mode A vs mode B
kb        inspect the knowledge base (RFC-0005)
agents    run the RFC-0006 agent cycle over a source
```

운영 배치 경로(`lnpl.wsgi:build_app()` + 환경 변수 계약)는 이
서브커맨드 목록과 별도 계약이며 정본은
[docs/serving.md](serving.md#운영-배치--wsgi-호스트gunicorn-이슈-80)다.

- **보장**: 기존 서브커맨드의 이름·필수 인자·성공 시 종료 코드(0)·
  실패 분류(진단 스키마와 동일 원칙)는 유지된다. 새 서브커맨드·선택
  플래그 추가는 breaking이 아니다.
- **breaking**: 기존 서브커맨드 제거·이름 변경, 필수 인자 의미 변경,
  성공 판정을 바꾸는 종료 코드 변경.

## 이 문서가 다루지 않는 것

- `.lnpl` 언어 어휘(동사/선언) 자체의 확장·축소 — 그 계약은 각 RFC가
  진다(정본은 `rfcs/`), 이 문서는 어휘를 소비하는 **도구 표면**만 다룬다.
- 내부 구현 세부(모듈 경로, private 함수) — 애초에 계약이 아니다.
