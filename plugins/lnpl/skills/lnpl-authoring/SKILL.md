---
name: lnpl-authoring
description: Use when writing, editing, or reviewing `.lnpl` sources for the linkly platform — entity/service/workflow declarations, guard conditions, spec blocks, refinements. LNPL uses closed vocabularies that are not in your training data; a plausible-looking file compiles and then silently does nothing. Route here before writing any `.lnpl` line.
---

# `.lnpl` 작성

LNPL은 **의도(what)를 선언**하는 언어다. 구현(how)은 컴파일러와 에이전트가 정한다.

이 언어의 어휘는 **닫혀 있고, 당신의 학습 데이터에 없다.** 그럴듯해 보이는 낱말을
쓰면 대개 파싱은 성공하고 런타임이 아무것도 하지 않는다. 그래서 추측 대신
아래 표로 라우팅한다.

## 무엇을 쓰기 전에 어디를 읽는가

| 지금 하려는 일 | 읽을 것 |
|----------------|---------|
| 워크플로 스텝을 쓴다 (`validate input`, `cache user` …) | [references/verbs.md](references/verbs.md) |
| `policy` / `security` / `performance`를 선언한다 | [references/declarations.md](references/declarations.md) |
| 필드 타입이나 `refine`을 정한다 | [references/types.md](references/types.md) |
| 블록 구조·제어 흐름·가드 스코프가 헷갈린다 | [references/grammar.md](references/grammar.md) |
| 선언 이름이 어떤 노드 id가 되는지, 스텝이 엔티티를 어떻게 가리키는지 | [references/naming.md](references/naming.md) |
| `spec` 블록으로 검증을 붙인다 | [references/spec.md](references/spec.md) |
| CLI 서브커맨드·플래그·종료 코드가 궁금하다 | [cli-surface.md](cli-surface.md) |
| 규칙이 **왜** 그런지, 또는 어휘에 없는 기능(`sum`/`count` 같은)의 **로드맵**이 궁금하다 | [references/rfcs.md](references/rfcs.md) |

## 먼저 알아야 할 세 가지 함정

**1. 사전에 없는 동사는 에러가 아니라 no-op이다.**
`return token`, `log event`, `send email` 같은 스텝은 컴파일에 성공하고 아무 효과도
내지 않는다. 동사는 반드시 `references/verbs.md`의 표에서 고른다.
이걸 spec으로 계약하는 수단이 `expect`의 `effects complete`다(저장소 변경이
있으면 `rows`도) — no-op 스텝이 하나라도 있으면 `effects complete`가 FAIL한다.
게이트 쪽은 `lnpl compile --strict=warning`이 1단계에서 막는다(issue #62,
`lnpl-verify` 스킬).

**2. 선언했다고 집행되는 게 아니다.**
`security jwt`는 토큰을 발급하지도 검증하지도 않는다. `policy rollback`은 아무것도
되돌리지 않는다. `performance response`는 측정만 하고 초과를 막지 않는다.
무엇이 실제로 실행을 바꾸는지는 `references/declarations.md`의 집행 매트릭스가 정본이다.
집행되지 않는 선언을 **의도적으로** 쓰는 것은 괜찮다 — 모른 채 쓰는 것이 문제다.

**3. `if` / `for` / `while` / `switch`는 문법적으로 표현 불가능하다.**
예약어라 렉서가 거부한다. 분기는 `when`, 반복은 `repeat` / `until`을 쓴다.

## 쓴 다음에 반드시 한다

```
lnpl compile <파일>
```

진단은 **stderr로 나가고 종료 코드는 0**이다(`--strict`를 주면 rc 2. 단 `build`에는
`--strict`가 없다). 즉 보지 않으면 사라진다. `unknown-verb`,
`declared-not-enforced`, `declared-measured-only`, `authorization-not-verified`,
`guard-skipped-steps`, `guard-orphaned-steps`, `validation-sample-derived` 중
하나라도 나오면, 그게 의도한 것인지 사용자에게 확인하고 넘어간다. 조용히
무시하지 않는다.

`guard-orphaned-steps`는 특히 조용히 넘기지 마라 — 가드는 **다음 항목 하나**만
소유하므로, 그 진단이 가리키는 스텝은 조건이 거짓이어도 실행된다(RFC-0023).

`lnpl`이 없다는 오류가 나면 `lnpl-doctor` 스킬을 쓴다.
