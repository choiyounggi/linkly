# RFC-0004: Compiler

## Status

- Status: Accepted (2026-07-31) <!-- Draft | Review | Accepted | Superseded -->

## Motivation

CHARTER §Native Compiler는 컴파일 경로를 한 줄로 선언한다 — `Source → Semantic
Parser → Semantic IR → Architecture Optimizer → Concurrency Optimizer → Memory
Optimizer → LLVM IR → Native Binary`. 이것은 단계의 **이름 목록**이지 계약이
아니다. 각 단계가 무엇을 입력으로 받고 무엇을 출력하며 **무엇을 보존해야
하는가**가 없으면, 어떤 패스가 IR을 어떻게 바꿔도 규칙 위반이라고 말할 수 없다.
이 문서가 그 빈칸을 채운다. 두 상류 RFC가 이 문서에 명시적으로 위임한 결정도
함께 이행한다: RFC-0001 부록 A.7은 "문서 수준 불변식 — id 유일성, dangling 참조
금지, 소유 유일, 비순환, kind별 children 허용 종별 — 은 스키마 표현 범위 밖이며,
컴파일 파이프라인의 검증 패스(RFC-0004 계열)가 소유한다"고 위임했고, RFC-0003
§Memory Model은 "어떤 값을 어느 배치로 보낼지의 선택 알고리즘은 RFC-0004
소유다"라고 위임했다.

**직접 LLVM IR로 내리지 않고 MLIR을 경유하는 이유.** LLVM IR은 저수준이라
프런트엔드가 고수준 정보를 일찍 버리게 된다. 그런데 LNPP에서 최적화 가치가 가장
큰 정보가 바로 그 고수준 정보다 — Effect(어떤 부수효과인가), Policy(재시도·
롤백·데드라인), Security(어떤 기제로 보호되는가), Concurrency(무엇이 병렬
브랜치인가). 이들을 LLVM IR의 load/store/call로 환원한 뒤에는 "이 호출이 멱등한
저장소 읽기라서 재시도 가능하다"는 판단을 되살릴 수 없다. MLIR은 고수준 dialect
에서 정보가 살아있는 동안 최적화하고 단계적으로 LLVM dialect까지 하강하며 하부
생태계(표준 dialect·코드젠)를 재사용하는 설계를 목표로 한다
(`docs/RESEARCH-NOTES.md` §3 — https://mlir.llvm.org/ , Lattner MLIR keynote).
LNPP의 Semantic
IR은 정확히 "도메인 시맨틱을 담는 최상위 dialect" 패턴에 해당하므로, plan.md
**D18**은 직접 하강을 기각하고 커스텀 dialect `lnpl` 경유 progressive lowering을
채택 결정으로 고정했다. 이 문서는 그 결정에 따라 CHARTER의 `→ LLVM IR` 화살표
하나를 S4(`lnpl` dialect 변환) · S5(표준 dialect 하강) · S6(LLVM dialect) 세
단계로 구체화한다.

**소비자가 둘이므로 동등성 요구가 필요하다.** LNPP의 실행 모드는 두 가지다
(plan.md **D14**): MVP의 **IR 인터프리터**와 Phase 2의 **LLVM 네이티브
바이너리**. 두 모드는 같은 파이프라인의 서로 다른 지점에서 갈라지므로, 계약에는
단계별 불변조건만이 아니라 "두 모드가 무엇에 대해 동등해야 하는가"가 함께
있어야 한다. 그것이 없으면 인터프리터로 검증한 프로그램이 네이티브에서 다르게
동작하는 것을 막을 방법이 없다 — RFC-0003이 자기 계약에 대해 같은 이유로 두 모드
공통 의무를 명시한 것과 같은 구조다.

## Guide-level Explanation

언어명 **LNPL**(워킹네임 — RFC-0000 §4)로 작성된 소스 `login.lnpl` 하나를 두고
개발자가 하는 일은 두 가지뿐이다: `run`(모드 A — 즉시 실행)과 `compile`(모드 B —
네이티브 바이너리 산출). 그 사이에서 컴파일러가 하는 일은 7단계다.

1. **S1 Semantic Parser** — `.lnpl` 텍스트를 읽어 Semantic IR 문서를 만든다.
   여기서 산출물은 이미 `.lir.json`이며, 이후 모든 단계는 텍스트가 아니라 IR을
   본다. 문법 표기와 IR 노드의 대응 표는 RFC-0002가 소유한다.
2. **S2 IR Validator** — IR이 스스로 성립하는지 검사한다. id가 겹치지 않는가,
   가리키는 id가 실제로 있는가, 소유 관계에 순환이 없는가. 이 단계는 IR을
   **고치지 않는다** — 통과 아니면 컴파일 실패다.
3. **S3 High-level Passes** — 고수준 최적화 3종이 순서대로 돈다. Architecture가
   "무엇으로 구현할지"(postgres·redis·jwt 바인딩)를 정하고, Concurrency가
   "무엇을 언제 어떤 동시성으로 실행할지"를 정하고, Memory가 "값을 어디에 둘지"를
   정한다. 세 패스 모두 **Semantic IR 레벨에서** 돌기 때문에, 각 패스 사이에서
   S2를 다시 돌려 IR이 여전히 성립하는지 확인할 수 있다. 이것이 이 단계 설계의
   핵심이다 — 최적화 결과가 여전히 검증 가능한 IR이라는 성질.
4. **S4 `lnpl` dialect 변환** — 최적화된 IR을 커스텀 MLIR dialect로 옮긴다.
   여기서 형식이 JSON에서 MLIR로 바뀌므로, IR 노드 id를 잃지 않도록 각 op에
   **원 노드 id를 심어 보낸다**. 네이티브 바이너리에서 난 오류를 원래 `.lnpl`의
   어느 줄로 되짚으려면 이 연결이 끝까지 살아 있어야 한다.
5. **S5 표준 dialect 하강** — `lnpl` op들을 MLIR 표준 dialect(`func`·`scf`·
   `async`·`memref`·`arith`·`vector`)로 내린다. workflow step은 순차 실행으로,
   `parallel` 블록은 비동기 브랜치와 join으로 바뀐다.
6. **S6 LLVM dialect** — 표준 dialect를 LLVM dialect로 내린다. 여기서부터는
   LNPP 고유 개념이 남아 있지 않고, LLVM 생태계의 최적화가 그대로 적용된다.
7. **S7 Native Binary** — 기계어와 실행 바이너리를 산출한다. JVM은 없다
   (CHARTER §Native Compiler).

모드 A(인터프리터)는 S3까지만 수행하고 그 IR을 직접 실행한다. 모드 B는 S7까지
간다. 두 모드는 **관측 가능한 동작**에서 같아야 한다 — 실행 순서, 정책 집행
결과, 관측성 신호, 마스킹. 그 밖의 것(스케줄러를 어떻게 짰는지, 값을 stack에
뒀는지 arena에 뒀는지)은 같을 필요가 없고, 같기를 요구해서도 안 된다.

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오 — RFC-0000
§5에 따라 참조만 하고 재정의하지 않는다)으로 보면: 개발자는 workflow의 6단계와
`retry 3` / `timeout 3s` / `jwt` / `response < 50ms`를 선언했을 뿐이지만,
컴파일러는 그 선언으로부터 어떤 저장소 구현체를 쓸지, 어느 단계를 병렬로 돌려도
되는지(그리고 왜 안 되는지), 인증 결과 객체를 어느 메모리 배치에 둘지를 전부
결정한다. §Examples가 그 결정을 노드 단위로 보여준다.

