# RFC-0043: 드라이버 집행 신고와 집행 매트릭스 연결

## Status

- Status: **Accepted** (RFC-0043, 2026-08-29)

이 RFC는 RFC-0042를 **Supersedes도 Updates도 하지 않는다** — 독립 신규 RFC다.
RFC-0042는 자신의 §Guide-level Explanation "하지 않는 것"과 Open Questions
2에서 "집행 매트릭스와의 연결(이슈 #138 후속 항목 6)은 이 RFC의 범위 밖이다.
진단 등록이 먼저이고, 매트릭스 연결은 별도 이슈로 다룬다"고 **명시적으로
유예**했다. 그 유예가 가리키는 별도 이슈를 이 RFC가 해소한다 — RFC-0042
본문을 개정할 이유가 없다(0042가 이미 자기 범위 밖이라고 적어 뒀으므로
지목할 절도, 모순도 없다). References: RFC-0042(확장 진단 네임스페이스 —
`<prefix>/<code>`, severity 상한, `--strict` 비참여 규칙을 그대로 물려받는다),
RFC-0021(진단 등급 규칙 — SEVERITY_OF의 "프로그램을 고쳐도 사라지는가" 판정).

## Motivation

이슈 #138이 실측으로 든 네 사례 중 셋(RFC-0042 §Motivation 표)은 RFC-0042가
**진단을 낼 자리**를 열었을 뿐, 그 자리를 채울 **사실 원천**은 아직 없다:

| 확장 | 알 수 있어야 하는 사실 | 오늘의 신고 표면 |
|------|-----------------------|------------------|
| kafka 아웃박스 릴레이 드라이버 | at-least-once만 보장 | `RepositoryDriver`에 신고 메서드/속성 0개 |
| postgres 드라이버 | `READ COMMITTED` | 동일 |
| 외부 토큰 프로바이더 | `role` 클레임 미포함 | `TokenProvider`에 신고 메서드/속성 0개 |
| 캐시 드라이버 | 프로세스 로컬 | `CacheDriver`에 신고 메서드/속성 0개 |

`impl/lnpl/drivers.py`의 네 계약 클래스 — `RepositoryDriver`(:130)·
`CacheDriver`(:264)·`TokenProvider`(:300)·`NetworkDriver`(:312) — 는 전부
**무엇을 하는가**만 정의하고 **어떻게 하는가**(전달 보증·격리 수준·캐시
스코프·클레임 구성)를 말할 자리가 없다. 선언(`capability`/`security`/
`performance`)과 설치된 드라이버를 대조하는 모듈도 없다 — `docs/backends.md`
§8이 문서화한 대로 드라이버 선택은 `--backend <scheme>:<arg>`가 컴파일과
무관하게 실행 시점에 고르는 문자열 조회이고, `lnpl compile`은 그 문자열을
보지 않는다.

이슈 #140의 판정 기준은 이 간극이 메워졌다는 것을 한 문장으로 요구한다:
**"capability kafka를 선언했고, 설치된 드라이버는 at-least-once만 보장하므로
emit userCreated는 중복 전달될 수 있다"는 문장이 `lnpl compile` 진단으로 나오는
것.** 이 RFC가 정확히 그 문장이 나올 수 있는 계약을 정한다 — 문장의 실제 주어가
capability 키워드가 아니라 **설치된 드라이버의 entry-point 이름**이라는 점은
아래 §Reference-level Specification/검사 주체가 정확히 다룬다(선언 이름은
슬롯만 정하고, 그 슬롯에 실제로 설치된 드라이버가 무엇인지는 선언과 무관하다 —
`docs/backends.md` §8이 이미 "코어 쪽에 이 스킴에 대한 if문이 하나도 없다"고
적어 둔 그 비결합의 자연스러운 결과다).

## Guide-level Explanation

드라이버를 만드는 쪽(외부 패키지 저자)은 자기 팩토리 객체에 클래스 속성
`lnpl_enforcement`를 하나 얹는다 — 딕셔너리이고, 인스턴스화도 연결도 필요
없다. 예를 들어 kafka 아웃박스 릴레이를 얹는 패키지라면:

```python
class KafkaOutboxRepository(RepositoryDriver):
    lnpl_enforcement = {"delivery": "at-least-once"}

    def __init__(self, arg):
        ...

def make_driver(arg):
    return KafkaOutboxRepository(arg)
```

`pyproject.toml`에 `docs/backends.md` §8과 같은 방식으로 등록한다
(`[project.entry-points."lnpl.drivers"]` `kafka = "my_pkg:make_driver"`).
`lnpl_enforcement`가 없는 드라이버(코어 내장 `fake`/`sqlite` 포함)는 그냥
신고하지 않는 것으로 취급된다 — 에러도 경고도 없다.

프로그램을 쓰는 쪽은 여느 때처럼 `capability postgres`/`capability redis`/
`capability jwt`/`capability http <Name>`를 선언한다. **이 선언은 어느
드라이버가 로드될지 정하지 않는다** — `--backend` 문자열이 정한다. 컴파일은
그 대신 그 선언이 활성화하는 슬롯(repository/cache/token/network)에 지금
**설치돼 있는 모든** 드라이버를 훑어, 신고가 있는 것마다 진단 하나씩을
합성한다. `capability postgres`가 있는 모듈이 있고, 그 컴퓨터에 위 kafka
패키지가 설치돼 있으며(설령 `--backend`가 그날 `sqlite:test.db`를 골라도),
그 모듈이 `emit userCreated`를 쓰면:

```
$ lnpl compile app.lnpl
info: kafka/delivery-at-least-once [line 12] emit userCreated — the
installed kafka outbox relay guarantees at-least-once delivery only;
userCreated may be delivered more than once
0 info, 0 warning(s), 0 error(s)
$ echo $?
0
```

`--strict`를 줘도 이 코드는 문턱을 움직이지 않는다(RFC-0042 계약 그대로).
`lnpl capabilities --json`의 `slots.repository.registered`에서 `kafka`
항목은 `{"name": "kafka", "loadable": true, "enforcement": {"delivery":
"at-least-once"}}`로 보인다 — `enforcement` 키는 신고가 있을 때만 존재하는
additive 필드다. `docs/ENFORCEMENT-MATRIX.md`는 이 신고를 사람이 읽는
표로 옮겨 렌더링하는 계약을 진다(구현은 t-enf).

## Reference-level Specification

### 신고 SPI

- entry-point가 로드하는 객체(드라이버 **팩토리**이자, `docs/backends.md`
  §8 관례대로 `factory(arg) -> Driver인스턴스`를 만드는 그 콜러블 자신, 또는
  콜러블이 클래스일 때는 그 클래스)가 **클래스/정적 속성 `lnpl_enforcement`**
  (`dict[str, object]`)를 가질 수 있다.
- 읽는 방법: `getattr(loaded, "lnpl_enforcement", None)`. `impl/lnpl/
  capabilities.py`의 `_registered_entries`가 이미 `ep.load()`까지만 하고
  인스턴스화하지 않는 것과 같은 층위 — **연결도 부작용도 없이** import만으로
  읽힌다.
