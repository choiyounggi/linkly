# RFC-0036: `policy rollback` 선언의 실제 효력 정정

## Status

- Status: **Accepted** (RFC-0036, 2026-08-26)
- Updates: RFC-0032 §Reference-level Specification/실행 경계, RFC-0032
  §Reference-level Specification/`docs/ENFORCEMENT-MATRIX.md` §B —
  `policy rollback` 행

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. 두 절 모두 이번이 첫
갱신이다 — RFC-0032 이후 어느 RFC도 이 두 절을 건드리지 않았다.

번호가 0036인 이유: 0035까지 점유됐다(RFC-0035, t119). RFC-0007 §3은 번호
재사용을 금지한다.

## Motivation

`impl/lnpl/interp.py`의 `run_workflow`(1070행대) 실측:

```python
        except RunError:
            self.repo.rollback()
            raise
        if result["status"] == "completed":
            self.repo.commit()
        else:
            self.repo.rollback()
            if con["rollback"]:
                self.trace.log(
                    "INFO", "rollback: execution boundary rolled back, "
                            "writes made during this run are discarded")
```

`self.repo.rollback()` 호출은 두 곳(`except RunError`, `else` 분기) 모두
`con["rollback"]`을 전혀 읽지 않는다 — **어느 서비스든, `policy rollback`을
선언했는지와 무관하게** 실행이 실패하면 호출된다. `con["rollback"]`
(`_constraints`가 `policy rollback` 선언에서 유도하는 플래그, 미선언 시
`False`)이 게이트하는 것은 그 아래 `if` 블록 하나 — INFO trace 로그 한
줄뿐이다.

그런데 `docs/ENFORCEMENT-MATRIX.md` §B의 `policy | rollback` 행과 RFC-0032
§Reference-level Specification/실행 경계는 이 선언을 "enforced"로 서술한다.
§B의 범례가 `enforced`를 "선언이 실행을 실제로 바꾼다"로 정의해 둔 채로,
실행 경계 절은 "선언이 바꾸는 것은 **오직** trace 로그 한 줄이다"라고
적었다 — "오직"이라는 단어 자체가 부정확하다: 선언은 컴파일 타임에도
`rollback-escapes-network`(warning, issue #112, `impl/lnpl/lower.py`의
`_check_rollback_escapes_network`)를 켜고 끈다. 이 두 서술을 나란히 읽으면
"`policy rollback`을 선언해야 실행이 실패했을 때 쓰기가 롤백된다"고
이해하기 쉽다. 실제로는 그 반대다 — 롤백은 선언과 무관하게 항상 일어나고,
선언은 그 롤백을 사람이 읽는 신호(trace 로그)와 컴파일 타임 진단
(`rollback-escapes-network`)으로 드러낼 뿐이다.

이 오독은 이웃 행 `policy retry`·`policy timeout`과 대조하면 더 도드라진다
— 그 둘은 실제로 선언이 실행을 바꾼다: `con["retry"]`(미선언 시 `0`)는
`_run_step`의 시도 상한이 직접 읽고, `con["timeout_ms"]`(미선언 시
`None`)는 데드라인 계산이 직접 읽는다 — 미선언이면 재시도도 데드라인도
없다. `policy rollback`은 이 두 이웃과 **다른 종류의 "enforced"**다: 보장
자체(실패 시 쓰기 롤백)는 선언과 무관하게 항상 성립하고, 선언이 여닫는
것은 그 보장을 둘러싼 관측·진단 채널이다. 이 차이를 지금까지 문서 어디도
말하지 않았다.

t120이 `FakeRepository.begin`/`commit`/`rollback`을 실제 폐기로 만든 지금
(`docs/backends.md` §5 — `--backend fake`에서도 `begin()`이 `self.rows`의
스냅샷을 뜨고 `rollback()`이 그 스냅샷으로 복원한다), 두 백엔드
(`SqliteRepositoryDriver`, `FakeRepository`) 모두에서 이 보장이 실재한다 —
이 정정을 미룰 이유가 없다.

## Guide-level Explanation

