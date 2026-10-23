# CI 게이트 로스터와 운영 절차

`ci.yml`의 결정론 게이트에 AI 게이트 4종을 얹는다. 이 문서는 그 전체 로스터,
AI 게이트가 산문이 아니라 스키마 검증으로 판정되는 배관(`schemas/ai-gate-verdict.schema.json`
+ `scripts/ai_gate_verdict.py` + `.github/workflows/_ai-gate.yml`), advisory→blocking
승격 절차, 시크릿 등록 절차, required status check 후보를 고정한다.

게이트별 워크플로 파일(`ai-gates.yml`, `ai-gates-quality.yml`)과 프롬프트
(`.github/ai-gates/*.md`)는 이 문서가 아니라 그 워크플로 자체가 소유한다 — 여기서는
로스터로만 존재한다.

## 게이트 로스터

| 게이트 | 결정론/AI | 트리거 | 현재 상태 | 무엇을 잡는가 |
|--------|-----------|--------|-----------|----------------|
| 테스트 스위트(matrix) | 결정론 | `ci.yml` — `pull_request`, `push: main` | blocking | `impl/tests/` 회귀 |
| RFC lint(`rfc_lint.py`) | 결정론 | `ci.yml` | blocking | RFC-0007 §2.1·§3·§7(상태·번호·템플릿 섹션) |
| 참조 drift(`gen_plugin_references.py --check`) | 결정론 | `ci.yml` | blocking | 플러그인 스킬 참조 문서가 컴파일러 상수에서 재생성한 것과 다름 |
| 버전 동기(`check_version_sync.py`) | 결정론 | `ci.yml` | blocking | 루트 `pyproject.toml`과 플러그인 manifest 버전 드리프트 |
| ruff | 결정론 | `ci.yml`(t1) | advisory → blocking 예정 | 파이썬 린트 위반 |
| 산문 스니펫 컴파일(`check_doc_snippets.py`) | 결정론 | `ci.yml`(t2) | advisory → blocking 예정 | 문서에 박힌 `.lnpl` 스니펫이 실제로 컴파일되는지 |
| `rfc-conformance` | AI | `_ai-gate.yml`(t4) | advisory | RFC가 말하는 것과 코드가 하는 것의 불일치 |
| `golden-approval` | AI | `_ai-gate.yml`(t4) | advisory | 골든 시나리오 변경의 타당성 |
| `test-quality` | AI | `_ai-gate.yml`(t5) | blocking + required (2026-10-22 승격 — 승격 기준 예외, 아래 "advisory → blocking 승격 절차") | 자기 코드를 자기가 평가하는 테스트(구현/평가 미분리), 가짜 통과 |
| `prose-factcheck` | AI | `_ai-gate.yml`(t5) | advisory | PR 산문(설명·주석)이 실제 diff와 어긋나는 주장 |
| 릴리스 워크플로 배선(`test_release_workflow.py`의 `image`·`publish-pypi` 잡과 태그·버전 가드 단언) | 결정론 | `release.yml`(태그 push) | blocking(릴리스 전용) | `image` 잡 누락, smoke-before-push 순서, 태그 목록(`vX.Y.Z`+`X.Y`, `latest` 없음), `run:` 블록의 `github.` 식 금지, `permissions` 범위, `publish-pypi` 배선 회귀(`environment: pypi`, `id-token: write` 단독 권한, `needs: [build, release]`, `if: false` 부활, `skip-existing` 추가, 액션 SHA 핀), `gates`의 태그·`pyproject.toml` 버전 불일치 미검출 |
| 요청당 결정적 카운터(`test_perf_counters.py`) | 결정론 | `ci.yml` — 테스트 스위트(matrix) 잡 안의 한 모듈 | blocking(`gate` 잡 경유) | 요청 1건당 DB 연결 생성·닫힘 수, 저장소 문장 수, 드라이버 생성 수의 회귀(예: 요청마다 연결을 하나 더 여는 변경) |
| 주간 부하 리포트(`load-weekly.yml`) | 결정론 | `load-weekly.yml` — `schedule`(월요일 07:00 UTC) + `workflow_dispatch` | report-only(비-required) | 절대 처리량·지연 추이(gunicorn sync 워커 2개, fake·sqlite 백엔드, 50/100/200/400 rps). 판정으로 쓰지 않는다 |