## Reference-level Specification

### 파이프라인

파이프라인은 7단계다. CHARTER §Native Compiler의 논리 단계를 유지하되 하강 경로는
plan.md D18의 MLIR progressive lowering으로 구체화한다. 고수준 최적화 3종은 S3
**한 단계** 안의 순차 서브패스이며(각각의 입력·출력·불변조건은 §고수준 패스 3종의
책임 경계 표에 있다), 단계 이름은 아래 표의 문자열을 정본으로 한다.

| 단계 | 입력 | 출력 | 보존 불변조건 |
|------|------|------|--------------|
| S1 `Semantic Parser` | `.lnpl` 소스 텍스트 | Semantic IR 문서(`.lir.json`) | 출력은 `schemas/lir.schema.json`의 유효 문서다(RFC-0001 A.1). 생성한 모든 노드는 원 소스 위치를 `meta.source`로 가리킬 수 있다. 문법 표기 → IR 노드 매핑 표는 RFC-0002 소유이므로 이 단계는 그 매핑을 인용해 구현하고 여기서 재정의하지 않는다 |
| S2 `IR Validator` | S1의 IR 문서 | 검증을 통과한 **동일** IR 문서 | ① 스키마 유효성(선행 게이트: `scripts/validate_ir.py`) ② 문서 수준 불변식 5종(아래 표) ③ **입출력이 바이트 동일하다** — 이 단계는 IR을 변형하지 않는다. 동일성은 RFC-0001 A.3의 RFC 8785 canonical form 비교로 판정한다. 위반은 컴파일 실패이며 경고로 강등하지 않는다 |
| S3 `High-level Passes (Semantic IR level)` | 검증된 IR 문서 | 변형된 IR 문서 + 컴파일 컨텍스트(노드 id → 결정) | ① 출력이 `schemas/lir.schema.json` 유효 ② 문서 수준 불변식 5종 유지 ③ 노드 id 안정성(아래 §노드 id 안정성) ④ Constraint 노드(Policy·Security·Performance)의 값 불변. 3개 서브패스 **경계마다 S2를 재실행할 수 있어야 한다** — 이 재실행 가능성이 ①②의 반증 수단이다 |
| S4 `lnpl dialect 변환` | S3의 IR + 컴파일 컨텍스트 | `lnpl` MLIR dialect 모듈 | IR 노드 id의 **역추적 보존**(아래 §dialect 변환 이후의 역추적). 이 단계부터 산출물은 JSON이 아니므로 IR 스키마 유효성은 적용 대상이 아니고, 역추적 보존이 그 자리를 대신하는 불변조건이다. S3의 컴파일 컨텍스트 항목은 전부 op attribute로 실체화되어야 한다 — 실체화되지 않은 결정은 유실이며 변환 실패로 취급한다 |
| S5 `표준 dialect 하강` | `lnpl` dialect 모듈 | `func`·`scf`·`async`·`memref`·`arith`·`vector` 조합 | ① 역추적 보존 ② RFC-0003 §Execution Model의 관측 가능한 동작 보존 — step 순서(children 순서), structured concurrency 4조건(전 브랜치 join, 실패 시 형제 취소, 부모 취소 전파, 고아 작업 금지), Effect의 await 지점 성질 |
| S6 `LLVM dialect` | 표준 dialect 모듈 | LLVM dialect 모듈 | ① 역추적 보존 ② 관측 가능한 동작 보존. 이 단계 이후 LNPP 고유 개념은 남지 않으며, 여기서부터의 최적화는 LLVM 생태계의 것을 그대로 적용한다 |
| S7 `Native Binary` | LLVM dialect 모듈 | 네이티브 실행 바이너리 | ① 역추적 보존(디버그 정보 경유 — 포맷은 §Open Questions ④) ② 관측 가능한 동작 보존. JVM은 산출물에 존재하지 않는다(CHARTER §Native Compiler) |

**문서 수준 불변식 5종(S2 소유).** RFC-0001 부록 A.7이 "스키마 표현 범위 밖이며
컴파일 파이프라인의 검증 패스(RFC-0004 계열)가 소유한다"고 위임한 항목이다.
`scripts/validate_ir.py`는 A.7대로 스키마 검증까지만 수행하므로, 아래 5종은 S2가
별도로 판정한다.

| # | 불변식 | 근거 | 위반 예 |
|---|--------|------|---------|
| V1 | 노드 `id`가 문서 내에서 유일 | RFC-0001 공통 필드 표 | 두 노드가 모두 `wf.login.step.3`을 가짐 |
| V2 | 모든 참조(소유·비소유)가 문서 내 `id`로 해소 — dangling 금지 | 구조 규칙 6 | `svc.login`의 `requires`가 문서에 없는 `cap.kafka`를 가리킴 |
| V3 | 한 노드는 최대 1개 노드의 `children`에만 등장(소유 유일), 진입 노드는 Declaration만 | 구조 규칙 2 | `wf.login.step.3`이 `wf.login`과 신설 병렬 step 양쪽 children에 동시 등장 |
| V4 | `children` 소유 그래프가 비순환 | 구조 규칙 4 | `wf.login`의 자손이 `wf.login`을 children으로 가짐 |
| V5 | kind별 children 허용 종별 준수 | RFC-0001 노드 카탈로그 | `wf.login`(Workflow)이 Concurrency 노드를 직접 children으로 가짐 — Workflow의 children은 WorkflowStep만 허용 |

### 고수준 패스가 IR에 할 수 있는 변형

스키마는 `additionalProperties: false`이고 `meta`도 정의된 두 키로 닫혀 있다
(RFC-0001 A.5). 따라서 **스키마 필드로 표현할 수 없는 결정을 IR 노드에 써넣는
것은 불가능하다** — 그렇게 하면 S3의 불변조건 ①(스키마 유효성)이 즉시 깨진다.
이 제약에서 두 규칙이 따라 나온다.