`policy rollback`을 선언하지 않은 서비스의 워크플로도, 실행이 실패하면 그
실행에서 만든 저장소 쓰기가 전부 롤백된다 — `create`/`update`/`delete`/
`set`의 flush, `emit`의 outbox 등록 전부. 이것은 RFC-0032가 도입한 "워크플로
실행 1회 = 암묵적 트랜잭션 1개" 경계(§Reference-level Specification/실행
경계, RFC-0032)가 워크플로 실행 자체의 속성이지, `policy` 선언의 속성이
아니기 때문이다.

`policy rollback`을 선언하면 이 이미 일어나는 롤백에 두 가지가 얹힌다:

1. 실행이 실패로 끝났을 때 trace에 사람이 읽는 `INFO` 로그 한 줄이 남는다:
   "rollback: execution boundary rolled back, writes made during this run
   are discarded".
2. 그 서비스가 소유한 워크플로에 트랜잭션 경계 밖 `NetworkCall`
   (`call`/`request`) 스텝이 있으면, 컴파일러가 `rollback-escapes-network`
   (warning, issue #112)로 신고한다 — 그 호출은 롤백 대상이 아니라는 뜻이다.

선언은 **관측**과 **경고**를 켤 뿐, 롤백 자체를 켜지 않는다. `policy rollback`
을 선언하지 않았다고 해서 그 서비스의 실패한 실행이 부분 쓰기를 남기는 것도
아니고, 트랜잭션 경계 밖 `NetworkCall`을 경고 없이 봐주는 것도 아니다 — 그저
그 두 신호가 나타나지 않을 뿐, 롤백 자체는 똑같이 일어난다.

## Reference-level Specification

RFC-0007 §2.2 규칙 4에 따라, 아래 두 절은 "무엇을 바꾼다"가 아니라 **치환 후
최종 텍스트**다.

### RFC-0032 §Reference-level Specification/실행 경계 (치환 후 최종 텍스트)

`interp.Interpreter.run_workflow`가 유일한 경계다(§Guide-level Explanation) —
step 단위가 아니라 **요청/실행당 트랜잭션 1개**. 첫 step을 평가하기 직전에
`self.repo.begin()`을 호출한다. 이후:

- step 순회가 예외 없이 끝나고 `result["status"] == "completed"`면
  `self.repo.commit()`을 호출한다.
- `result["status"]`가 `"failed"`로 확정되면(재시도 소진, 또는 데드라인 초과)
  `self.repo.rollback()`을 호출한다.
- step 순회 자체가 `RunError`를 던지며 중간에 빠져나가면(가드 조건 평가 실패
  등, step 실행 루프 진입 이전/도중의 구성 오류) `self.repo.rollback()`을
  호출한 뒤 그 예외를 그대로 다시 던진다 — 기존에 이 경로가 호출자에게
  전파되던 방식은 바뀌지 않는다, 그 앞에 롤백이 추가될 뿐이다.

세 경로 중 정확히 하나만 실행되므로 `begin()` 이후 `commit()`/`rollback()`
중 하나는 항상 호출된다 — 트랜잭션이 열린 채로 실행이 끝나는 경로는 없다.
이 세 경로 중 어느 것도 `con["rollback"]`(정책이 `rollback`을 선언했는지)을
읽지 않는다 — `self.repo.rollback()` 호출 자체는 **선언 여부와 무관하게,
어느 서비스든** 실행이 실패로 끝날 때마다 무조건 일어난다. t120부터는 두
백엔드(`SqliteRepositoryDriver`, `FakeRepository`) 모두에서 이 호출이 실제로
데이터를 되돌린다(`docs/backends.md` §5).

`policy rollback` 선언이 실제로 좌우하는 것은 이 트랜잭션 경계의 존재가
아니라 다음 두 가지뿐이다:

1. **런타임** — 정책이 `rollback`을 선언했고 실행이 실패로 끝났을 때만,
   trace에 "rollback: execution boundary rolled back, writes made during
   this run are discarded"를 `INFO`로 남긴다(사람이 읽는 신호일 뿐 — 이
   로그가 없어도 롤백은 똑같이 일어났다).
