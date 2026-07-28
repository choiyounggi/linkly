# Task 02: RFC-0001 부록 — IR JSON 직렬화 + 스키마 + 검증 스크립트

## Objective
IR의 canonical JSON 직렬화가 JSON Schema로 정의되고, 골든 예제가 스키마를 통과하며
고의로 깨뜨린 예제는 실패하는 실행 가능한 검증이 존재한다.

## Wiki pages (read these first, only these)
- wiki/testing/quality/tests-that-cannot-fail.md — use for: 검증 스크립트가 부정
  케이스(반드시 실패해야 하는 입력)를 포함하도록 설계

## Inputs
- `rfcs/0001-semantic-ir.md`의 노드 카탈로그·공통 필드(`kind`/`id`/`meta`)·타입 표 (Task 01 산출물)
- plan.md: D4(canonical JSON, draft 2020-12, `.lir.json`), 골든 시나리오

## Steps
1. `schemas/lir.schema.json` 작성 — draft 2020-12. 루트는
   `{"lir_version": "0.1", "module": <이름>, "nodes": [...]}`. **D4의
   constrained-decoding 호환 부분집합 준수**: 노드는 `kind`로 분기하는
   **`anyOf`**(`oneOf`·`default` 키워드 사용 금지 — OpenAI Structured Outputs 등
   constrained decoding이 미지원), root는 object, 스키마 중첩 ≤5레벨(D17의 평탄
   노드 테이블이라 자연 충족 — 노드가 인라인 자식을 갖지 않음을 스키마로도 강제:
   `children`은 id 문자열 배열 타입). Task 01 카탈로그의 필수/선택 필드를
   `required`/`properties`로 반영, `additionalProperties: false`
2. `examples/login.lir.json` 작성 — 골든 시나리오 전체(Entity User, Service
   LoginService, Workflow Login 6단계, Policy retry3/rollback/timeout3s, Security
   jwt, Performance response<50ms·cache5m, Event UserCreated, Capability 3종)를
   스키마에 맞는 JSON으로 표현
3. `scripts/validate_ir.py` 작성 — Python 3.11+, `jsonschema` 사용. 동작:
   (a) 인자로 받은 `.lir.json`을 스키마 검증, 성공 시 exit 0
   (b) `--self-test` 플래그: `examples/login.lir.json` 검증 성공 **그리고**
   메모리 안에서 login 예제를 3가지로 변형(필수 필드 삭제, 미정의 kind 주입,
   미정의 추가 필드 주입)한 각각이 검증 **실패**해야 exit 0. 하나라도 통과해버리면
   exit 1 — 위키 페이지의 원칙: 실패할 수 없는 검증은 검증이 아니다
4. `rfcs/0001-semantic-ir.md`의 Reference-level Specification 끝에 "부록 A:
   직렬화" 절을 추가하고 명시: (a) 스키마 파일 경로 (b) **저장 형식 = 2-space
   pretty JSON**(LLM·사람 가독) (c) **동등성 비교·해시·서명용 canonical form =
   RFC 8785 JCS**(키 정렬·수치 표현·공백 제거를 JCS에 위임 — 자체 규칙 발명 금지)
   (d) 스키마가 constrained-decoding 호환 부분집합임과 그 이유(에이전트가 IR
   조각을 structured output으로 직접 생성 가능해야 함)

## Deliverables
- `schemas/lir.schema.json`
- `examples/login.lir.json`
- `scripts/validate_ir.py` (+ `rfcs/0001-semantic-ir.md` 부록 A 추가 — 수정)

## Verify
- 레포(워크트리) 루트에서 `python3 scripts/validate_ir.py --self-test`
  → exit 0, 출력에 positive 1건 PASS + negative 3건 모두 REJECTED 표시
- `grep -c '"oneOf"\|"default"' schemas/lir.schema.json` → 0 (D4 부분집합 준수)

## Out of scope
- 문법→IR 변환(Task 04), IR 인터프리터(ROADMAP/MVP 단계)
