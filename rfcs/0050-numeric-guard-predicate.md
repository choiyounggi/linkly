# RFC-0050: 숫자 형태 가드 술어 — `is-numeric` / `is-not-numeric`

## Status

- Status: Draft
- Updates: RFC-0015 §1, RFC-0028 §Reference-level Specification/1. Full Grammar,
  RFC-0014 §Reference-level Specification/2.4 스킵 레코드,
  RFC-0028 §Reference-level Specification/4. Guard Runtime Semantics (2.4),
  RFC-0028 §Reference-level Specification/6. Mode B

RFC-0007 §2.2 규칙 5(연쇄 갱신)에 따라 대상 RFC와 **직전 갱신 RFC를 모두** 지목한다.

- **문법(RFC-0015 §1).** `Condition`/`Presence`/`Comparison` 생산 규칙은 RFC-0015
  §1 원문이 지금도 유효한 기준선이다 — RFC-0028 §1은 같은 §1의 `Guard`/`ArithOp`만
  갱신했고 나머지는 "손대지 않는다"고 명시했다. 그래도 §1이라는 절은 이미 RFC-0025
  §2와 RFC-0028 §1이 갱신한 절이므로, RFC-0028이 자기 차례에 RFC-0025를 함께
  지목했던 선례 그대로 **직전 갱신 RFC인 RFC-0028 §1**을 함께 지목한다.
- **스킵 레코드(RFC-0014 §2.4).** RFC-0014 §2.4는 RFC-0027 §6이 마스킹 범위를,
  RFC-0028 §4가 §2 전체(§2.1·§2.4·§2.6)를 갱신했다. 이 문서는 §2.4의
  `evaluations` 행만 바꾸므로 §2.4 하나를 지목하고, 직전 갱신인 RFC-0028 §4를
  함께 지목한다. §2.1·§2.2·§2.3·§2.5·§2.6은 손대지 않는다.
- **모드 B(RFC-0028 §6).** RFC-0028이 신설한 절이고 이번이 첫 갱신이다 — 지목할
  직전 갱신 RFC가 없다.

이 RFC는 Draft다. RFC-0007 §2.2 규칙 6에 따라 Updates RFC는 Accepted가 되는 순간
효력이 생기므로, 대상 RFC(RFC-0014/RFC-0015/RFC-0028)의 `Updated-by:` 줄과 절 머리
포인터 줄은 **승격 시점에** 단다(RFC-0049 선례와 같다).

지목하지 **않는** 것:

- RFC-0015 §4 / RFC-0028 §2(값 도메인과 실패 표). **비수치 값의 비교는 여전히
  `RunError`다** — 이슈 #177이 그 행을 의도된 계약이라 적었다. 술어는 그 표에 행을
  더하지 않는다: 술어는 어떤 값에 대해서도 실패하지 않으므로(§3) 실패 표의 대상이
  아니다.
- RFC-0015 §3(정적 거부 표). 술어의 필드가 받는 정적 판정은 기존 참조 판정 그대로다
  (§2) — 새 거부 클래스가 없다.
- RFC-0038 §2(`list where` 술어 IR). 그 IR은 `{field, op, value}` 비교만 구조화한다.
  `list where`가 이 술어를 존재 검사와 똑같이 거부하는 것(§2)은 그 절의 기존 범위
  안이다.

번호가 0050인 이유: 0049까지 점유됐다(RFC-0049). RFC-0007 §3은 번호 재사용을
금지한다.

## Motivation

