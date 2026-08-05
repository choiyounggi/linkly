# lnpl-plugin-p1 — 작성 이후의 루프를 닫는다

Goal: P0가 `.lnpl`을 **쓰는 순간**을 다뤘다면, P1은 그 다음을 다룬다 — 쓴 것이
맞는지 확인하는 완료 게이트(`lnpl-verify`), 검증을 선언에서 기계적으로 도출하는 법
(`lnpl-spec`), 그리고 설계 결정을 추측이 아니라 KB에서 끌어오는 경로(`lnpl-kb`).

P0에서 예고했던 항목 두 개는 **실측 결과 필요 없다고 판단해 뺀다**(B4·B5). 근거는
아래 Decisions에 있다.

수용 기준(acceptance):
1. `lnpl-verify` 스킬이 존재하고, 완료 게이트 순서(compile 진단 → `spec --run` →
   툴체인이 있을 때만 `diff`)를 명시한다.
2. `lnpl-spec` 스킬이 선언→기대 도출 규칙을 담는다(`retry N` → `attempts N+1` 등).
3. `lnpl-kb` 스킬이 `lnpl kb --route` / `--load` 사용법을 담는다.
4. 세 스킬 모두 머리말 `name`이 디렉터리명과 일치하고, `description`이 트리거
   가능한 길이다.
5. `plugin.json`·`marketplace.json`·`plugins/lnpl/README.md`가 새 스킬 3종을 반영한다.
6. `claude plugin validate .`가 경고 없이 통과한다.
7. 골든 예제 무변경. 전체 스위트 무회귀.

Stack: 산출물은 Markdown뿐이다 — **CLI 변경도, 훅 추가도, 런타임 의존 추가도 없다.**
테스트는 스킬 구조 검사(unittest).

Baseline: HEAD `71116c4`, working tree clean(실측). 전체 스위트 **1094 tests, OK**.
`claude plugin validate .` 경고 0건.

