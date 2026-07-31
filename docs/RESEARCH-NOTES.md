# RESEARCH-NOTES — 계획 결정의 외부 근거 (2026-07-28 조사)

plan.md의 `[ext]` 표기 결정들이 참조하는 근거 모음. RFC 본문에서 인용할 때 이 문서의
링크를 쓴다. (조사 시점 기준 — RFC Accepted 승격 전 링크 유효성 재확인.)

## 1. 문법 — 들여쓰기 유의미(오프사이드 룰) 기각 → 키워드 구획 (D5)

- 공백·들여쓰기·개행이 코드 토큰의 **~24.5%**를 차지하며 의미 기여는 미미.
  중괄호 언어는 포맷팅 제거로 큰 절감(Java 개행 제거만 18.7~22.0%)이 가능하지만,
  **오프사이드 언어(Python)는 포맷팅이 문법이라 제거 불가**(평균 6.51%만 절감).
  → "The Hidden Cost of Readability" https://arxiv.org/html/2508.13666
- AI-native 언어 선행 사례 **MoonBit**: 중첩 축소·최상위 명시 타입 = KV-cache 친화,
  추론 속도 향상. → https://www.moonbitlang.com/blog/moonbit-ai ,
  ICSE LLM4Code 2024 https://dl.acm.org/doi/10.1145/3643795.3648376
- Armin Ronacher, "A Language For Agents" (2026-02): significant whitespace는
  LLM 작업에 불리. → https://lucumr.pocoo.org/2026/2/9/a-language-for-agents/
- **주의(트레이드오프)**: YAML류 들여쓰기 계층이 토큰 효율 자체는 좋을 수 있으나
  스트리밍 생성 중 들여쓰기 오류가 파싱을 깨는 리스크가 있음 — LNPL은 "들여쓰기
  비유의미 + 키워드 구획"으로 두 문제를 동시에 회피.

## 2. IR 직렬화 — RFC 8785 canonical + constrained-decoding 부분집합 (D4, D17)

- Canonical JSON은 자체 규칙 발명 대신 **RFC 8785 (JCS)**: 키 정렬·수치 표현(Ryū)·
  공백 제거를 표준화, 해시/서명 일관성 보장.
  → https://www.rfc-editor.org/info/rfc8785/
- OpenAI Structured Outputs의 스키마 제약: **oneOf 미지원(anyOf 사용)**,
  `default` 미지원, root는 object, **중첩 ≤5레벨**, pattern/format 미강제.
  에이전트가 IR 조각을 constrained decoding으로 직접 생성하려면 스키마가 이
  부분집합 안에 있어야 함.
  → https://developers.openai.com/api/docs/guides/structured-outputs
- 평탄 노드 테이블 + id 참조(D17)는 위 중첩 한계를 구조적으로 충족시키고,
  MoonBit의 "중첩 축소" 원칙과 일치.

## 3. 컴파일러 — 직접 LLVM IR 대신 MLIR progressive lowering (D18)

- LLVM IR은 저수준이라 프런트엔드가 고수준 정보를 일찍 버리게 됨. MLIR은 고수준
  dialect에서 정보가 살아있는 동안 최적화하고 단계적으로 LLVM dialect까지 하강,
  하부 생태계(표준 dialect·코드젠) 재사용.
  → https://mlir.llvm.org/ , Lattner MLIR keynote
  https://llvm.org/devmtg/2019-04/slides/Keynote-ShpeismanLattner-MLIR.pdf
- LNPP의 Semantic IR(BusinessRule·Effect·Policy)은 정확히 "도메인 시맨틱을 담는
  최상위 dialect" 패턴에 해당.

## 4. 에이전트 프로토콜 — JSON-RPC 2.0 = A2A/MCP 정렬 확증 (D8, D19)

- **A2A(Agent2Agent, Google 2025-04 공개)**: JSON-RPC 2.0 + HTTP + SSE,
  Agent Card로 능력 공표, 태스크 상태기계(submitted/working/input-required/
  completed/failed/canceled), 장기 실행 태스크 지원.
  → https://atlan.com/know/google-a2a-protocol/ ,
  서베이 https://arxiv.org/html/2505.02279v1
- 계층 구분 관례: **에이전트↔도구 = MCP, 에이전트↔에이전트 = A2A** — LNPP
  프로토콜도 이 두 계층을 구분(D8).
  → https://atlan.com/know/mcp/mcp-vs-a2a-protocol/