**허용 변형 4종.** 고수준 패스가 IR에 가할 수 있는 변형은 이 4종뿐이다.

- **M1 노드 삭제** — 삭제한 노드를 가리키는 참조도 함께 정리한다(V2 유지).
- **M2 `children` 순서 변경·재그룹** — 허용 종별(V5) 안에서만.
- **M3 신규 노드 추가** — 스키마 20 kind 중 하나이며 신규 `id`를 받는다.
- **M4 스키마 허용 필드의 값 변경** — 단 Constraint 노드(Policy·Security·
  Performance)의 값은 제외한다. 제약은 최적화의 **입력**이며 대상이 아니다.

**컴파일 컨텍스트(pass side table).** capability 바인딩 결정, 메모리 배치 결정,
병렬화 가능 여부 판정 결과처럼 스키마에 자리가 없는 결정은 IR에 쓰지 않고 별도
산출물에 `노드 id → 결정` 형태로 누적한다. 이 표는 S4에서 op attribute로
실체화되며(S4 불변조건), 모드 A(인터프리터)는 IR과 이 표를 함께 소비한다. 즉
IR은 끝까지 "선언된 의도"만 담고, "컴파일러가 정한 것"은 컨텍스트에 담긴다.

### 노드 id 안정성

S3의 불변조건 ③을 규칙으로 확정한다. 이 규칙이 있어야 에이전트가 노드 단위 diff를
주고받고(plan.md D17) 최종 바이너리의 오류를 원 노드로 되짚을 수 있다.

- **재명명 금지.** 기존 노드의 `id`를 다른 문자열로 바꿀 수 없다.
  위반 예: `wf.login.step.3` → `wf.login.step.03`.
- **삭제만 가능.** 노드는 사라질 수 있으나(M1) 이름이 바뀔 수는 없다.
  위반 예: 미사용 노드를 정규화하면서 남은 노드의 id를 순번으로 다시 매김.
- **삭제한 id의 재사용 금지.** 삭제된 `id`를 신규 노드에 다시 부여하지 않는다.
  위반 예: `wf.login.step.5`를 지운 뒤 신설 병렬 step에 같은 id를 부여 — 역추적이
  다른 노드를 가리킨다.
- **신규 노드는 신규 id.** M3로 추가하는 노드는 문서에 한 번도 등장하지 않은
  `id`를 받으며 형식은 RFC-0001의 패턴 `^[a-z][a-z0-9]*(\.[a-z0-9]+)*$`을 따른다.
  위반 예: 대문자·하이픈이 든 `wf.login.PAR-1`.

### dialect 변환 이후의 역추적

S4에서 형식이 MLIR로 바뀌어도 원 IR 노드 id는 사라지지 않는다. 각 op은 두 경로로
id를 싣는다: **① MLIR 위치 정보(Location)** — 진단·디버그 정보가 따라가는 경로이며
② **discardable attribute `lnpl.node_id`**(문자열) — 패스가 조회하는 경로. 두
경로를 함께 두는 이유는 attribute가 하강 중 버려질 수 있는 성질(discardable)을
갖기 때문이다. 보존 규칙 4개:

- **1:1 변환**은 원 노드의 id를 그대로 전달한다.
- **다:1 병합**(여러 IR 노드가 한 op으로)은 병합된 위치 정보로 **전 id를
  보존**한다 — 하나만 남기고 축약하지 않는다.
- **1:다 확장**(한 노드가 여러 op으로)은 생성된 전 op이 같은 id를 갖는다.
- **S5~S7 하강 중 op이 소멸**해도, 그 지점을 가리키는 진단·디버그 정보가 해소하는
  id는 유지된다.

역추적 요구는 다음 한 문장으로 판정한다: **최종 산출물의 임의 지점에서 원 IR 노드
id를 최소 1개 이상 얻을 수 있다.** attribute 이름 `lnpl.node_id`는 이 RFC가
소유하는 결정이고, MLIR 위치 정보 API의 정확한 표기는 §Open Questions ②로 미룬다.

### 고수준 패스 3종의 책임 경계

세 패스는 **결정 대상이 서로 배타**다 — Architecture는 *무엇으로 구현하고 무엇을
생성하는가*, Concurrency는 *무엇을 언제 어떤 동시성으로 실행하는가*, Memory는
*값을 어디에 두는가*.

**용어 주의.** 이 문서에서 **배치(placement)** 는 값의 메모리 배치만을 가리킨다.
Effect가 어느 capability에 묶이는지는 **귀속**으로 표기해 구분한다 — 두 결정의
소유 패스가 다르므로(S3-1 vs S3-3) 같은 낱말을 쓰면 책임 경계가 흐려진다.

| 패스 | 결정 대상 | 입력 | 출력 | 보존 불변조건 | 하지 않는 것 |
|------|----------|------|------|--------------|-------------|
| S3-1 `Architecture Optimizer` | capability 구현체 선택, Effect 노드의 **capability 귀속**(어느 capability에 묶이는가), 자동 생성물 산출 지점, Security mechanism의 이행 지점 | 검증된 IR + 선언된 Capability 노드 | IR(변형 최소) + 컨텍스트에 `Effect 노드 id → capability 바인딩`, 자동 생성물(REST/OpenAPI/마이그레이션) | S3 불변조건 4개. Security·Performance 제약 값을 바꾸지 않는다 | 실행 순서·동시성을 정하지 않는다. 값의 메모리 배치를 정하지 않는다 |
| S3-2 `Concurrency Optimizer` | `parallel` 블록(Concurrency 노드) 스케줄링, 독립 step의 자동 병렬화 판정, capability 커넥션의 획득 시점·동시 획득 수 | S3-1의 IR + 바인딩 컨텍스트 | `children` 순서·그룹이 조정된 IR(M2·M3) + 컨텍스트에 `step id → 병렬화 판정 결과와 사유` | S3 불변조건 4개. 특히 V3·V5를 깨지 않는 형태로만 재그룹한다 | capability 구현체를 바꾸지 않는다. 값의 메모리 배치를 정하지 않는다 |
| S3-3 `Memory Optimizer` | 값의 배치(Stack/Heap/Arena) 선택, pool 획득·반환 지점 삽입 | S3-2의 IR(순서 확정) + 앞선 컨텍스트 | IR(변형 없음이 기본) + 컨텍스트에 `노드 id → 배치` 및 pool 획득/반환 지점 | S3 불변조건 4개. 실행 순서를 바꾸지 않는다 | 순서·동시성을 바꾸지 않는다. capability 구현체를 바꾸지 않는다 |

