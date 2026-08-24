# RFC-0032: 실행-스코프 트랜잭션 경계와 `policy rollback` 집행 승격

## Status

- Status: **Accepted** (RFC-0032, 2026-08-24)
- Updates: RFC-0003 §Reference-level Specification/Execution Model (Effect 표의 `Transaction`·`EventEmit` 행)
- Updates: RFC-0003 §Reference-level Specification/Policy Enforcement (`Policy.rollback` 행 — RFC-0013 개정분 중 이 행만)
- Updates: RFC-0003 §Examples (타임라인 C의 rollback 서술)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. `Transaction`·`EventEmit` 행은
RFC-0027(NetworkCall 행)·RFC-0029(Clock 문단)가 건드리지 않은 행이므로 이번이 그
두 행의 첫 갱신이다(규칙 5의 연쇄 갱신 대상 아님). `Policy Enforcement`는
RFC-0013이 절 전체를 이미 갱신했으므로, 규칙 5에 따라 대상(RFC-0003)과 직전 갱신
(RFC-0013)을 함께 지목한다 — 이번 갱신은 그 절의 `Policy.rollback` 행 하나만
다시 바꾼다. `Examples`의 타임라인 C는 이번이 첫 갱신이다.

## Motivation

이슈 #79(#102 이월분 포함), 1차 오케스트레이션 런에서 병합된 t92(`_version`
조건부 쓰기)·t102(`lnpl_outbox`)가 이 RFC의 선행 조건이다.

`impl/lnpl/drivers.py`의 모든 쓰기 경로(`persist`·`record_emission`·`_create`·
`_touch`·`seed`)는 연산마다 개별 커밋한다(`docs/backends.md` §5가 스스로
기록해 둔 공백). 워크플로가 두 번째 쓰기에서 실패해도 첫 번째 쓰기는 이미
커밋되어 있다 — 실패한 실행이 부분 쓰기를 영구히 남긴다. `lnpl_outbox`도 같은
문제를 공유한다: `EventEmit`의 `record_emission` 호출이 그 자체로 커밋되므로,
등록 직후 같은 실행이 실패해도 이미 durable해진 발행 레코드는 남는다 — RFC-0003
§Execution Model의 EventEmit 행이 약속하는 "커밋 성공 후에만 발행"(롤백된
트랜잭션의 이벤트 유출 금지)을 지킬 방법이 없었다.

`diagnostics.ENFORCEMENT[("policy", "rollback")]`은 정확히 이 공백을 이유로
`unenforced`다: "Phase 1 has no Transaction boundary, so there is nothing to
compensate; the #25 drivers commit per operation." RFC-0003 §Execution Model의
`Transaction` 행과 §Policy Enforcement의 `Policy.rollback` 행은 보상 경계를
**명시적 `Transaction` IR 노드**로 규정하지만, `lower.VERB_LEXICON`의 어떤
동사도 `Transaction` Effect를 도출하지 않는다(`EFFECT_SLUG`에 슬롯만 예약돼
있다) — Phase 1에는 이 노드를 선언할 문법 자체가 없다. 그 결과 §Examples
타임라인 C는 "Transaction 노드가 없으므로 보상 목록이 비어 있다 — rollback은
no-op으로 종결되고, 이것 자체가 계약 준수"라고 서술한다: 노드가 없는 한
rollback은 원리적으로 아무것도 할 수 없다는 뜻이었다.

이 RFC는 그 명시적 노드를 만들지 않는다(문법 확장·다중 스코프·중첩 보상은
범위 밖 — §Open Questions와 아래 §Alternatives). 대신 **명시적 `Transaction`
노드가 없는 동안**의 경계를 실행 전체로 좁혀 정의한다: 워크플로 실행 1회 =
암묵적 트랜잭션 1개. 이것으로 `Policy.rollback`을 `unenforced`에서 `enforced`로
올릴 수 있다 — 진짜로 무언가를 되돌리기 때문이다.

