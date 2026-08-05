# lnpl-plugin — `.lnpl` 작성자를 위한 Claude Code 플러그인

Goal: linkly의 닫힌 어휘를 LLM에게 전달하는 통로를 만든다. linkly의 전제는 "언어는
LLM이 이해하기 쉽도록 설계한다"인데, **LLM은 `.lnpl`을 학습한 적이 없다**. 그래서
지금 Claude에게 `.lnpl`을 쓰게 하면 일반 프로그래밍 지식으로 그럴듯한 파일을 만들고,
그 파일은 파싱에 성공한 뒤 조용히 아무 일도 하지 않는다. 이 계획은 그 통로를
Claude Code 플러그인(스킬 + 훅)으로 세우고, 플러그인이 전역 설치돼도 동작하도록
`lnpl` CLI를 배포 가능한 패키지로 만든다.

이것은 도구 편의가 아니라 플랫폼의 빠진 절반이다 — 어휘를 모르는 생성기에게
어휘를 주지 않으면, "LLM 네이티브 언어"라는 주장이 성립하지 않는다.

수용 기준(acceptance):
1. `pip install .` 후 **linkly 레포 밖 임의 디렉터리에서** `lnpl compile <src.lnpl>`이
   동작한다. 기존 `PYTHONPATH=impl python -m lnpl` 경로도 그대로 동작한다(README:147
   무효화 금지).
2. `/plugin marketplace add choiyounggi/linkly` → `/plugin install lnpl@linkly`로
   설치되고, `.claude-plugin/marketplace.json`과 `plugins/lnpl/.claude-plugin/plugin.json`이
   각자의 스키마를 통과한다.
3. `plugins/lnpl/skills/lnpl-authoring/references/`의 모든 어휘 파일이
   `scripts/gen_plugin_references.py`의 출력과 **바이트 동일**하다. 사람이 손으로
   고치면 `impl/tests/test_plugin_references.py`가 RED가 된다.
4. `*.lnpl`을 Write/Edit한 직후 훅이 `lnpl compile`의 진단을 세션에 표면화한다.
   `examples/shorten.lnpl`을 편집하면 경고 3건(`declared-not-enforced`,
   `declared-measured-only`, `unknown-verb`)이 보인다.
5. `lnpl`이 PATH에 없는 환경에서 훅이 사용자 워크플로를 깨지 않는다(조용히 skip),
   그리고 `lnpl-doctor` 스킬이 미설치·버전 불일치를 진단한다.
6. 골든 예제 4종(`examples/*.lir.json`, `*.spec.json`, `*.openapi.json`) 무변경 —
   기계 생성물이므로 바이트 동일해야 한다.
7. 기존 테스트 전부 통과(현재 386건). RFC 본문 무변경.

Stack: Python 3.13.1(venv `.venv`), unittest, `PYTHONPATH=impl`. 패키징은 setuptools +
`pyproject.toml`. 플러그인 자산은 Markdown + JSON + POSIX `sh` 훅 — 런타임 의존
추가 없음(`jsonschema`는 기존 의존).

Baseline: HEAD `a90a8f6`, working tree clean(실측). `lnpl.__version__ == "0.2.0"`.

프로젝트 루트: `/Users/choeyeong-gi/Desktop/workspace/linkly/`. 이하 상대경로는 이
루트 기준. 워크트리에서 실행될 땐 해당 워크트리 루트를 기준으로 한다.

## 이 계획을 촉발한 실측

전부 이번 조사에서 직접 확인한 사실이다. 추정이 아니다.

