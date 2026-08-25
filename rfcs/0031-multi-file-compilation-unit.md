# RFC-0031: 다중 파일 컴파일 단위

## Status

- Status: **Accepted** (RFC-0031, 2026-08-24)
- Updates: RFC-0004 §Reference-level Specification > 파이프라인 표, S1
  `Semantic Parser` 행의 입력 서술("`.lnpl` 소스 텍스트", 단수) — 컴파일 단위가
  파일 하나에서 파일 집합으로 확장됨에 따라 그 서술을 개정한다. RFC-0004의
  다른 어떤 절도 아직 이 행을 갱신하지 않았으므로 연쇄 갱신 지목 대상은
  RFC-0004 하나뿐이다(RFC-0007 §2.2 규칙 5).
- Updated-by: RFC-0033 (§Guide-level Explanation, §Reference-level
  Specification > 로더: `load_sources(paths)`)

번호가 0031인 이유: 0030까지 점유됐다(RFC-0030). RFC-0007 §3은 번호 재사용을
금지한다.

## Motivation

issue #77: linkly는 "서비스 하나 = 파일 하나"에 갇혀 있다. lexer의
`KEYWORDS_TOP`에는 import류 키워드가 없고, CLI의 모든 서브커맨드는 `source`
위치 인자를 정확히 하나만 받는다(`cli.py` — `compile`/`run`/`spec`/`openapi`/
`serve`/`token`/`build`/`diff`/`agents` 아홉 서브커맨드 전부). 실제 서비스가
커지면 entity·workflow·capability 선언을 파일 하나에 몰아넣는 것 말고는
구조화할 방법이 없다.

이 RFC는 최소 변경으로 그 제약을 없앤다: **컴파일 단위를 파일 하나에서 파일
집합으로 확장**하되, 문법·lexer·parser는 한 글자도 건드리지 않는다. 언어
어휘가 닫혀 있어(closed vocabulary) 학습 데이터에 없는 `use`류 키워드를
넣으면 파싱은 성공하고 런타임은 아무것도 하지 않는 실패 모드가 생긴다
(`lnpl-authoring` 스킬의 존재 이유 자체가 이 위험이다) — 그래서 이 RFC는
문법을 전혀 확장하지 않는 안을 택한다(§Alternatives에서 `use` 선언 도입을
검토하고 기각한다).

**핵심 위험은 소비처 분열이다.** `.lnpl` 소스를 읽는 지점이 하나가 아니다 —
CLI 아홉 서브커맨드, `.lnpl` 저장 직후 도는 진단 훅
(`plugins/lnpl/hooks/lnpl-diagnostics.sh`), MCP `lnpl_compile` 툴
(`mcp_server.py`), 그리고 `lnpl serve`가 `_compile()`을 통해 공유하는 소스
로딩 경로. 이 넷이 각자 다른 방식으로 "여러 파일"을 해석하게 두면, 어느
표면에서는 되고 어느 표면에서는 안 되는 새로운 결함 계열이 생긴다 — RFC-0028
~RFC-0030이 이미 겪은 연쇄 갱신 패턴과 같은 종류의 위험이다. 그래서 이 RFC는
**단일 정본 로더 함수 하나**를 두고 네 소비처 전부가 그 함수만 부르게
한다(§Reference-level Specification).

## Guide-level Explanation

