# RFC-0017: guarded.lnpl 예제 정정

## Status

- Status: **Accepted** (RFC-0017, 2026-08-06)
- Updates: RFC-0008 §Examples/5.2 Guarded Workflow: guarded.lnpl

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. 이 문서는 RFC-0008 §5.2의
**예제 목록만** 갱신한다. 가드의 문법(RFC-0008 §1, RFC-0015·RFC-0016이 갱신),
실행 의미(RFC-0008 §2, RFC-0014가 갱신), skip의 관측 계약(RFC-0014)은 지목하지
않으며 어느 것도 바꾸지 않는다 — 이 개정은 **문서가 약속한 산출물을 실재하게**
만들 뿐이다(규칙 2).

번호가 0017인 이유: 0016까지 점유되어 있다. RFC-0007 §3은 번호 재사용을 금지한다.

## Motivation

2026-08-05 프로덕션 준비도 실측(`qa/REPORT.md`)의 t4가 보고했다(F-8).

RFC-0008 §5.2는 "조건식 두 형태를 실증하는 새 시나리오"로 `examples/guarded.lnpl`을
명시했고, 기계 생성물 `examples/guarded.lir.json`까지 약속했다. **두 파일 다 레포에
없었다.** `ls examples/`는 checkout·login·shorten만 보여준다.

공백은 두 겹이었다.

**① 약속한 파일의 부재.** 가드를 쓰는 공식 예제는 `checkout.lnpl`의
`when product.stock > 0` 한 줄뿐이었다. 존재 검사(`exists`/`missing`) 예제는 0건.
저자는 준거할 것이 없어 checkout 한 줄을 베끼는 것 말고 할 수 있는 일이 없었다.

**② 실린 코드 블록이 구현된 적 없는 문법.** §5.2의 블록은 이렇게 시작한다.

```
step GetToken
  guard when tokenCache missing
  effect
    kind NetworkCall
```

`step`·`guard`·`effect`·`kind`는 이 언어의 키워드가 아니다. 워크플로 본문은 스텝
한 줄이고, 가드는 그 앞 줄에 `when`/`until`로 선다. 즉 §5.2를 그대로 따라 쓴 파일은
**파싱되지 않는다.** 문서가 구현보다 앞선 약속을 했고, 그 약속이 검증되지 않은 채
Accepted로 굳었다 — C10(미문서 규칙·문서-구현 불일치, 4/4 케이스 관측)의 한 사례다.

## Guide-level Explanation

`examples/guarded.lnpl`이 실제 문법으로 존재한다. 한 워크플로가 조건식 두 형태를
각각 하나씩 쓴다.

- `when token.cachedAt exists` — **존재 검사(Presence)**
- `when token.retryBudget > 0` — **비교식(Comparison)**

가드는 바로 다음 항목 하나를 소유하므로, 각 가드 아래에는 스텝이 정확히 하나씩
있다. 앞의 `validate token`·`find token`은 조건과 무관하게 늘 실행된다.

읽는 사람이 이 예제에서 가져가야 할 것은 셋이다.

1. 가드 조건의 두 형태가 문법에서 어떻게 생겼는가.
2. 가드의 스코프가 한 항목이라는 것 — 여러 스텝을 감싸려면 가드를 반복하거나
   블록으로 묶는다.
3. 두 분기가 모두 관측 가능하다는 것 — 참 분기는 `lnpl run`이, 거짓 분기는 모드 B의
   `--skip`·`--field`가 보여준다.

## Reference-level Specification

RFC-0008 §5.2의 소스 목록을 아래로 **대체한다.** 이것이 `examples/guarded.lnpl`의
선언부와 바이트 동일하다(파일 머리의 설명 주석은 제외).

```lnpl
capability postgres
capability redis

entity Token
    field
        id UUID
        cachedAt DateTime
        retryBudget Integer

service TokenService
    policy
        retry 3
    performance
        cache 5m

workflow RetrieveWithCache
    validate token
    find token
    when token.cachedAt exists
    cache token
    when token.retryBudget > 0
    call token
    spec
        given
            valid token
        when
            retrieveWithCache
        expect
            completed
```

**기계 생성물.** §5.2가 약속한 `examples/guarded.lir.json`에 더해, 다른 예제와
같은 4종 묶음을 커밋한다. 셋 다 컴파일러가 만든다.

| 파일 | 생성 명령 |
|------|-----------|
| `examples/guarded.lir.json` | `lnpl compile examples/guarded.lnpl -o examples/guarded.lir.json` |
| `examples/guarded.openapi.json` | `lnpl openapi examples/guarded.lnpl -o examples/guarded.openapi.json` |
| `examples/guarded.spec.json` | `lnpl spec examples/guarded.lnpl -o examples/guarded.spec.json` |

노드 id 안정성과 산출물 신선도는 이 문서가 아니라
`impl/tests/test_golden.py`(`TestGuardedGoldenPair`·`TestGuardedGeneratedArtifacts`)가
고정한다. 이 RFC가 계약하는 것은 **파일의 존재와 두 가드 형태의 실증**이다.

**설계 제약 둘.** 예제는 아래를 지킨다.

1. **가드 아래에 저장소 호출을 두지 않는다.** 모드 B는 실제로 참인 가드 아래의
   저장소 호출 실패를 재현하지 못한다(`impl/lnpl/backend.py`의 KNOWN LIMITATION).
   `impl/tests/test_backend.py`가 모든 예제를 전수 검사하므로, 이를 어기면 스위트가
   붉어진다.