AI 게이트 4종의 체크 이름은 `rfc-conformance / gate`, `golden-approval / gate`,
`test-quality / gate`, `prose-factcheck / gate`이다(generic-http 호출부는
`<잡>-generic-http / gate`) — 재사용 잡에 `name:`이 없기 때문이고, 잡 수준 `if:`로
skip된 잡은 `name:` 식을 평가하지 않은 채 보고된다(2026-10-22 공개 레포 4곳
실측: facebook/rocksdb, qualcomm-linux/meta-qcom, shakfu/inferna,
zeta-chain/node. GitHub 문서에는 없는 동작이다).

AI 게이트 4종은 전부 이 문서가 만든 재사용 워크플로 `_ai-gate.yml`(`on:
workflow_call`) 위에 얹힌다. 게이트별 워크플로는 `gate_name`·`prompt_file`만
넘기면 되고, 판정 자체(스키마 검증·exit code)는 전부 여기서 공유한다 — 산문이
exit code를 정하지 못하게 하는 것이 이 배관의 핵심 가치다.

## AI 게이트가 판정되는 방식

1. `_ai-gate.yml`이 `anthropics/claude-code-action`을 커밋 SHA로 고정해 부른다
   (`claude_args`에 `--json-schema schemas/ai-gate-verdict.schema.json`).
   에이전트는 그 스키마에 맞는 JSON만 `structured_output`으로 낸다.
2. `scripts/ai_gate_verdict.py`가 그 JSON을 검증해 exit code를 정한다 — 에이전트가
   뭐라고 썼든 이 스크립트만이 통과/실패를 가른다.

| exit code | 의미 |
|-----------|------|
| 0 | 통과 |
| 1 | 위반(`verdict=fail` 또는 `severity=blocker` finding 1건 이상) |
| 2 | 형식 오류(입력 없음/빈 파일/JSON 아님, 스키마 위반, `gate` 필드 불일치) |
| 3 | 공허한 통과(`--expect-nonempty`인데 `verdict=pass`이면서 `examined.files`가 비어 있음 — 아무것도 안 봤는데 통과) |

2와 3을 1과 구분하는 이유: "게이트가 고장남"과 "코드가 나쁨"을 섞으면 재현이 안 된다.

위 표는 `scripts/ai_gate_verdict.py`가 실제로 실행됐을 때의 exit code다. `_ai-gate.yml`은
그 앞에 한 가지 상태를 더 구분한다: **게이트 실행 실패**(claude 스텝이 non-zero로
끝났거나 `structured_output`이 비어 있음 — Anthropic API 5xx/rate-limit 같은 일시
장애가 전형적인 원인). 이때는 판정 스크립트를 아예 부르지 않는다 — 빈 입력을 넘기면
exit 2(형식 오류)가 되어 "게이트 정의 결함"과 "게이트가 실행조차 못함"이 뒤섞이기
때문이다. 원인이 일시적이면 **PR을 다시 열 필요 없이 워크플로만 재실행(re-run)하면
된다** — diff나 게이트 정의를 고칠 문제가 아니다.

`_ai-gate.yml`은 `runner` 입력으로 실행기를 고른다: `claude-code`(기본, 위의 기존
경로)와 `generic-http`(OpenAI 호환 `/chat/completions` 엔드포인트,
`scripts/ai_gate_http_runner.py`). 두 러너는 같은 판정 파일을 쓰고,
`scripts/ai_gate_verdict.py`가 같은 스키마·같은 exit code로 그 파일을 검사한다.
generic-http의 실패(비-2xx 응답, 잘린 출력, 비었거나 JSON이 아닌 content)는 Claude Code
액션의 실패와 같은 **게이트 실행 실패**(`unavailable`) 갈래로 떨어진다.

## advisory → blocking 승격 절차

AI 게이트 4종은 전부 **advisory**로 시작한다(`_ai-gate.yml`의 `blocking` 입력
기본값 `false`). advisory는 **exit 1(verdict=fail 또는 blocker finding)과
게이트 실행 실패에만** 적용된다 — PR 코멘트로 결과는 남지만(또는 실행 실패
로그만 남고) 머지를 막지 않는다. exit 2(형식 오류)·exit 3(공허한 통과)는
`blocking` 값과 무관하게 **항상** 잡을 실패시킨다. "코드가 나쁨"(1)과
"게이트 자체가 고장남"(2·3)을 advisory가 같이 삼키면, 고장난 게이트가 오탐
0건의 가장 깨끗한 게이트로 보여 아래 승격 절차 자체를 속인다.