Global Constraints는 [P0 계획서](../lnpl-plugin/plan.md#global-constraints)의 것을
그대로 승계한다 — python3.13, 툴체인 env, `.venv`에 `lnpl` 콘솔 스크립트,
`grep -E "^(OK|FAILED|Ran )"`로 결과 읽기, `.claude/tmp/`만 사용.

## 이 계획을 촉발한 실측

| # | 사실 | 근거 |
|---|------|------|
| G1 | mode B(`lnpl diff`)는 `mlir-opt`·`mlir-translate`·`clang`을 전부 요구한다 | `impl/lnpl/backend.py:98` `toolchain_available()` |
| G2 | `spec --run`은 사람이 읽을 요약(`spec: 4 passed, 0 failed`)과 exit code를 준다 | `lnpl spec examples/login.lnpl --run` → rc=0 |
| G3 | 골든 예제 3종이 **전부** 경고를 낸다. `shorten.lnpl`은 의도적으로 낸다 | 파일 주석이 "기계 / 서술"로 선언을 분류한다 |
| G4 | `kb --route`는 doc id를 줄바꿈으로만 내고, `kb --load`는 마크다운 본문을 낸다 | `impl/lnpl/cli.py:234-256` |
| G5 | `.claude/tmp`의 998개 중 686개가 `lnpl-g8-*`, 306개가 `lnpl-until-*` | `impl/tests/test_g8_condition_params.py:108` 등 `mkdtemp` 호출 |

## Decisions

| # | Decision | Choice | 근거 |
|---|----------|--------|------|
| B1 | `lnpl-verify`의 게이트 구성 | `lnpl compile`(진단 확인) → `lnpl spec --run`(전건 통과). `lnpl diff`는 **툴체인이 있을 때만** 돌리고, 없으면 건너뛴 사실을 보고한다 | G1 — mode B는 LLVM 툴체인을 요구하는데 `.lnpl` 작성자 대부분에게 없다. 없는 것을 게이트에 넣으면 게이트가 늘 실패하거나 늘 조용히 건너뛰어진다. 둘 다 게이트를 무의미하게 만든다 |
| B2 | 진단 0건을 **강제하지 않는다** | 진단이 있으면 "각 항목이 의도된 것인지 사용자에게 확인하고 넘어간다". 0건을 완료 조건으로 두지 않는다 | G3 — 골든 예제 셋 다 경고를 내고 `shorten.lnpl`은 일부러 낸다. 0건을 강제하면 모델이 정당한 선언(`security jwt` 같은 문서적 선언)을 지워서 게이트를 통과시키려 든다. 게이트가 코드를 나쁘게 만드는 셈이다 |
| B3 | `lnpl-spec`의 실제 내용 | 어휘 나열이 아니라 **선언 → 기대 도출 규칙**. `impl/lnpl/agents.py:588-650`의 Tester가 실제로 하는 것만 가르친다: 정상 케이스는 항상 `completed` + `steps N`, `performance response` → `slo met` 추가, `performance cache` → `cache written` 추가, `policy retry N` → 실패 케이스 `failed` + `attempts N+1` | 어휘는 이미 생성물 `references/spec.md`에 있다. 스킬이 그걸 반복하면 A3(정본은 소스)을 깨고 drift를 만든다. 더할 값은 도출 규칙이다. **단, 정본은 구현이지 `plans/agent-roles` A5가 아니다** — A5는 `timeout` → 데드라인 케이스도 열거하지만 Tester는 그것을 도출하지 않는다(실측). 구현에 없는 규칙을 가르치면 A3이 막으려던 drift를 스킬이 다시 만든다 |
| B4 | `kb --route/--load`에 `--json`을 **만들지 않는다** (P0 A8의 예고를 철회) | 스킬은 기존 텍스트 출력을 그대로 쓴다 | G4 — `route`는 doc id를 줄바꿈으로만 내고 `load`는 마크다운을 낸다. **둘 다 이미 LLM이 그대로 읽는 형식이다.** 소비자가 생겨서 필요해질 줄 알았는데, 실제 소비자를 설계해 보니 필요가 없었다. 쓰지 않을 플래그를 짓지 않는다 |
| B5 | tmp 정리 훅을 **만들지 않는다** (P0 A11의 예고를 철회) | 플러그인 범위 밖으로 뺀다 | G5 — 43MB의 정체가 사용자 산출물이 아니라 **`impl/tests`가 `mkdtemp`로 만들고 지우지 않은 테스트 잔해**였다. 이건 linkly 자체의 테스트 위생 문제이고, `.lnpl` 작성자용 플러그인이 고칠 일이 아니다. P0 계획서가 이미 "기여자용 도구는 범위 밖"이라고 못 박았다. 아래 "분리한 것"에 남긴다 |
| B6 | `references/` 재생성 없음 | 세 스킬 모두 기존 생성물 5종을 링크만 한다 | 새 어휘가 없다. 생성기를 건드리면 drift 게이트가 무의미하게 흔들린다 |
| B7 | 스킬 테스트 배치 | 세 스킬을 한 파일 `impl/tests/test_plugin_skills.py`에 모은다 | P0에서 두 워커가 같은 테스트 파일을 만지며 충돌 위험이 있었다. P1은 태스크를 2개로만 쪼개고 파일 경합을 아예 만들지 않는다 |

## Task order

| Task | Depends on | Parallel-ok |
|------|-----------|-------------|
| 01-verify-skill | — | — |
| 02-spec-and-kb-skills | 01 (같은 테스트 파일) | — |

순차다. P1은 산출물이 Markdown 3개뿐이라 병렬화 이득보다 파일 경합 위험이 크다 —
P0에서 워크트리 base가 두 번 어긋난 경험을 반영한다.

## 범위 밖 — 그러나 진짜 문제인 것

**`impl/tests`가 임시 디렉터리를 안 지운다.** `.claude/tmp`에 998개 / 43MB가 쌓여
있고 출처는 `test_g8_condition_params.py:108`(686개), `test_until*`(306개) 등의
`tempfile.mkdtemp`다. `tearDown`에서 정리하지 않는다.

이건 linkly의 테스트 위생 이슈이지 플러그인 일이 아니다. 별도 이슈/계획으로 다룬다 —
`.lnpl` 작성자용 플러그인에 청소 훅을 넣어 남의 문제를 가리지 않는다.

**기여자용 플러그인.** RFC 번호 충돌 검사, mutation sweep 래퍼, 테스트 환경
부트스트랩(툴체인 env + python3.13 + `pip install .`)은 대상 사용자가 다르다.
이번 실행에서 그 환경 계약이 반복해서 발목을 잡았으니 값은 분명하지만, 별도
플러그인이다.