2. **스텝 이름은 워크플로 안에서 유일하고, 같은 스텝이 반복되지 않는다.** 차등
   검사의 관측 맵은 스텝 **이름**으로 키를 잡는데, 두 모드가 그것을 다르게 접는다:
   모드 A는 dict comprehension이라 마지막 하나만 남기고
   (`impl/lnpl/differential.py`의 `observe_mode_a`), 모드 B는
   `setdefault(...).append(...)`로 전부 누적한다(`observe_mode_b`). 같은 이름이
   N번 나오면 두 모드가 **같은 일을 해도** 맵이 달라져 DIVERGENT가 난다.

**`until`을 싣지 않는 이유.** RFC-0008 §5.2의 수용 기준 ②는 `when`과 `until`
둘 다를 명시하지만, 이 예제는 `when` 두 형태만 싣는다. `until`은 피가드 스텝을
여러 라운드 반복하므로 **위 제약 2에 정면으로 걸린다** — 같은 스텝 이름이 N번
나오고, 그래서 두 모드가 동일하게 N라운드를 돌아도 `lnpl diff`가 DIVERGENT를 낸다.
발산의 원인은 `until`의 실행 의미가 아니라 차등 **관측기**의 비대칭이다.

기존 `impl/tests/test_until_mode_equivalence.py`는 유효하다. 그 픽스처는
`observe_*`의 effects 맵이 아니라 라운드 수를 직접 비교하므로 이 비대칭을 타지
않는다.

공식 예제가 DIVERGENT를 내는 것을 받아들이지 않으므로 `until`은 제외한다.
**이 관측기 비대칭의 수리는 이 RFC의 범위가 아니다** — 별도 추적 이슈로 올린다.
재현 증적은 `.orchestration/verify/i50-docs.md`에 있다. 수리된 뒤 `until` 예제를
더하는 것은 이 문서를 Updates하는 후속 RFC의 일이다.

## Examples

커밋된 예제에 대해 실측한 네 명령이다.

```
$ lnpl run examples/guarded.lnpl
workflow RetrieveWithCache -> completed  (24ms, correlation_id=cid-0001)
  step validate token     6ms attempts=1 [Validation -]
  step find token         6ms attempts=1 [RepositoryCall found=True]
  step cache token        6ms attempts=1 [CacheAccess ttl_ms=300000]
  step call token         6ms attempts=1 [NetworkCall target=token]
```

두 가드 다 참이라 피가드 스텝 둘이 **실제로 실행된다.** 진단은 0건이다.

```
$ lnpl spec examples/guarded.lnpl --run
PASS RetrieveWithCache spec — completed (status=completed)
spec: 1 passed, 0 failed

$ lnpl diff examples/guarded.lnpl
PASS 1/4 execution order — 4 step(s): validate token -> find token -> cache token -> call token | 0 skip(s)
PASS 2/4 policy outcome — status=completed
PASS 3/4 observability signals — 4 effect(s) per step match
PASS 4/4 masking — no secret marker in either mode's output
differential: EQUIVALENT
```

거짓 분기는 모드 B에서 명시적으로 몬다. 생략한 `--field`는 0이 기본이므로, 한쪽만
끄려면 다른 쪽 필드를 명시한다.

```
$ lnpl build examples/guarded.lnpl --run --skip --field token.retryBudget=1
step 1 validate token
step 2 find token
step 4 call token            # 존재 검사가 거짓 → cache token 건너뜀

$ lnpl build examples/guarded.lnpl --run --field token.retryBudget=0
step 1 validate token
step 2 find token
step 3 cache token           # 비교식이 거짓 → call token 건너뜀
```

## Alternatives

**RFC-0008 §5.2 본문을 직접 고친다.** 기각. RFC-0007 §2.2는 Accepted RFC의 본문
편집을 금지하고 Supersedes/Updates를 쓰게 한다. §5.2 하나만 바뀌므로 통째 대체
(Supersedes)가 아니라 Updates가 크기에 맞다.

**§5.2 원문 문법이 컴파일되도록 언어를 바꾼다.** 기각. `step`/`guard`/`effect`/
`kind`를 키워드로 들이는 것은 문법 개정이고, 그 문법이 더 나은 근거가 없다. 문서가
구현을 서술해야지 그 반대가 아니다 — 문서 과대 계약이 애초에 이 결함의 원인이다.

**예제를 지우고 §5.2의 약속만 철회한다.** 기각. 존재 검사 예제가 0건이라는 원래
공백(t4 F-8)이 그대로 남는다. 약속을 지키는 비용이 철회하는 비용보다 낮다.

**`until`을 DIVERGENT인 채로 싣는다.** 기각. 공식 예제는 플랫폼의 정상 동작을
가르치는 표면이고, 알려진 발산을 내는 예제는 그 반대를 가르친다.

## Open Questions

1. **차등 관측 맵의 스텝 이름 키.** 맵을 스텝 이름으로 키잡는 것이 의도된
   설계인지, 스텝 id로 잡아야 하는지 정해진 바가 없다. 정해지지 않은 채 두 모드가
   **서로 다르게** 접고 있다는 것이 문제의 핵심이다(모드 A는 덮어쓰기, 모드 B는
   누적). 어느 쪽으로 통일하든 `until` 예제와 같은 이름의 스텝 둘이 다시 가능해진다.
2. **`until` 예제의 복귀.** 위가 수리되면 RFC-0008 §5.2의 수용 기준 ②를 문자 그대로
   만족시키는 `until` 예제를 더할 수 있다. 이 문서를 Updates하는 후속 RFC의 일이다.
3. **예제 4종 묶음의 지위.** `.lir.json`만 §5.2가 약속했고 나머지 둘은 다른 예제와의
   일관성으로 더했다. 예제가 몇 종의 산출물을 커밋해야 하는지는 RFC가 아니라 관행이다.