**단방향 규칙(겹침 없음의 구조적 보장).** S3 내부 순서는 S3-1 → S3-2 → S3-3으로
고정이며, **하류 패스는 상류 패스의 결정을 뒤집지 못한다**. 세 패스가 같은 대상을
두고 경합할 수 없으므로 책임 겹침이 구조적으로 발생하지 않는다. 겹치는 것처럼
보이는 경계 3케이스의 판정은 다음과 같다.

| # | 경계 케이스 | 소유 패스 | 판정 근거 |
|---|------------|----------|----------|
| B1 | 병렬 브랜치 둘이 같은 capability를 쓸 때의 커넥션 획득 | 획득 시점·동시 획득 수 = S3-2 Concurrency / 획득·반환 **지점 삽입** = S3-3 Memory | 두 결정의 대상이 다르므로 분할한다(B3과 같은 형태). *언제 몇 개를 동시에 획득하는가*는 실행 스케줄이라 순서를 확정하는 S3-2가 소유하고, *어느 Effect의 앞뒤에 획득·반환을 넣는가*는 자원 수명의 배치라 S3-3이 소유한다. 두 브랜치는 형제이므로 각자 1개를 획득하며 RFC-0003의 중첩 획득 금지에 걸리지 않는다. bounded pool 고갈 시 fail-fast는 런타임 계약(RFC-0003)이며 컴파일러가 완화하지 않는다 |
| B2 | capability 구현체 선택이 성능에 영향을 줄 때 | S3-1 Architecture | 구현체 선택은 "무엇으로 구현하는가" 축이다. 성능 영향이 있다는 사실이 결정 주체를 바꾸지 않는다. `Performance` 제약은 두 패스 모두에게 입력이며 어느 패스도 그 값을 변경하지 않는다(S3 불변조건 ④) |
| B3 | 병렬화로 중간 값의 수명이 브랜치 경계를 넘게 될 때 | 순서 = S3-2, 배치 = S3-3 | 단방향 규칙의 적용례다. S3-2가 순서를 확정한 **뒤** S3-3이 그 순서를 사실로 받아들이고 배치를 정한다. 역방향(배치 때문에 순서를 되돌리는 것)은 금지다 |

### 자동 병렬화 판정 기준

`policy`에 `parallel`이 선언되지 않은 독립 step을 컴파일러가 병렬화하려면 **두
조건을 모두** 만족해야 한다.

1. **Effect 간 데이터 의존이 없다** — 한 step의 Effect 결과가 다른 step의 Effect
   입력으로 흐르지 않는다.
2. **같은 capability 인스턴스를 공유하지 않는다** — 같은 인스턴스를 쓰면 직렬화
   지점이 생기고, actor 직렬 메일박스(RFC-0003 §Execution Model) 전제에서 병렬화
   이득이 사라진다.

**보수 규칙.** 두 조건 중 하나라도 **IR로 확증할 수 없으면 병렬화하지 않는다.**
특히 `children`이 없어 소유 Effect가 선언되지 않은 step은 부수효과 집합이
공집합인지 미상인지 IR에서 구분할 수 없으므로 병렬화 후보가 아니다. 자동 최적화가
관측 가능한 동작을 바꾸는 것보다 최적화를 포기하는 편이 항상 낫다.

**변형의 형태.** RFC-0001 카탈로그상 Workflow의 `children`은 WorkflowStep만
허용하므로(V5), 병렬화는 Concurrency 노드를 Workflow에 직접 넣는 것이 아니라
**신설 WorkflowStep이 Concurrency 노드를 소유하고 그 아래로 원 step들을 옮기는**
형태를 취한다. 원 step의 `id`는 그대로 유지되고(재명명 금지), 신설 노드만 새
`id`를 받는다:

- 신설 WorkflowStep `id` = `<workflow id>.par.<n>` (n = 해당 workflow 내 신설
  순번, 1부터)
- 신설 WorkflowStep `name` = `parallel(<브랜치 step name들을 children 순서로
  ", "로 연결>)`
- Concurrency 노드 `id` = `<신설 step id>.conc`, `mode` = `parallel`

### Memory 배치 규칙

런타임이 제공하는 프리미티브 2종(arena·pool)의 계약은 RFC-0003 §Memory Model이
소유하며 이 문서는 인용만 한다. RFC-0003은 그 위에서 "컴파일러는 'step 간 전달
값은 arena, capability I/O는 pool'이라는 전제 위에서 Stack/Heap 승격·탈출 분석을
수행할 수 있다. 그 결정 자체(escape analysis, 배치 선택)는 RFC-0004의 최적화
패스가 소유한다"고 위임했다. 그 위임의 이행이 아래 표다.

| 배치 | 선택 조건 |
|------|----------|
| **Stack** | 소유 step 안에서 생성되고 그 step 안에서 소멸하며, 값이나 그 참조가 다른 step·다른 노드로 흐르지 않는 값. 즉 탈출이 **없음이 확증된** 값만 해당한다 |
| **Arena** | step 경계를 넘어 흐르는 중간 값 — **기본 배치**다. 개별 해제가 없고 workflow 실행 종결 시 일괄 해제된다(RFC-0003 arena 계약) |
| **Heap** | workflow 실행 수명(= arena 수명)을 넘겨 생존해야 하는 값. 소유권이 외부 계층으로 이전되는 값, 비동기 발행 이후에도 읽히는 페이로드가 해당한다. 런타임 계약은 RFC-0003 §Memory Model의 **`transfer` 프리미티브**가 소유한다(2026-07-31 개정으로 C8 해소): 선언된 이전 경계 — EventEmit 페이로드와 workflow 반환값 — 에서만 생성되고, 참조 카운트로 관리되며, 마지막 참조가 사라질 때 해제된다. 이 행은 **배치 분류**를, RFC-0003은 **생성·해제 책임**을 규정한다. 이전 경계 밖에서는 arena를 탈출하는 값을 만들 수 없으므로 S3-3의 탈출 판정은 "이 값이 선언된 이전 경계를 지나는가"로 축소된다 |
| **Pool** | capability 커넥션. 배치 선택의 대상이 아니라 **획득·반환 지점 삽입**의 대상이다: operation당 1회 획득, 다른 자원 획득 전 반환(RFC-0003 — 중첩 획득 금지) |

**escape analysis 적용 지점과 판정 근거.** 판정은 S3-3에서 수행하며, 입력은
`children` 소유 그래프와 명명 참조(`entity`·`event`·`target`·`key` 템플릿)다.
판정 질문은 하나다 — *이 값이 소유 step의 경계를 벗어나는가?*

- 같은 step 안에서만 소비되면 **Stack** 후보.
- 다른 step의 Effect가 소비하면 **Arena**.
- workflow 종결 이후에도 읽히면 **Heap**.