probe-v0.8 s2의 발견 F-5(blocker, 이슈 #177): 외부 환율 API 응답을 받아 정상이면
실시간 경로, 아니면 대체 경로로 보내는 프로그램을

```
call Fx as fxResult
when fxResult.status == 200 and fxResult.rate >= 0
    ...           # 실시간 경로
when fxResult.status != 200
    ...           # 대체 경로
```

처럼 쓰면 컴파일은 되지만, 응답의 `rate`가 `abc`처럼 숫자가 아닐 때 첫 가드의
비교가 `RunError: Cannot compare non-numeric fxResult.rate=abc`로 **실행 전체를**
rc=3으로 끝낸다. 대체 경로는 `status == 200`이라 발동하지 않는다.

비교가 비수치 값에 `RunError`를 내는 것은 RFC-0015 §4(RFC-0028 §2 갱신)가 정한
의도된 계약이다 — 숫자 비교를 조용히 거짓으로 만들면 오타난 필드와 진짜 거짓을
구분할 수 없다. 빠진 것은 **"이 값이 숫자인가"를 실패 없이 묻는 방법**이다. 오늘의
언어에는 `exists`/`missing`(존재) 말고는 값의 모양을 묻는 술어가 없고, `not`도
없다. 그래서 저자는 "응답 값이 숫자가 아니면 대체 경로"를 **표현할 수 없다**.

이 RFC는 그 술어 한 쌍을 더한다. 새 실패 클래스도, 새 결과 상태도 없다.

## Guide-level Explanation

```
<ref> is-numeric        # 값이 숫자로 읽히면 참
<ref> is-not-numeric    # 정확히 그 반대
```

`exists`/`missing`처럼 **두 낱말 한 쌍**이다 — 언어에 `not`이 없기 때문이다
(RFC-0028 §Alternatives). 낱말은 하이픈 포함 한 토큰이다(렉서는 공백으로만
자른다).

`exists`/`missing`과 달리 **`and` 안에 쓸 수 있다**:

```
when fxResult.status == 200 and fxResult.rate is-numeric
```

대체 경로는 `or` 대안 가드(RFC-0028)로 쓴다:

```
when fxResult.status != 200
or fxResult.rate is-not-numeric
```

`rate`가 `1350`이면 첫 가드만, `abc`이거나 응답에 아예 없으면 두 번째 가드만
실행된다. 어느 쪽도 `RunError`를 내지 않는다 — 비교(`>= 0`) 대신 술어로 물었기
때문이다. 술어가 참인 값을 비교에 쓰는 것은 여전히 안전하다: `is-numeric`이 참인
값은 비교가 `RunError`를 내지 않는 값과 정확히 같은 집합이다(§3).

선언된 엔티티 필드에 술어를 걸면, 비교와 같은 규칙으로 판정한다: `Integer`/
`DateTime` 필드는 받고, `Text`·`Money` 필드는 거부한다(RFC-0016). 타입이 문서에
없는 참조 — 입력 payload의 맨 이름, `caller.*`, `call ... as <name>` 네트워크
결과 — 는 받고 런타임에 판정한다. 외부 응답을 검증하는 것이 이 술어의 주 용도다.

## Reference-level Specification

### 1. Full Grammar — RFC-0015 §1 / RFC-0028 §1 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0015 §1의 `Condition`·`Presence` 생산
규칙과 "`and`는 비교식만 잇는다" 문단에 대한 **치환 후 최종 텍스트**다. 이 절의 다른
생산 규칙(`Comparison`/`Comparator`/`Value`/`Operand`/`Reference`/`Namespace`/
`Integer`/`Duration`, RFC-0025 §2가 갱신한 `AssignStep`/`Aggregate`/`AggFunc`,
RFC-0028 §1이 갱신한 `Guard`/`AltGuard`/`ArithOp`)은 각 원문의 최종형이 그대로
유효하다.

```
Condition    ::= Presence | Term ('and' Term)*
Term         ::= Comparison | NumericPred
Presence     ::= Reference ('exists' | 'missing')
NumericPred  ::= Reference ('is-numeric' | 'is-not-numeric')
```

**Old (RFC-0015 §1):**
```
Condition    ::= Presence | Comparison ('and' Comparison)*
Presence     ::= Reference ('exists' | 'missing')
```

- **`and`는 비교식과 숫자 형태 술어만 잇는다.** 모드 B는 존재 여부를 실행당 boolean
  하나(`run_binary(skip=…)`)로 판정하고 비교는 i64 파라미터로 판정한다. 한 조건에 두
  채널이 섞이면 모드 B가 모드 A와 다른 스텝 집합을 낼 수 있다. 그래서 존재 검사는
  여전히 단독 가드로 쓴다. 숫자 형태 술어에는 이 우려가 없다 — 모드 B에 그 술어의
  채널이 아예 없고, 술어를 쓴 워크플로는 모드 B가 빌드를 거부한다(§4). 섞일 두
  번째 컴파일 채널이 없다.

구현: `impl/lnpl/lexer.py`의 `NUMERIC_PREDICATE_KINDS = ("is-numeric",
"is-not-numeric")`와(같은 파일로 옮긴 `PRESENCE_KINDS = ("exists", "missing")`),
`impl/lnpl/condition.py`의 `NumericPredicate(field, kind)` 노드. 두 낱말은
참조 이름이 될 수 없다(`and`/`to`/`exists`/`missing`과 같은 예약). 정규화 문자열은
`<field> <kind>`이고, `and` 항 안에서도 소스 순서 그대로 ` and `로 이어진다 — IR의
`Guard.condition`은 여전히 문자열 하나다(RFC-0015 §2 불변, 스키마 변경 없음).

`lnpl vocab`(및 MCP `lnpl_vocabulary`)의 `keywords`는 `presence_kinds`와
`numeric_predicate_kinds`를 싣는다.

### 2. 정적 규칙 (신설)

술어의 참조는 비교의 참조와 **같은 함수**로 판정한다(`lower._check_one_condition`
→ `_Scope.check_reference`). 새 판정이 없다:

| 참조 | 판정 |
|------|------|
| 선언된 `Integer`/`DateTime` 필드 | 받는다 |
| 선언된 그 밖의 필드(`Text`, `Money`, …) | `LowerError` — "neither Integer nor DateTime" (RFC-0016, 비교·존재 검사와 동일) |
| 입력 payload의 맨 이름, `caller.*`, `call ... as <name>`의 필드 | 받는다 — 타입이 문서에 없으므로 런타임에 판정(RFC-0027 §2/§4) |
| 선언되지 않은 바인딩·필드 | 기존 참조 거부 그대로 |

`or` 대안(RFC-0028)은 각 대안을 같은 판정에 태운다 — 술어를 쓴 대안도 마찬가지다.

**`list <Entity> where <cond>`(RFC-0038)는 술어를 거부한다.** 그 술어 IR은 드라이버로
밀어 넣는 `{field, op, value}` 비교만 표현한다. 단독이든 `and` 항이든, 술어가 있으면
`LowerError`: "`list where` supports comparisons only (no `is-numeric`/
`is-not-numeric` predicates)". 존재 검사를 거부하는 기존 규칙과 같은 자리·같은 모양이다.

