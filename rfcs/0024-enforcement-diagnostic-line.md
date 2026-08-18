# RFC-0024: 집행 진단에 소스 line 병기

## Status

- Status: **Accepted** (RFC-0024, 2026-08-17)
- Updates: **RFC-0023 §Reference-level Specification/5. `where`** — "IR 노드는
  위치가 아니라 의미를 담으므로 줄 번호를 싣지 않는다"는 서술을 개정한다. 이제
  IR 노드는 선택 필드 `line`(1-base 소스 줄, integer)을 가질 수 있다.
  `guard-orphaned-steps` 자신의 판정과 `where` 표기(고아 스텝의 줄)는 이 RFC가
  바꾸지 않는다 — `_WfContext.step_lines`를 그대로 쓴다.
- Updated-by: RFC-0026 (§Reference-level Specification/3. 집행 진단 3종의
  `line`), RFC-0026 (§Examples/바뀌지 않는다)

Supersedes는 없다. 코드·등급 체계(RFC-0021)를 바꾸지 않는다 — 새 코드를 신설하지
않고, 기존 코드의 등급도 그대로다. 진단이 **어디를 가리키는지**를 늘릴 뿐,
**무엇을 진단하는지**는 건드리지 않는다.

번호가 0024인 이유: 0023까지 점유됐다. RFC-0007 §3은 번호 재사용을 금지한다.

언어 워킹네임은 **LNPL**(소스 확장자 `.lnpl`)이다.

## Motivation

이슈 #67이 보고한 증상: 집행 진단(`declared-not-enforced` /
`declared-measured-only` / `authorization-not-verified`, 이슈 #38)은 노드 id만
가리킨다. 한 절(clause)에 선언이 둘 이상이면, 그 절이 낳는 진단들은 **서로 다른
소스 줄에서 왔는데도 같은 위치**를 가리킨다:

```
entity Order
    field
        id UUID

service Ord
    security
        jwt
        role admin

workflow Place
    validate order
```

이 모듈을 컴파일하면:

```
info: declared-not-enforced [security.ord] security jwt — declared but unenforced: ...
info: declared-not-enforced [security.ord] security role — declared but unenforced: ...
```

두 줄 다 `[security.ord]`다. `subject`(`security jwt` / `security role`)를 읽어야
어느 게 몇 번째 줄인지 알 수 있고, 절이 길어질수록 그 되짚기는 선형으로 느려진다.
`authorization-not-verified`도 마찬가지다 — 워크플로 하나에 `authorize` 스텝이
여럿이면 전부 그 스텝의 Effect id만 가리킨다.

노드 id에서 소스 줄로 가려면 `lnpl compile -o`로 IR을 뽑아 그 id의 원본 선언
줄을 손으로 찾아야 했다. RFC-0023 §5는 정확히 같은 문제를 `guard-orphaned-steps`
하나에 대해 이미 풀었다 — "저자가 옮겨야 할 스텝의 줄을 가리킨다"고 적고
`_WfContext.step_lines`로 줄을 되짚는다. 이 RFC는 그 해법을 집행 진단 3종까지
넓힌다. 다만 그 해법을 그대로 복제하지는 않는다: `step_lines`는 워크플로 스텝
전용 곁표이고, 집행 진단은 워크플로 밖(서비스의 `policy`/`security`/`performance`
절)에서도 나오므로 **IR 노드 자신에** 위치를 싣는 편이 lowering이 아는 모든 곳에
같은 방식으로 적용된다.

## Guide-level Explanation

IR 노드는 선택 필드 `line`을 가질 수 있다 — lowering이 그 노드의 소스 줄을 아는
경우에만 싣고, 모르면(예: 여러 소스 줄을 아우르는 절 노드, preset에서
emit-on-use로 합성된 Refinement 노드) 생략한다. 필드가 있으면 있는 그대로,
없으면 아무것도 달라지지 않는다 — 이 RFC 이전의 모든 소비자는 그대로 동작한다.

집행 진단 3종은 `where`(노드 id)에 **더해** 그 진단이 정확히 어떤 소스 줄에서
왔는지를 판정 시점에 직접 실어 나른다. 컴파일타임 진단
(`lower.py::_declaration_diagnostics`)은 절을 파싱하는 바로 그 순간의 줄 번호를
전달하고, 런타임 진단(`interp.py`의 `authorization-not-verified`)은 소스 텍스트가
없으므로 이미 lowering이 그 Effect 노드에 적어 둔 `line`을 IR에서 되짚는다.
`subject`로 어느 선언인지 알아내던 것을, 이제 `(line N)`으로 바로 안다:

```
info: declared-not-enforced [security.ord] (line 7) security jwt — ...
info: declared-not-enforced [security.ord] (line 8) security role — ...
```