**보수적 폴백: 판정 불가는 Arena.** Semantic IR v0.1에는 값의 명시적 데이터 흐름
노드가 없으므로(RFC-0001은 값 노드를 두지 않는다) 이 판정은 step 경계 기준의
근사다. 소비 관계를 IR에서 확증할 수 없으면 **Stack으로 승격하지 않고 Arena에
둔다** — Stack 승격은 탈출 없음이 확증된 경우에만 한다. 잘못된 Stack 배치는 해제된
메모리 참조를 만들고, 불필요한 Arena 배치는 해제를 workflow 종결까지 늦추는 데
그친다. 근사의 한계는 §Open Questions ⑥으로 남긴다.

**층위 구분.** 이 절이 정하는 것은 **S3-3의 배치 선택 층위**다 — 값이 arena·stack·
heap 중 어디에 속하는가. S5~S7 하강에서 LLVM이 수행하는 레지스터 할당·스택 슬롯
재사용은 **다른 층위**이며 이 절의 규칙 대상이 아니다. 따라서 "arena에 속한 값"이
하강 후 물리적으로 스택 슬롯에 놓이는 것은 이 절의 Stack 배치와 다른 사건이고,
§Examples의 §두 모드에서의 동일 관측이 말하는 "실현 방식"의 차이가 바로 이것이며,
그 차이는 §실행 모드와 semantic equivalence의 동등성 비대상에 속한다.

### 실행 모드와 semantic equivalence

| 모드 | 수행 단계 | 위치 |
|------|----------|------|
| **모드 A — IR 인터프리터** | S1 → S2 → S3 (S4~S7 미수행). S3 출력 IR + 컴파일 컨텍스트를 직접 실행 | MVP(plan.md D14). 목적은 성능이 아니라 실행 가능한 명세 |
| **모드 B — LLVM 네이티브** | S1 → S7 전부 | Phase 2 |

**동등성 요구.** 두 모드는 같은 IR 문서에 대해 **관측 가능한 동작**에서 동등해야
한다. 동등성의 대상은 RFC-0003 §Reference-level 서두의 4종을 그대로 채택한다:

1. **실행 순서** — step 순서, structured concurrency의 join·취소 전파
2. **정책 집행 결과** — retry 판정, rollback 경계, timeout 시 종결 상태
3. **관측성 신호** — trace 구조(step = span), 상관ID 전파, 메트릭 라벨 집합, 로그 레벨
4. **마스킹** — Password·secret이 로그·trace·에러·직렬화에 평문으로 나타나지 않음

**동등성 대상이 아닌 것**을 함께 못박는다: 스케줄러 구조, **메모리 배치의 실현 방식**
(S5~S7 하강에서의 레지스터·스택 슬롯 승격 등), 명령 선택, op 개수, 실행 시간. 배치의
*선택* 자체는 S3에서 확정되어 두 모드가 공유하므로 비대상이 아니다(§층위 구분). 비대상에
동등성을 요구하면 모드 B의 최적화가 계약 위반이 된다 — 계약은 **외부에서 관측되는 것**에만 성립한다.

**검증 방식 — 차동(differential) 검증.** 같은 `.lir.json`을 두 모드로 실행하고 위
4종을 대조한다. 불일치는 컴파일러 결함으로 취급한다(느린 쪽을 정답으로 삼는
조정은 하지 않는다). 이 대조는 D20의 채택 요건 ④(테스트 스위트)에 포함된다.

**이 검증이 실패할 수 있음을 증명한다.** 항상 통과하는 대조는 대조가 아니므로,
스위트에는 **고의 불일치 케이스**를 포함해 red를 확인한다 — 예: ① S3-2가 데이터
의존이 있는 두 step의 `children` 순서를 바꾸는 잘못된 최적화 ② 모드 B에서만 retry
백오프 대기를 제거 ③ 모드 B에서만 마스킹 필터를 우회. 세 케이스에서 대조가
red를 내지 못하면 대조 하네스 자체에 결함이 있다는 뜻이다.

### 자동 최적화 9종

CHARTER §Optimization의 9종을 각 1줄로 정의하고 발생 레벨을 표기한다. 레벨은
`lnpl dialect` / `표준 dialect` / `LLVM` 3값이며 복수 표기가 가능하다. 표기는
**실체화 지점** 기준이다 — 판정이 Semantic IR 레벨(S3)에서 일어나는 항목도 그 결정이
op으로 실체화되는 dialect를 레벨로 적고, 판정 지점은 괄호로 병기한다. 알고리즘
상세는 §Open Questions ⑤로 미룬다.

| # | 최적화 | 정의(1줄) | 발생 레벨 |
|---|--------|-----------|----------|
| O1 | Inline | 호출 대상을 호출 지점에 펼쳐 호출 경계를 제거한다 | lnpl dialect(step·Pipeline 경계 펼침) + LLVM(함수 인라인) |
| O2 | Dead Code Elimination | 도달 불가하거나 결과가 소비되지 않는 연산을 제거한다 | lnpl dialect(미참조 노드 유래 op) + LLVM |
| O3 | Escape Analysis | 값이 소유 스코프를 벗어나는지 판정해 배치를 정한다 | lnpl dialect(판정은 S3-3, 실체화는 lnpl dialect) |
| O4 | SIMD | 한 명령이 여러 데이터 요소를 처리하도록 대상 명령을 선택한다 | LLVM |
| O5 | Lock Elimination | 불필요한 상호배제를 제거한다 — LNPP에서는 actor 직렬 메일박스(RFC-0003) 전제로 **락이 생성되지 않는 형태**로 이행된다 | lnpl dialect |
| O6 | Prefetch | 접근이 예정된 데이터를 미리 캐시 계층으로 끌어온다 | 표준 dialect(memref 접근 패턴) + LLVM |
| O7 | Vectorization | 루프를 벡터 폭 단위 연산으로 변환한다 | 표준 dialect(vector) + LLVM |
| O8 | Cache Optimization | 데이터 배치와 순회 순서를 CPU 캐시 지역성에 맞춘다 — 애플리케이션 캐시 계층(CacheAccess·`Performance.cache`)과 다른 개념이며 후자는 RFC-0003 계약이다 | 표준 dialect + LLVM |
| O9 | Branch Prediction | 분기 확률 힌트를 부여해 예측 실패 비용을 줄인다 — 힌트 원천은 lnpl dialect의 실패·재시도 경로 표시(cold)다 | LLVM |

## Examples

골든 시나리오 "Login"을 사용한다(정본: `plans/rfc-suite/plan.md` §골든 시나리오 —
RFC-0000 §5에 따라 참조만 하고 재정의하지 않는다). 인용하는 노드 id는
`examples/login.lir.json`의 실제 값이다: `svc.login`, `entity.user`, `wf.login`,
`wf.login.step.1`~`wf.login.step.6`, `wf.login.step.1.check`,
`wf.login.step.2.repo`, `wf.login.step.3.cache`, `policy.login`,
`security.login`, `perf.login`, `cap.postgres`, `cap.redis`, `cap.jwt`,
`event.user.created`.

