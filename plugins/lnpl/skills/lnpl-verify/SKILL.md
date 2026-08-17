---
name: lnpl-verify
description: Use before claiming a `.lnpl` change is done, complete, working, or ready — the completion gate for the linkly platform. Runs compile diagnostics, the spec manifest, and the mode A/B differential when the toolchain allows. Evidence before assertions.
---

# `.lnpl` 완료 게이트

"아마 될 거예요"로 끝내지 않는다. 아래를 **실행한 출력**으로 완료를 증명한다.
실행하지 않았다면 완료가 아니다.

## 1. 컴파일과 진단 — `--strict=warning` 게이트

```
lnpl compile <파일> --strict=warning
```

진단은 stderr로 나간다. `--strict=warning`은 `warning` 등급 이상(예: 미지
동사가 내는 `unknown-verb`)이 하나라도 있으면 **종료 코드를 0이 아니게
만든다** — no-op 동사 유출이 조용히 통과하지 못하게 막는 1단계 기계 게이트다
(issue #62). `info` 등급(`declared-not-enforced`, `declared-measured-only` 등
— 선언은 했으나 집행하지 않는다는 서술)은 이 게이트를 통과시킨다.

**진단 0건이 완료 조건이 아니다.** 커밋된 예제(`shorten`/`checkout`/`guarded`)는
`info` 진단을 일부러 낸다(집행되지 않는 선언을 서술로 남긴 것) — `info`는
`--strict=warning`을 통과한다. `warning` 등급이 실제로 게이트를 막는 실증은
`examples/login.lnpl`(issue #36 전용 회귀 픽스처, 절대 고치지 않는다)이
보여준다 — 어휘 밖 동사 셋이 `unknown-verb` 경고를 내고 rc≠0으로 멈춘다.
게이트를 통과시키려고 정당한 선언을 지우지 마라 — 그건 게이트가 코드를 나쁘게
만드는 것이다.

대신 각 항목마다 판정한다:

- 의도한 것이면 **왜 의도했는지 한 줄로** 말하고 넘어간다
- 의도하지 않은 것이면 고친다

어휘가 헷갈리면 `lnpl-authoring` 스킬로 간다.

## 2. spec 실행

```
lnpl spec <파일> --run
```

`spec: N passed, 0 failed`여야 한다. 하나라도 실패하면 완료가 아니다.

`spec` 블록이 아예 없다면 **그 사실을 보고한다.** 검증이 없는 것과 검증을
통과한 것은 다르다. 케이스를 선언에서 도출하는 법은 `lnpl-spec` 스킬.

## 3. mode A/B 동치 — 툴체인이 있을 때만

```
lnpl diff <파일>
```

`mlir-opt` / `mlir-translate` / `clang`이 전부 필요하다. 없는 환경이 정상이고,
그때는 이 단계를 건너뛴다 — 다만 **건너뛰었다는 사실을 보고한다.** 조용히
생략하면 돌린 것과 구별되지 않는다.

## 완료 보고에 반드시 들어갈 것

1. 각 명령의 실제 출력 (요약이 아니라 출력)
2. 남은 진단과 각각이 의도된 이유
3. 건너뛴 단계와 그 이유

셋 중 하나라도 없으면 아직 보고하지 마라.