승격 기준: 약 **50 PR 분량**을 advisory로 운용해 리뷰어의 수용률을 재고,
**수용률 80% 이상(오탐률 10% 미만)**이면 그 게이트 하나를 `blocking: true`로
뒤집는다. 게이트마다 독립적으로 판단한다 — 4종을 한꺼번에 승격하지 않는다.

- 수용률 측정: 게이트가 낸 `blocker` finding 중 리뷰어가 실제로 반영(코드
  수정 또는 PR 코멘트에서 인정)한 비율. `use_sticky_comment`로 남는 코멘트
  이력이 그 근거다.
- 승격은 해당 게이트를 부르는 워크플로 파일(`ai-gates.yml`/`ai-gates-quality.yml`,
  t4·t5 소유)의 `blocking: true` 한 줄을 뒤집는 일이다 — 이 재사용 워크플로
  자체는 건드리지 않는다.
- 근거 출처: 이 임계(80%/10%, 50 PR)는 이 프로젝트의 관측치가 아니라 advisory
  → blocking 단계적 승격이라는 조사된 정설을 적용한 것이다. 실제 50 PR을
  채운 뒤 이 문서의 표를 이 레포의 실측 수용률로 갱신한다.

### test-quality 승격 — 기준 예외 (issue #244)

`test-quality`(claude-code 호출부 잡 하나)는 2026-10-22에 위 기준을 채우기
**전에** `blocking: true`로 올랐다. 기준(약 50 PR, 수용률 80%)은 충족되지
않았다. 근거가 되는 실측(2026-10-22, main `315d410`):

| 사실 | 측정 명령 |
|------|-----------|
| `ai-gates-quality.yml` 실행 33건, 브랜치 16개, 2026-08-31 이후 전부 `success` | `gh run list --repo choiyounggi/linkly --workflow ai-gates-quality.yml --limit 200 --json conclusion,headBranch,createdAt` |
| 2026-10-01 이후 실행 20건의 `test-quality` 잡 20건이 모두 시크릿이 있는 상태로 돌아 `success` | 각 실행에 `gh run view <id> --repo choiyounggi/linkly --json jobs` — "시크릿 부재 처리" 스텝이 `skipped`, 잡이 `success` |
| 같은 20건의 로그에 "게이트 통과(exit 0)"가 20건, `##[warning]`·`##[error]` 애노테이션이 0건 — 러너 실패 0건, `unavailable` 0건, blocker finding 0건, 머지를 막았을 판정 0건 | 각 실행에 `gh run view <id> --repo choiyounggi/linkly --log`, `test-quality` 잡의 줄(옛 이름 기준 접두사)만 센다 |
| 최근 PR #221·#259의 코멘트 0건, 리뷰 0건 | `gh pr view <n> --repo choiyounggi/linkly --json comments,reviews` |