### S3-1 Architecture Optimizer — before / after

입력 IR의 해당 노드는 구현체를 말하지 않는다. 예를 들어 `wf.login.step.2`가
소유한 Effect는 원문 그대로 다음이다:

```json
{ "kind": "RepositoryCall", "id": "wf.login.step.2.repo",
  "entity": "entity.user", "operation": "read" }
```

**after의 IR은 이 노드와 동일하다.** 스키마에 "구현체" 필드가 없고
`additionalProperties: false`이므로 바인딩을 노드에 써넣을 수 없다(§고수준 패스가
IR에 할 수 있는 변형). 결정은 컴파일 컨텍스트에 쌓인다:

| 노드 id | 결정 | 근거 |
|---------|------|------|
| `wf.login.step.2.repo` | `cap.postgres` 바인딩 — postgres 커넥션 pool 경유 read | `svc.login`의 `requires`에 `cap.postgres`가 있고 RepositoryCall은 저장소 Effect다 |
| `wf.login.step.3.cache` | `cap.redis` 바인딩, `set`의 TTL = `perf.login`의 `cache 5m` | CacheAccess는 캐시 capability에 묶인다. TTL 소유권은 Performance 제약에 있다(RFC-0001 CacheAccess 행 — 중복 지정 금지) |
| `wf.login.step.4` | `cap.jwt` 바인딩 — 토큰 생성 구현체 선택 | `security.login`의 `mechanisms` = `["jwt"]`를 이행하는 지점 |
| `entity.user`의 `password` 필드(Password 타입) | 로거·직렬화 파이프라인 **중앙 1곳**에 마스킹 필터 생성 | RFC-0003 §Observability의 마스킹 계약 — 콜사이트별 수동 마스킹은 계약 위반 |
| `svc.login` + `entity.user` | 자동 생성물 산출 지점: REST 표면·OpenAPI 문서·마이그레이션 | CHARTER §Auto Generation. 생성물은 IR 노드가 아니라 별도 산출물이다 |

### S3-2 Concurrency Optimizer — 병렬화 판정

`policy.login`의 `rules`는 `retry 3` / `rollback` / `timeout 3s`이며 `parallel`이
**없다**. 따라서 명시적 `parallel` 블록(Concurrency 노드)은 이 시나리오에 존재하지
않고, 이 패스가 하는 일은 자동 병렬화 판정뿐이다.

검토 후보: `wf.login.step.3`(`cache user`) ∥ `wf.login.step.5`(`audit login`).

**판정 = 거부.** 사유는 두 단이다.

1. **판정 정보 부족(1차).** `wf.login.step.5`의 원문은
   `{ "kind": "WorkflowStep", "id": "wf.login.step.5", "name": "audit login" }`
   뿐이다 — `children`이 없어 소유 Effect가 하나도 선언되지 않았다. 그래서 이 step의
   부수효과 집합이 **공집합인지 미상인지 IR에서 구분할 수 없고**, 판정 조건 1(데이터
   의존 없음)과 2(capability 인스턴스 미공유)를 어느 쪽으로도 확증할 수 없다.
   §자동 병렬화 판정 기준의 보수 규칙에 따라 후보에서 탈락한다. 같은 이유로
   `wf.login.step.4`·`wf.login.step.6`도 후보가 아니다.
2. **순서 의존(2차).** `wf.login`의 `children` 순서가 실행 순서다(RFC-0001 구조
   규칙 3). `audit login`은 선행 step들의 결과를 기록하는 감사 지점이므로,
   `cache user`와 순서가 뒤바뀌거나 겹치면 감사 기록이 관측하는 상태가 달라진다 —
   §실행 모드와 semantic equivalence의 동등성 대상 1(실행 순서)과 3(관측성 신호)을
   바꾸는 변형이다. 최적화는 관측 가능한 동작을 바꿀 수 없다.

**출력.** IR 변형 없음 — `wf.login`의 `children`은 `wf.login.step.1` … `.6` 6개
순서를 그대로 유지한다(M2·M3 미적용). 컴파일 컨텍스트에는
`wf.login.step.3 ∥ wf.login.step.5 → 거부(Effect 미선언 · 순서 의존)`이 기록된다.
판정 사유를 남기는 이유는, 나중에 IR이 보강되면 같은 쌍이 다시 판정 대상이 되기
때문이다.

**대조군 — 이 기준은 반대 방향으로도 갈린다.** 만약 `wf.login.step.5`가 Effect를
선언해 `{ "kind": "NetworkCall", "id": "wf.login.step.5.audit", "target":
"audit-service", "protocol": "http" }`를 소유하고, `wf.login.step.3`은
`cap.redis`만 쓴다고 하자. 그러면 조건 1(감사 호출의 입력이 캐시 쓰기 결과를 쓰지
않음)과 조건 2(`cap.redis` vs `audit-service` — 인스턴스 미공유)가 모두 확증되어
**판정 = 병렬화 후보**가 된다. 그 경우의 변형은 신설 WorkflowStep
`wf.login.par.1`(`name` = `parallel(cache user, audit login)`)이 Concurrency 노드
`wf.login.par.1.conc`를 소유하고 그 아래로 `wf.login.step.3`·`wf.login.step.5`를
옮기는 형태이며, **원 step의 id는 둘 다 그대로 유지된다**(재명명 금지). 같은 기준이
같은 쌍에 대해 IR 내용에 따라 거부와 수락으로 갈리므로, 이 판정 기준은 언제나 같은
답을 내는 장식이 아니다.

### S3-3 Memory Optimizer — 배치 결정

| 값 | 배치 | 근거 |
|----|------|------|
| `wf.login.step.2.repo`의 `read` 결과(User) | **Arena** | `wf.login.step.3.cache`의 입력으로 흘러 step 경계를 넘는다 — 기본 배치 |
| `wf.login.step.1.check`(Validation, `rule` = `Email`)의 판정 결과 | **Stack** | `wf.login.step.1` 안에서 생성·소비되고 밖으로 흐르지 않는다(탈출 없음이 확증됨) |
| `cap.postgres`·`cap.redis` 커넥션 | **Pool** | 배치가 아니라 획득·반환 지점 삽입 대상. `wf.login.step.2.repo`와 `wf.login.step.3.cache` 각각에서 operation당 1회 획득 후 반환 |
| `wf.login.step.4`·`wf.login.step.6`이 다루는 값 | **Arena**(폴백) | 두 step은 `children`이 없어 값 흐름을 IR로 확증할 수 없다 → Stack으로 승격하지 않고 Arena에 둔다 |
| (해당 없음) | **Heap** | 이 시나리오에는 발생하지 않는다. `event.user.created`는 Event **선언**만 존재하고 이를 발행하는 EventEmit 노드가 없으므로, workflow 실행 수명을 넘겨 생존해야 하는 값이 없다. 없는 사례를 만들지 않는다 |