`authorization-not-verified`는 여전히 런타임에만 발화한다 — `lnpl compile`은
parse+lower만 하고 인터프리터를 돌리지 않으므로(`cli.py::_compile`), 이 진단은
`lnpl compile`이 아니라 `lnpl run`(혹은 MCP `lnpl_compile` 도구가 아니라
인터프리터를 직접 돌리는 경로)에서만 관측된다. 이 경계는 RFC-0024가 바꾸지
않는다 — `compile`과 `run`이 서로 다른 보고 범위를 갖는 것은 기존 설계다
(`cli.py::cmd_run`의 "Compile-time and run-time findings are one report, not
two" 주석대로, `run`이 `compile`의 결과에 자신의 진단을 얹는다).

## Reference-level Specification

### 1. IR 스키마

`schemas/lir.schema.json`의 노드 kind별 정의(`$defs.node*`, 22종 — `Policy` /
`Security` / `Performance` / `Refinement` / `Transaction` 포함 전부) 각각에
선택 속성 `line`을 추가한다:

```json
"line": { "$ref": "#/$defs/lineNumber" }
```

`$defs.lineNumber`는 `{ "type": "integer", "minimum": 1 }`. `required`에는
어디에도 넣지 않는다 — 모든 노드 kind에서 여전히 선택이다.

### 2. lowering이 `line`을 싣는 노드

`lower.py`가 소스 줄을 이미 손에 쥔 시점에 그 값을 그대로 넘긴다. 새로 유도하지
않는다:

| 노드 | `line` 출처 |
|------|-------------|
| `Entity` | 그 엔티티를 선언한 `entity` 줄(`decl.lineno`) |
| `Service` / `Workflow` / `Event` / `Capability` | 그 선언 헤더 줄(`d.lineno`) |
| `BusinessRule`(`goal`) | 그 `goal` 줄 |
| `WorkflowStep` | 그 스텝 줄 |
| `Guard` | 그 가드 줄(`guard["lineno"]`) |
| `Concurrency` / `Pipeline` | 그 블록 헤더 줄(`block["lineno"]`) |
| Effect 노드 전부(`Validation` / `RepositoryCall` / `CacheAccess` /
  `NetworkCall` / `Authorization` / `EventEmit` / `Assignment`) | 그 노드를 파생시킨
  스텝 줄 |

`Policy` / `Security` / `Performance` 노드는 **싣지 않는다** — 한 절이 여러 소스
줄(각 선언 줄)을 아우르는 집합 노드라, 노드 하나에 대응하는 단일 줄이 없다.
그래서 §3의 집행 진단은 이 노드들의 `line`을 읽지 않고, 절을 파싱하는 시점의
줄을 직접 받는다. `Refinement` 노드도 싣지 않는다 — preset에서 emit-on-use로
합성되는 경로(`_refinement_node`)가 소스 줄을 받지 않는다.

### 3. 집행 진단 3종의 `line`

`diagnostics.py`의 `Diagnostic`에 필드 `line: int = None`을 추가하고,
`Diagnostics.add(*, code, where, subject, message, line=None)`으로 받는다.
`to_records`는 `"line"` 키를 항상 담아 반환한다(값이 `None`이어도) — MCP 등
구조화 소비자가 키 존재 여부가 아니라 값으로 분기하게 한다.

`format_lines`의 렌더는:

- `line`이 있으면 `<sev>: <code> [<where>] (line <N>) <subject> — <message>`
- 없으면 이 RFC 이전 그대로 `<sev>: <code> [<where>] <subject> — <message>`

세 발화 지점:

- `declared-not-enforced` / `declared-measured-only`
  (`lower.py::_declaration_diagnostics`) — 호출부가 `[(name, lineno), ...]`를
  넘긴다. `lineno`는 그 절의 해당 선언 줄(`d.clauses[clause][i].lineno`) —
  Security/Policy/Performance 노드 자신이 아니라 절을 파싱하는 루프가 이미 쥐고
  있는 값이다. `event schedule`은 그 이벤트 선언의 `d.lineno`.
- `authorization-not-verified` (`interp.py`) — 런타임에는 소스 텍스트가 없다.
  이미 lowering이 그 Authorization Effect 노드에 적어 둔 `line`을
  `self.nodes[effect["id"]].get("line")`으로 되짚는다. 그 노드가 `line`을 모르면
  (§4의 로 폴백 규칙대로) `None`이 그대로 전달된다 — 예외를 던지지 않는다.

이 3종 밖의 진단(`unknown-verb`, `guard-skipped-steps`, `guard-orphaned-steps`,
`validation-sample-derived`)은 `line`을 넘기지 않는다 — 각자의 기존 `where`
표기(줄 또는 워크플로 id)가 그대로 유일한 위치 정보다.

### 4. 없는 `line`은 조용히 폴백한다

`line`은 어디서든 선택이다 — IR 노드 자신에서도, `Diagnostic`에서도. 이 RFC가
새로 만든 IR을 다루지 않는 소비자(이 RFC 이전에 만들어진 `.lir.json`, 손으로
합성한 IR, 이 RFC가 다루지 않는 노드 kind)를 인터프리터에 태워도, `line`이 없는
Effect의 `authorization-not-verified`는 `.get("line")`이 `None`을 돌려주고
`format_lines`가 옛 형식으로 렌더한다 — 크래시하지 않는다
(`impl/tests/test_enforcement_diag_lines.py::TestMissingLineFallsBackToTheOldFormat`
가 고정).

## Examples

### 발화(집행 진단, compile 경로)

`examples/shorten.lnpl`의 `security jwt`(46행)와 `performance response < 40ms`
(48행):

```
$ lnpl compile examples/shorten.lnpl
info: declared-not-enforced [security.shorten] (line 46) security jwt — declared but unenforced: ...
info: declared-measured-only [perf.shorten] (line 48) performance response — declared but measured: ...
```

### 발화(집행 진단, run 경로 — 런타임 전용)

같은 파일의 `authorize owner`(53행)는 `authorization-not-verified`를 낸다.
`lnpl compile`에는 나오지 않고 `lnpl run`에만 나온다(§Guide-level Explanation의
경계):

```
$ lnpl run examples/shorten.lnpl
...
info: authorization-not-verified [wf.shorten.step.2.authz] (line 53) owner — ...
```

### 발화하지 않는다(폴백)

`line`을 모르는 Authorization Effect(수기 IR, 또는 이 RFC 이전 산출물)를
인터프리터에 직접 태우면 `authorization-not-verified`는 뜨되 `(line`이 없는 옛
형식으로 렌더한다 — 크래시도, 다른 진단으로의 오분류도 없다.

### 바뀌지 않는다

`guard-orphaned-steps`(RFC-0023)와 `unknown-verb`는 이 RFC 이전과 바이트 단위로
같은 형식이다 — 둘 다 이미 `line N`만 가졌고 노드 id가 없었으므로 더할 것이
없다. `guard-skipped-steps` / `validation-sample-derived`(mode B)도 워크플로 id만
갖는 그대로다.

## Alternatives

**(a) `where`를 노드 id 대신 `"line N"`으로 바꾼다.** RFC-0023이 이미 이 형태를
쓰고 있어 일관돼 보이지만, 노드 id는 `compile -o`로 뽑은 IR과 진단을 이어 주는
유일한 손잡이다(§Reference-level Specification/1 자체가 그 되짚기 규칙을 문서화
한다 — `references/naming.md`). `where`를 지우면 그 되짚기가 사라진다. 채택하지
않았다.

**(b) 집행 진단마다 노드 id 대신 `subject`를 바꿔 줄을 실어 나른다** (예:
`subject="security jwt (line 46)"`). `subject`는 "코드와 등급으로 분기할 수
있어야 한다 — message를 정규식으로 긁는 것이 아니라"는 계약을 갖는다
(`impl/tests/test_mcp_server.py`). 줄을 문자열로 섞으면 그 계약이 깨져 MCP 소비자가
다시 정규식을 써야 한다. 채택하지 않았다.

**(c) `line`을 필수 필드로 만든다.** `Policy`/`Security`/`Performance`/
`Refinement` 노드는 대응하는 단일 소스 줄이 없다(§Reference-level
Specification/2) — 필수로 만들면 그 노드들에 억지 값을 지어내야 한다. 선택
필드로 남겨 "모르면 생략"을 그대로 표현한다. 채택하지 않았다.

**(d) `authorization-not-verified`가 발화하도록 `lnpl compile`이 인터프리터까지
돌리게 한다.** DoD를 문자 그대로 읽으면 끌리지만, `compile`과 `run`의 경계(각자
다른 보고 범위, `cmd_compile`은 parse+lower만)는 이슈 #67보다 훨씬 큰 CLI 의미론
결정이라 별도 RFC의 몫이다. 이 RFC는 그 경계를 그대로 두고, 그 경계가 이미
있다는 사실을 `cli-surface.md`에 명시하는 쪽을 택했다.

## Open Questions

1. `Refinement` 노드가 명시적 `refine X of Y` 선언에서 나올 때는 그 decl이
   `lineno`를 갖고 있다(emit-on-use로 합성될 때만 없다) — 지금은 두 경로를
   구분하지 않고 둘 다 생략한다. `_refinement_node`에 lineno를 관통시키는 것은
   이 RFC의 범위 밖으로 남겨 둔다.
2. `Policy` / `Security` / `Performance` 노드 자신에 "그 절이 시작하는 줄"
   정도의 근사값을 실을 여지는 있다(정확한 선언별 줄은 이미 진단이 갖고
   있으므로 노드 자신은 근사만 필요). 실측에서 노드 단위 위치가 요구되면
   추가한다.
