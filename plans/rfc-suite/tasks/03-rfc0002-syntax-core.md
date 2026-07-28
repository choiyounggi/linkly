# Task 03: RFC-0002 Syntax — 문법 코어(EBNF·키워드·블록 규칙)

## Objective
`rfcs/0002-syntax.md`가 존재하고, LNPL의 전체 문법이 EBNF와 LLM-친화 설계 근거와
함께 정의되어 있다(IR로의 매핑은 다음 태스크).

## Wiki pages (read these first, only these)
- (없음 — 형식화 방식은 plan.md D5로 확정됨)

## Inputs
- `rfcs/0000-rfc-process.md`의 7섹션 템플릿 (Task 00 산출물)
- `rfcs/0001-semantic-ir.md`의 노드 카탈로그 — 문법의 최상위 선언은 IR Declaration
  대분류와 1:1이어야 함 (Task 01 산출물)
- plan.md: D3(LNPL/.lnpl), D5(EBNF+라인 지향·키워드 구획 블록·비유의미 들여쓰기),
  D16(타입명), 골든 시나리오

## Steps
1. `rfcs/0002-syntax.md`를 7섹션 템플릿으로 생성, Status=Draft
2. 최상위 선언 키워드를 확정(전부 소문자, IR Declaration과 1:1):
   `entity`, `service`, `workflow`, `event`, `capability`
   선언 내부 절 키워드: `field`, `goal`, `policy`, `security`, `performance`,
   `database`, `given`/`when`/`expect`(spec 블록), `spec`
3. 제어 어휘를 확정: `when`, `repeat`, `parallel`, `until`, `pipeline` +
   블록 종결 키워드 `merge`(parallel 전용, Charter 예제 그대로)
   (Charter 규정 — `if`/`for`/`while`/`switch`는 예약만 하고 사용 금지 명시)
4. Reference-level Specification에 W3C-style EBNF 전체 문법 작성:
   - 렉시컬: 식별자(PascalCase 타입/entity, camelCase 필드), 리터럴(수치+단위
     `3s`/`5m`/`50ms`, 비교식 `response < 50ms`), 주석(`#` 한 줄)
   - 블록(D5 개정판): **라인 지향 + 키워드 구획** — 블록 경계는 들여쓰기가 아니라
     키워드가 정한다. 최상위 선언 키워드는 이전 블록을 자동 종결, 내부 절 키워드
     (`field`/`goal`/`policy`…)는 소속 선언의 하위 구획을 열고 다음 절 키워드 또는
     최상위 키워드에서 닫힘, `parallel` 블록만 명시적 종결 키워드 `merge`를 가짐
     (Charter 예제 그대로). **들여쓰기는 비유의미** — 관례 4칸·탭 금지를 표기
     권장(style)으로만 규정하고 파서는 무시. 중첩 깊이 ≤2(선언 > 절 > parallel 1단)
   - workflow 본문: 한 줄 = 한 step(동사구), step은 자유 텍스트가 아니라
     `동사 + 목적어` 2~4 토큰으로 제한한다고 규정
5. Guide-level Explanation에 LLM-친화 설계 근거 4원칙(Charter의 Predictable /
   Deterministic / Semantic / Low Ambiguity)을 각 문법 결정과 연결해 서술
   (예: 키워드 구획 → 중괄호 짝·들여쓰기 오류가 문법적으로 불가능 = Deterministic,
   스트리밍 생성 중 라인 단위 유효성 = Predictable)
5b. Guide-level에 "Prior Art" 절 추가 — 3건 요약·인용: ① MoonBit(AI-native 언어:
   중첩 축소·최상위 명시 타입 = KV-cache 친화, LLM4Code 2024) ② 포맷팅 토큰
   연구(공백·개행이 코드 토큰 ~24.5%, 오프사이드 언어는 제거 불가 —
   arXiv:2508.13666) ③ Ronacher "A Language For Agents". LNPL이 각각에서 무엇을
   채택/기각했는지 1줄씩
6. Examples 섹션: 골든 시나리오 전체를 유효한 `.lnpl` 소스로 표기(이 코드 블록이
   Task 04에서 `examples/login.lnpl` 파일로 추출됨)

## Deliverables
- `rfcs/0002-syntax.md`

## Verify
- 체크리스트: (a) EBNF에 위 키워드 전부가 생산규칙으로 존재 (b) Examples의
  Login 소스가 EBNF의 모든 최상위 선언(entity/service/workflow/event/capability)을
  1회 이상 사용 (c) 금지 어휘(if/for/while/switch)가 예약어 목록에 명시
  (d) 7섹션 모두 비어있지 않음

## Out of scope
- 문법→IR lowering 매핑과 .lnpl 파일 추출(Task 04), 타입 시스템 정의(Task 01 소유)