| # | 사실 | 근거 |
|---|------|------|
| F1 | `VERB_LEXICON`은 동사 16개짜리 닫힌 집합이고, 밖의 동사는 **에러가 아니라 no-op**이다 | `impl/lnpl/lower.py:66`, `lower.py:610` |
| F2 | 골든 예제 자체가 그 함정을 밟고 있다 — `login.lnpl`의 `return token`은 효과 없는 스텝인데 spec은 `steps 6`으로 정상 카운트한다 | `examples/login.lnpl`, issue #36 |
| F3 | 같은 구조의 닫힌 집합이 6개 더 있다: `POLICY_NAMES`(4), `SECURITY_MECHANISMS`(3), `PERF_METRICS`(5), `SEMANTIC_TYPES`, `refinements.PRESETS`(3), `spec.EXPECTATIONS`(12) | `lower.py:90-94`, `types.py:26`, `refinements.py:60`, `spec.py:252` |
| F4 | `security jwt`·`policy rollback`은 **UNENFORCED**, `performance response`는 **MEASURED**다 — 선언해도 집행되지 않는다 | `impl/lnpl/diagnostics.py:55` ENFORCEMENT |
| F5 | `lnpl compile`은 진단을 **stderr에 쓰고 exit 0으로 끝난다**. 그래서 아무도 보지 않으면 그냥 사라진다 | `python -m lnpl compile examples/shorten.lnpl` → `exit=0`, stderr 3 warnings |
| F6 | `if / for / while / switch`는 문법적으로 표현 불가인데, 이게 LLM의 기본 반사다 | `impl/lnpl/lexer.py:13` RESERVED |
| F7 | KB는 RFC-0005 3단 progressive disclosure 라우팅으로 **LLM을 위해** 설계됐는데, Claude Code가 호출할 통로가 없다 | `kb/INDEX.md`, `cli.py:344` |
| F8 | `lnpl` CLI는 레포 밖에서 실행 불가다 — `pyproject.toml`도 `setup.py`도 없다 | `README.md:146-150`, 레포 전수 확인 |
| F9 | 레포는 tracked 2.1MB / packed 621KB로 작아서 마켓플레이스를 겸해도 클론 비용이 없다 | `git count-objects -vH` |
| F10 | `.claude/tmp`에 빌드 산출물 593개 디렉터리 / 43MB가 방치돼 있다 — `build`/`diff`의 기본 workdir다 | `du -sh .claude/tmp`, `cli.py:323,339` |

## Decisions