2. **컴파일 타임** — `policy rollback`을 선언한 서비스가 소유한 워크플로에
   트랜잭션 경계 밖 `NetworkCall`(`call`/`request`) 스텝이 있으면
   `rollback-escapes-network`(warning, issue #112)가 발화한다
   (`docs/ENFORCEMENT-MATRIX.md`). 선언하지 않은 서비스는 이 진단의 대상이
   되지 않는다 — 진단이 없다고 해서 그 서비스의 실행이 롤백되지 않는다는
   뜻은 아니다.

선언이 없어도 트랜잭션 경계 자체는 동일하게 열리고 닫힌다 — `rollback`
선언은 위 두 신호의 존재만 결정하지, 트랜잭션의 존재를 결정하지 않는다
(트랜잭션은 워크플로 실행 자체의 속성이지 `policy` 선언의 속성이 아니다).

### RFC-0032 §Reference-level Specification/`docs/ENFORCEMENT-MATRIX.md` §B — `policy rollback` 행 (치환 후 최종 텍스트)

`status`는 `enforced`로 유지된다 — "실행이 실패하면 그 실행에서 이뤄진 모든
쓰기가 롤백된다"는 보장 자체는 실제로 집행되고 있다(t120부터는 두 백엔드
모두에서). `enforced` 행은 진단 코드 열이 없으므로(`—`,
`diagnostics._declaration_diagnostics`가 `ENFORCED` 항목을 건너뛴다)
`declared-not-enforced`가 발화하지 않는다 — `retry`/`timeout`이 이미
그렇듯, 선언한 그대로 실행되는 것은 보고할 간극이 아니다.

`근거` 칸의 텍스트는 아래로 고정한다(이전 서술 — "`run_workflow`가 첫 step
전에 트랜잭션을 열고, 실행이 실패하면 그 실행에서 이뤄진 모든 쓰기(outbox
등록 포함)를 롤백한다(issue #79, RFC-0032)" — 는 §실행 경계에서 정정한
것과 같은 이유로, 선언이 이 롤백을 좌우하는 것처럼 읽혔다):

> `run_workflow`가 첫 step 전에 트랜잭션을 열고, 실행이 실패하면 그
> 실행에서 이뤄진 모든 쓰기(outbox 등록 포함)를 **선언 여부와 무관하게
> 모든 서비스에서 무조건** 롤백한다 — `policy rollback` 선언이 실제로
> 좌우하는 것은 (a) 그 INFO trace 로그 한 줄과 (b) 컴파일 타임
> `rollback-escapes-network` 진단(issue #112)의 활성화뿐이다(issue #79,
> RFC-0032, RFC-0036).

(다른 행 — `retry`·`timeout`·`parallel`과 security/performance/event의 전
클로즈 — 은 이 갱신의 대상이 아니며 바뀌지 않는다.)

## Examples

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오
"Login"). `policy.login`은 `retry 3, rollback, timeout 3s`를 선언한다 —
RFC-0032 §Examples 타임라인 C가 이미 이 경로(재시도 소진 후 rollback)를
보여준다. 그 타임라인은 이 RFC로 바뀌지 않는다.

### 골든 인접 예제 — `rollback`을 선언하지 않은 서비스도 롤백된다

골든 시나리오는 `rollback` 선언이 있는 경우만 다룬다. 이 RFC가 바로잡는
것은 선언이 **없는** 경우이므로(골든이 다루지 않는 축 — §6), Login과
나란한 대조군을 든다: `policy.login`에서 `rollback` 절 하나만 뺀 가상의
변형이다(골든 자체는 바뀌지 않는다).

<!-- lnpl-check: skip — fragment: 자리표시자 `...` 포함, 완전한 문법이 아님(컴파일러: unknown policy '...') -->
```lnpl
service LoginServiceNoRollbackDecl
    policy
        retry 3
        timeout 3s
    ...
```

이 서비스의 `Login` 워크플로가 타임라인 C와 똑같이 재시도 4회 전부
`connection refused`로 소진돼 실패로 끝나면:

- `run_workflow`는 `con["rollback"]`을 확인하지 않고 `self.repo.rollback()`
  을 호출한다(§Reference-level Specification/실행 경계) — 이 실행이 만든
  쓰기가 있었다면 타임라인 C와 똑같이 사라진다(타임라인 C의 `step 1`은
  쓰기가 없어 되돌릴 것이 없을 뿐이다).