- 부재(`None`)는 유효하고 아무 진단도 만들지 않는다("신고 없음"이지 "신고를
  안 지켰다"가 아니다) — 선언을 시스템이 강제하지 않는 것과, 강제 여부를
  아예 말하지 않는 것은 다른 상태다(부재=ignore, 신고=info 진단으로 갈린다).
  내장 드라이버(`fake`/`sqlite` 등)는 이 속성을 갖지 않으며, 이 RFC가 갖게
  만들지도 않는다(§Reference-level Specification/매칭 규칙 참조).
- `lnpl_enforcement`의 키는 아래 축 표의 이름이어야 하지만, **모르는 키는
  무시**한다(경고 없음) — 드라이버가 코어보다 새 축을 먼저 신고해도 로드
  실패로 이어지지 않는다(forward-compat).

### 신고 어휘와 축

축과 값은 **코어 소유의 닫힌 표**다:

| axis (dict key) | 값 형태 | 값 어휘 | 이슈 #138 사례 |
|------------------|---------|---------|-----------------|
| `delivery` | scalar | `at-most-once` \| `at-least-once` \| `exactly-once` | kafka 아웃박스 릴레이 |
| `isolation` | scalar | `read-uncommitted` \| `read-committed` \| `repeatable-read` \| `serializable` | postgres 드라이버 |
| `cache_scope` | scalar | `process-local` \| `shared` | 캐시 드라이버 |
| `token_claims` | `list[str]` | 클레임 이름(자유 문자열, 예: `sub`/`aud`/`role`) | 외부 토큰 프로바이더 |

이 넷이 #138의 네 사례를 정확히 덮는다 — 다섯 번째 축은 이 RFC가 만들지
않는다. 축 이름 추가·값 어휘 확장은 코어 릴리스에서만, additive로만 한다
(§Reference-level Specification/호환성). `token_claims`가 scalar가 아니라
list인 이유: 클레임은 한 드라이버가 여러 개를 동시에 싣는 것이 정상이고("보증은
홉 단위"라는 Kafka delivery semantics의 교훈과 같은 축에서, 클레임 보증도
"어느 클레임들의 집합"이지 단일 값이 아니다), 닫힌 3치 어휘로 축소하면
표현할 수 없는 조합이 생긴다.

### 검사 주체와 진단 네임스페이스

**코어 브리지가 합성한다.** `lnpl.diagnostics`(RFC-0042)처럼 드라이버마다
자기 확장을 따로 등록시키지 않는다 — 드라이버는 SPI 하나(`lnpl_enforcement`)만
채우고, 진단 코드·등급·문구 조립은 코어가 도맡는다. 이렇게 하는 이유는
RFC-0042 §Motivation이 이미 세운 "확장이 코어 자산을 물려받는다"는 원칙의
적용이다 — 드라이버마다 자기 `lnpl.diagnostics` 확장을 요구하면 신고가
아니라 **중복 구현**을 강제하게 된다(§Alternatives에서 기각).

**코드 형태**: `<entry-point 이름>/<axis-code>`. `<entry-point 이름>`은 그
드라이버가 등록된 `lnpl.drivers`/`lnpl.caches`/`lnpl.tokens` entry-point
그룹의 이름 그 자체다(capability 선언 이름이 아니다 — §매칭 규칙 참조).
`<axis-code>`는:

- scalar 축(`delivery`/`isolation`/`cache_scope`): `<axis를 '_'→'-'로 치환>-<값>`
  — 예: `delivery-at-least-once`, `isolation-read-committed`,
  `cache-scope-process-local`. 값 자체가 이미 `-`를 쓰므로 코드 전체가
  `-`로 이어진 하나의 슬러그가 된다.
- list 축(`token_claims`): 고정 코드 `token-claims`(값 접미 없음) — 리스트를
  코드 슬러그에 이어 붙이면 순서·이스케이프 문제가 생기고, 리스트 값은
  코드가 아니라 `message`가 진술할 몫이다.

**RFC-0042 prefix 소유 규칙과의 정합**: entry-point 이름은 `lnpl.diagnostics`
prefix와 같은 문자 공간을 쓴다(둘 다 `^[a-z][a-z0-9-]{1,15}$`, `lnpl`/`core`
예약). 같은 이름으로 `lnpl.diagnostics` 확장이 이미 등록돼 있으면 그 확장이
그 prefix의 **자유 코드** 소유자다. 다만 합성 코드가 쓰는 예약 슬러그 패턴
`^(delivery|isolation|cache-scope|token-claims)(-.+)?$`는 어떤 prefix
아래서도 **`lnpl.diagnostics` 확장이 등록할 수 없다** — `load_extensions()`가
이 패턴과 겹치는 코드를 선언한 확장을 로드 시점에 거부한다(같은 이름의
드라이버가 실제로 `lnpl_enforcement`를 신고하는지와 무관하게 정적으로 예약한다
— 그래야 "이번 실행에 그 드라이버가 신고했는지"에 따라 로드 성패가 갈리는
비결정성을 피한다). 합성 코드 자신은 `CODES`/`SEVERITY_OF`에도
`load_extensions()`의 레지스트리에도 들어가지 않는다 — 코어 브리지가 그때
그때 조립해 낼 뿐이다.

### 매칭 규칙(선언 ↔ 설치)

capability 선언 이름 → 슬롯의 고정 표(`impl/lnpl/capabilities.py`의 `SLOTS`
어휘 재사용, issue #134):

| capability 선언 | 슬롯 | 계약 클래스 |
|-------------------|------|--------------|
| `capability postgres` | `repository` | `RepositoryDriver` |
| `capability redis` | `cache` | `CacheDriver` |
| `capability jwt` | `token` | `TokenProvider` |
| `capability http <Name>` | `network` | `NetworkDriver` |

(`exporter`/`generators`/`diagnostics`/`kb` 슬롯은 `RepositoryDriver`류
계약 클래스가 없고 이 RFC가 정의하는 신고 의미론의 대상이 아니다 — 범위
밖.) 이 넷 이외의 이름으로 `capability <name>`을 선언해도(예:
`capability stripe`) 이 RFC의 신고 합성은 관여하지 않는다 — 매핑되지 않는
이름은 여전히 순수 서술 노드다(오늘과 동일).

**슬롯이 활성화되면, 그 슬롯의 entry-point 그룹에 설치·등록된 드라이버
전부를 대조한다** — 이 컴파일이 어느 것으로 실행될지(`--backend` 등,
RFC-0021 §Reference-level Specification 계약) 추정하지 않는다. `capability
postgres`를 선언한 모듈이 있는 컴퓨터에 `postgres`라는 이름의 드라이버
패키지 하나와 `kafka`라는 이름의 드라이버 패키지 하나가 동시에 설치돼
있으면(둘 다 `lnpl.drivers`에 등록된 `RepositoryDriver` 구현), 신고가 있는
쪽마다 각자의 entry-point 이름을 prefix로 진단이 나온다 — capability
선언의 문자열(`postgres`)과 실제 신고 진단의 prefix(`kafka`)가 다를 수
있다는 것이 이 규칙의 핵심이고, §Motivation이 인용한 판정 문장의 주어가
"capability" 자신이 아니라 "설치된 드라이버"인 이유다. 내장 드라이버
(`fake`/`sqlite`)는 `lnpl_enforcement`를 갖지 않으므로 대조 대상에 들어와도
아무 것도 신고하지 않는다.

**앵커(어느 IR 노드에 진단을 붙이는가)**: 축마다 이슈 #138의 예문이 실제로
가리키는 노드가 다르므로, 하나로 통일하지 않는다 — 노드마다 있는 만큼
찍는다(기존 `unknown-verb` 등과 같은 "발생 1건당 진단 1건" 관례):

| axis | 앵커 IR 노드 | 근거 |
|------|--------------|------|
| `delivery` | 그 모듈의 각 `EventEmit` effect 노드(`emit`/`publish` 스텝) | #138 예문이 특정 emit 발생을 가리킨다 — "emit userCreated" |
| `isolation` | 그 모듈의 `capability postgres` 선언 노드(모듈당 최대 1건) | 언어에 "가정한 격리 수준"을 적는 절이 없다 — 격리 수준은 스텝이 아니라 그 모듈의 repository capability 전체에 대한 사실이다 |
| `cache_scope` | 그 모듈의 각 `performance cache <ttl>` 제약 노드 | #138 예문이 그 선언을 가리킨다 — "performance cache 5m이 선언됨" |
| `token_claims` | 그 모듈의 각 `security jwt`/`security role <r>` 제약 노드 | #138 예문이 그 선언을 가리킨다 — "security role admin이 선언됨" |

`where`는 그 노드를 소유한 workflow/service id, `subject`는 그 노드의
표면 텍스트(예: `"security role admin"`, `"emit userCreated"`) — 기존
`declared-not-enforced`가 `subject="%s %s" % (clause, name)`로 쓰는 관례
(`impl/lnpl/lower.py:744`)와 같은 모양이다. **이 진단은 선언과 신고
사이의 불일치를 판정하지 않는다** — 예를 들어 `token_claims`가 `role`을
안 실어도 `security role admin`이 실제로 그 클레임을 요구하는지 대조하지
않고, 신고된 사실을 있는 그대로 진술할 뿐이다(§Alternatives에서 그런
대조 진단은 별도로 남긴다).

### 등급과 게이팅

합성 진단은 전원 **`info`**로 고정한다. SEVERITY_OF 규칙(RFC-0021):
프로그램을 고쳐도 사라지지 않고, 설치된 드라이버가 바뀌어야 사라진다 —
RFC-0042 §Motivation이 이미 이 자리를 "정확히 info"라고 예약해 뒀다.
`--strict`는 참여하지 않는다: RFC-0042의 확장 코드 비참여 규칙(entry-point
이름이 prefix인 코드는 전부 `<prefix>/<code>` 형태이므로) 그대로 적용된다
— 별도 예외를 만들지 않는다.

### 매트릭스 실측 렌더링(`docs/ENFORCEMENT-MATRIX.md`)

별도 렌더 명령을 신설하지 않는다. 계약은 둘:

1. `lnpl capabilities --json`의 `slots.<slot>.registered` 각 항목에
   `enforcement` 키를 **additive**로 더한다 — 신고가 있을 때만 존재하는
   `{axis: value}` dict(값은 위 §신고 어휘 표 그대로, list 축은 list 그대로).
   신고가 없으면 키 자체가 없다(빈 dict가 아니다 — "신고 없음"과 "빈 신고"를
   구별한다).
2. `docs/ENFORCEMENT-MATRIX.md` §B("서비스 선언 → 집행 상태")에, 이 신고가
   그 표의 "실측 열"의 유일한 소스라는 계약 문장을 더한다 — 표 자체를 손으로
   유지하지 않는다는 원칙(§A/§B가 이미 코드에서 파생됨을 밝힌 것과 동일
   원칙)의 연장. 실측이 없으면(신고 부재) 그 칸은 "미신고"이지 "unenforced"가
   아니다 — 둘은 다른 사실이므로 섞어 적지 않는다.

구현·문서 반영은 t-enf(Wave 2)의 몫이다. 이 RFC는 계약만 확정한다.

### 호환성(`docs/compatibility.md` §1과의 정합)

§1은 이미 "새 진단 `code` 추가는 breaking이 아니다"와 "확장 `code`의 존속·
재의미부여·severity는 코어가 아니라 그 확장 자신의 보증"(RFC-0042 몫)을
적어 뒀다. 이 RFC가 더하는 것: **합성 코드(`<entry-point>/<axis-code>`)의
존속·재의미부여도 코어가 보증하지 않는다** — entry-point 이름이 곧 prefix이고
그 이름을 고르는 것은 드라이버 저자이지 코어가 아니기 때문이다. 코어가
보증하는 것은 §신고 어휘와 축의 닫힌 축 표(값 어휘의 additive 확장 규칙)와
다섯 키 봉투 형태뿐이다. 축 표·값 어휘 자체는 코어 소유이므로, 새 축·새 값
추가는 §1의 "새 code 추가는 breaking이 아니다"와 같은 취급을 받는다(코어
릴리스에서만, additive로만).

### 하지 않는 것

- **`--strict` opt-in 참여.** RFC-0042 Open Question 1이 실제 확장 소비자가
  생긴 뒤 별도 RFC로 재론하기로 이미 결정했다 — 이 RFC는 그 유예를 그대로
  유지한다. 재론하지 않는다.
- **동사 어휘 개방.** RFC-0042가 영구히 닫았다. 이 RFC는 신고 SPI만
  열 뿐, `VERB_LEXICON`에 아무것도 더하지 않는다 — 재론하지 않는다.
- **신고의 런타임 검증.** `lnpl_enforcement`는 드라이버의 자기 진술이지
  계측이 아니다. 컴파일도 런타임도 그 값이 사실인지 확인하지 않는다 —
  거짓 신고를 걸러내는 것은 이 RFC의 범위 밖이다(JDBC `DatabaseMetaData`도
  같은 전제를 진다: 벤더가 스스로 보고한다).
- **신고 서명·신뢰 체인.** 드라이버 설치 자체가 신뢰 경계다(패키지를
  설치하는 행위가 이미 임의 코드 실행을 허용한다) — 신고값에 별도 서명을
  요구하지 않는다.
- **선언-신고 불일치 판정.** `token_claims`가 `security role`이 요구하는
  클레임을 실제로 싣는지 대조하는 것은 이 RFC가 만들지 않는다(§Reference-level
  Specification/매칭 규칙, §Alternatives) — 신고를 있는 그대로 진술하는
  것과 요구-대-신고 간극을 판정하는 것은 다른 크기의 문제다.

## Examples

골든 시나리오 "Login"(`examples/login.lnpl`, RFC-0007 §6)은 `capability
postgres`/`redis`/`jwt`와 `security jwt`·`performance cache 5m`을 선언한다
— `delivery` 축 하나를 빼면 나머지 세 축을 그대로 관통한다.

가상의 컴퓨터에 아래 세 드라이버 패키지가 설치돼 있다고 하자(전부 신고를
채운 예):

```python
# my_lnpl_pg: entry-point "postgres" (lnpl.drivers)
class PgDriver(RepositoryDriver):
    lnpl_enforcement = {"isolation": "read-committed"}

# my_lnpl_cache: entry-point "redis" (lnpl.caches)
class ProcCache(CacheDriver):
    lnpl_enforcement = {"cache_scope": "process-local"}

# my_lnpl_tok: entry-point "jwt" (lnpl.tokens)
class ExtToken(TokenProvider):
    lnpl_enforcement = {"token_claims": ["sub", "aud", "exp"]}
```

```
$ lnpl compile examples/login.lnpl
info: postgres/isolation-read-committed [line 18] capability postgres —
the installed postgres driver reports read-committed isolation
info: redis/cache-scope-process-local [line 40] performance cache 5m —
the installed redis driver reports process-local cache scope
info: jwt/token-claims [line 37] security jwt — the installed jwt driver
issues claims: sub, aud, exp
warning: unknown-verb [line 46] generate — ...   # 기존 골든 회귀 픽스처 그대로
warning: unknown-verb [line 47] audit — ...
warning: unknown-verb [line 48] return — ...
3 info, 3 warning(s), 0 error(s)
$ echo $?
0
```

(위 `unknown-verb` 세 줄은 `login.lnpl` 자신의 주석이 밝히듯 이슈 #36의
회귀 픽스처다 — 이 RFC와 무관하게 이미 나던 진단이고, 신규 `info` 셋과
공존한다는 것만 보여준다. 구현은 t-enf가 하므로 위 전사는 오늘 실행되는
명령이 아니라 이 RFC가 확정한 계약이 적용됐을 때의 **설계 예시**다 —
RFC-0042 §Examples와 같은 위상.)

Login은 `delivery` 축을 다루지 않는다(kafka류 이벤트 릴레이 capability를
선언하지 않는다) — RFC-0007 §6이 허용하는 **골든 인접 예제**로 보충한다.
`capability postgres`를 쓰는 별도 모듈에, 위 kafka 패키지(§Guide-level
Explanation의 예)가 설치돼 있을 때:

```
$ lnpl compile examples/kafka-outbox-adjacent.lnpl
info: kafka/delivery-at-least-once [line 12] emit userCreated — the
installed kafka outbox relay guarantees at-least-once delivery only;
userCreated may be delivered more than once
0 info, 0 warning(s), 0 error(s)
$ echo $?
0
```

이 문장이 정확히 §Motivation이 인용한 이슈 #140의 판정 기준이다.

## Alternatives

**드라이버마다 자기 `lnpl.diagnostics` 확장을 등록하게 한다.** 검토했고
버렸다 — RFC-0042의 확장 진단 SPI가 이미 있으니 재사용해 보이지만, 그러면
매 드라이버 저자가 `register()` → `{"codes", "check"}` 계약을 자기 손으로
구현해야 한다. #140 조건 ③("확장이 코어 자산을 물려받는다")이 요구하는
것은 정확히 그 반대 — 드라이버는 사실 하나(`lnpl_enforcement`)만 신고하고,
코드·등급·문구 조립은 코어가 공짜로 준다. 드라이버마다 재구현을 강제하면
설치 필요조건만 늘고 실제 신고율은 낮아진다.

**bare(무슬래시) 코드로 새 코드를 코어에 추가한다.** 검토했고 버렸다 —
`declared-not-enforced`류와 형태는 같지만, 소유자가 안 보인다. "이
진단은 왜 나왔나"에 대한 답이 "kafka 패키지가 설치돼 있어서"인데 코드가
`enforcement-delivery-at-least-once`처럼 bare이면 코어가 알 수 없는 사실을
코어 이름으로 주장하는 모양이 된다. RFC-0042가 이미 "확장이 낸 사실은
확장의 이름으로 나가야 한다"는 이유로 `/` 네임스페이스를 열었다 — 이
RFC는 그 판단을 뒤집지 않는다.

**신고를 인스턴스 메서드로 받는다(클래스/정적 속성 대신).** 검토했고
버렸다 — 인스턴스 메서드를 부르려면 드라이버를 생성자 인자(`arg`, 예:
DSN·브로커 주소)까지 채워 연결해야 하는데, 컴파일 시점에는 그 인자가
없다(`--backend`가 실행 시점에만 주어진다, RFC-0021). 정적 속성은 `ep.load()`
만으로 읽히므로 `capabilities.py`의 기존 loadable 검사와 정확히 같은 비용
층위에 머문다.

**선언-신고 불일치를 판정하는 진단까지 이 RFC에서 정한다.** 검토했고
버렸다(§Reference-level Specification "하지 않는 것"에도 기록) — `security
role admin`이 요구하는 클레임과 `token_claims`가 신고한 클레임을 대조하려면
"요구 클레임"이라는 새 언어 개념이 필요한데, 오늘 `security role <r>`은
역할 이름 하나만 받고 클레임 이름을 받지 않는다. 그 어휘 확장은 이 RFC의
신고 SPI보다 훨씬 큰 결정이고, 따로 검토해야 한다.

## Open Questions

1. **`isolation`/`cache_scope`/`token_claims`와 실제 요구치의 대조 진단.**
   §Alternatives에서 기각한 항목의 후속 — `security role`이 클레임 이름을
   받게 하는 어휘 확장이 선행돼야 이 대조가 가능해진다. 이 RFC는 신고를
   있는 그대로 진술하는 것까지만 정한다.
2. **`isolation` 축의 앵커가 모듈당 최대 1건인 것이 여러 `capability
   postgres` 유사 선언(향후 어휘가 늘면)에서도 유지되는가.** 오늘은
   `capability postgres`가 모듈에 최대 1건이므로 문제가 없지만, 여러
   저장소 capability를 한 모듈이 선언할 수 있게 되는 미래 변경이 있다면
   앵커 규칙을 다시 봐야 한다.
3. **신고 축 표의 확장 절차.** §Reference-level Specification/신고 어휘와
   축은 "코어 릴리스에서만 additive"라고만 적었다 — RFC 필요 여부, 축
   추가와 값 추가를 다른 절차로 가를지는 실제 다섯 번째 축 후보가 나온
   뒤 정한다.