| # | Decision | Choice | 근거 |
|---|----------|--------|------|
| A1 | 패키징 형태 | 레포 루트에 `pyproject.toml`. setuptools + `package-dir = {"" = "impl"}`, `packages = ["lnpl"]`, `project.scripts`에 `lnpl = "lnpl.cli:main"`. `requires-python = ">=3.9"` | `impl/`이 이미 소스 루트다(F8의 `PYTHONPATH=impl`). package-dir로 그 사실을 선언하면 기존 실행 경로를 하나도 깨지 않고 콘솔 스크립트만 추가된다. `cli.main(argv=None)`이 이미 엔트리포인트 시그니처를 갖췄다(`cli.py:291`) |
| A2 | 플러그인 배치 | 레포 안. 루트에 `.claude-plugin/marketplace.json`, 플러그인 본체는 `plugins/lnpl/`, 매니페스트의 `"source": "./plugins/lnpl"` | `groundwork` 레포가 검증한 구조다. 제품 레포가 마켓플레이스를 겸하는 걸 막는 규칙은 없고, F9로 클론 비용도 없다. **무엇보다 스킬과 `lower.py`가 같은 커밋에 묶여서 어휘가 구조적으로 갈라설 수 없다** — 별도 레포였다면 동기화 장치를 따로 지어야 한다 |
| A3 | 어휘의 정본 | 정본은 **소스 코드**다. 스킬의 `references/*.md`는 `scripts/gen_plugin_references.py`가 `lower.py`·`types.py`·`diagnostics.py`·`refinements.py`·`spec.py`·`lexer.py`에서 **생성한 산출물**이고, `test_plugin_references.py`가 drift 시 실패한다 | 문서로 옮겨 적는 순간 갈라지고, 그러면 플러그인이 문제를 고치는 게 아니라 **틀린 어휘를 권위 있게 가르치는** 물건이 된다. `docs/ENFORCEMENT-MATRIX.md` + `test_enforcement_matrix.py`가 이 레포에 이미 세운 패턴을 그대로 쓴다 |
| A4 | 스킬 본문 구조 | `SKILL.md`는 **라우팅 표와 위반 시 증상만** 담고, 어휘 전체는 `references/`로 내린다. 모델은 매칭된 뒤에만 본문을 읽는다 | RFC-0005가 KB에 적용한 3단 progressive disclosure와 같은 원리다. 어휘 6종 전체를 `SKILL.md`에 넣으면 `.lnpl`을 안 쓰는 세션까지 비용을 낸다 |
| A5 | 훅이 읽는 채널 | `PostToolUse(Write\|Edit)` 훅은 `lnpl compile`의 **stderr**를 캡처해 피드백으로 승격한다. exit code로 판단하지 않는다 | F5 — 진단은 exit 0과 함께 stderr로 나간다. exit code만 보면 경고가 전부 사라진다 |
| A6 | 훅의 차단 여부 | **차단하지 않는다.** 파싱 에러조차 피드백으로만 돌려준다 | 작성 중간 상태는 정상적으로 불완전하다. Write를 막으면 편집이 불가능해진다. 판단은 모델에게 남기고 훅은 사실만 전달한다 |
| A7 | `lnpl` 부재 시 훅 동작 | PATH에 `lnpl`이 없으면 **조용히 exit 0**. 세션당 한 번만 "`lnpl-doctor`를 실행하라"는 한 줄을 남긴다 | 훅 실패가 사용자의 Write를 깨면 플러그인이 순손해가 된다. 안내는 필요하지만 매 편집마다 반복되면 소음이다 |
| A8 | MCP 서버 | **만들지 않는다.** 구조화된 출력이 필요해지면 CLI의 `--json`을 확충한다(현재 `--json`은 `run`에만 있다, `cli.py:304`). 다만 이 계획에서 실제로 필요한 건 `--version`뿐이고(A12), `kb --route/--load`의 `--json`은 그것을 소비하는 `lnpl-kb`와 함께 P1으로 간다 | MCP 툴 스키마는 세션마다 영구 컨텍스트 비용인데, CLI는 이미 에이전트 친화적이다. MCP가 줄 유일한 실이익은 구조화된 출력인데 그건 `--json`이 더 싸게 준다. 소비자가 없는 플래그를 미리 짓지 않는다 |
| A9 | RFC 필요 여부 | **불필요.** 새 의미론이 없고 기존 어휘를 반영·전달만 한다. `--json`과 `--version`은 additive한 CLI 표면 확장이다 | RFC-0001~0006은 플랫폼 **구성요소의 설계**를 정본화한다(RFC-0007 §1). 배포·도구 표면은 그 범주가 아니다. 어휘를 한 글자라도 바꾸는 변경이 생기면 그때는 해당 RFC 개정이 선행한다 |
| A10 | P0 범위 | 스킬 2종(`lnpl-authoring`, `lnpl-doctor`) + 훅 1종(compile 진단) + 패키징 + 생성/drift 테스트. 그 외 전부 P1 이하 | F1·F2·F4·F6이 지배적 실패 모드이고, 이 넷이 P0만으로 끊긴다. 나머지 스킬은 이 뼈대 위에 증분으로 얹힌다 |
| A11 | tmp 정리 훅 | P1이고 **기본 off(opt-in)**. 대상은 `.claude/tmp/lnpl-*` 접두사로 한정 | F10은 실제 문제지만, 사용자 파일이 섞일 수 있는 디렉터리를 기본 on인 훅이 지우는 건 위험 대비 이득이 나쁘다 |
| A12 | 버전 정합 확인 | `lnpl --version`을 추가하고(`lnpl.__version__` 출력), `plugin.json`의 `version`을 같은 값으로 유지한다. `lnpl-doctor`가 둘을 비교해 불일치를 보고한다 | 플러그인은 레포에 묶여 커밋 단위로 정합하지만(A2), 사용자가 설치한 `lnpl`은 다른 버전일 수 있다. drift 문제가 배포 경계에서 다시 나타나는 지점이라 여기서만 런타임 검사가 필요하다 |
| A13 | 골든 예제 취급 | `examples/*.lnpl`은 **고치지 않는다**. `login.lnpl`의 `return token`(F2)도 그대로 둔다 | 그 파일들은 issue #36/#38의 증상을 보존하는 교보재이고, 파생 산출물은 바이트 동일해야 한다(수용 기준 6). 어휘를 가르치는 것과 예제를 고치는 것은 별개의 결정이다 |