### 3. 런타임 판정 — 모드 A (신설)

`is-numeric(v)`는 **비교가 `RunError` 없이 수로 읽는 값**과 정확히 같은 집합에서
참이다 — 비교의 값 해석(`interp.eval_value`)의 여집합이 곧 `RunError`다.

| `v` (참조가 해소한 값) | `is-numeric` | `is-not-numeric` |
|------------------------|--------------|------------------|
| 참조가 아무것도 가리키지 않음 (`None`) | 거짓 | **참** |
| `bool` | 참 | 거짓 |
| `int` | 참 | 거짓 |
| `int()`로 읽히는 문자열 (`"1350"`, `"-3"`) | 참 | 거짓 |
| 시간대가 있는 instant 문자열 (`2026-09-28T10:00:00Z`, RFC-0016) | 참 | 거짓 |
| 시간대가 없는 instant 모양 문자열 (`2026-09-28T10:00:00`) | 거짓 | 참 |
| 시간대가 있지만 날짜가 유효하지 않은 문자열 (`2026-13-40T10:00:00Z`) | 거짓 | 참 |
| 그 밖의 문자열 (`"abc"`, `""`, `"13.5"`) | 거짓 | 참 |
| `dict`, `list`, 그 밖의 값 | 거짓 | 참 |

- **`is-not-numeric`은 모든 입력에서 `is-numeric`의 정확한 부정이다 — `None`
  포함.** 비교의 "참조 미해소 → 양쪽 다 거짓" 규칙(RFC-0015 §4)을 따르지 않는다. 그
  규칙은 null과 X의 대소가 어느 방향으로도 결정 불가능하기 때문에 있다. "숫자인가"는
  없는 값에 대해서도 결정 가능하다(아니다). 그래서 `exists`/`missing`처럼 진짜
  여집합 쌍이며, 이 덕분에 `or fxResult.rate is-not-numeric`이 응답에 `rate`가 아예
  없는 경우도 대체 경로로 보낸다.
