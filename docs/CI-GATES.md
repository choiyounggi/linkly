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
| `test-quality` | AI | `_ai-gate.yml`(t5) | advisory | 자기 코드를 자기가 평가하는 테스트(구현/평가 미분리), 가짜 통과 |
| `prose-factcheck` | AI | `_ai-gate.yml`(t5) | advisory | PR 산문(설명·주석)이 실제 diff와 어긋나는 주장 |

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

이 레포는 지금 시크릿이 하나도 등록돼 있지 않다(`gh secret list` → 0건). 등록
전까지 모든 AI 게이트는 `_ai-gate.yml`의 "시크릿 존재 확인" 스텝에서
`SKIPPED: ANTHROPIC_API_KEY not configured`를 찍고 실행되지 않는다.

**그때 잡이 어떻게 끝나는지가 중요하다.** 시크릿이 없다고 잡을 조용히
`success`로 끝내면, 초록불이 "AI가 보고 문제없었다"와 "AI가 아예 돌지
않았다"를 구별해 주지 못한다 — 이 배관 전체가 막으려는 공허한 통과가 배관
자신에게서 일어난다. 그래서 "시크릿 부재 처리" 스텝이 `판정 반영`의
`unavailable` 갈래와 **같은 의미론**으로 이 경우를 다룬다:

| `blocking` | 시크릿 없음 → |
|---|---|
| `false` (advisory, 현재 4종 전부) | `::warning::` 애노테이션을 남기고 잡은 초록. 애노테이션이 "이 초록은 검토하지 않았다는 뜻"이라고 화면에 적는다. 머지는 막지 않는다 |
| `true` (승격 후) | `::error::` + 잡 실패 |

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

## required status check 후보

`main`에는 지금 브랜치 보호가 걸려 있지 않다 — 즉 **어떤 게이트도 지금은
머지를 막지 못한다.** 결정론 게이트가 실패해도, AI 게이트가 blocker를 내도
PR은 머지될 수 있다. 브랜치 보호를 켜는 일 자체는 레포 소유자의 몫(범위
밖)이지만, 켤 때 required status check로 등록할 후보는 다음과 같다 —
GitHub이 실제로 만들어내는 체크런 이름 그대로다(`ci.yml`의 잡 `name:` 필드에서
직접 확인, 추측 아님):

- `gate (py3.11)` / `gate (py3.12)` / `gate (py3.13)` — 테스트 매트릭스(`ci.yml`)
- `lint (ruff)` — ruff 게이트(`ci.yml`)

RFC lint, Plugin reference drift check, Version sync check, Doc snippet
compile gate는 별도 체크런이 **아니다** — 전부 위 `gate` 잡 하나의 스텝으로
실행되므로 GitHub은 이들을 독립적으로 주소 지정 가능한 체크런으로 노출하지
않는다. 이전 버전의 이 목록은 이 스텝 이름들을 체크런 이름으로 착각해
기재했었다 — 이 표는 그 정정판이다.

`modeb-linux (test_repo_state under real mode B)`는 issue #161로 `ci.yml`에
추가됐지만 의도적으로 이 후보 목록에서 제외한다 — GitHub 호스팅 러너에서
실제로 green 실행을 관측하기 전까지는 required로 걸지 않는다
(`scripts/setup_branch_protection.sh --include-modeb`로 나중에 추가할 수 있다).

`scripts/setup_branch_protection.sh`가 위 페이로드를 적용하는 스크립트로
존재한다(멱등, `--check`는 읽기 전용). 하지만 이 스크립트는 CI나 어떤
오케스트레이션 태스크로도 자동 실행되지 않는다 — 적용은 항상 사람/코디네이터의
명시적 결정을 거친 수동 단계다.

AI 게이트 4종은 advisory인 동안은 required로 등록하지 않는다 — required
status check는 정의상 실패 시 머지를 막으므로, 오탐률이 검증되지 않은 채로
걸면 advisory 단계의 목적(수용률을 재는 동안 머지를 막지 않는 것)이 무너진다.
위 승격 절차를 거쳐 `blocking: true`로 뒤집힌 게이트만 이 목록에 추가한다.

뮤테이션 테스팅(issue #166)도 같은 이유로 이 목록에 없다 — PR용
`mutation-pr` 잡은 advisory(비-required, `continue-on-error` 없이 진짜
red/green)이고, 주간 `mutation-weekly` 잡은 SURVIVED 뮤테이션을 이슈로
리포트할 뿐 PR을 막지 않는다. 자세한 내용은 아래 "뮤테이션 테스팅 2단계"
절을 참고.

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

## `skip-ai-gate` 라벨

PR에 `skip-ai-gate` 라벨이 붙어 있으면 `_ai-gate.yml`의 잡 자체가 그 이유를
로그에 남기고 skip된다(전체 잡이 안 도는 것이지, 판정만 우회하는 것이 아니다).

사용 기준: 급히 머지해야 하는데 AI 게이트가 (모델 문제·타임아웃·명백한 오탐 등으로)
막고 있을 때만 쓴다. 결정론 게이트를 우회하는 용도가 아니다 — 이 라벨은
`_ai-gate.yml`의 잡 조건에만 걸려 있고 `ci.yml`의 결정론 게이트에는 아무
영향을 주지 않는다. 라벨을 붙인 PR은 리뷰어가 그 사유를 PR 설명이나 코멘트에
남기는 것을 권장한다(기계적으로 강제하지는 않는다).
