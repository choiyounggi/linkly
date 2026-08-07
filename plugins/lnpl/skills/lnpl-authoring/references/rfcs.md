<!-- 생성물 — 손으로 고치지 마라. 정본은 rfcs/와 이 스크립트의 RFC_ROUTES이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# RFC 포인터 — 규칙의 근거와 로드맵

> lnpl 0.3.0 기준.

`.lnpl`을 쓰다 막혔을 때 **어느 RFC를 열지**만 답하는 표다. 규칙의 정본은 이 디렉터리의 다른 참조들이고, RFC는 그 규칙이 **왜 그런지**와 **아직 없는 것의 로드맵**을 갖는다. 아직 없는 어휘를 만났을 때 (`sum`/`count` 같은) "없다"에서 멈추지 않으려면 여기를 본다.

경로는 레포 루트 기준이다.

| RFC | 이 질문이면 여기 | 경로 |
|-----|------------------|------|
| RFC-0000 RFC Process | — | `rfcs/0000-rfc-process.md` |
| RFC-0001 Semantic IR | 컴파일 산출물(IR)의 노드가 어떻게 생겼는지 읽어야 한다 | `rfcs/0001-semantic-ir.md` |
| RFC-0002 Syntax | 문법 생산규칙 전체와 문법에서 IR로 내려가는 대응이 궁금하다 | `rfcs/0002-syntax.md` |
| RFC-0003 Runtime | 실행기가 정책·동시성·관측을 어떻게 다루는지 | `rfcs/0003-runtime.md` |
| RFC-0004 Compiler | mode B(MLIR/LLVM)가 무엇을 관측하고 어디까지 내려가는지 | `rfcs/0004-compiler.md` |
| RFC-0005 Knowledge Base | kb 라우팅이 어떤 카테고리로 나뉘는지 | `rfcs/0005-knowledge-base.md` |
| RFC-0006 Agent Protocol | 에이전트 역할과 JSON-RPC 메서드 | `rfcs/0006-agent-protocol.md` |
| RFC-0007 RFC Process v2 | — | `rfcs/0007-rfc-process-v2.md` |
| RFC-0008 Guard Conditions | 가드 조건의 두 형태(존재 검사·비교)가 각각 무엇을 받는지 | `rfcs/0008-guard-conditions.md` |
| RFC-0009 Guard Condition Open Question 정리 | 가드 문법의 미결 질문이 왜 닫혔는지 | `rfcs/0009-guard-condition-open-question.md` |
| RFC-0010 Proposal Intent | 에이전트가 자기 소유가 아닌 노드를 어떻게 붙이는지 | `rfcs/0010-proposal-intent.md` |
| RFC-0011 Refinement enum 정합과 이름 충돌 | refinement 이름이 어디까지 합법이고 충돌하면 어떻게 되는지 | `rfcs/0011-refinement-enum-and-name-collisions.md` |
| RFC-0012 실행 스코프와 스텝 결과 바인딩 | 가드가 무엇을 이름 지을 수 있는지, 스텝 결과가 다음 스텝에 어떻게 바인딩되는지 — `set` 대상 규칙의 정본 | `rfcs/0012-execution-scope.md` |
| RFC-0013 Step Attempt Ceiling | retry 예산을 잃어도 왜 무한 루프가 되지 않는지 | `rfcs/0013-step-attempt-ceiling.md` |
| RFC-0014 가드 스킵의 관측 가능성 | 스킵된 스텝이 완료로 보이지 않게 하는 계약 | `rfcs/0014-guard-skip-observability.md` |
| RFC-0015 값 의미론 | 값 표현식과 산술, 그리고 집계(`sum`/`count`)가 왜 아직 없고 로드맵이 어디 있는지 — §Alternatives | `rfcs/0015-value-semantics.md` |
| RFC-0016 시간 값 의미론과 스케줄 트리거 | 기간·시각을 비교하거나 스케줄로 트리거하고 싶다 | `rfcs/0016-time-and-schedule-semantics.md` |
| RFC-0017 guarded.lnpl 예제 정정 | 동봉된 `guarded.lnpl` 예제가 왜 그렇게 고쳐졌는지 | `rfcs/0017-guarded-example-correction.md` |
| RFC-0018 반복 스텝 관측의 fold 규칙 | `repeat`/`until`의 반복이 관측에서 어떻게 접히는지 | `rfcs/0018-repeated-step-observation-fold.md` |
| RFC-0019 구조와 모순되는 들여쓰기의 거부 | 들여쓰기가 의미 없다면서 왜 어떤 들여쓰기는 거부되는지 | `rfcs/0019-misleading-indentation.md` |
| RFC-0020 spec `given`의 입력 네임스페이스 | spec의 `given`에서 입력 필드를 어떻게 지목하는지 | `rfcs/0020-spec-given-input-namespace.md` |
| RFC-0021 진단 등급과 `--strict` 문턱 | `--strict`가 무엇을 게이팅하는지, 진단 등급이 무엇인지 | `rfcs/0021-diagnostic-severity-levels.md` |
| RFC-0022 mode B의 관측 표면 | mode B가 스킵과 `--field`를 어떻게 드러내는지 | `rfcs/0022-mode-b-observation-surface.md` |

Accepted RFC는 직접 편집하지 않는다 — 개정 절차는 `rfcs/0007-rfc-process-v2.md`에 있다.