## 5. KB — progressive disclosure 3단 로딩 (D9)

- Anthropic Agent Skills 패턴: ① 메타데이터(이름+설명)만 상시 로드 → ② 매칭 시
  본문(SKILL.md) 로드 → ③ 부속 리소스는 본문이 지시할 때만. 컨텍스트 토큰 절약의
  검증된 구조.
  → https://bdtechtalks.com/2025/10/20/anthropic-agent-skills/ ,
  https://www.newsletter.swirlai.com/p/agent-skills-progressive-disclosure
- LNPP KB의 2단 라우팅(루트 도메인 맵→카테고리 index→문서)은 이 패턴과 동형 —
  D9를 3단(+리소스 계층)으로 확장, 본문 ≤500줄 예산.

## 6. MVP — 참조 인터프리터 = 실행 가능한 명세 (D14, D20)

- WebAssembly 표준화 관례: 기능 채택에 4종 아티팩트(형식 명세 + 산문 + **참조
  인터프리터 구현** + 테스트 스위트). 참조 인터프리터는 "명확성·단순성 우선,
  성능 비목표" — 명세의 실행 가능한 형태.
  → https://github.com/WebAssembly/spec ,
  https://github.com/WebAssembly/spec/blob/main/interpreter/README.md
- LNPP Phase 1 인터프리터의 목적 규정(D14)과 채택 게이트(D20)의 직접 근거.

## 7. 플랫폼 층위 선행 사례 (2026-07-31 조사 — RFC-0002 §Prior Art 근거)

세 프로젝트를 직접 읽고 대조했다. 요약표와 갈림점 분석은 `rfcs/0002-syntax.md`
§Prior Art의 "플랫폼 층위 선행 사례와 갈림점"에 있다(정본). 여기에는 조사 원문과
수치만 남긴다.

- **[lhaig/intent](https://github.com/lhaig/intent)** — "AI 코드 어시스턴트가
  쓰도록 설계된 언어, 여러 타깃으로 컴파일". 설계 3원칙: 명시적 계약(함수마다
  사전·사후조건, 엔티티 불변식) / 선언된 의도(자연어 목표를 형식 검증 지점에
  연결) / 검증 가능한 정확성(Z3 SMT + 런타임 계약 집행). IR 레이어
  `internal/ir/` 보유, 툴체인 self-hosting, 산출 = Rust·JavaScript·WebAssembly.
  `AGENTS.md`로 멀티에이전트 워크플로, `HARNESS.md`로 검증 계약, ADR 33건+.
  성숙도: 별 5, 커밋 339.
- **[l3yx/intentlang](https://github.com/l3yx/intentlang)** — "Python에 직접
  임베드된 실행 가능한 자연어"("Python을 쓸 수 있으면 IntentLang을 이미 안다").
  신규 문법 없음 — `Intent` 객체 메서드 체이닝 + `MagicIntent.hack_str()`.
  IR은 **프롬프트 구조화용** XML Intent IR(Goal·Contexts·Tools·Input·Strategy·
  Constraints·Output을 형식화해 LLM 생성을 유도). 실행 모델 = Intent → 프롬프트 →
  LLM이 Python 코드 생성 → 런타임 실행 → 관측/예외 포착 → LLM 재투입(최대 30회).
  타깃 = Python 바이트코드(네이티브 아님). 성숙도: 별 92, 커밋 17.
- **[pboueri/intentc](https://github.com/pboueri/intentc)** — "의도의 컴파일러".
  입력 = `.ic`(마크다운 + YAML frontmatter)로 피처와 의존을 기술해 DAG 구성.
  빌드 = 미처리 피처를 토폴로지 정렬 → 피처당 에이전트(Claude Code 등) 호출 →
  `.icv` 검증 실행 → 성공분만 git 커밋(실패는 미커밋 상태로 보존). 산출 = 타깃
  언어 소스 코드(네이티브 아님), 언어 비종속("새 모델·새 언어가 나오면 새 타깃으로
  재빌드"). 성숙도: 별 1, 커밋 85.

**LNPP에 미친 영향 2건**: ① `spec` 절을 IR 노드가 아니라 테스트 스위트
아티팩트로 산출한다는 판단(RFC-0002 부록 A.4-②)은 intentc의 `.icv` 선례로 보강
② "합성(synthesis) vs 결정적 lowering" 대비가 RFC-0004 파이프라인의 설계 의도를
명문화하는 근거가 됐다(에이전트는 소스가 아니라 IR을 제안한다).