> **Updated by RFC-0033**: 아래 "선언 이름은 전역에서 유일해야 한다 —
> 이름공간이나 가시성 규칙은 없다"는 하위 디렉터리가 없는 컴파일 단위(이
> 절 그대로)에 한정된다. 하위 디렉터리가 있는 레이아웃("네임스페이스
> 루트")에서는 RFC-0033 §Guide-level Explanation이 이긴다 — 이름은
> 네임스페이스 내에서만 유일하면 된다.

여러 `.lnpl` 파일로 서비스 하나를 구성하려면, 파일들을 CLI에 나열하거나
디렉터리 하나를 준다:

```
$ lnpl compile entity.lnpl workflow.lnpl        # 파일 여러 개, 인자 순서대로 병합
$ lnpl compile linkhub/                          # 디렉터리 1개 — *.lnpl을 파일명 정렬로 수집
$ lnpl compile linkhub.lnpl                      # 파일 1개 — 오늘과 완전히 동일 (RFC 이전 동작 보존)
```

이 셋은 `run`/`spec`/`openapi`/`serve`/`token`/`build`/`diff`/`agents` 전
서브커맨드에서 동일하게 동작한다 — 전부 같은 `source` 위치 인자를 확장한
것이기 때문이다.

병합은 결정적이다: 명시적으로 나열한 파일은 **인자 순서**대로, 디렉터리는
**파일명 정렬 순서**대로 이어 붙여 하나의 선언 집합을 만든다. 이 병합된
집합에서 선언 이름은 **전역에서 유일**해야 한다 — 이름공간이나 가시성 규칙은
없다(그런 개념 자체를 이 RFC는 발명하지 않는다; 파일은 순수하게 텍스트를
나누는 경계일 뿐, 선언에게 서로 다른 스코프를 주지 않는다). 같은 이름이
서로 다른 파일에 두 번 선언되면 컴파일이 실패하고, 두 선언 위치를
`<파일>:<줄번호>` 쌍으로 병기한다:

```
$ lnpl compile a.lnpl b.lnpl
compile error: duplicate declaration 'Bookmark': first declared at a.lnpl:3, again at b.lnpl:7
```

파일 1개만 준 호출은 이 RFC 이전과 **바이트 단위로 동일**하다 — 병합 로직은
파일이 둘 이상일 때만 실질적으로 관여하고, 파일 하나는 그 파일의 선언 집합
그대로 lowering된다(오늘과 같은 `module` 이름 유도 규칙 포함).

## Reference-level Specification

### 로더: `impl/lnpl/lower.py::load_sources(paths)`

> **Updated by RFC-0033**: 아래 중복 선언 검사는 하위 디렉터리가 없는
> 컴파일 단위(이 절 그대로, `decl.namespace is None`)에 한정된다.
> 네임스페이스 루트 레이아웃에서는 RFC-0033 §Reference-level Specification
> > "중복 선언 검사 — 네임스페이스 내 유일로 완화"가 이긴다.

```python
def load_sources(paths):
    """paths: 시퀀스(str) — 파일 경로들, 또는 디렉터리 1개.

    반환: list[Decl] — parse()가 오늘 돌려주는 것과 같은 타입, 병합된 순서로.
    module_name은 반환하지 않는다 — 호출자가 별도로 정한다(아래 참고).
    """
```

- **입력이 디렉터리 1개**(`len(paths) == 1`이고 `os.path.isdir(paths[0])`)이면
  그 디렉터리의 `*.lnpl`을 **파일명 정렬**로 수집한다. 파일이 0개면
  `LoaderError`로 거부한다(재귀 탐색 없음 — 하위 디렉터리는 보지 않는다).
- 그 외에는 `paths`를 **주어진 순서 그대로** 파일 목록으로 취급한다.
- 각 파일을 읽어 `parser.parse()`로 개별 파싱한 뒤, 파일 순서대로 이어
  붙인다 — 파일 내부의 선언 순서는 그 파일 안에서 그대로 보존된다.
- **중복 선언 검사는 파일 경계를 넘는 경우만 본다.** 같은 파일 안에서 이름이
  겹치는 경우는 이 함수가 새로 막지 않는다 — 그건 오늘도 `lower()`가
  담당하는 기존 규칙(예: entity/refine 네임스페이스 충돌, RFC-0011 A.7(e))
  그대로 둔다. 이 함수는 **서로 다른 두 파일**에서 같은 이름이 선언된
  경우에만 개입한다. 이렇게 스코프를 좁힌 이유는 파일 1개 호출이 이 RFC
  이전과 바이트 동일해야 하기 때문이다(§Guide-level Explanation) — 파일이
  하나뿐이면 "서로 다른 두 파일"이 존재할 수 없으므로 이 검사는 저절로
  발동하지 않는다.
- 위반 시 `LoaderError`(신설, `LowerError`의 서브클래스 — 기존
  `except (LexError, ParseError, LowerError, ...)` 처리 경로에 새 import
  없이 편입된다)를 던진다. 메시지: `"duplicate declaration %r: first "
  "declared at %s:%d, again at %s:%d"`.
- 문법·lexer는 관여하지 않는다 — `parse()`는 파일마다 독립적으로, 오늘과
  똑같이 호출된다.

### 소비처 네 곳 — 이 함수만 소비한다

| 소비처 | 변경 |
|--------|------|
| `cli.py` 아홉 서브커맨드(`compile`/`run`/`spec`/`openapi`/`serve`/`token`/`build`/`diff`/`agents`) | `source` 위치 인자를 `nargs="+"`로 확장. 공유 헬퍼 `_compile()`/`compile_source()`가 `load_sources(paths)`를 호출 — 서브커맨드마다 흩어져 있던 소스 로딩 호출부가 이미 이 둘 하나로 모여 있었으므로, 이 둘만 고치면 아홉 서브커맨드 전부가 이행된다 |
| 진단 훅(`plugins/lnpl/hooks/lnpl-diagnostics.sh`) | **코드 변경 없음.** 이 훅은 `lnpl compile <파일 1개>`를 셸로 호출할 뿐이며, `_compile()`이 내부적으로 `load_sources([파일])`를 쓰게 되어도 파일 1개 호출은 바이트 동일이므로 훅은 그대로 동작한다 |
| MCP `lnpl_compile`(`mcp_server.py::tool_compile`) | `path`가 파일이면 오늘처럼 그 파일 하나, `path`가 디렉터리면 `load_sources([path])`로 병합 — 새 입력 스키마 필드 없이 기존 `path` 인자가 디렉터리도 받는 것으로 확장. `text` 입력(인라인 소스)은 이 RFC의 대상이 아니다 — 여러 파일을 병합할 대상 자체가 없다 |
| `lnpl serve`의 소스 로딩 | `serve.py`에는 소스 로딩 코드가 없다 — `cmd_serve()`가 다른 서브커맨드와 같은 `_compile()`을 호출한다. 위 `cli.py` 행의 변경이 곧 이 소비처의 변경이다. `serve.py`의 핸들러 구조·WSGI는 손대지 않는다 |

### `module_name` 유도 (변경, `load_sources`가 아니라 `cli.py::_compile()`이 소유)

`load_sources`는 `module_name`을 모른다 — IR 문서의 `module` 필드(RFC-0001
A.1)를 채우는 이름은 호출자가 정한다. `cli.py`의 규칙:

- 입력이 파일 1개 → 그 파일의 basename(확장자 제거) — **RFC 이전과 동일**.
- 입력이 디렉터리 1개 → 그 디렉터리의 basename.
- 입력이 파일 여러 개(디렉터리 아님) → **첫 번째** 파일의 basename(확장자
  제거) — 병합 순서(인자 순서)가 이미 결정적이므로 그 순서의 첫 항목을
  쓴다.

MCP `lnpl_compile`은 이 유도 규칙을 쓰지 않는다 — `module` 인자(생략 시
literal `"mcp"`)를 오늘처럼 그대로 쓴다. path가 파일이든 디렉터리든 동일.

### IR 동일성 — `line`을 뺀 비교

RFC-0024가 IR 노드에 얹은 선택 필드 `line`은 그 노드를 lowering이 어느
**소스 줄**에서 봤는지 기록하는 진단용 위치 메타데이터다(§RFC-0024 — 무엇을
집행하는지가 아니라 어디서 왔는지). D4가 "라인 번호가 파일 경계를 넘어
흐르지 않게 — 위치 표기는 (파일, 라인) 쌍 유지"라고 정한 그대로, 병합된 여러
파일에서 나온 노드의 `line`은 **그 노드가 실려 있던 파일 안에서의 줄**이다
— 원본 단일 파일에서의 절대 줄로 재계산하지 않는다. 그 결과, 분할
전(원본)과 분할 후(병합)를 비교하면 같은 선언이라도 `line` 값이 다르다(예:
`workflow SaveBookmark`는 단일 파일에서 53번째 줄이지만, 분할 후 두 번째
파일 1번째 줄에서 시작한다) — 이는 버그가 아니라 D4가 요구한 동작이다.

그래서 **"IR 해시 동일"(이슈 #77 DoD)은 `line`을 제외한 문서 비교**를
말한다 — `line`은 프로그램이 "무엇을 하는가"가 아니라 "어디서 왔는가"를
말하는 필드이고, 병합 정확성이 확인해야 하는 것은 전자다. 테스트는
`to_document()`의 각 노드에서 `line` 키를 제거한 뒤 두 문서를 비교하고,
그 비교(및 `json.dumps(..., sort_keys=True)`의 sha256 — "IR 해시")로 D5를
판정한다.

RFC-0001 A.3은 (원래 `line` 필드가 없던 시절부터) 두 IR 문서의 동등성
판정을 RFC 8785(JCS)에 위임했다 — 그 위임은 이 RFC가 바꾸지 않는다.
`line`을 제외하는 규칙은 이 RFC가 다루는 "분할 전/후 병합 정확성" 비교에
한정된다(모드 A/B 등가성처럼 `line`이 있든 없든 같아야 하는 다른 비교는
그대로 전체 문서를 본다). 완전한 JCS 캐노니컬라이저는 여전히 이 RFC의
범위 밖이다(기존 코드에도 없다) — `to_document()`가 담는 값 범위(문자열/
정수/불리언/리스트, 부동소수점 없음)에서는 `sort_keys` sha256과 결과가
갈리지 않는다(§Open Questions).

## Examples

**분할 컴파일 — `examples/linkhub.lnpl`을 2파일로 나눈 픽스처**
(`impl/tests/lnpl_fixtures/linkhub/` — 디렉터리 이름이 곧 `module_name`이
되므로(§Reference-level Specification), 원본 파일의 basename `linkhub`와
맞춘다):

```
linkhub/
  01_entity.lnpl     # capability postgres/redis, refine VisitCount, entity Bookmark, event BookmarkSaved, service LinkHubService
  02_workflow.lnpl    # workflow SaveBookmark, workflow GetBookmark
```

파일명이 `01_`/`02_`로 정렬되므로 디렉터리 병합 순서가 원본
`linkhub.lnpl`의 선언 순서와 정확히 같다:

```
$ lnpl compile examples/linkhub.lnpl -o /tmp/single.lir.json
$ lnpl compile impl/tests/lnpl_fixtures/linkhub/ -o /tmp/split.lir.json
```

두 문서는 `module`을 포함해 전부 같지만, 각 노드의 `line`만 다르다 — 병합된
두 번째 파일(`02_workflow.lnpl`)의 선언들은 그 파일 안에서의 줄을 담기
때문이다(§IR 동일성). `line`을 뺀 비교(위 절)가 D5(§Reference-level
Specification)를 판정하는 방법이다.

**중복 선언 거부**:

```
$ cat a.lnpl
entity Bookmark
    field
        id UUID
$ cat b.lnpl
entity Bookmark
    field
        id UUID
$ lnpl compile a.lnpl b.lnpl
compile error: duplicate declaration 'Bookmark': first declared at a.lnpl:1, again at b.lnpl:1
$ echo $?
2
```

**빈 디렉터리 거부**:

```
$ mkdir empty && lnpl compile empty/
compile error: directory 'empty/' has no .lnpl files
$ echo $?
2
```

## Alternatives

**`use <path>` 선언(파일 안에서 다른 파일을 참조)** — 기각. 최상위 키워드를
하나 늘려야 하는데, 언어 어휘는 닫혀 있고 학습 데이터에 없는 키워드는 파싱은
성공하고 런타임은 아무 효과도 내지 않는 실패 모드를 만든다(`unknown-verb`류
문제의 선언 버전). 게다가 `use`는 순환 참조 검출을 요구한다 — A가 B를
쓰고 B가 A를 쓰는 경우를 잡아야 하는데, 지금 그 수요가 없다(단일 컴파일
단위 안에서 순서 있는 병합만 있으면 issue #77의 요구가 풀린다). 두 비용
다 지금 얻는 이득(문법 불변 유지)보다 크다. 이름공간·가시성 규칙도 함께
발명해야 했을 것이다 — 이 RFC는 그 설계 공간 자체를 열지 않는다.

**소비처마다 독립적으로 다중 파일을 해석** (예: CLI는 `argparse`
`nargs="+"`로, MCP는 자체 로직으로) — 기각. `이 RFC의 Motivation`이 이미
지적한 위험 그대로다 — 표면 간 동작이 갈라지면 "CLI에서는 되는데 MCP에서는
안 된다" 류의 결함이 생긴다. 단일 정본 함수(`load_sources`) 하나로 네 소비처
전부가 수렴하는 지금 설계가 그 위험을 구조적으로 없앤다.

**파일별 독립 이름공간**(같은 이름이 다른 파일에 있으면 다른 선언으로 취급) —
기각. 이름 해석이 "어느 파일에서 참조했는가"에 의존하게 되는데, 지금 언어는
선언을 이름으로만 참조하고 파일 개념을 아예 모른다(lexer가 파일 경계를
토큰화하지 않는다). 이 구분을 넣으려면 파서·lowering 양쪽에 "지금 어느
파일을 보고 있는가"라는 새 상태를 흘려야 하고, 그건 문법 불변이라는 이 RFC의
전제와 정면으로 부딪힌다. 전역 유일 이름이 구현 비용도 훨씬 작고, issue #77이
요구하는 것 — "파일을 나눠 구조화하고 싶다" — 을 충족하는 데 이름공간까지는
필요 없다.

## Open Questions

- 파일 여러 개를 명시적으로 나열할 때(`lnpl compile a.lnpl b.lnpl`, 디렉터리
  아님) 인자 순서에 **의미**(예: 나중 선언이 앞선 선언을 오버라이드)를 줄지는
  아직 열려 있다 — 지금은 순서가 병합 순서만 결정하고, 이름 충돌은 순서와
  무관하게 전부 거부된다(§Reference-level Specification). 오버라이드
  의미론이 필요해지면 별도 RFC가 다룬다.
- RFC-0001 A.3의 RFC 8785(JCS) 캐노니컬라이저는 여전히 코드로 존재하지
  않는다 — 이 RFC의 테스트는 그 필요가 생기지 않는 값 범위(문자열/정수/불리언
  /리스트, 부동소수점 없음)에서 `sort_keys` sha256으로 대체한다. 완전한 JCS
  구현이 필요한 시점(예: 서명·원격 캐시 키)이 오면 별도 RFC가 다룬다.
