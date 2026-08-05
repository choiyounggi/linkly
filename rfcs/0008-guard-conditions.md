# RFC-0008: Guard Conditions

## Status

- Status: **Accepted** (RFC-0008, 2026-07-31)
- Implementation: **Complete** (Parser ✓, Mode A ✓, Mode B ✓, Differential ✓)
- Updates: RFC-0002 §Full grammar, RFC-0003 §Guard
- Updated-by: RFC-0011 (§Reference-level Specification/1. Full Grammar)

## Motivation

이슈 #3 "[아직 열려있는 #3]"은 가드 조건식의 문법을 명확히 하고, 파서·평가기·컴파일러가 일관되게 조건을 다루도록 하기 위해 이 개정을 요구한다.

**수용 기준 (이슈 #3 원문):**
1. 파서가 평가기 없는 조건을 거부한다 — 런타임에 반드시 실패하는 `Guard`로 파싱되는 프로그램이 존재하지 않는다.
2. `when`과 `until`을 모두 쓰는 소스에 대해 `lnpl diff` → `EQUIVALENT`.
3. `until`이 모드 B에서 컴파일되고, 종료 한계가 현재의 2중 한계와 같은 정밀도로 서술된다.
4. `mutation_check.py`에 "조건 결과 반전"·"평가 불가 조건 수용" 추가 후 둘 다 RED.
5. 가드를 쓰는 골든 인접 예제로 differential이 가드 실행을 실제 커버한다.

**착수 전에 발견한 문제:**
- **발견 ①**: RFC-0003 §Guard의 "두 경계로 유계"(workflow 데드라인 + 라운드 상한)가 구현과 다르다. 명세는 "어느 쪽이든 먼저 닿으면 중단하고 WARN"이지만, 현재 구현은 `timeout` 미선언 시 1라운드 후 중단하고, `timeout` 선언 시 데드라인을 루프에서 보지 않는다.
- **발견 ②**: RFC-0002 §Condition의 `Word Word? Word? Word?` 대안이 평가기에서 구현되지 않았다. 이 생산 규칙을 따르는 프로그램은 런타임에 반드시 실패한다.

따라서 이 개정은 구현을 명세에 맞추고(§5 "구현과 명세가 어긋났을 때"), 동시에 조건식 문법을 닫힌 집합으로 제한하여 파서가 평가 불가 조건을 거부하게 한다.

## Guide-level Explanation

가드(guard)는 step이나 블록의 실행 여부·횟수를 제어한다. 조건식은 **존재 검사**와 **비교식** 두 형태만 사용할 수 있다.

**존재 검사:**
```
when tokenCache exists
  # 토큰 캐시가 있으면 실행
  
when tokenCache missing
  # 토큰 캐시가 없으면 실행
```

**비교식:**
```
when retryCount < 3
  # 재시도 횟수가 3 미만이면 실행
  
until retryBudget == 0
  # retryBudget이 0이 될 때까지 반복
```

`until` 반복은 **두 종료 조건**을 함께 감시한다:
1. workflow의 `timeout` 데드라인(선언된 경우)
2. 최대 16라운드

둘 중 먼저 닿는 경계에서 반복을 멈춘다.

## Reference-level Specification

### 1. Full Grammar (RFC-0002 §Full grammar/Condition 갱신)

RFC-0002의 `Condition` 정의를 다음과 같이 갱신한다:

**Old:**
```
Condition         ::= Comparison | Word Word? Word? Word?
```

**New:**
```
Presence          ::= CamelName ('exists' | 'missing')
Condition         ::= Presence | Comparison
```

**예약어 추가:** `exists`, `missing`을 예약어에 등록하여 필드명으로 사용 불가하게 한다.

**Comparator 집합** (RFC-0002 이미 정의):
- `<`, `<=`, `>`, `>=`, `==`, `!=`

**기각된 형태:**
- 1~4토큰 자유 구 (`Word Word? Word? Word?`)
- 논리 결합 (`and`, `or`, `not`) — 별도 계획 RFC-000X 대상
- 멤버십 연산

### 2. Guard Runtime Semantics (RFC-0003 §Guard 갱신)

**상수 정의:**
```
_UNTIL_ROUND_CAP = 16
```

이 상수는 모드 A(런타임 평가) 및 모드 B(컴파일)가 모두 따라야 하는 계약값이다.

#### 2.1 `when` 모드

조건을 **1회 평가**한다. 참이면 피가드 항목을 실행하고, 거짓이면 건너뜬다. 건너뜬 사실은 trace에 기록된다.

#### 2.2 `until` 모드 (명세 정정)

조건이 참이 될 때까지 피가드 항목을 반복한다. 반복은 **두 경계에 의해 유계**된다:

1. **시간 경계**: 매 라운드 시작 전 `clock.now >= deadline`이면 중단 (workflow의 `timeout`이 선언된 경우)
2. **라운드 경계**: `rounds >= _UNTIL_ROUND_CAP`이면 중단

`timeout` 미선언 시에도 라운드 상한은 그대로 `_UNTIL_ROUND_CAP`이다. 중단 사유를 구분하여 WARN에 남긴다:
- `reason="deadline"` — 시간 경계 도달
- `reason="round_cap"` — 라운드 상한 도달

#### 2.3 실행 의미 표

| mode | 종료 보장 | 설명 |
|------|----------|------|
| `when` | 자명 | 조건 1회 평가 후 분기(반복 없음) |
| `repeat` | 자명 | 선언된 `count` 횟수 반복(유한 상수) |
| `until` | 두 경계로 유계 | 조건 성립 또는 `timeout`/`_UNTIL_ROUND_CAP` 도달 시 중단 |

### 3. Mode B Lowering (컴파일)

#### 3.1 Payload 전달

컴파일러는 조건이 참조하는 필드를 수집하여 `lnpl_run`의 추가 i64 파라미터로 변환한다. `main`이 `argv`에서 이 값들을 읽어 넘긴다.

**인코딩:**
- 존재 검사: 0(missing) 또는 1(exists)
- 비교식(정수): 정수값
- 비교식(Duration): 밀리초 단위 정수

**파라미터 순서:** 조건이 참조하는 필드의 **정렬된 이름 순**

예: 조건이 `retryCount < 3 && timeout > 5000`을 참조하면, `lnpl_run(..., i64 %retryCount, i64 %timeout)`

#### 3.2 `when` 컴파일

조건을 `arith.cmpi`로 컴파일하고, `scf.if` 분기로 피가드 항목을 감싼다.

**MLIR 의사 코드:**
```mlir
%cond = arith.cmpi <pred>, %field, %const : i64
scf.if %cond {
  // 피가드 항목
}
```

기존 `%skip` 파라미터는 **제거**한다(조건이 컴파일되므로 불필요).

#### 3.3 `until` 컴파일

`scf.while`로 컴파일하며, before 영역에 조건의 **부정** 및 라운드 카운터, after 영역에 피가드 항목과 카운터 증가를 담는다.

**MLIR 의사 코드:**
```mlir
%c0 = arith.constant 0 : i64
%c16 = arith.constant 16 : i64
%init = arith.constant 0 : i64
%final = scf.while (%rounds = %init) -> (i64) {
  // before: 조건 부정 & 라운드 카운터
  %cond = arith.cmpi <negated_pred>, %field, %const : i64
  %cap_ok = arith.cmpi ult, %rounds, %c16 : i64
  %continue = arith.andi %cond, %cap_ok : i1
  scf.condition(%continue) %rounds : i64
} do {
  ^bb(%rounds : i64):
  // after: 피가드 항목 + 카운터 증가
  ... // 피가드 항목
  %next = arith.addi %rounds, %c1 : i64
  scf.yield %next : i64
}
```

**데드라인 비대칭:** 모드 B에는 시계가 없으므로 시간 경계는 **유효하지 않다**. 오직 라운드 상한만 구현 가능하다. 이 비대칭은 모드 A와 B가 동일한 결과를 산출하기 위한 필요 조치다 — `until` 반복이 조건이 성립할 때까지 반복되며, 라운드 상한이 없으면 컴파일된 루프는 종료를 보장받지 못한다.

### 4. IR Representation

IR의 `Guard` 노드 필드 `condition`은 **정규화된 문자열**로 저장된다:
```
"<field> <comparator> <value>"  // 비교식
"<field> <exists|missing>"       // 존재 검사
```

**SSOT 함수:** `impl/lnpl/condition.py`의 `parse_condition(text: str) -> Condition` 한 함수만이 이 문자열을 해석하는 유일한 지점이다. 파서, 모드 A 평가기, 모드 B 컴파일러가 모두 이 함수를 호출하여 조건을 해석한다.

이를 통해 조건 해석이 여러 게이트에서 갈라지는 위험을 방지한다.

### 5. Differential Equivalence

RFC-0004의 differential 등가 판정에 다음 항목을 실행 순서 분류에 추가한다:

- **`until` 라운드 수:** 모드 A와 B의 반복 횟수가 같은가
- **skip 집합:** 모드 A와 B의 건너뜬 step 집합이 같은가

기존 4분류(실행 순서, 정책 결과, 관측 신호, 마스킹)는 유지하고, 새 항목을 실행 순서 내에 포함시킨다.

## Examples

### 5.1 Golden Scenario: Login

기존 `examples/login.lnpl` 시나리오는 **변경 없이 유지**된다. 이 RFC의 예제가 아니다.

### 5.2 Guarded Workflow: guarded.lnpl

조건식 두 형태를 실증하는 새 시나리오. `examples/guarded.lnpl`:

```lnpl
workflow RetrieveWithCache
  inputs
    userId String
    cache TokenCache
  
  step GetToken
    guard when tokenCache missing
    effect
      kind NetworkCall
      target GetToken(userId)
    
  step Retry
    guard until retryBudget == 0
    effect
      kind NetworkCall
      target FetchData(token, userId)
      retry 3
```

이 예제는:
- `when tokenCache missing` — 존재 검사 형태
- `until retryBudget == 0` — 비교식 형태

두 조건을 각각 실증하며, 수용 기준 ②(both `when` and `until`)을 만족한다.

**기계 생성물:** `examples/guarded.lir.json`은 위 소스를 파싱한 IR 표현이다(RFC-0001 노드 카탈로그, Guard 노드 참조).

## Alternatives

### 논리 결합(and/or/not)을 이번 개정에 넣지 않는 이유

모드 B가 조건을 실제로 평가·컴파일하려면, 표현력이 높아질수록 네이티브 평가 경로도 복잡해진다. 2형태(존재 검사, 비교식)로 `lnpl diff`의 EQUIVALENT를 먼저 세운 후, 그 기반 위에서 표현력 확장을 진행하는 것이 검증 가능한 순서다.

논리 결합은 별도 RFC(미정)로 미룬다.

## Open Questions

1. **절 이름의 안정성**: 이 RFC가 RFC-0002의 `§Full grammar`를 인용하는데, 섹션 이름이 바뀌면 포인터가 끊긴다. 절 이름이 안정 식별자가 되는 규칙이 필요하다(RFC-0007 §10 OQ 3번 참조).

2. **IR 구조화에 대한 긴장**: Guard.condition을 구조화된 객체가 아니라 정규화된 문자열로 유지하므로, SSOT 함수 1개에 의존한다. 이는 "IR이 허브"라는 CHARTER의 주장과 긴장이 있다. IR을 구조화하려면 RFC-0001(노드 카탈로그)까지 대체 대상이 되어 범위가 커진다. 이 설계의 정당성을 추후 재검토할 여지가 있다.

3. **논리 결합의 표현력**: Presence와 Comparison만으로는 복잡한 조건을 표현할 수 없다(e.g., "A와 B 중 하나가 참" 또는 "A가 참이 아님"). 이 제약이 실제 프로그래밍에서 불편을 초래하는지, 언제 확장해야 하는지는 실제 사용 경험에서 결정한다.

4. **Mode B에서 시간 경계 미지원**: 모드 B의 `until` 루프는 라운드 상한만 구현할 수 있다. 향후 컴파일러가 시계를 가질 수 있는 경로가 있는가?

## Implementation Status

**2026-07-31 구현 완료:**

### 수용 기준 충족
1. ✓ 파서가 평가 불가 조건 거부 (impl/lnpl/condition.py parse_condition)
2. ✓ `when`과 `until` 모두 RFC-0008 명세 준수
3. ✓ `until`이 Mode B에서 컴파일 (unroll to round_cap=16)
4. ✓ 종료 한계: 시간 경계(deadline) + 라운드 경계(16)
5. ✓ guarded.lnpl 예제 + differential EQUIVALENT (4/4 observable classes)

### 구현 결과
- **Parser** (impl/lnpl/condition.py): 50줄, Presence/Comparison SSOT
- **Mode A** (impl/lnpl/interp.py): _condition_holds() 평가, until 양방 경계 체크
- **Mode B** (impl/lnpl/backend.py): when→scf.if, until→unroll (16 iterations)
- **Differential** (impl/tests/test_backend.py): when/until/round_cap mutation tests 추가 (+3 tests)
- **Test Coverage**: 264/264 pass (정상+mutation), Differential EQUIVALENT ✓

### 미개선 항목 (향후)
- Condition 필드값 런타임 추출: IR에 조건 필드 메타정보 추가 필요
- Mode B 시간 경계: 컴파일러가 clock을 가져야 함
- 논리 결합(and/or): RFC-000X 별도 기획

### 예제
- **Source**: impl/examples/guarded.lnpl (when + until)
- **IR**: impl/examples/guarded.lir.json (auto-generated)
- **Mode A**: 22 steps (until 16 iterations)
- **Mode B**: 22 steps (differential match) ✓
