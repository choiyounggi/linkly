# RFC-0019: 구조와 모순되는 들여쓰기의 거부

## Status

- Status: **Accepted** (RFC-0019, 2026-08-07)
- Updates: RFC-0002 §Block structure

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. 이 문서는 RFC-0002
§Block structure **한 절만** 갱신한다. §Full grammar의 생산규칙, §Lexical의
토큰 규칙, 부록 A의 lowering 매핑은 지목하지 않으며 어느 것도 바꾸지 않는다
(규칙 2) — 이 개정은 **어떤 토큰열이 어떤 구조로 파싱되는가**를 그대로 두고,
**어떤 프로그램이 수용되는가**만 좁힌다.

번호가 0018인 이유: 0017까지 점유되어 있다. RFC-0007 §3은 번호 재사용을 금지한다.

## Motivation

2026-08-07 재측정(`qa/rerun/cases/batch-report/FINDINGS.md`)이 무음 실패 2건을
보고했고(N-1·N-3), 그 수리 과정에서 같은 계보의 3번째(N-5)가 나왔다. 이 RFC가
다루는 것은 그중 **들여쓰기 없이는 탐지가 불가능한** 둘이다.

**N-1 — `repeat` 아래 다중 스텝의 무진단 분리.** 저자는 이렇게 쓴다.

```
workflow AccumulateAll
    read report
    repeat 3
        read order
        set report.totalAmount to report.totalAmount + order.amount
```

가드는 **바로 다음 항목 하나**를 소유한다(RFC-0008 §5.2). 따라서 `set` 줄은
반복 밖에서 한 번만 실행된다. 컴파일은 rc=0, 진단 0건이었고, IR의 repeat Guard는
children이 `read order` 하나뿐이었다. 저자는 누적 루프를 썼다고 믿는다.

**N-5 — `spec` 뒤에 쓴 스텝의 증발.** `WorkflowDecl ::= 'workflow' PascalName
EOL WorkflowItem* SpecClause?`이므로 항목은 spec 앞에 온다. spec 뒤에 쓴 스텝은
열려 있던 섹션에 흡수되어 워크플로 항목이 되지 못했고, 이 또한 rc=0 무진단이었다.

### 왜 토큰만으로는 닫을 수 없는가

N-1의 두 프로그램은 **토큰열이 완전히 같다.**

```
repeat 3              repeat 3
    read order            read order
                          set …
```

앞은 "한 스텝을 3회 반복", 뒤는 "한 스텝을 3회 반복한 뒤 다른 스텝을 1회". 후자는
**정당한 프로그램**이고 실제로 쓰인다(`examples/guarded.lnpl`이 같은 열 스타일로
가드를 쓴다). 즉 단일 스텝 반복을 계속 허용하는 한, 두 의도를 가르는 신호는
저자가 준 **열(column)뿐**이다.

### 왜 경고로는 부족한가

진단 채널(`impl/lnpl/diagnostics.py`)은 설계상 **종료 코드를 바꾸지 않는다** —
서술적 스텝이 정당한 작성법이므로 보고는 하되 거부하지 않는다. 무음 통과를
끝내는 것이 목적이므로 이 결함은 진단이 아니라 **거부**여야 한다.

### 왜 다중 스텝 반복을 정식 지원하지 않는가

새 블록 형태는 IR과 모드 B 하강까지 파급된다. 그런데 언어에는 **이미** 다중 스텝
블록이 있고 가드가 그것을 통째로 소유할 수 있다 — `pipeline`이다. 그래서 이
개정은 문법을 늘리지 않고, 이미 동작하는 철자를 가리키는 거부를 도입한다.

## Guide-level Explanation

**들여쓰기는 여전히 구조를 만들지 않는다.** 블록 경계는 계속 키워드가 정한다.
수용되는 두 프로그램의 토큰열이 같다면 구조도 같다 — RFC-0002 D5의 보장은
그대로다.

바뀌는 것은 하나뿐이다. 들여쓰기는 이제 프로그램을 **반증**할 수 있다. 저자가
어떤 줄을 가드 안에 있는 것처럼 들여썼는데 문법이 그것을 가드 밖에 두었다면,
그 프로그램은 컴파일되지 않는다. 조용히 저자의 의도와 다르게 실행되는 대신,
어디가 어긋났고 무엇으로 고치는지 말한다.