수용률은 **잴 수 없다** — blocker finding이 0건이라 분모가 없고 sticky 코멘트도
남지 않았다. 즉 이 승격은 "수용률 80%를 확인했다"가 아니라 "러너 실패 없이
돌았고 오탐 신호도 없었다"에 기댄 예외다. 지금 승격하는 이유: #244에서 사용자가
정했다 — 협업자가 1명이라 사람 리뷰를 요구할 수 없으므로(아래 "왜 required
approvals를 걸지 않는가") AI 게이트 하나가 두 번째 리뷰어 자리를 대신한다.
하나만 고른 이유는 네 게이트 중 `test-quality`가 모든 PR에서 돌고(`paths`
필터 없음) 러너 실패 이력이 없기 때문이다. 나머지 셋은 advisory로 남는다.

게이트가 판정하지 못하는 경우는 전부 잡 실패다(blocking일 때):

1. 시크릿 부재 — "시크릿 부재 처리"가 `::error::` + 실패.
2. 게이트 실행 실패 — "판정 반영"의 `unavailable` 갈래(Claude 스텝 실패 또는 빈 출력).
3. 변경 파일 0건 — 삭제만 있는 PR이거나 빈 diff. "변경 파일 없음 처리"가 실패시킨다
   (advisory이면 경고만). 삭제만 있는 PR은 아래 `skip-ai-gate` 라벨로 우회한다.
4. 판정 스크립트 exit 2(형식 오류)·exit 3(공허한 통과) — `blocking`과 무관하게 항상 실패.

탈출구는 `skip-ai-gate` 라벨이다(아래 절). 이 예외는 기준을 채운 뒤 이 절을
실측 수용률로 갱신해 닫는다.

## `ANTHROPIC_API_KEY` 등록 절차와 OIDC 대안

### 자격증명은 셋 중 하나 — API 키 / OAuth 토큰 / OIDC 페더레이션

`_ai-gate.yml`은 `anthropic_api_key`와 `claude_code_oauth_token`을 **둘 다**
선언하고, 둘 중 **하나만 있으면** 게이트가 돈다. "시크릿 존재 확인" 스텝이
둘 다 비었을 때만 skip으로 판정하고, 어느 쪽으로 인증했는지 로그에 찍는다.

| 방식 | 등록할 시크릿 이름 | 성격 |
|---|---|---|
| API 키 | `ANTHROPIC_API_KEY` | console.anthropic.com에서 발급. 사용량 과금 |
| OAuth 토큰 | `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token`으로 발급. 구독에 묶인다 |
| OIDC 페더레이션 | (정적 시크릿 없음) | 아래 절 참고. 저장되는 자격증명이 없어 가장 안전 |

둘 다 등록돼 있으면 API 키가 우선한다.

**이름을 바꿔 달면 안 된다.** OAuth 토큰을 `ANTHROPIC_API_KEY`라는 이름으로
등록하면 액션이 그 값을 `ANTHROPIC_API_KEY` 환경변수로 넘기는데, OAuth
토큰은 `CLAUDE_CODE_OAUTH_TOKEN`으로 가야 하므로 인증이 실패한다.

### API 키를 리포지토리 시크릿으로 등록

이 레포에는 `CLAUDE_CODE_OAUTH_TOKEN`이 등록돼 있다(`gh secret list`, 2026-10-22).
시크릿이 없을 때 AI 게이트는 `_ai-gate.yml`의 "시크릿 존재 확인" 스텝에서
`SKIPPED: neither ANTHROPIC_API_KEY nor CLAUDE_CODE_OAUTH_TOKEN is configured`를 찍고
실행되지 않는다.

**그때 잡이 어떻게 끝나는지가 중요하다.** 시크릿이 없다고 잡을 조용히
`success`로 끝내면, 초록불이 "AI가 보고 문제없었다"와 "AI가 아예 돌지
않았다"를 구별해 주지 못한다 — 이 배관 전체가 막으려는 공허한 통과가 배관
자신에게서 일어난다. 그래서 "시크릿 부재 처리" 스텝이 `판정 반영`의
`unavailable` 갈래와 **같은 의미론**으로 이 경우를 다룬다:

| `blocking` | 시크릿 없음 → |
|---|---|
| `false` (advisory — test-quality 외 3종) | `::warning::` 애노테이션을 남기고 잡은 초록. 애노테이션이 "이 초록은 검토하지 않았다는 뜻"이라고 화면에 적는다. 머지는 막지 않는다 |
| `true` (blocking — 현재 test-quality) | `::error::` + 잡 실패 |

게이트가 판정하지 못하는 다른 두 경우도 같은 결과가 된다: 러너 실패 또는 빈 출력
("판정 반영"의 `unavailable` 갈래)과 변경 파일 0건("변경 파일 없음 처리" —
삭제만 있는 PR이거나 빈 diff; 삭제만 있는 PR은 `skip-ai-gate` 라벨로 간다).
advisory면 경고 + 초록, blocking이면 에러 + 실패다.

두 번째 줄이 승격 절차의 구멍을 막는다. 게이트를 `blocking: true`로 올려
required status check에 등록한 뒤 시크릿이 만료·회전·개명되면, 이 갈래가
없을 때 그 required check는 **영원히 조용히 통과한다** — 아무도 보지 않는
게이트가 머지를 승인해 주는 상태가 된다.

등록 절차(레포 소유자만 가능 — 범위 밖):

1. GitHub 리포지토리 Settings → Secrets and variables → Actions.
2. `New repository secret` → 이름 `ANTHROPIC_API_KEY` → Anthropic API 키 값 입력.
3. 각 게이트 워크플로(t4·t5 소유)에서 `_ai-gate.yml`을
   `secrets: anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}`로 호출하는지 확인.

### 권장 대안: GitHub OIDC 워크로드 아이덴티티 페더레이션

정적 키 대신, Anthropic 조직이 GitHub Actions를 신뢰 발급자로 등록하면 잡이
매 실행마다 GitHub의 OIDC 토큰을 짧은 수명의 Anthropic 토큰으로 교환한다 —
저장된 장기 키가 없으니 유출·로테이션 대상 자체가 사라진다. `claude-code-action`은
`anthropic_federation_rule_id` + `anthropic_organization_id` 입력으로 이 경로를
지원한다(`anthropic_service_account_id`/`anthropic_workspace_id`는 선택).

전제조건은 Anthropic 콘솔 쪽 조직 설정(federation rule 발급)이 선행되어야
한다는 것 — 이 레포의 워크플로만으로는 켤 수 없다(범위 밖). 그 설정이 끝나면
`_ai-gate.yml`의 "Claude Code 게이트 실행" 스텝에 남긴 주석대로 `anthropic_api_key`
줄을 지우고 `anthropic_federation_rule_id`/`anthropic_organization_id` 두 줄로
바꾸고, 잡의 `permissions`에 `id-token: write`를 추가한다.

### generic-http 러너(OpenAI 호환 엔드포인트) 등록

`rfc-conformance-generic-http`, `golden-approval-generic-http`, `test-quality-generic-http`,
`prose-factcheck-generic-http` 네 잡이 같은 PR에서 claude-code 잡 옆에 advisory로 돌되,
리포지토리 변수 `AI_GATE_HTTP_BASE_URL`이 등록돼 있을 때만 돈다. 그 전에는 `Skipped`
체크로 보이고, 기존 네 잡은 이전과 똑같이 동작한다.

```
gh secret set AI_GATE_HTTP_API_KEY
gh variable set AI_GATE_HTTP_BASE_URL --body "https://api.example.com/v1"
gh variable set AI_GATE_HTTP_MODEL --body "<model-id>"
gh variable set AI_GATE_HTTP_API_STYLE --body "classic"   # 선택
```

- `AI_GATE_HTTP_BASE_URL`은 `/chat/completions` 앞까지의 접두이고 `/v1`을 포함한다.
  러너가 `/chat/completions`를 직접 붙인다.
- `AI_GATE_HTTP_API_STYLE`:
  - 비우거나 `classic`이면 `max_tokens`(16384)와 `temperature: 0`을 보낸다. OpenAI
    gpt-4o·gpt-4.1 모델과 자체 호스팅 vLLM·llama.cpp·Ollama 서버에 맞는다.
  - `reasoning`이면 `max_completion_tokens`(32768)를 보내고 temperature를 보내지 않는다.
    OpenAI o-series·gpt-5 모델용이다 — 이 모델들은 `max_tokens`와 기본값이 아닌
    temperature를 HTTP 400으로 거부한다.
- 변수는 있는데 시크릿이 없으면, Anthropic 경우와 같은 `시크릿 부재 처리` 규칙으로
  skip한다(advisory: `::warning::`을 남기고 초록, blocking: 빨강).
- 크기 예산: diff는 200000바이트에서 잘리고 `[diff truncated at 200000 bytes]` 줄이 눈에
  보이게 붙는다. 대상 모델의 컨텍스트 창은 128k 토큰 이상이어야 한다. 창이 더 작으면
  `error: http 400`으로 실패하고 `unavailable`로 보인다.
- 키 노출:
  - 평문 `http://` base URL은 키를 암호화 없이 보낸다. 엔드포인트가 신뢰된 사설망에
    있지 않다면 `https://`를 쓴다. 리다이렉트는 따라가지 않으므로(3xx는 이름 붙은
    실패다) 키가 다른 호스트로 넘어가지 않는다.
  - 잡은 PR 쪽의 `scripts/ai_gate_http_runner.py` 사본을 키와 함께 돌린다. 이것은 새
    노출을 만들지 않는다: 포크 PR은 이 잡에 닿지 않고(포크 차단), 같은 레포에 쓸 수
    있는 사람은 이미 워크플로 자체를 고칠 수 있다.

## required status check 후보

`main`의 브랜치 보호는 2026-10-23 현재 이렇다(`gh api
repos/choiyounggi/linkly/branches/main/protection`): required status check 6개
(`gate (py3.11)`, `gate (py3.12)`, `gate (py3.13)`, `lint (ruff)`,
`modeb-linux (test_repo_state under real mode B)`, `test-quality / gate`), `strict` 켜짐,
`enforce_admins: true`, force push·삭제 차단, `required_pull_request_reviews` 없음,
`required_conversation_resolution: true`, linear history·block creations·lock·fork
syncing는 꺼짐. 즉 결정론 게이트와 AI 게이트 `test-quality`가 실패하면 머지가 막히고,
풀리지 않은 리뷰 대화가 남아 있어도 막힌다. 나머지 AI 게이트 셋은 머지를 막지 않는다.
required status check로 등록할 후보는 다음과 같다 — GitHub이 실제로 만들어내는
체크런 이름 그대로다(`ci.yml`의 잡 `name:` 필드에서 직접 확인, 추측 아님. AI 게이트의
이름은 `_ai-gate.yml`의 잡에 `name:`이 없어서 `<호출 잡> / gate`다):

- `gate (py3.11)` / `gate (py3.12)` / `gate (py3.13)` — 테스트 매트릭스(`ci.yml`)
- `lint (ruff)` — ruff 게이트(`ci.yml`)
- `modeb-linux (test_repo_state under real mode B)` — 실제 mode B 게이트(`ci.yml`)
- `test-quality / gate` — 승격된 AI 게이트 하나(`ai-gates-quality.yml`의 `test-quality`
  호출 잡 + `_ai-gate.yml`의 잡 id `gate`)

RFC lint, Plugin reference drift check, Version sync check, Doc snippet
compile gate는 별도 체크런이 **아니다** — 전부 위 `gate` 잡 하나의 스텝으로
실행되므로 GitHub은 이들을 독립적으로 주소 지정 가능한 체크런으로 노출하지
않는다. 이전 버전의 이 목록은 이 스텝 이름들을 체크런 이름으로 착각해
기재했었다 — 이 표는 그 정정판이다.

`modeb-linux (test_repo_state under real mode B)`는 issue #161로 `ci.yml`에
추가됐다. GitHub 호스팅 러너에서 green 실행이 관측됐고
(`gh api repos/choiyounggi/linkly/commits/315d410/check-runs`, 2026-10-22: `success`)
라이브 보호에도 이미 required로 걸려 있으므로 기본 목록에 들어 있다.
`--include-modeb`는 옛 런북이 깨지지 않도록 남겨 뒀을 뿐 아무것도 바꾸지 않는다.

`scripts/setup_branch_protection.sh`가 원하는 페이로드를 가진 스크립트로
존재한다(멱등). 페이로드는 위 라이브 설정에 `test-quality / gate`와
`required_conversation_resolution: true`를 더한 것이고, `required_linear_history`,
`block_creations`, `lock_branch`, `allow_fork_syncing`은 기본값(false)을 명시적으로
적는다. `--check`는 읽기 전용이다: 페이로드를 출력하고, 라이브 main 보호 설정을 GET
한 번으로 읽어 항목마다 `ok:`/`drift:` 줄과 `summary:` 줄을 낸다. 2026-10-23 적용
뒤로 기대하는 결과는 `summary: 0 drift, 17 ok`다. 이 스크립트는
CI나 어떤 오케스트레이션 태스크로도 자동 실행되지 않는다 — 적용은 항상
사람/코디네이터의 명시적 결정을 거친 수동 단계이며, `--check` 뒤에, 그리고
이 변경을 실은 PR의 head에서 `test-quality / gate` 체크런이 실제로 관측된 뒤에만
한다. 변경 전에 만들어진 브랜치의 PR은 옛 체크 이름을 보고하므로, 새 required
check를 만족하려면 main을 머지해야 한다.

AI 게이트 4종 중 `test-quality`만 `blocking: true`이고 위 목록에
`test-quality / gate`로 올라 있다. 나머지 셋(`rfc-conformance`, `golden-approval`,
`prose-factcheck`)은 advisory인 동안 required로 등록하지 않는다 — required
status check는 정의상 실패 시 머지를 막으므로, 오탐률이 검증되지 않은 채로
걸면 advisory 단계의 목적(수용률을 재는 동안 머지를 막지 않는 것)이 무너진다.
위 승격 절차를 거쳐 `blocking: true`로 뒤집힌 게이트만 이 목록에 추가한다.

뮤테이션 테스팅(issue #166)도 같은 이유로 이 목록에 없다 — PR용
`mutation-pr` 잡은 advisory(비-required, `continue-on-error` 없이 진짜
red/green)이고, 주간 `mutation-weekly` 잡은 SURVIVED 뮤테이션을 이슈로
리포트할 뿐 PR을 막지 않는다. 자세한 내용은 아래 "뮤테이션 테스팅 2단계"
절을 참고.

주간 부하 리포트(`load-weekly`, issue #195)도 이 목록에 없다 — 절대 수치는
러너마다 달라 PR 판정에 쓸 수 없고, 이 잡은 `pull_request`로 깨어나지도
않는다. 성능 회귀의 PR 차단은 `gate` 잡 안의 결정적 카운터 테스트가 맡는다
(아래 "성능 회귀 — 결정적 카운터와 주간 부하 리포트" 절).

### 왜 required approvals를 걸지 않는가

협업자가 1명이고(`gh api repos/choiyounggi/linkly/collaborators --jq length` → 1,
2026-10-22) `enforce_admins: true`이며, PR 작성자는 자기 PR을 승인할 수 없다
([GitHub 문서](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-pull-request-reviews-before-merging)).
그래서 `required_approving_review_count: 1`을 걸면 모든 머지가 막힌다 — 관리자도
예외가 아니다. 대신 두 가지를 둔다: 대화 해결 필수(`required_conversation_resolution`)와
`test-quality / gate` required check. 이것은 사람 리뷰를 대체하지 못한다 —
OpenSSF Scorecard의 `Code-Review` 체크는 이 대안 아래에서 **충족되지 않는다**
([Scorecard checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md):
"Review by bots, including bots powered by artificial intelligence / machine learning
(AI/ML), do not count as code review"). Scorecard도 활동 참여자가 1명이면 리뷰를
요구하는 것이 불가능하다고 적는다. 두 번째 협업자가 생기면 다시 본다.

## 뮤테이션 테스팅 2단계

`impl/tests/mutation_check.py`(77개 뮤테이션 + no-op 컨트롤, 전체 실행
25분+)는 그대로 두고(의미론 변경 없음, issue #166 범위 밖), `.github/workflows/mutation.yml`이
이를 두 갈래로 감싼다:

- **`mutation-pr`**(PR 트리거, advisory, 비-required): `scripts/mutation_scope_select.py`가
  `mutation_check.MUTATIONS`를 PR의 변경 파일과 앵커 파일이 교차하는 항목만
  남기도록 필터링한 뒤 하네스의 원본 `main()`을 그대로 호출한다.
  `mutation_check.py` 자체는 한 줄도 고치지 않는다. 이 잡은 `continue-on-error`를
  쓰지 않는다 — 실패하면 진짜 red로 보이지만, required 목록에 없으므로 PR
  머지를 막지는 않는다(위 절 참고).
- **`mutation-weekly`**(주간 cron, 전체 77종 + no-op 컨트롤): 하네스의 rc를
  캡처한 뒤 `scripts/mutation_report.py`로 stdout을 파싱한다. SURVIVED
  뮤테이션(테스트가 없는 규칙)만 GitHub 이슈로 리포트한다 — 이건 실패가
  아니라 "미검증 규칙" 알림이다. 반대로 STALE(앵커 문자열이 소스와 어긋남),
  HANG(타임아웃), 또는 no-op 컨트롤이 걸려서 생기는 설명되지 않은 nonzero rc는
  하네스 자체가 판정 불능이라는 뜻이므로 **fail closed**로 잡을 실패시키고
  이슈 업데이트를 건너뛴다.

두 잡 모두 issue #161의 `modeb-linux` 잡이 쓰는 apt.llvm.org 고정 LLVM/MLIR
툴체인 설치 시퀀스를 그대로 재사용한다(`mlir/llvm.pin`에서 버전 파생,
`LNPL_LLVM_BIN` export). `ci.yml`은 수정하지 않는다 — 별도 워크플로 파일이다.

뮤테이션 스코어 임계치 게이트(예: "80% 이상 캐치해야 통과")는 이 issue의
명시적 비목표다 — SURVIVED는 항상 리포트일 뿐 실패 조건이 아니다.

## 성능 회귀 — 결정적 카운터와 주간 부하 리포트 (issue #195)

처리량·지연의 절대 수치는 같은 코드라도 러너의 CPU·이웃 잡에 따라 달라진다.
그런 수치로 PR을 막으면 코드와 무관한 실패가 생기므로, PR 차단 게이트는
실행마다 똑같이 나오는 **결정적 카운터**만 단언한다:

- `impl/tests/test_perf_counters.py`가 요청 1건이 하는 일을 센다 — DB 연결
  생성 수(`sqlite3.connect`), 연결 닫힘 수, 저장소 문장 수(`execute`),
  드라이버 생성 수(`repository_factory` 호출). sqlite 경로·fake 경로·
  `build_app()` 경로에서 정확한 값(`== 1` 등)으로 단언하고, 저장소에 닿지
  않은 요청(0)도 실패로 잡는다. 일반 unittest 스위트의 한 모듈이므로
  `ci.yml`의 `gate` 잡이 그대로 실행한다(네트워크·도커 없음).
- 같은 파일의 `DegradedDoubleControlTest`가 문장마다 연결을 하나 더 여는
  드라이버(`_ConnectPerCallDriver`)로 카운터가 실제로 회귀를 본다는 것을
  매 실행 증명한다. 그 드라이버를 게이트 테스트에 넣으면 세 테스트가
  `1 != 3`/`1 != 2`로 실패한다.

절대 수치는 `.github/workflows/load-weekly.yml`이 주 1회(월요일 07:00 UTC,
수동 `workflow_dispatch`도 가능) 리포트만 남긴다: gunicorn sync 워커 2개로
fake·sqlite 백엔드를 50/100/200/400 rps로 잰 `scripts/load_probe.py`의 출력
(판정 줄 `verdict=` 포함)을 잡 요약과 아티팩트(`load-weekly-report`, 90일
보관)에 올린다. 측정값이 어떻든 잡은 실패하지 않는다. 서버가 뜨지 않는
경우만 하네스 결함으로 잡을 실패시킨다 — "측정 결과"가 아니라 "측정 불능"
이기 때문이다. 로컬 한 대에서 잰 상한표는 `docs/gunicorn-load-measurement.md`
에 있다.

## `skip-ai-gate` 라벨

PR에 `skip-ai-gate` 라벨이 붙어 있으면 `_ai-gate.yml`의 잡 자체가 `if:`로 skip된다
(전체 잡이 안 도는 것이지, 판정만 우회하는 것이 아니다). `if:`로 skip된 잡은 스텝을
하나도 실행하지 않으므로 로그에 이유를 남기지 않는다 — 이유는 PR 본문에 적는다.

이 라벨은 required check `test-quality / gate`의 **의도된 탈출구**다. 잡이 skip되면
체크런 `test-quality / gate`는 `skipped`로 끝나고, GitHub은 `skipped`를 required status
check를 만족한 것으로 센다("Required status checks must have a successful, skipped, or
neutral status" —
[About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches),
2026-10-22 확인). 재사용 잡에 `name:`이 없어서 skip돼도 같은 이름으로 보고된다는 점은
GitHub 문서에 없고 공개 레포 4곳의 실측이다(위 로스터 아래 설명) — 보호를 적용한 뒤
라벨을 붙인 PR 하나로 실제 이름을 확인한다.

- **라벨은 실행을 시작시키지 않는다.** `pull_request`의 기본 activity type은
  `opened`/`synchronize`/`reopened`다
  ([문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)).
  라벨을 붙인 뒤에 커밋을 하나 push하거나 PR을 닫았다 다시 열어야(reopen) 워크플로가
  새로 돌아 `skipped`가 보고된다.
- **삭제만 있는 PR**(변경 파일 0건)은 blocking 게이트가 판정할 수 없어 실패한다
  ("변경 파일 없음 처리"). 이 라벨로 간다.
- **라벨은 아직 레포에 없다.** 보호를 적용하기 전에 코디네이터가
  `gh label create skip-ai-gate --repo choiyounggi/linkly`로 만든다.
- **포크 PR**은 잡의 `if:`(`head.repo.full_name == github.repository`)에 걸려 skip된다.
  같은 경로로 required check를 통과한다(AI 리뷰 없음) — 포크 PR은 사람이 읽고 머지한다.

사용 기준: 급히 머지해야 하는데 AI 게이트가 (모델 문제·타임아웃·명백한 오탐 등으로)
막고 있을 때, 또는 삭제만 있는 PR일 때만 쓴다. 결정론 게이트를 우회하는 용도가
아니다 — 이 라벨은 `_ai-gate.yml`의 잡 조건에만 걸려 있고 `ci.yml`의 결정론 게이트에는
아무 영향을 주지 않는다. 라벨을 붙인 PR은 그 사유를 PR 본문에 적는다(기계적으로
강제하지는 않는다).