`timeout 3s`(`policy.login`)는 arena 해제 시점과 무관하지 않다 — 데드라인 초과로
실행이 종결되어도 arena는 성공·실패·취소를 불문하고 일괄 해제된다(RFC-0003 arena
계약). 즉 배치 결정은 취소 경로에서도 누수를 만들지 않는다.

### 두 모드에서의 동일 관측

같은 `examples/login.lir.json`을 모드 A(S3까지)와 모드 B(S7까지)로 실행하면,
`wf.login.step.1` → `.6` 순서, `retry 3`의 재시도 판정, `timeout 3s` 초과 시
`TimedOut` 종결, trace의 step = span 구조, `password` 마스킹이 동일해야 한다.

**배치 결정 자체는 두 모드에서 갈리지 않는다** — S3은 두 모드가 공유하는 단계이므로
`wf.login.step.2.repo`의 read 결과는 양쪽 모두 **Arena**다(탈출이 확증됨 —
§Memory 배치 규칙). 갈리는 것은 그 결정의 **실현 방식**이다: 모드 A는 인터프리터
자료구조로 arena 슬롯을 잡고, 모드 B는 S5~S7 하강에서 같은 슬롯을 레지스터나 스택
슬롯으로 승격할 수 있다. 이 차이는 **동등성 대상이 아닌** 쪽에 속한다 — 외부에서
관측되지 않기 때문이다.

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | CHARTER §Native Compiler 원문대로 Semantic IR에서 **직접 LLVM IR**로 하강 | LLVM IR은 저수준이라 Effect·Policy·Security 같은 고수준 시맨틱이 조기에 소실되고, "이 호출은 멱등한 저장소 읽기라 재시도 가능"류의 판단을 되살릴 수 없다. MLIR 경유가 고수준 정보 보존 + 하부 생태계 재사용을 동시에 준다(`docs/RESEARCH-NOTES.md` §3, plan.md D18) |
| 2 | 인터프리터만 두고 네이티브 백엔드를 포기 | CHARTER의 목표(네이티브 산출·JVM 부재)를 포기하는 것이다. 단 *순서*는 인터프리터 우선이 맞다 — plan.md D14가 MVP를 인터프리터로 고정했고 이 문서는 그것을 모드 A로 명세했다 |
| 3 | 고수준 최적화 3종을 Semantic IR 레벨 없이 **MLIR dialect 패스로만** 수행 | 두 가지를 잃는다. ① `lir.schema.json` 유효성과 문서 수준 불변식이라는 **기계 검증 가능한** 불변조건 — dialect 안에서는 S2 재실행으로 반증할 수단이 없다. ② 모드 A가 최적화된 IR을 실행할 수 없게 되어 두 모드의 갈림점이 S1 직후로 밀리고, 동등성 검증의 범위가 그만큼 줄어든다 |
| 4 | 패스마다 노드 `id`를 재명명·정규화(연속 번호 부여 등) 허용 | 역추적(최종 산출물 → 원 노드)과 노드 단위 diff·fragment 교환(plan.md D17)이 함께 붕괴한다. 에이전트가 IR 조각을 주고받는 전제가 id 안정성이므로, 정규화의 이득보다 잃는 것이 크다 |
| 5 | 추적식 GC를 도입해 배치 결정을 런타임에 위임 | RFC-0003이 arena/pool 계약으로 그 자리를 이미 대체했고(§Alternatives), 컴파일 시점에 결정 가능한 것을 런타임 추적 비용으로 바꾸는 것은 CHARTER §Runtime의 "GC 최소화"에 역행한다 |

## Open Questions

