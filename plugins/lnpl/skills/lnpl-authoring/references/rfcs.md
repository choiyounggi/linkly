<!-- 생성물 — 손으로 고치지 마라. 정본은 rfcs/와 이 스크립트의 RFC_ROUTES이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# RFC 포인터 — 규칙의 근거와 로드맵

> lnpl 0.5.0 기준.

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
| RFC-0023 가드 밖으로 새어 나간 상태 변경의 컴파일 타임 진단 | 가드 뒤의 스텝이 왜 가드 밖인지, 그리고 컴파일러가 그걸 언제 경고하는지 | `rfcs/0023-guard-scope-diagnostic.md` |
| RFC-0024 집행 진단에 소스 line 병기 | 집행 진단이 노드 id에 더해 소스 line을 왜, 어떻게 싣는지 — `lnpl compile`과 `lnpl run`이 나눠 가진 진단 범위도 함께 | `rfcs/0024-enforcement-diagnostic-line.md` |
| RFC-0025 행 집합(Row Set)과 집계 | `list`로 엔티티의 전 행을 읽고 `sum`/`count`로 집계하고 싶다 — RowSet이 단일 행 바인딩과 왜 별개 이름공간인지, mode B가 왜 집계 값을 전혀 계산하지 않는지 | `rfcs/0025-row-sets-and-aggregation.md` |
| RFC-0026 `unknown-verb`/`guard-orphaned-steps`/`guard-skipped-steps`의 `line`과 `suggestion` | `unknown-verb`/`guard-orphaned-steps`가 왜 구조화 `line`을 갖는지, did-you-mean 제안이 별칭과 철자 오타를 어떻게 나눠 잡는지 | `rfcs/0026-unknown-verb-line-and-suggestion.md` |
| RFC-0027 네트워크 드라이버와 결과 바인딩 | `call`/`request ... as <name>`로 네트워크 응답을 바인딩하고 실패를 status 값으로 분기하고 싶다 — `--network`의 fake/http 선택이 무엇을 고르는지, 접속 실패가 왜 예외가 아니라 값인지 | `rfcs/0027-network-driver-and-result-binding.md` |
| RFC-0028 산술 연산자 확장과 대안 가드 | `*`/`/`를 쓰고 싶다, 또는 `when A` / `or B`로 대안 가드를 쓰고 싶다 — 0 나눗셈이 왜 컴파일 에러가 아니라 RunError인지, mode B가 왜 그 실패에 합의할 의무가 없는지 | `rfcs/0028-arithmetic-and-alternative-guards.md` |
| RFC-0029 Clock 계약과 `--clock real` 바인딩 | `CacheAccess` TTL을 벽시계 경과에 묶고 싶다 — `--clock real`이 무엇을 바꾸고 무엇을 바꾸지 않는지, `diff`/`spec`이 왜 이 선택자를 받지 않는지 | `rfcs/0029-clock-contract-and-real-binding.md` |
| RFC-0030 `create` 결과 바인딩과 payload 시드 | `create <명사> as <이름>`로 생성 직후 그 행에 `set`/`format`/`respond`를 쓰고 싶다 — payload 동명 필드가 `derived` 제외하고 왜 `as` 유무와 무관하게 시드되는지, `as` 없는 `create`는 정확히 무엇이 바이트 동일한지 | `rfcs/0030-create-result-binding-and-payload-seed.md` |
| RFC-0031 다중 파일 컴파일 단위 | 서비스 하나를 여러 `.lnpl` 파일로 나누고 싶다 — 파일을 여러 개 주거나 디렉터리를 줄 때 병합 순서가 무엇으로 정해지는지, 이름이 겹치면 왜 두 파일:줄이 함께 나오는지, 파일 하나만 줄 때 왜 여전히 바이트 동일한지 | `rfcs/0031-multi-file-compilation-unit.md` |
| RFC-0032 실행-스코프 트랜잭션 경계와 `policy rollback` 집행 승격 | `policy rollback`이 실패한 실행의 쓰기를 정말 되돌리는지, 그 경계가 어디까지인지 — 명시적 `Transaction` 노드 없이 워크플로 실행 전체가 왜 암묵적 트랜잭션 하나가 되는지, `emit`으로 등록한 outbox 행이 그 롤백에 왜 같이 묶이는지 | `rfcs/0032-transaction-boundary-and-rollback-enforcement.md` |
| RFC-0033 선언 이름공간 — 디렉터리 스코프와 `internal/` 가시성 | (Draft) 서로 다른 도메인 디렉터리에서 같은 엔티티 이름(`Order` 등)을 쓰고 싶다 — 디렉터리가 어떻게 네임스페이스가 되는지, `internal/`이 가시성을 어떻게 좁히는지, 짧은 이름이 어느 순서로 해소되는지, `derive_id`가 네임스페이스를 왜 대부분의 골든 IR에 영향 없이 담는지 | `rfcs/0033-namespace-directories.md` |
| RFC-0034 NetworkCall 보상(compensation) 방식 결정 — `compensate` 절 + `rollback-escapes-network` | (Draft) `policy rollback`을 선언한 워크플로에 `call`/`request`를 쓰고 싶다 — `rollback-escapes-network` 경고가 왜 나는지, `compensate` 절이 그 경고를 어떻게 침묵시킬지, outbox 방식을 왜 기각했는지 | `rfcs/0034-network-call-compensation.md` |
| RFC-0035 인가 집행의 유보된 범위 — 워크플로 수준 role, `authorize`의 운명, `security encrypt` | (Draft) 워크플로마다 다른 `security role`을 왜 아직 못 쓰는지, `authorize` 동사가 왜 아직 선언과 연결되지 않았는지, `security encrypt`를 계속 써도 되는지 궁금하다 — 셋 다 이슈 #119가 미결로 남긴 질문이고, 이 RFC가 지금은 안 하는 이유와 재검토 조건을 적는다 | `rfcs/0035-authorization-enforcement-deferred-scope.md` |
| RFC-0036 `policy rollback` 선언의 실제 효력 정정 | `policy rollback`을 선언해야 실패한 실행의 쓰기가 롤백되는지 궁금하다 — 선언 여부와 무관하게 왜 항상 롤백되는지, 선언이 실제로 좌우하는 것(INFO trace 로그, `rollback-escapes-network` 진단)이 무엇뿐인지 | `rfcs/0036-policy-rollback-declaration-effect.md` |
| RFC-0037 아웃바운드 HTTP 회복성 계층 | `capability http`에 재시도·서킷브레이커·경로 템플릿을 어떻게 선언하는지, `NetworkDriver.call`이 왜 3-튜플이 됐는지 궁금하다 — 재시도 대상 판정(408/429/5xx, 501 제외)·지수 백오프와 jitter·Retry-After 반영·브레이커 half-open 규칙의 정본 | `rfcs/0037-http-resilience.md` |
| RFC-0038 `list where` — 질의 술어, order by/limit, 드라이버 푸시다운 | `list <Entity> where <cond>`로 RowSet을 걸러 `order by`/`limit`을 쓰고 싶다 — 좌변이 왜 항상 나열 대상 엔티티 자신의 필드인지, 등가(`==`/`!=`)가 왜 UUID/Text/Email까지 허용하는데 순서 비교는 여전히 Integer/DateTime뿐인지, `RepositoryDriver.query`가 예전 호출부와 왜 바이트 동일을 지키는지 | `rfcs/0038-list-where-predicate.md` |

Accepted RFC는 직접 편집하지 않는다 — 개정 절차는 `rfcs/0007-rfc-process-v2.md`에 있다.