## Guide-level Explanation

`policy(rollback)`을 선언한 워크플로가 실행되면, 런타임은 첫 step이 시작되기
전에 저장소 트랜잭션을 하나 연다. 워크플로가 끝까지 성공하면 그 트랜잭션을
커밋한다 — 실행 중 이뤄진 모든 쓰기(`create`/`update`/`delete`/`set`의 flush/
`emit`의 outbox 등록)가 한꺼번에 영속화된다. 워크플로가 실패로 끝나면(재시도가
소진됐거나, 데드라인을 넘겼거나, step 평가 자체가 실행 불가능한 프로그램을
만났거나) 런타임은 그 트랜잭션을 롤백한다 — 이 실행이 만든 쓰기는 하나도 저장소에
남지 않는다. 개발자가 손으로 보상 코드를 쓸 필요는 없다: `rollback` 한 단어를
선언하는 것만으로 이 경계가 생긴다.

이것은 "무제한 보상"이 아니다. 이 실행이 시작하기 **전에** 이미 커밋되어 있던
데이터(예: 이전 실행이 쓴 값)는 되돌아가지 않는다 — 롤백은 이번 실행이 스스로
만든 쓰기만 되돌린다. 외부 `NetworkCall`처럼 저장소 트랜잭션 밖의 부수효과는
여전히 자동 보상 대상이 아니다(§Reference-level Specification의 `Policy.rollback`
행). `capability`가 없어 이 계약 자체를 못 지키는 드라이버(예: `redis` — #75
소유)도 있을 수 있으므로, 계약은 기본적으로 no-op이고 저장소가 실제로 트랜잭션을
가질 때만 의미를 갖는다 — `RepositoryDriver.begin`/`commit`/`rollback`의 기본
구현이 no-op인 이유다.

## Reference-level Specification

### 드라이버 계약

`RepositoryDriver`(`impl/lnpl/drivers.py`)에 세 메서드를 추가한다:

```python
def begin(self):
    """Open a transaction boundary spanning one workflow execution."""
    raise NotImplementedError  # 실제로는 기본 구현이 no-op — 아래 참조

def commit(self):
    """Close the boundary `begin` opened, keeping every write since."""

def rollback(self):
    """Close the boundary `begin` opened, discarding every write since."""
```

**기본 구현은 no-op이다** — 세 메서드 모두 `RepositoryDriver`(추상 계약)와
`interp.FakeRepository`(참조 구현) 양쪽에서 아무 것도 하지 않고 반환한다. 이것이
드라이버 계약을 깨지 않는 이유: `interp.py`는 매 실행마다 이 세 메서드를
무조건 호출하므로(§실행 경계), 트랜잭션 개념이 없는 드라이버(Fake, 그리고 이
계약이 생기기 전에 작성된 미래의 외부 SPI)도 아무 것도 구현하지 않은 채
계약을 만족한다 — 그런 드라이버 위에서 `rollback`은 계속 `unenforced`인 채로
남는 것이 아니라, "그 드라이버가 트랜잭션을 갖지 않는다"는 사실 자체가
`begin`/`commit`/`rollback`이 아무 일도 하지 않는 것으로 정직하게 드러난다.