- trace에는 `INFO` "rollback: ..." 줄이 **남지 않는다** — `con["rollback"]`
  이 `False`라서 그 로그를 여는 `if` 하나만 건너뛴다.
- 이 서비스가 소유한 워크플로에 트랜잭션 밖 `NetworkCall`이 있어도
  `rollback-escapes-network`는 **발화하지 않는다** — 선언하지 않은
  서비스는 이 진단의 대상이 아니다.

관측 가능한 유일한 차이는 로그·진단 두 채널이지, 저장소에 남는 데이터가
아니다.

## Alternatives

| # | 대안 | 기각 이유 |
|---|------|-----------|
| 1 | `policy rollback`을 실제로 선언 여부로 게이트한다 — 미선언 서비스는 `run_workflow`가 `self.repo.rollback()`을 부르지 않도록 코드를 바꾼다 | 기각. 이것은 문서 정정이 아니라 **동작 변경**이다 — 미선언 서비스의 실패한 실행이 부분 쓰기를 커밋된 채로 남긴다는 뜻이 되고, RFC-0032가 막으려던 문제(§Motivation — "실패한 실행이 부분 쓰기를 영구히 남긴다")로 되돌아간다. 지금 이 레포의 기존 워크플로 다수가 `policy rollback`을 선언하지 않은 채로 쓰기를 하고 있어, 이들의 실패 의미가 조용히 바뀐다 — 어느 서비스가 영향을 받는지·마이그레이션 경로가 무엇인지는 별도 설계 결정이 필요한 범위이며, 코드를 건드리지 않는 이 RFC(문서 정정만)의 범위 밖이다 |
| 2 | ENFORCEMENT-MATRIX의 `policy rollback` 상태를 `unenforced` 또는 `measured`로 낮춘다 | 기각. "실패한 실행의 쓰기는 되돌려진다"는 보장 자체는 t120부터 두 백엔드 모두에서 실제로 집행되고 있다 — `unenforced`(선언이 전혀 읽지 않는다)라고 적으면 그것이야말로 거짓이다. `measured`(관측만, 차단하지 않는다)도 맞지 않는다 — 이 보장은 관측이 아니라 실제로 데이터를 되돌리는 집행이다. RFC-0032 §Alternatives 2가 같은 이유로 이미 `measured` 승격을 기각했다 |
| 3 | 트랜잭션 경계를 실행 전체가 아니라 선언한 서비스에만 적용되도록 재정의한다 | 기각. RFC-0032가 이미 "명시적 `Transaction` 노드가 없는 동안은 워크플로 실행 전체가 유일한 암묵적 경계"라고 정했다(§Reference-level Specification/실행 경계) — 이 경계를 선언 여부에 따라 서비스마다 다르게 만들면, RFC-0032 §Alternatives 1이 범위 밖으로 미룬 "명시적 Transaction 노드·다중 스코프" 설계를 이 RFC(문서 정정만)가 대신 여는 셈이 된다 |

## Open Questions

1. **RFC-0032 §Guide-level Explanation의 서술** — "`rollback` 한 단어를
   선언하는 것만으로 이 경계가 생긴다"는 문장은 §Reference-level
   Specification/실행 경계가 정정된 뒤에도 원문 그대로 남는다 — 이 RFC의
   Updates 대상이 아니기 때문이다(작업 범위가 RFC-0032 본문을 Status
   블록과 갱신 절 머리 포인터 외에는 바이트 동일하게 유지하도록 좁혔다).
   산문 설명과 정밀 명세가 갈리는 이 지점은, 다음에 Guide-level
   Explanation을 갱신할 기회(예: 명시적 `Transaction` 노드를 다루는 후속
   RFC)가 함께 바로잡을 수 있다.
2. **다른 문서의 유사 오독 위험** — 이번 정정과 같은 "선언 → enforced →
   선언이 원인"이라는 오독 패턴이 `docs/serving.md` 같은 다른 문서에도
   있는지는 이 RFC가 훑지 않았다 — 발견되면 별도 Updates RFC가 처리한다.