> **S4 구현 완료 (2026-08-01) — 이탈 해소.** 이전 판은 "참조 구현의 모드 B가 커스텀
> `lnpl` dialect를 거치지 않고 표준 dialect를 직접 방출하며, 등록에는 MLIR 개발
> 라이브러리를 대상으로 한 C++ TableGen 빌드가 필요하다"고 적었다. **그 전제는 틀렸다.**
> MLIR의 **IRDL**(`irdl` dialect + `mlir-opt --irdl-file`)로 dialect를 선언적으로 정의해
> 표준 `mlir-opt`에 등록할 수 있으므로 C++ 빌드도 cmake도 필요하지 않다. (개발
> 라이브러리·`mlir-tblgen`·`MLIRConfig.cmake`는 실측해보니 실제로 존재하기도 했으나,
> IRDL 경로에서는 그 사실 자체가 무관하다.) 따라서 새 빌드 의존성은 **없다** — 모드 B의
> 전제 조건은 여전히 `brew install llvm` 하나다.
>
> dialect 정의는 `mlir/lnpl.irdl.mlir`이 소유하고, op 목록·역추적 표기는 아래 Open
> Question ②에 기록했다. 실측된 하강 경로는
> `IR → lnpl dialect MLIR (검증됨) → 표준 dialect MLIR → (mlir-opt: scf→cf→llvm) →
> LLVM dialect → (mlir-translate) → LLVM IR → (clang) → 네이티브 바이너리`이며, 모드 A/B
> 차동 검증은 관측 가능 4종에 대해 EQUIVALENT를 유지한다(`impl/lnpl/differential.py`).
>
> **S4 산출물은 장식이 아니다.** `build()`는 `module.lnpl.mlir`을 기록한 뒤 그 파일에
> dialect 검증기를 돌리고, 검증에 실패하면 `BackendError`로 중단해 바이너리를 만들지
> 않는다 — 이 문서가 S4 불변조건으로 규정한 "실체화되지 않은 결정은 유실이며 변환 실패로
> 취급한다"의 이행이다.
>
> **역추적 두 경로의 강제 수준은 다르다.** `lnpl.node_id`의 존재와 문자열 타입은 IRDL의
> `irdl.attributes`로 **검증기가 강제**한다. 그러나 **Location 경로는 강제되지 않는다** —
> IRDL은 attribute를 제약할 뿐 location을 제약할 수 없으므로, `loc(...)`가 없거나 값이
> 틀린 op도 검증기는 통과시킨다. 그쪽은 방출 시 항상 붙이고 테스트로 내용까지 대조하는
> 수준이다. 이 문서가 §역추적에서 Location을 "attribute가 discardable하므로 두는 durable한
> 경로"라 규정한 것과 비교하면, 실제로는 durable하다고 규정한 쪽이 기계 강제가 약하다.
>
> **남은 한계 4종 (설계 선택이 아니라 실제 공백이다).**
>
> ① **S5 하강은 lnpl 모듈을 재파싱하지 않는다.** `emit_lnpl_mlir`(S4 텍스트)과
> `_render_std`(S5 표준 dialect)는 같은 **op 스트림**(`_lnpl_ops`)의 두 렌더링이며, 하강은
> 그 인메모리 구조를 소비한다. 즉 S5의 입력은 직렬화의 *원본*이지 재파싱된 산출물이
> 아니다. Python MLIR 파서를 새로 쓰지 않기 위한 선택이고, 그 대가로 두 렌더링이 어긋날
> 수 있는 여지가 생기므로 ⓐ 위 검증 게이트와 ⓑ 두 렌더링의 step/effect 개수·node_id
> 순서를 대조하는 테스트로 막았다. 하강을 진짜 MLIR `ConversionPattern`으로 만드는 것은
> 별도 이슈다.
>
> ② **S3 컴파일 컨텍스트 side table이 참조 구현에 존재하지 않는다.** 따라서 "컨텍스트
> 항목을 전부 op attribute로 실체화한다"는 S4 불변조건은 현재 **방출 시점에 실재하는
> 컴파일 결정에 대해서만** 충족된다 — guard mode, guard condition, unroll round,
> 조건필드 목록. 없는 side table을 만들어 채우지는 않았다.
>
> ③ **구조 노드(`Guard`·`Concurrency`·`Pipeline`)의 id가 lnpl 모듈에 실리지 않는다 —
> §역추적 보존 규칙 2(다:1 병합은 전 id를 보존하며 하나만 남기고 축약하지 않는다) 위반이다.**
> `_steps_in_order`가 이 노드들을 평탄화하면서 `WorkflowStep`만 남기므로, 실측하면
> `wf.w.guard.1`·`wf.w.parallel.1` 같은 id는 산출물에서 사라진다(guard의 mode·condition
> 자체는 `lnpl.step`에 병합되어 살아남는다). 이 문서의 판정 문장("최종 산출물의 임의
> 지점에서 원 IR 노드 id를 최소 1개 이상 얻을 수 있다")은 여전히 성립하므로 역추적 요구의
> 전면 실패는 아니지만, 보존 규칙 2는 지켜지지 않는다.
>
> ④ **dialect가 Concurrency를 표현하지 못한다.** op이 2종(`lnpl.step`·`lnpl.effect`)이고
> region이 없으므로, `parallel` 블록을 쓴 워크플로우와 같은 step을 순차로 쓴 워크플로우는
> **바이트 동일한 lnpl 모듈**을 낸다(실측). 즉 S5 불변조건의 "structured concurrency
> 4조건 보존"은 S4 산출물 안에서 표현 자체가 불가능하고, ①의 후속 작업(하강을 lnpl 모듈
> 재파싱으로 바꾸는 것)만으로는 복구되지 않는다 — region을 갖는 op(예: `lnpl.concurrency`)
> 추가가 함께 필요하다. 현재 파이프라인이 `async` dialect를 쓰지 않아 실동작에는 영향이
> 없으나, 이 공백은 `async` 하강을 착수할 때 선행 해소 대상이다.



1. **MLIR/LLVM 버전 고정 정책.** 어떤 형식의 핀 파일로 무엇을 고정할지는 미결이다.
   다만 형태는 지금 정한다: 버전은 **레포에 커밋된 핀 파일 하나를 정본**으로 하고
   CI가 그 파일을 읽는다. README 산문으로 "LLVM 18을 설치하라"고 쓰거나 CI 워크플로
   안에 버전을 다시 적는 방식은 채택하지 않는다 — 선언이 둘이면 언젠가 갈라진다.
2. ~~**`lnpl` dialect의 커스텀 op 목록 확정**과 MLIR 위치 정보 API의 정확한 표기.~~
   **해소 (2026-08-01).** 정본은 `mlir/lnpl.irdl.mlir`이다.
   - **op 목록** — `lnpl.step`, `lnpl.effect` 2종. operand·result 없이 attribute로
     정보를 싣고, 모듈 본문에 flat하게 놓인다(`builtin.module`이 `NoTerminator`이므로
     region·terminator 배선이 필요없다). guard는 region이 아니라 **attribute**다 —
     `_steps_in_order`가 S4에 도달하기 전에 이미 평탄화·언롤을 끝내기 때문이다.
     attribute: `lnpl.node_id`(필수·문자열), `lnpl.name`, `lnpl.index`, `lnpl.kind`,
     `lnpl.step`, `lnpl.guard_mode`, `lnpl.guard_condition`, `lnpl.unroll_round`.
     선언되지 않은 attribute는 IRDL이 통과시키므로, 새 컴파일 결정을 추가할 때
     dialect 정의를 고칠 필요가 없다.
   - **Location 표기** — `loc("<node id>")`(NameLoc)를 모든 op에 단다.
     `lnpl.node_id` attribute와 이중 경로다(§dialect 변환 이후의 역추적).
     주의: `mlir-opt`는 `--mlir-print-debuginfo` 없이는 `loc(...)`를 아예 출력하지
     않으므로, 라운드트립으로 Location 보존을 확인하려면 그 플래그가 필요하다.
   - **강제 수단** — `irdl.attributes`가 `lnpl.node_id`를 필수로, `irdl.base
     "#builtin.string"`이 문자열로 제약한다. node id가 없거나 문자열이 아닌 op은
     검증기가 거부한다.
   - 언롤된 op은 전부 같은 `lnpl.node_id`를 유지하고 `lnpl.unroll_round`로 구분한다
     (§역추적 보존 규칙 3의 1:다 확장). `until`과 `repeat` 양쪽에 적용된다.
3. **증분 컴파일의 단위.** 노드 `id`가 안정적이므로 id 단위 캐시가 가능해 보이지만,
   컴파일 컨텍스트가 노드 간 결정에 의존할 때의 무효화 범위가 미결이다.
4. **디버그 정보 포맷.** IR 노드 id ↔ DWARF 매핑 방식(S7 불변조건이 의존한다).
5. **자동 최적화 9종의 알고리즘 상세.** 이 문서는 정의 1줄과 발생 레벨까지만
   고정했다.
6. **escape analysis의 정밀도.** Semantic IR v0.1에는 값의 명시적 데이터 흐름
   노드가 없어(RFC-0001은 값 노드를 두지 않는다) 판정이 step 경계 기준의 보수적
   근사에 머문다. 명시적 데이터 흐름 표현을 IR에 도입할지는 RFC-0001의 개정
   사항이며, 도입 전까지 Stack 승격 범위는 좁게 유지된다.
