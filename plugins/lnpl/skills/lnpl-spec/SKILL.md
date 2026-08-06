---
name: lnpl-spec
description: Use when writing or reviewing a `spec` block in a `.lnpl` workflow for the linkly platform — derives test cases mechanically from the module's own declarations instead of guessing assertions. Covers given/when/expect and the declaration-to-expectation rules.
---

# `spec` — 선언에서 기대를 도출한다

`spec` 블록은 워크플로 안에 있고 `given` / `when` / `expect` 세 절을 갖는다.
워크플로당 블록을 여러 개 선언할 수 있고, **블록마다 독립 케이스 하나**가 된다 —
정상/에러/경계 시나리오는 블록을 나눠 싣는다 (매니페스트 케이스 이름: 블록 1개면
`<워크플로> spec`, N개면 `<워크플로> spec 1..N`). 한 블록 안에서 같은 절을 두 번
열면 파싱 에러다.
기대를 **지어내지 않는다.** 모듈이 이미 선언한 것에서 기계적으로 끌어낸다.

## 도출 규칙

정본은 구현이다 — `impl/lnpl/agents.py`의 Tester가 실제로 하는 것이 아래 표다.

| 모듈이 선언한 것 | 도출되는 기대 |
|------------------|---------------|
| (항상) | 정상 케이스 1건 — `completed`, 그리고 `steps` = 워크플로 스텝 수 |
| `performance response ...` | 정상 케이스에 `slo` 충족을 추가 |
| `performance cache ...` | 정상 케이스에 `cache` 기록을 추가 |
| `policy retry N` | 실패 케이스 1건 — `failed`, 그리고 시도 횟수 `attempts` = N + 1 |

`attempts`가 N + 1인 이유: `retry 3`은 최초 1회 + 재시도 3회 = 4회다.
N으로 쓰면 항상 어긋난다.

**표에 없는 선언에서 케이스를 만들지 마라.** 예를 들어 `policy timeout`은
여기 없다 — Tester가 데드라인 케이스를 도출하지 않기 때문이다. 표에 없는 규칙을
쓰면 러너가 평가할 수 없는 기대가 되고, spec은 실행 시점에 깨진다.

## 어휘

`expect`가 받는 키 전체와 `given`이 알아듣는 형식은 생성된 레퍼런스에 있다:
[references/spec.md](../lnpl-authoring/references/spec.md)

그 파일은 컴파일러 테이블에서 생성되므로 항상 구현과 일치한다. 여기에 옮겨 적지
않는 이유가 그것이다 — 사본은 갈라진다.

## 확인

```
lnpl spec <파일> --run
```

`spec: N passed, 0 failed`. 완료 판정 전체는 `lnpl-verify` 스킬.