## Global Constraints

모든 태스크의 요구사항에 암묵적으로 포함된다. 태스크 파일은 이것을 반복하지 않는다.

- **Python**: `>=3.9` 선언, 개발 venv는 `.venv`(3.13.1). 테스트는
  `PYTHONPATH=impl .venv/bin/python -m unittest ...`로 돌린다.
- **런타임 의존 추가 금지.** 기존 의존은 `jsonschema` 하나뿐이다. 플러그인 자산은
  Markdown / JSON / POSIX `sh`만 쓴다.
- **문서 언어**: 본문 한국어, 식별자·키워드·스키마 필드는 영어(RFC-0007 §4).
- **골든 무변경**: `examples/*.lir.json`, `*.spec.json`, `*.openapi.json`은 바이트
  동일해야 한다. `examples/*.lnpl`도 수정 금지(A13).
- **임시 파일**: `/tmp`·`$TMPDIR` 사용 금지. 반드시 `.claude/tmp/` 아래에 만든다.
- **훅 계약(실측)**: 입력은 stdin JSON(`.tool_name`, `.tool_input.file_path`, `.cwd`),
  플러그인 경로는 `${CLAUDE_PLUGIN_ROOT}`. PostToolUse에서 **exit 0 = 조용,
  exit 2 = stderr가 모델에게 전달**. PostToolUse는 도구 실행 뒤에 돌기 때문에
  exit 2가 쓰기를 되돌리지 않는다 — A6과 정합한다.
- **버전 단일 출처**: `impl/lnpl/__init__.py`의 `__version__`(현재 `"0.2.0"`).
  `pyproject.toml`과 `plugin.json`이 이 값을 따른다(A12).

## Task order

| Task | Depends on | Parallel-ok |
|------|-----------|-------------|
| 01-packaging | — | — |
| 02-cli-version | 01 | 03과 parallel-ok |
| 03-reference-generator | — | 02와 parallel-ok |
| 04-authoring-skill | 03 | — |
| 05-diagnostics-hook | 01, 04 | 06과 parallel-ok |
| 06-doctor-skill | 01, 02 | 05와 parallel-ok |
| 07-marketplace-manifest | 04, 05, 06 | — |

P1 이후(이 계획의 범위 밖, 별도 계획으로 뽑는다): `lnpl-verify` 완료 게이트,
`lnpl-kb` 라우팅 스킬 + `kb --route/--load`의 `--json`(A8), `lnpl-spec` 작성 스킬,
tmp 정리 훅(A11).
P2: `lnpl-refine`, `lnpl-agents`.

## 범위 밖

- **어휘 확장.** `VERB_LEXICON`에 동사를 더하는 것은 issue #36의 유혹이지만 R1 계약
  위반이다(2026-08-04 결정). 이 계획은 있는 어휘를 가르칠 뿐 늘리지 않는다.
- **`examples/*.lnpl` 수정** (A13).
- **RFC 개정** (A9).
- **linkly 기여자용 도구** — RFC 번호 충돌 검사, mutation sweep 래퍼, 테스트 환경
  부트스트랩 등은 대상 사용자가 다르다. 필요하면 별도 플러그인으로 만든다.