- **술어는 실패하지 않는다.** 시간대가 없거나 날짜가 유효하지 않은 instant를 비교에
  쓰면 `RunError`가 나지만, 술어는 같은 인코더(`encode_instant`)의 거부를 "수로
  읽히지 않음"으로 분류한다.
- **i64 범위는 판정하지 않는다.** 범위 밖 정수 문자열은 `is-numeric`이 참이고, 그
  값을 비교에 쓰면 기존 "i64 범위 밖" `RunError`가 난다(§Open Questions 2).
- `and` 안의 술어도 다른 항과 똑같이 **전부 평가**한다(단락 평가 없음 —
  RFC-0028 §4 §2.1 불변).

### 4. Guard Runtime Semantics §2.4 — RFC-0014 §2.4 / RFC-0028 §4 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0014 §Reference-level Specification/2.4
(RFC-0028 §4가 갱신한 최종형)의 **치환 후 최종 텍스트**다. `evaluations` 행만
달라진다. 인용 안의 "§Reference-level Specification/N"은 RFC-0028의 절을 가리킨다.

#### 2.4 스킵 레코드 (갱신)

실행 결과는 **스킵 매니페스트**를 가진다. 피가드 항목을 실행하지 않은 가드마다
레코드가 하나씩, 가드를 만난 순서대로 들어간다.