세 줄로 요약하면:

- 들여쓰기로 **구조를 만들 수는 없다** (이전과 같다).
- 들여쓰기로 **구조를 반박할 수는 있다** (이 개정이 더한 것).
- 레이아웃이 아무 말도 하지 않는 프로그램 — 전부 같은 열에 쓴 것 — 은 **영향받지
  않는다.**

고치는 법도 하나다. 여러 스텝을 반복하거나 조건 아래 두고 싶으면 `pipeline`으로
묶고 가드가 그 블록을 소유하게 한다.

```
workflow AccumulateAll
    read report
    repeat 3
        pipeline Accumulate
            read order
            set report.totalAmount to report.totalAmount + order.amount
```

## Reference-level Specification

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0002 §Block structure를 치환하는
**최종 텍스트 전문**이다.

---

### Block structure (RFC-0019 개정판)

1. **키워드 구획** — 블록 경계는 키워드가 정한다. 최상위 선언 키워드는 이전
   블록 전체를 자동 종결한다. 절 키워드는 소속 선언의 하위 구획을 열고, 다음
   절 키워드 또는 최상위 키워드에서 닫힌다. 명시적 종결 키워드를 가지는 블록은
   `parallel`(→ `merge`) 하나뿐이다.

2. **들여쓰기 비구조성** — 파서는 라인 선두 공백으로 블록을 만들지 않는다.
   관례 4칸·탭 금지는 style 권장일 뿐 문법이 아니다. **수용되는 모든
   프로그램에서, 같은 토큰열은 포맷팅과 무관하게 항상 같은 구조로 파싱된다.**

3. **모순 들여쓰기의 거부** — 다만 들여쓰기가 2항이 정한 구조와 **모순되는**
   프로그램은 수용 집합에서 제외한다(컴파일 에러). 들여쓰기는 구조를 만들지
   못하고 오직 프로그램을 반증할 수만 있으므로, 2항의 보장은 유지된다.
   모순은 다음 둘이며, 이 목록은 닫혀 있다.

   a. **가드 스코프 모순.** 가드(`when`/`until`/`repeat`)가 자기보다 깊은 열의
      항목을 소유할 때, 그 가드 다음에 오는 첫 최상위 항목이 여전히 가드보다
      깊은 열에 있으면 거부한다. 가드는 항목 하나만 소유하므로(RFC-0008 §5.2)
      그 항목은 가드 밖에서 실행되는데, 열은 안에 있다고 말하기 때문이다.

   b. **spec 꼬리 모순.** `spec` 절의 섹션(`given`/`when`/`expect`)이 `spec`보다
      깊은 열에 있을 때, 그 블록 안의 내용 줄이 `spec`과 같거나 더 얕은 열에
      있으면 거부한다. 워크플로의 항목은 `spec` 앞에 오므로(§Full grammar:
      `WorkflowItem* SpecClause?`) 그 줄은 항목이 될 수 없는데, 열은 항목인 것처럼
      말하기 때문이다.

   두 규칙 모두 **레이아웃이 정보를 담을 때만** 발동한다: 가드와 그 항목이 같은
   열이면 a가, 섹션과 `spec`이 같은 열이면 b가 발동하지 않는다. 전부 같은 열에
   쓴 프로그램은 이 항의 적용을 받지 않는다.

4. **중첩 ≤2** — 선언 = 레벨 0, 절과 제어 블록 = 레벨 1, 그 내부 구획
   (`given`/`when`/`expect`, `parallel`의 브랜치 step) = 레벨 2. 그 이상의
   중첩은 문법적으로 불가능하다 — `ParallelBlock`과 `PipelineBlock`의 본문은
   `StepLine`만 허용하므로(§Full grammar의 EBNF) parallel 안의 parallel,
   spec 안의 spec은 생산규칙 차원에서 존재하지 않는다.

5. **한 줄 한 선언** — 모든 선언·절 개시·step·내용 항목은 정확히 한 라인이다.

---

## Examples

**거부 ① — 가드 스코프 모순 (N-1).**

```
workflow AccumulateAll
    repeat 3
        read order
        set report.totalAmount to report.totalAmount + order.amount
```