`SqliteRepositoryDriver`는 실제 트랜잭션을 연다: `begin()`이 연결 위에
`BEGIN`을 실행하고 `_in_transaction` 플래그를 켠다. `commit()`/`rollback()`은
연결의 `commit()`/`rollback()`을 호출하고 플래그를 끈다. 트랜잭션이 열려 있는
동안, 기존에 연산마다 개별 커밋하던 다섯 쓰기 경로(`seed`·`persist`의 두 갈래·
`record_emission`·`_create`·`_touch`)는 그 개별 커밋을 미룬다 — 최종 커밋/
롤백은 `begin`을 연 경계가 결정한다. `persist`의 낙관적 동시성 충돌 분기
(`_version` 불일치 — t92, issue #92)가 여는 로컬 롤백은, 트랜잭션이 열려 있는
동안에는 호출하지 않는다: 그 로컬 롤백은 개별-커밋 시절 각 연산이 자신의
암묵적 트랜잭션만 되돌리기 위한 것이었고, 명시적 트랜잭션이 열려 있는 동안
같은 호출은 이번 실행이 이미 만든 다른 쓰기까지 함께 되돌려 버린다 — 대신
`DriverError`만 올리고, 실행 경계의 `rollback()`이 전체를 정리한다. `_version`
충돌 판정 자체(행이 없으면 실패, `rowcount == 0`이면 충돌)는 바뀌지 않는다.

CLI가 직접 여는 outbox drain/ack 경로(`ack_outbox`)는 트랜잭션 밖에서 그대로
개별 커밋한다 — 워크플로 실행과 무관한 별도 진입점이므로 이 RFC의 대상이
아니다.

### 실행 경계

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
`con["rollback"]`(정책이 `rollback`을 선언했는지)은 이 경계의 존재 여부를
바꾸지 않는다 — 경계는 항상 열리고 닫힌다. 선언이 바꾸는 것은 오직 trace
로그 한 줄(사람이 읽는 신호)이다: 정책이 `rollback`을 선언했고 실행이 실패로
끝났을 때만 "rollback: execution boundary rolled back, writes made during
this run are discarded"를 `INFO`로 남긴다. 선언이 없어도 트랜잭션 경계 자체는
동일하게 열리고 닫힌다 — `rollback` 선언은 로그의 존재만 결정하지, 트랜잭션의
존재를 결정하지 않는다(트랜잭션은 워크플로 실행 자체의 속성이지 `policy`
선언의 속성이 아니다).

### RFC-0003 §Execution Model — `Transaction`·`EventEmit` 행 (치환 후 최종 텍스트)

| Effect kind | 실행 의미(계약) |
|-------------|----------------|
| Transaction | 원자적 스코프 노드: children 전부 성공 시 커밋, 하나라도 실패 시 abort — 부분 쓰기는 관측되지 않는다. `isolation` 서술은 힌트이며 집행 수준은 해당 capability가 결정한다. Policy `rollback`의 보상 경계가 이 노드다(§Policy Enforcement). **Phase 1은 이 노드를 선언할 문법이 없다**(`VERB_LEXICON`이 어떤 동사도 `Transaction`으로 도출하지 않는다) — 그 공백 동안 워크플로 실행 전체가 유일한 암묵적 경계다: 실행 시작 시 열리고, 완주 시 커밋되며, 실패 시 그 실행에서 이뤄진 모든 쓰기를 롤백한다(RFC-0032). 명시적 `Transaction` 노드가 도입되면 이 암묵적 경계는 "children으로 아무 `Transaction`도 갖지 않는 워크플로"의 경계로 좁혀진다 — 지금은 모든 워크플로가 그 경우다 |
| EventEmit | 비동기 발행 — step의 동기 구간은 발행 요청 등록까지다. Transaction의 children으로 소유된 EventEmit은 **커밋 성공 후에만** 발행된다(롤백된 트랜잭션의 이벤트 유출 금지). Phase 1은 명시적 `Transaction` 노드가 없으므로(위 Transaction 행), 모든 EventEmit은 워크플로 실행 전체의 암묵적 경계가 그 소유자다 — 등록(`record_emission`)은 그 경계의 커밋과 함께만 durable해지고, 실행이 실패해 롤백되면 등록 자체가 저장소에 남지 않는다(RFC-0032, issue #102). 전달 보장은 at-least-once이며, 소비자가 event id로 dedupe할 수 있도록 발행마다 유일한 event id를 부여한다(발행 메커니즘의 구현은 §Open Questions ③) |

(다른 행 — NetworkCall·RepositoryCall·CacheAccess·Authorization — 은 이 갱신의
대상이 아니며 바뀌지 않는다.)

### RFC-0003 §Policy Enforcement — `Policy.rollback` 행 (치환 후 최종 텍스트)

| 항목 | 런타임 의미(계약) |
|------|------------------|
| `Policy.rollback` | 실패 시 보상의 경계는 **Transaction 노드**다(§Execution Model Transaction 행). Phase 1은 이 노드를 선언할 문법이 없으므로, 그 공백 동안은 워크플로 실행 전체가 유일한 경계다: 실행이 실패로 종결하면(재시도 소진, 데드라인 초과, 또는 step 순회 자체를 중단시키는 구성 오류를 포함해 `status`가 `failed`로 확정되거나 예외가 전파되는 모든 경로) 그 실행에서 커밋되지 않은 모든 쓰기가 롤백된다 — 그리고 경계가 실행 전체이므로 "이미 커밋된 선행 Transaction"은 존재할 수 없다(있었다면 그것은 이전 실행이 커밋한 데이터이고, 이번 rollback의 대상이 아니다). 명시적 `Transaction` 노드가 도입되면 한 워크플로 안에 여러 개가 존재할 수 있고, 그때는 원래 서술대로 진행 중이던 것만 abort, 이미 커밋된 선행 Transaction들은 역순 보상 대상이 된다. Transaction 경계(현재는 실행 전체) 밖의 Effect(예: 외부 NetworkCall)는 여전히 자동 보상이 불가하다 — rollback이 보장하는 범위는 그 경계까지이며, 그 밖의 보상은 계약하지 않는다(한계는 §Open Questions ③과 연결) |

(다른 행 — `Policy.retry`·`Policy.timeout`·`Performance.cache`·
`Performance.response` — 은 이 갱신의 대상이 아니며 바뀌지 않는다.)

### `docs/ENFORCEMENT-MATRIX.md` §B — `policy rollback` 행

`status`가 `unenforced`에서 `enforced`로 바뀐다. `enforced` 행은 진단 코드
열이 없으므로(`—`, `diagnostics._declaration_diagnostics`가 `ENFORCED` 항목을
건너뛴다) `declared-not-enforced`가 더 이상 발화하지 않는다 — `retry`/
`timeout`이 이미 그렇듯, 선언한 그대로 실행되는 것은 보고할 간극이 아니다.

## Examples

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오 "Login").
`policy.login`은 `retry 3, rollback, timeout 3s`를 선언한다 — RFC-0003
§Examples 타임라인 C가 그 `rollback`이 재시도 소진 후 평가되는 지점이다.

### 타임라인 C — 재시도 소진과 rollback (치환 후 최종 텍스트)

```
trace tr-003  (workflow=login, cid-e08d, deadline 3000ms)
└── span wf.login                        [ 0 → 388ms]  status=Failed
    ├── step.1  validate input           → pass
    └── step.2  authenticate
        ├── 시도 1~4 (초기 1 + retry 3/3, 매회 connection refused,
        │    backoff+jitter — 전부 잔여 데드라인 내)
        ├── retry 소진 → step 실패
        └── policy.login rollback 평가:
              보상 경계 = 워크플로 실행 전체(RFC-0032 — Phase 1은 명시적
              Transaction 노드를 선언할 문법이 없다). driver.rollback()이
              실제로 호출된다. Login IR의 step 1(validate)은 쓰기가 없고
              step 2(authenticate)는 read만 시도했으므로, 이 실행이 커밋한
              쓰기는 애초에 없다 — 되돌릴 것이 없을 뿐, rollback이 no-op으로
              "정의돼서" 그런 것이 아니다(이전 서술과의 차이). 쓰기가 있는
              워크플로라면(RFC-0032 §Reference-level Specification 참조,
              `impl/tests/test_transactions.py`가 두 번째 쓰기가 실패하는
              변형을 정확히 이 방식으로 검증한다) 첫 번째 쓰기도 이번
              rollback으로 함께 사라졌을 것이다.
```

- workflow는 `Failed`로 종결, 원인(connection refused ×4)이 보존된다 —
  타임라인 C의 이 부분은 바뀌지 않는다.
- `policy.login`이 `rollback`을 선언했고 실행이 실패로 끝났으므로, trace에
  `INFO` 로그 한 줄이 추가된다: "rollback: execution boundary rolled back,
  writes made during this run are discarded"(§실행 경계).

## Alternatives

1. **명시적 `Transaction` IR 노드를 지금 구현한다** — 기각. `VERB_LEXICON`에
   새 동사(또는 새 블록 문법)를 추가하고, 중첩 스코프·스코프별 재시도(§Policy
   Enforcement의 기존 "children 전부가 멱등일 때만" 행)·역순 다중 보상까지
   구현하는 것은 이 이슈(#79)의 범위를 훨씬 넘는다 — 분산 트랜잭션·보상 로직은
   이 태스크의 명시적 범위 밖이다. 실행-스코프 암묵적 경계는 명시적 노드가
   생겨도 무효화되지 않는 부분집합(§Reference-level Specification의 Transaction
   행)이므로, 나중에 노드를 추가해도 이 RFC를 Supersede할 필요가 없다 —
   Updates로 좁히기만 하면 된다.
2. **`Policy.rollback`을 `measured`로 승격한다(관측만, 집행 아님)** — 기각.
   `record_emission`·`persist`의 실제 커밋 지점을 억제하는 코드가 이미 있고,
   그것이 진짜로 쓰기를 되돌린다 — "관측만 한다"는 이 구현이 실제로 하는 일을
   과소 보고한다. `declared-measured-only`는 "실행이 관측·보고하지만 차단하지
   않는" 선언에 쓰는 코드(예: `performance response`)이며, rollback은 이제
   무언가를 실제로 바꾼다.
3. **드라이버별로 트랜잭션 지원 여부를 새 진단으로 노출한다** — 기각. 이미
   `begin`/`commit`/`rollback`의 기본 no-op 계약이 이것을 조용히 흡수한다 —
   Fake나 트랜잭션 없는 미래 드라이버 위에서 `rollback`을 선언해도 실행은
   깨지지 않고, 그저 되돌릴 것이 애초에 즉시 커밋됐을 뿐이다. 새 진단 코드를
   추가하면 "그 드라이버가 트랜잭션을 지원하는가"라는 컴파일타임에 알 수 없는
   질문(백엔드는 `--backend` 런타임 선택이다)에 컴파일타임 진단이 답하려는
   구조적 모순이 생긴다 — `security jwt` 행이 이미 같은 이유로 컴파일타임
   `unenforced` 표시를 유지한 채 실제 집행 여부는 산문으로 갈라 설명한다
   (RFC-0003 §Policy Enforcement, `docs/ENFORCEMENT-MATRIX.md`).

## Open Questions

1. **명시적 `Transaction` 노드와 다중 스코프** — 위 §Alternatives 1이 기각한
   범위. 문법(새 동사? 블록?), 스코프별 재시도, 역순 다중 보상의 설계는
   후속 이슈로 넘긴다.
2. **Transaction 밖 부수효과의 보상** — 외부 `NetworkCall`처럼 저장소
   트랜잭션에 속하지 않는 효과의 실패 시 처리(사가·보상 트랜잭션)는 RFC-0003
   §Open Questions ③, ④와 이어지며 이 RFC가 명시적으로 배제한 범위다.
3. **외부 드라이버 SPI의 트랜잭션 계약 검증** — t75(entry-points SPI/TCK)가
   `begin`/`commit`/`rollback`의 기본 no-op 계약을 외부 구현이 지키는지
   검증하는 TCK 케이스를 가질지는 t75의 몫이다. 이 RFC는 계약만 정의한다.