| 필드 | 의미 |
|------|------|
| `guard` | 가드 노드의 IR id. 모드 A 전용 — 모드 간 비교에서 제외한다 |
| `mode` | `"when"` 또는 `"until"` |
| `condition` | **갱신**: 대안이 없으면 정규화된 조건 문자열 그대로(RFC-0008 §4 불변). 대안이 있으면 조건과 모든 대안을 소스 순서대로 `" or "`로 이어붙인 문자열 — `"input.channel == 1 or input.amount <= 100"`. 이 결합은 **표시/비교 전용**이며 `parse_condition`으로 재파싱되지 않는다(§Reference-level Specification/3) |
| `steps` | 그 가드가 감싼 **모든 WorkflowStep의 이름**, 선언 순서. 중첩 블록(`Concurrency`·`Pipeline`)까지 하강해 수집한다 |
| `rounds` | `when`이면 없음(`null`), `until` 0라운드면 `0` |
| `evaluations` | (issue #83, RFC-0014 원문 불변 필드) **갱신**: 대안이 있으면 조건 자신의 항들에 이어 각 대안의 항들도 소스 순서대로 같은 리스트에 담는다 — 어느 항이 어느 대안 소속인지는 이 리스트의 위치가 아니라 `ref`가 가리키는 값으로 읽는다(추가 태깅 없음, RFC-0014가 이미 "다섯 키는 불변"이라 적은 원칙을 존중해 `evaluations`의 원소 shape을 넓히지 않는다). **갱신 (RFC-0050)**: 숫자 형태 술어 항도 한 원소를 남긴다 — 존재 검사와 같은 모양으로 `{"ref": <필드>, "value": <해소한 값, 없으면 null>, "op": "is-numeric" 또는 "is-not-numeric", "expected": null, "holds": <판정>}`. `and` 안의 술어 항은 다른 항과 함께 소스 순서대로 담긴다 |

`condition`의 결합 표기는 `restore_skips`(모드 B 재구성)와 `_skip_record`(모드
A 실측)가 **같은 함수**로 만든다 — 이름은 §Reference-level Specification/5가
고정한다. 두 모드가 각자 결합하면 공백 하나의 실수가 `differential.verify`를
거짓 양성/거짓 음성으로 만든다.

**status 어휘는 변경되지 않는다** (RFC-0014 원문 불변).

### 5. Mode B — RFC-0028 §6 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0028 §Reference-level Specification/6의
**치환 후 최종 텍스트**다. 마지막 문단("숫자 형태 술어")이 새로 붙고, 그 앞은 RFC-0028
원문 그대로다. 인용 안의 "이 RFC"와 "§Reference-level Specification/N"은 RFC-0028을
가리킨다.

이 절은 `impl/lnpl/backend.py`의 **표현식 lowering**(S4/S5, `arith`/`scf`
방출)만을 규정한다 — clang 호출부·`tool()`·툴체인 경로(S7)는 이 RFC의 범위
밖이다(이슈 #93 dependencies, t104 소유).

**`*`/`/`는 가드 조건에만 닿는다 — Assignment 표현식에는 닿지 않는다.**
`_emit_operand`(`Arith` 분기가 사는 자리)의 유일한 호출자는
`_emit_condition`이고, `_emit_condition`의 유일한 호출자는 `_render_std`의
`when`/`until` 처리다. `Assignment.expression`은 `_lnpl_ops`가 `"lnpl.effect"`
마커 하나로만 방출하며 — 이름 그대로 문자열 하나, 파싱도 산술도 없다 — 이
경로는 RFC-0015가 `+`/`-`를 넣을 때도 손대지 않았다(§Differential
Equivalence "할당이 만든 값은 허용된 차이 — 모드 B는 저장소를 모형화하지
않는다"). 이 RFC도 그 경계를 넓히지 않는다: **DoD 1번의 예제
(`set order.total to product.price * input.quantity`)는 Assignment이므로,
모드 B에서의 EQUIVALENT는 여전히 "그 이름의 Assignment 효과가 있었다"는
사실만 검증한다 — 계산된 값(200)은 여전히 모드 A 단독 단언이다.** 이것은
새 제약이 아니라 `-`가 이미 서 있던 자리를 `*`가 그대로 따르는 것이다.

가드 조건 안에서 쓰인 `*`/`/`(예: `when product.stock * 2 >= input.min`)는
다르다 — 조건은 `condition_field_names`가 모든 참조를 i64 파라미터로
승격하므로(RFC-0008 G8), 그 필드가 저장 행에서 왔든 payload에서 왔든 모드 B
바이너리는 **실행 시점**에 실제 값을 받아 실제로 계산·비교한다. `_emit_
operand`의 `Arith` 분기(RFC-0015가 `+`/`-`에 이미 세운 것과 같은 자리)에
두 연산을 더한다: `*` → `arith.muli`, `/` → `arith.divsi`(부호 있는 절삭
나눗셈 — §Reference-level Specification/1의 "나눗셈은 절삭이다"가 바로 이
선택으로 실현된다).

**가드 조건에서 나눗셈이 0으로 평가되면.** `arith.divsi`는 0 나눗셈에 대해
정의되지 않은 동작이다(LLVM `sdiv`와 동형). 이것을 그대로 방출하면 컴파일된
바이너리가 크래시하거나 미정의 값을 낼 수 있다. 그런데 RFC-0015 §5가 이미
그은 경계 — **"값 차원은 모드 A가 단독으로 단언한다"** — 는 이 신설 값
실패에도 그대로 적용된다: 모드 B가 이 실패를 `RunError`/`failed`로
**보고할 의무는 없다**(오늘도 산술 오버플로·비수치 비교 같은 다른 값 실패를
보고하지 않는다 — 이 RFC 이전부터 있던 차동 경계이지, 이 RFC가 새로 뚫는
자리가 아니다). 모드 B의 유일한 의무는 **정의되지 않은 동작을 만들지
않는 것**이다: `/`를 방출하기 전에 오른쪽 피연산자가 0인지
`arith.cmpi eq`로 검사하고, 0이면 그 비교 항을 **거짓**으로 접어 넣는다
(참조가 아무것도 가리키지 않을 때 `false`로 접히는 §Reference-level
Specification/2의 "참조 미해소" 행과 같은 안전한 기본값 — 실패를 신호하는
값이 아니라 UB를 피하는 값이다). 이 분기는 `scf.if`로 `arith.divsi`
자체를 감싸 실행하지 않는 쪽을 택한다 — 정의되지 않은 연산은 계산 후 버리는
것이 아니라 애초에 실행하지 않아야 UB가 없다.

**따라서 DoD 2번(0 나눗셈 → RunError, status failed)의 차동 커버리지는
경계가 있다.** 정상 분모(0이 아닌)에서는 `*`/`/`를 쓴 가드 조건이 두 모드
합의를 내는지 차동으로 검증한다(§Reference-level Specification/7 D5).
분모가 실제로 0인 케이스는 — Assignment 경로든 가드 조건 경로든 — 모드 A만
`RunError`/`failed`를 단언하는 테스트로 남는다(오늘의 오버플로·비수치
RunError 테스트가 이미 그런 것과 같은 층위). 이것은 이 RFC의 결정이지
누락이 아니다 — §Alternatives에 기록한다.

**대안 가드.** `_emit_condition`은 단일 조건일 때 완전히 불변이다(SSA 이름
`%cond<idx>`/`%ucond<idx>`가 그대로 유지되어 `impl/tests/golden/*.std.mlir`의
동결 픽스처가 움직이지 않는다). 대안이 있을 때만 새 경로를 탄다: 조건과 각
대안을 독립적으로 `_emit_condition`에 태워 `%cond<idx>_0`, `%cond<idx>_1`, …
i1 SSA 이름을 얻고, `arith.ori`로 순서대로 접어 하나의 i1을 만든다. 대안 중
하나라도 `_emit_condition`이 `None`을 반환하면(Presence — 컴파일된 평가기가
없다, RFC-0015 §1 원문 불변) 전체가 `None`이 되어 기존 런타임 `%skip` 플래그
경로로 떨어진다 — OR의 한쪽이 컴파일 불가능한데 다른 쪽만 컴파일하면 그
쪽만 평가하고 트레이스가 조용해지는 결과를 낳는다(§2.1의 "전부 평가" 원칙과
모순). `condition_field_names`는 조건과 모든 대안의 참조 합집합을 모은다
(정렬 순서는 RFC-0008 G8 불변). `_render_std`의 리터럴 상수 수집(`cond_i64_
values`)도 조건과 모든 대안을 스윕한다. `_walk_markers`/`emit_lnpl_mlir`의
`lnpl.guard` 마커는 `lnpl.guard_alternatives`(문자열 배열, 대안이 없으면
생략) 속성을 추가로 싣는다 — `_mlir_attr`은 이미 리스트/튜플을 렌더링하므로
새 직렬화 코드가 필요 없다.

**숫자 형태 술어 (RFC-0050).** 모드 B는 `when`/`until` 가드의 조건이나 어느 `or`
대안에든 `NumericPredicate`가 있으면(단독이든 `and` 항이든) 그 워크플로의 빌드를
**거부한다** — `BackendError`가 스텝과 가드 텍스트를 이름으로 댄다. 술어에는 컴파일된
평가기가 없고, 존재 검사처럼 런타임 `%skip` 플래그로 떨어뜨리는 길도 택하지 않는다:
`differential._derive_skip_from_payload`는 워크플로에서 **첫 번째** 존재 검사 가드
하나만 평가하는데, F-5 프로그램은 술어를 쓰는 가드가 둘이다(실시간 경로의 `and` 항,
대체 경로의 대안). 섞인 `and`에서 `Comparison` 반쪽만 컴파일하는 것은 모드 A가
거부할 값을 모드 B가 받아들이는 발산이다 — 그래서 조용히 빼지 않고 거부한다.
`differential.verify`는 이 워크플로를 툴체인 확인보다 **먼저** 알아보고,
`DifferentialError`로 "RFC-0050 §Mode B 기록된 예외"라고 보고한다 — LLVM이 없는
환경에서도 같은 판정이 나온다. 술어를 쓰지 않는 워크플로의 MLIR은 바이트 단위로
그대로다(`impl/tests/golden/*.std.mlir` 불변).

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

골든 시나리오는 가드 술어를 쓰지 않는다. 이 RFC 뒤에도 `examples/login.lnpl`의 IR과
모드 B 출력은 바이트 단위로 같다.

### 골든 인접 예제 — F-5 외부 응답 검증 (RFC-0007 §6, 골든이 다루지 않는 기능)

```
capability postgres

entity Quote
    field
        id UUID

service QuoteService
    policy
        timeout 5s

workflow Convert
    call Fx as fxResult
    when fxResult.status == 200 and fxResult.rate is-numeric
    create quote
    when fxResult.status != 200
    or fxResult.rate is-not-numeric
    note "fallback"
```

- `status=200, rate=1350` → 첫 가드 참, `create quote` 실행. 두 번째 가드는 조건과
  대안이 모두 거짓이라 건너뛴다. `guard alternative matched` 로그는 없다(RFC-0028
  §4 §2.1 그대로 — 대안이 참이었던 적이 없다).
- `status=200, rate=abc` → 첫 가드의 `and` 항 `rate is-numeric`이 거짓이라 건너뛴다.
  두 번째 가드의 대안이 참이라 대체 경로 실행. 실행 상태 `completed`, `RunError`
  없음. 첫 가드의 스킵 레코드:
  ```json
  {"mode": "when",
   "condition": "fxResult.status == 200 and fxResult.rate is-numeric",
   "steps": ["create quote"], "rounds": null,
   "evaluations": [
     {"ref": "fxResult.status", "value": 200, "op": "==", "expected": 200, "holds": true},
     {"ref": "fxResult.rate", "value": "abc", "op": "is-numeric", "expected": null, "holds": false}
   ]}
  ```
- `status=200`, `rate` 없음 → `rate is-numeric` 거짓, `rate is-not-numeric` 참
  (§3의 여집합 규칙). `rate=abc`와 같은 경로.

### 컴파일 거부 — 존재 검사는 여전히 `and`에 못 들어간다

```
when fxResult.rate exists and fxResult.status == 200
```

→ `ConditionError`: "`exists` cannot appear inside `and`". §1이 바꾼 것은 `Term`에
술어를 더한 것뿐이다.

### 컴파일 거부 — 선언된 Text 필드

```
entity Product
    field
        id UUID
        name Text
...
    find product
    when product.name is-numeric
```

→ `LowerError`: "… neither Integer nor DateTime …" (§2).

## Alternatives

### `Presence`에 세 번째·네 번째 kind로 넣는 안 (기각)

`Presence(field, kind)`의 `kind`는 "`and` 안에 못 들어간다"는 규칙과 한 몸이다.
술어는 그 반대여야 하므로(§1), 같은 클래스에 넣으면 규칙에 kind별 예외가 생긴다.
"값이 있는가"와 "있는 값이 숫자 모양인가"는 다른 질문이다 — 클래스를 나눈다.

### 술어를 `and` 밖에만 두는 안 (기각)

존재 검사와 똑같이 단독 가드로만 허용하면 F-5의 실시간 경로(`status == 200` 그리고
`rate`가 숫자)를 한 가드로 쓸 수 없다. 중첩 블록으로 두 가드를 겹치는 우회는 이
문법에서 검증된 적이 없다. 존재 검사를 `and`에서 막는 이유(모드 B 두 채널의 혼합)는
술어에 적용되지 않는다(§1, §5).

### 모드 B에서 존재 검사처럼 `%skip` 플래그로 떨어뜨리는 안 (기각)

§5 참조. `%skip`은 실행당 boolean 하나이고, 그 값을 만드는
`_derive_skip_from_payload`는 첫 번째 존재 검사 가드 하나만 본다. 술어 가드가 둘인
F-5에서 두 모드가 합의한다는 증거가 없다. 거부는 증명이 필요 없다.

### 비수치 비교를 `RunError` 대신 거짓으로 만드는 안 (기각)

이슈 #177이 명시적으로 배제했다. 오타난 필드명과 진짜 비수치 응답이 같은 "거짓"이
되어 조용히 틀린다. 저자가 묻고 싶을 때 묻는 술어가 맞는 도구다.

### `not`을 넣고 `not <ref> is-numeric`으로 쓰는 안 (기각)

RFC-0028 §Alternatives가 `not`을 넣지 않은 이유(평가기 두 벌, 드모르간)를 그대로
잇는다. 존재 검사가 `exists`/`missing` 쌍으로 푼 것과 같은 방식으로 푼다.

## Open Questions

1. **Accepted 승격.** 이 RFC는 구현과 함께 Draft로 들어간다. 승격 시 RFC-0014/
   RFC-0015/RFC-0028에 `Updated-by:`와 절 머리 포인터를 단다(§Status).
2. **i64 범위.** 범위 밖 정수 문자열에 `is-numeric`은 참이다(§3). 필요가 생기면
   "비교에 써도 실패하지 않는다"로 좁힐지 후속에서 정한다.
3. **`until`/`repeat`의 대안 가드와 술어.** RFC-0028 §Open Questions 1이 미룬
   그대로다. `until <ref> is-numeric` 자체는 문법상 허용되고 모드 A에서 평가된다.
4. **`list where`의 술어.** 드라이버 푸시다운에 "숫자 모양" 판정이 없으므로 이번에는
   거부한다(§2). 요구가 생기면 RFC-0038 §2의 IR 확장으로 다룬다.