```
compile error: line 4: this line is indented as if it were inside the `repeat`
guard on line 2, but a guard owns exactly one step or block — so it runs outside
the guard. Wrap the steps in a `pipeline` block and let the guard own that, or
dedent this line to the guard's own column (RFC-0002 §Block structure)
```

**수용 ① — 같은 의도를 `pipeline`으로.** 가드가 블록 하나를 소유한다.

```
workflow AccumulateAll
    repeat 3
        pipeline Accumulate
            read order
            set report.totalAmount to report.totalAmount + order.amount
```

**수용 ② — 단일 스텝 반복.** 가드와 항목이 같은 열이므로 3항 a는 발동하지 않는다.
`examples/guarded.lnpl`의 스타일이다.

```
workflow RetrieveWithCache
    find token
    repeat 3
    cache token
    call token
```

**수용 ③ — 들여썼다가 내어쓰기.** 다음 항목이 가드보다 얕으므로 모순이 없다.

```
workflow RetrieveWithCache
    repeat 3
        cache token
    call token
```

**거부 ② — spec 꼬리 모순 (N-5).**

```
workflow Restock
    validate order
    spec
        given
            valid order
        when
            restock
        expect
            completed
    notify order
```

```
compile error: line 11: a workflow step cannot follow the `spec` block opened on
line 3 — a workflow's steps come before its `spec` (RFC-0002 §Full grammar:
WorkflowItem* SpecClause?); move this line above the block
```

## Alternatives

**① 그대로 둔다 (무음 유지).** 기각. 재측정이 major로 분류한 결함이고, 저자가
쓴 것과 플랫폼이 하는 것이 말없이 갈린다 — 이 프로젝트가 #36·#38 이래 닫아 온
계보 전체와 모순된다.

**② 거부 대신 경고.** 기각. 진단 채널은 종료 코드를 바꾸지 않으므로 무음 통과가
끝나지 않는다. 등급을 두어 선택적으로 승격하는 설계는 별도 과제(이슈 #52)이며,
그것이 생기더라도 기본값이 통과인 한 이 결함은 남는다.

**③ `repeat`이 블록만 소유하게 한다.** 토큰만으로 판정할 수 있어 이 RFC가
불필요해진다. 기각 — **단일 스텝 반복을 깨뜨린다.** 위 수용 ②가 컴파일되지 않게
되고, 이는 현행 테스트와 예제가 의존하는 계약이다.

**④ 들여쓰기를 구조적으로 만든다 (Python식).** 기각. RFC-0002 D5의 핵심 결정을
뒤집는 언어 전면 개정이고, 절 하나의 갱신으로 담을 수 없다(RFC-0007 §2.2 규칙 7이
말하는 "전면 대체로 승격해야 하는 때"에 해당). 이 개정은 그 결정을 유지한 채
수용 집합만 좁힌다.

**⑤ 다중 스텝 반복을 정식 지원한다.** 보류(기각 아님). 새 블록 형태가 IR과 모드 B
하강까지 파급되며, 같은 의도를 `pipeline`으로 이미 쓸 수 있다. 표기 부담이
문제라고 판단되면 별도 RFC에서 다룬다.

## Open Questions

① **`when`/`until`에도 같은 강도가 맞는가.** 3항 a는 세 가드 모두에 적용된다.
`repeat`은 다중 스텝 의도가 거의 확실하지만, `when` 아래 두 줄을 들여쓴 저자가
"둘 다 조건부"를 의도했는지 "하나만"을 의도했는지는 `repeat`만큼 자명하지 않다.
현행 코퍼스에는 해당 사례가 0건이라 실측 근거가 없다. 이슈 #52의 진단 등급이
생기면 `when`/`until`만 경고 등급으로 낮추는 선택지가 열린다.

② **포매터가 정본이 되어야 하는가.** 3항은 저자가 열을 **틀리게** 쓴 경우를
거부한다. `lnpl fmt`가 존재해 열을 구조에 맞게 정규화한다면 이 거부는 대부분
포맷 단계에서 사라진다. 포매터는 아직 없다.

③ **탭.** 탭은 렉서가 이미 거부하므로(§Lexical) 열 계산은 공백만 센다. 탭 허용이
논의된다면 3항의 열 비교 규칙을 함께 정해야 한다.
