# capability 어댑터와 실제 백엔드 (이슈 #25)

**정본은 코드다.** 계약은 `impl/lnpl/drivers.py`의 세 클래스와 그 docstring이고,
이 문서는 그것을 사람이 읽는 형태로 옮기면서 **왜 그렇게 정했는지**와
**무엇을 하지 않는지**를 적는다. 둘이 갈라지면 코드가 옳다.

`capability postgres` / `capability redis` / `security jwt`는 이 이슈 전까지
선언에서 멈췄다 — 인터프리터는 `FakeRepository`/`FakeCache`를 하드와이어했고,
jwt는 기록만 됐다. 어댑터는 그 선언이 **바인딩되는 자리**다.

## 1. 세 계약

```python
class RepositoryDriver:      # capability postgres
    def seed(self, rows)                    # {entity_id: {row_key: row}} — 없을 때만 삽입
    def execute(self, entity_id, operation, key)
    def persist(self, entity_id, key, row)  # 바인딩을 통해 갱신된 행을 flush
    def close(self)

class CacheDriver:           # capability redis
    def get(self, key); def set(self, key, value, ttl_ms)
    def invalidate(self, key); def close(self)
    # `set`의 ttl_ms는 클록 비교(FakeCache가 하는 것)와 스토어 네이티브 만료
    # (예: Redis SETEX) 위임 둘 중 어느 쪽으로 판정해도 계약을 만족한다 —
    # 드라이버가 고른다. RFC-0003 §Execution Model/Clock(RFC-0029), 이슈 #100

class TokenProvider:         # security jwt
    def issue(self, subject, audience, ttl_ms=None)   # -> compact JWS
    def verify(self, token, audience)                 # -> claims, 실패 시 TokenError
```

레퍼런스 구현은 `interp.FakeRepository`/`interp.FakeCache`다. 이 둘은 계약을
만족하는 **정상적인 드라이버**이며, "테스트용 가짜"가 아니라 인메모리 구현이다 —
같은 계약 스위트(`impl/tests/test_driver_contract.py`)가 fake와 sqlite를 **같은
단언으로** 통과시킨다.

### 실패는 한 종류로 나간다

드라이버의 모든 실패는 `DriverError`(토큰은 그 하위 `TokenError`)로 나가고,
인터프리터가 **호출 지점 세 곳**에서 `RunError`로 번역한다(원인 체인 보존).
그래서 저장소 장애는 트레이스백이 아니라 **평범한 실패한 실행**이 된다 —
`status: failed`, CLI rc 1, HTTP 500. `--backend`가 재작성이 아니라 교체인 이유가
이것이다.

## 2. 선택 표면

```bash
lnpl run   <src>.lnpl --backend sqlite:./store.db
lnpl serve <src>.lnpl --backend sqlite:./store.db --jwt-secret-env LNPL_JWT_SECRET
lnpl token <src>.lnpl --path /shop/checkout --subject alice \
                      --secret-env LNPL_JWT_SECRET [--ttl 15m]
```

| 값 | 뜻 |
|----|-----|
| `--backend fake` | **기본값.** 인메모리, 실행마다 새로. 이 이슈 이전과 바이트 동일하게 동작한다 |
| `--backend sqlite:<path>` | 파일에 남는 실제 저장소 |
| `--backend <scheme>:<arg>` (등록된 경우) | `lnpl.drivers` entry-points에 등록된 외부 드라이버 — §8 SPI |
| 그 밖의 값(미등록) | rc 2. 받은 토큰과 **내장 + 등록된 entry-points 허용 집합**을 함께 출력한다 — 추론하지 않는다 |

기본이 `fake`인 것은 비파괴 원칙이다. 이미 출하된 표면을 조이는 것은 파괴적
변경이고, 새 기능은 **선택했을 때만** 켜진다.

### 경로 값

`sqlite:<path>`는 상대경로를 받는다(사람이 셸에서 타이핑하는 인자이므로 CWD가
곧 의도다). 다만 **여는 시점에** `~` 확장 → 절대경로 resolve를 한 번 하고 그
형태를 보관하며, 부모 디렉터리가 없거나 쓸 수 없으면 rc 2로 죽는다. 메시지는
**받은 원문 그대로**를 싣는다 — 조작자가 쓰지 않은 resolve된 경로는 디버깅할
대상이 하나 더 늘어나는 것이다.

### 시크릿

`--secret-env`/`--jwt-secret-env`는 **환경변수 이름**을 받는다. 값 자체는 명령줄로
받지 않는다 — 셸 히스토리와 `ps`에 남기 때문이다. 변수가 없거나 32바이트 미만이면
**서버가 소켓을 열기 전에** rc 2로 죽고, 메시지는 변수 **이름만** 싣는다.

```bash
export LNPL_JWT_SECRET="…여기에 32바이트 이상의 무작위 값. 이 문자열이 아니라…"
```

## 3. sqlite 저장소

### 스키마 — 엔티티별 테이블이 아니다

```sql
CREATE TABLE IF NOT EXISTS lnpl_rows (
    entity_id TEXT NOT NULL,
    row_key   TEXT NOT NULL,
    payload   TEXT NOT NULL,
    _version  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entity_id, row_key)
)
```

`entity_id`는 **바인딩된 컬럼 값**이지 테이블 이름이 아니다. 엔티티마다 테이블을
만들면 문서에서 온 이름이 SQL **문장 텍스트**에 들어가고, 그것이 인젝션이 필요로
하는 모양이다. 여기서는 문장이 전부 상수이고 변하는 값은 전부 바인드 파라미터다.

`_version`은 아래 "쓰기 충돌" 절 전용 내부 컬럼이다. 어떤 `.lnpl` 문서·payload·
응답도 이 이름을 알지 못한다 — 닫힌 어휘에 낱말이 하나도 늘지 않는다(이슈 #92).
기존 DB에 이 컬럼이 없다면 배포 시 한 번만 실행한다:

```sql
ALTER TABLE lnpl_rows ADD COLUMN _version INTEGER NOT NULL DEFAULT 0;
```

새로 만든 파일은 `CREATE TABLE IF NOT EXISTS`가 이미 이 컬럼을 포함해 만드므로
이 ALTER가 필요 없다 — 이 이슈 이전에 만들어진 파일에만 한 번 해당한다.

### 동시성

읽기끼리는 WAL이 처리하고, 쓰기끼리는 `_version`이 처리한다 — 서로 다른 문제다.

- 파일을 **만들 때 한 번**: `journal_mode=WAL`, `synchronous=NORMAL` (파일에 영속)
- **모든 연결**: `busy_timeout=5000` — 잠금을 만나면 즉시 에러 대신 기다린다
- **요청(=Interpreter)마다 새 연결**을 열고 `finally`에서 닫는다. 연결 열기는
  ~0.05ms라 풀이 사줄 것이 없고, 연결이 스레드를 넘지 않는 것이 `ThreadingHTTPServer`
  아래에서 락 없이 안전한 이유다.

#### 쓰기 충돌 — `_version`

동시 read-modify-write(예: `read x` 다음 `set x.n to x.n + 1`)는 WAL만으로는
풀리지 않는다: 두 실행이 같은 값을 읽고, 각자 계산하고, 나중에 쓰는 쪽이 먼저 쓴
값을 흔적 없이 덮어쓴다 — 측정치로 동시 31회 increment 중 12건이 이렇게 사라졌다.

`SqliteRepositoryDriver._read`가 반환하는 행은 그 순간의 `_version`을 함께
기억한다(payload에는 나타나지 않는, 반환된 dict의 내부 속성일 뿐이다).
`persist()`는 그 값을 안 UPDATE 문에 조건으로 건다:

```sql
UPDATE lnpl_rows
   SET payload = ?, _version = _version + 1
 WHERE entity_id = ? AND row_key = ? AND _version = ?
```

영향받은 행이 0이면 읽은 뒤 누군가 먼저 썼다는 뜻이다 — 조용히 덮어쓰는 대신
`DriverError("write conflict: row changed since read ...")`를 내고, 이는 다른
드라이버 오류와 같은 경로로 `RunError`가 되어 평범한 실패 실행이 된다(`status:
failed`, `failure_reason`에 "conflict" 포함). fake 드라이버는 단일 프로세스
인메모리라 이 충돌이 존재할 수 없으므로 `persist()`가 그대로 no-op이다.

**충돌이 났을 때 누가 재시도하는가.** 한 `WorkflowStep`은 소스 한 줄이라
(`lower.py`의 `_step`), `read`와 그 뒤의 `set`은 항상 서로 다른 스텝이다. 실패한
`set` 스텝만 재시도하면 같은(다시 읽지 않은) 바인딩을 그대로 다시 쓰므로 절대
복구되지 않는다 — 복구하는 것은 **워크플로 전체를 다시 부르는 새 호출**이며, 이는
처음부터 다시 읽는다. `policy retry`가 이미 이 효과들을 멱등으로 선언하므로
(RFC-0003 §Policy Enforcement) 그 호출을 다시 하는 것은 안전하다 — 아무것도
반영되지 않았으니 중복이 아니고, 선언된 재시도 예산이 몇 번까지 안전한지도 이미
정해져 있다. 새 개념이 아니라 기존 계약을 그대로 다시 쓰는 것이다. 서빙 표면에서
409로 매핑하는 것은 이 이슈의 범위 밖이며 `serve.py`는 손대지 않는다 — 후속
이슈의 몫이다.

### 시드와 flush

`seed()`는 **없을 때만 삽입**(`INSERT OR IGNORE`)한다. 그래야 `repo_policy`의 시드
규칙(과 그 위에 선 모드 B의 정적 판정)이 영속 저장소에서도 그대로 성립하면서,
앞선 실행이 쓴 행을 덮지 않는다.

`persist()`는 RFC-0015의 `set`이 **바인딩된 행에 쓴 값**을 디스크로 내린다. fake는
바인딩된 dict가 곧 저장된 행이라 no-op이지만, 실제 저장소에서 이 flush가 없으면
갱신이 실행 중에만 보이고 끝나서 사라진다.

### 아웃박스 — `lnpl_outbox` (이슈 #102)

관측에서 끝나던 `emit`을 실화한다. 코어가 소유하는 것은 테이블 스키마와
drain/ack 의미론뿐이다 — 릴레이(실제로 브로커에 퍼블리시하는 쪽)는 프로세스
밖이다(#88 원칙).

```sql
CREATE TABLE IF NOT EXISTS lnpl_outbox (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    emission_id  TEXT NOT NULL,
    event        TEXT NOT NULL,
    payload      TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    delivered_at INTEGER
)
```

`--backend sqlite:...`로 실행한 `EventEmit` 효과는 등록되는 순간(RFC-0003 —
동기 구간은 "퍼블리시를 등록"에서 끝난다) 이 테이블에 한 행으로 남는다. 삭제가
아니라 **상태 마킹**이다 — `delivered_at`이 `NULL`이면 미전달, 값이 있으면
전달됨이고, 행 자체는 지워지지 않는다.

**행의 정체성은 `seq`이지 `emission_id`가 아니다 — 이슈 #102 원문(PK를
`emission_id`로)에서 측정치를 근거로 벗어난 결정이다.** `emission_id`는
`"%s#%d" % (effect_id, len(outbox)+1)`(`interp.py`)로, **한 `Interpreter`
인스턴스에 로컬한 카운터**다. 같은 문서를 `lnpl run`으로 같은 저장소에 대해
두 번 따로 실행하면, 두 실행 각각의 첫 emit이 정확히 같은 `emission_id`를
재현한다 — CLI가 실행마다 새 `Interpreter`를 만들고 `correlation_id`도 넘기지
않아 기본값(`cid-0001`)으로 고정되기 때문이다. 처음에는 `emission_id`를 PK로
잡았으나, **두 번째 `lnpl run` 호출이 PK 충돌로 실패**하는 것을 그대로 실측했다
(2026-08-24, 이 태스크 구현 중). 이것은 재전송이 아니라 — at-least-once의
dedupe 대상은 **같은 배달**이 다시 오는 경우다 — 서로 다른 두 실행이 만든
**서로 다른 두 emission**이므로, 두 번째 행이 성공적으로 쌓이는 쪽이 옳다.
그래서 배달의 정체성은 저장소가 소유하는 대리키 `seq`(sqlite
`AUTOINCREMENT`)로 옮기고, `emission_id`는 그 emission을 만든 트레이스를
가리키는 평범한 컬럼으로 남긴다 — `interp.py`의 `emission_id`/`correlation_id`
생성 자체는 손대지 않았다(골든 출력과 모드 A/B 차동 검사가 그 값을 읽는
결정적 트레이스 계약의 일부라 파급 범위가 이 태스크보다 크다).

CLI 계약(`plugins/lnpl/skills/lnpl-authoring/cli-surface.md`에 상세):

- `lnpl outbox drain --backend sqlite:<path> [--limit N]` — 미전달 행을
  `seq` 오름차순(삽입 순서) JSON Lines로 stdout에 낸다. 한 줄이
  `{"seq", "emission_id", "event", "payload", "created_at"}`. `seq`가
  insertion order와 같으므로 그대로 커서로 쓸 수 있다 — SSE 구독(t103)이
  Last-Event-ID 스타일로 재개하려는 지점이 정확히 이 값이다.
- `lnpl outbox ack --backend sqlite:<path> <seq> [<seq>...]` — 해당
  `seq`들을 delivered로 마킹한다. **같은 `seq` 재-ack는 멱등**(성공, 상태
  불변) — `UPDATE ... WHERE seq = ? AND delivered_at IS NULL`이 이미
  마킹된 행에는 0행을 건드리고 조용히 성공한다. 배치 중 **모르는 `seq`가
  하나라도 있으면 아무것도 쓰지 않고** 그 `seq`를 이름과 함께 rc≠0으로
  거부한다 — 나머지가 조용히 acked되어 "일부만 성공했다"를 호출자가 메시지
  만으로 알 수 없게 되는 일은 없다.

**외부 릴레이가 소유하는 것.** 이 구현은 drain으로 읽고 ack로 지우는 것까지만
한다 — 실제로 카프카·SQS 등에 퍼블리시하는 폴링 퍼블리셔는 cron·systemd
타이머·k8s `CronJob` 같은 프로세스 밖 스케줄러가 소유하며, 그 루프는
`drain → (각 행을 브로커에 퍼블리시) → 성공한 seq만 ack`다. `ack`는 실제
퍼블리시가 확인된 뒤에만 불러야 한다 — 미리 ack하면 퍼블리시가 실패했을 때
그 emission을 다시 볼 방법이 없다(at-least-once가 깨진다).

**하지 않는 것.** HTTP 드레인(`GET /_outbox`)과 웹훅 push는 이슈가 후속으로
명시한 범위라 `serve.py`를 건드리지 않았다. 브로커 바인딩(kafka 등)은 릴레이
구현체의 몫이다. `#79`의 워크플로 단위 트랜잭션 경계와의 결합(실패한 실행이
emit한 행이 남는가)은 명시적으로 이월했다 — 그 결합 규칙 자체가 아직 없다.

## 4. jwt

| 항목 | 값 |
|------|-----|
| 알고리즘 | **HS256 고정.** 발급자와 검증자가 같은 서비스이므로 대칭키가 맞는 모양이다 |
| 키 | ≥32바이트(256비트). 환경변수에서 런타임에 읽는다 |
| 검증 순서 | 3조각 → **alg allowlist** → 서명(`hmac.compare_digest`) → `typ` → `iss` → `aud` → `nbf`/`exp` |
| leeway | 60초 (RFC 7519가 승인하는 상한은 "몇 분") |
| 클레임 | `iss`/`aud`/`sub`/`jti`/`iat`/`nbf`/`exp`. payload는 암호문이 아니라 base64이므로 PII를 넣지 않는다 |
| 수명 | 기본 15분 |

`alg`는 **서버 측 allowlist**로 판정한다. 토큰이 자기 알고리즘을 고르게 두는 것이
`alg: none`과 alg-confusion이 사는 자리다. 서명 검증은 언제나 HS256으로 계산한다.

`aud`는 **요청 경로의 서비스 슬러그**에서 유도한다(`/shop/checkout` → `shop`).
발급(`lnpl token`)과 검증(`serve`)이 같은 함수(`audience_for_path`)를 읽으므로
드리프트가 불가능하고, 이웃 서비스용 토큰은 통하지 않는다.

라이브러리를 추가하지 않았다. HS256은 HMAC-SHA256이고 그 원시 함수는 stdlib
`hmac`/`hashlib`가 준다 — 여기서 쓴 것은 인코딩과 검증 체크리스트이지 암호
알고리즘 구현이 아니다.

**이슈 #119b로 확장됨.** `iss`는 더 이상 하드코딩이 아니다 — `--jwt-issuer`로
기대 발급자를 지정할 수 있고, 미지정 시 기존 `"lnpl"`이 바이트 단위로 그대로
남는다. RS256/ES256처럼 이 표 자체가 다른 알고리즘은 코어에 들어오지
않는다 — §9 `lnpl.tokens` SPI가 그 경계다.

## 5. 이 구현이 하지 않는 것

무엇이 남았는지 적지 않으면 남은 것이 된 것처럼 읽힌다.

| 하지 않는 것 | 왜 |
|--------------|-----|
| **`redis` 실제 바인딩** | 클록 원인은 해소됐다(RFC-0003 §Execution Model/Clock, RFC-0029, 이슈 #100) — `CacheDriver.set`이 받는 `ttl_ms`를 스토어 네이티브 만료(예: Redis `SETEX`)에 위임하면 프로세스를 넘는 클록 리셋 문제가 애초에 생기지 않는다(`--clock real`로 클록 비교 경로도 가능하지만 위임이 권장 경로다). 남은 이유는 다음 행뿐이다: 서버·드라이버 라이브러리가 이 계획을 세운 머신에 없다. `CacheDriver` 계약은 정의돼 있고 `FakeCache`가 그 구현이다 — 실드라이버 자체는 #75(SPI 외부 공급)가 소유한다 |
| **refresh 토큰·회전·폐기 목록** | 셋 다 서버 측 세션 저장소를 요구한다. 저장소 없는 refresh는 수명만 긴 액세스 토큰에 다른 이름을 붙인 것이다. 폐기 간극 = 액세스 토큰 수명 |
| **postgres / redis 서버 바인딩** | `psycopg2`/`redis` 자체는 이제 문제가 아니다(Testcontainers로 로컬에 서버를 띄울 수 있다) — 그 바인딩을 실을 `lnpl-postgres` 외부 레포와 그 레포의 Testcontainers CI가 아직 없다. 이슈 #115가 레포 안(TCK 강화) 절반만 완료했고, 이 절반은 후속 이슈로 등재돼 있다 |
| **트랜잭션 경계 밖 `NetworkCall`의 보상** | `policy rollback`은 저장소 쓰기만 되돌린다(RFC-0032 §Open Questions ②) — `call`/`request`는 이미 나간 뒤라 되돌아가지 않는다. 컴파일러는 그 워크플로마다 `rollback-escapes-network`(warning, 이슈 #112)로 **신고만** 한다. 보상 방식은 RFC-0034(Draft)가 결정했고 구현은 후속(Batch B) |
| **모드 B(네이티브)의 부수효과** | 모드 B는 구조 트레이스 전용이라는 계약이 그대로다. 어댑터는 모드 B에 아무것도 하지 않는다 |
| **아웃박스 HTTP 드레인(`GET /_outbox`)·웹훅 push** | 이슈 #102가 후속으로 명시한 범위다. `serve.py`는 건드리지 않았다 — CLI(`lnpl outbox drain`/`ack`)까지가 이 태스크다 |
| **아웃박스 → 브로커 실바인딩(kafka 등)** | 코어는 테이블 스키마와 drain/ack 의미론만 소유한다(#88 원칙). 실제로 퍼블리시하는 폴링 퍼블리셔는 릴레이 구현체(cron/systemd/k8s `CronJob`)의 몫이다 |
| **브로커 → `consume by` 인입의 실바인딩(kafka 컨슈머 등)** | #88 원칙을 소비 쪽에 대칭 적용한 것(이슈 #118). 코어가 소유하는 것은 구독 선언(`consume by`)·인입 엔드포인트(`POST /-/events/<slug>`)·멱등/오류-분류 의미론뿐이다 — 브로커에서 읽어 그 엔드포인트를 찌르는 것은 `lnpl relay`(레퍼런스, urllib만) 또는 외부 릴레이 구현체의 몫이다. 실제 kafka 컨슈머 그룹·오프셋 관리는 이 레포 밖 |
| **`security encrypt <field>`** | 제거됨 — RFC-0035 §D3 참조(issue #127). 실제로 집행할 외부 드라이버가 0건이었던 것이 "드라이버 의존"이 아니라 항상 빈 집합이었다는 이유로, 닫힌 어휘에서 빠졌다. `Password` 마스킹(#43, 필드 타입이 `Password` 계열일 때 응답/트레이스에서 값을 가리는 관측 채널 규칙)은 이 결정과 무관하게 그대로 남는다 |
| **`NetworkDriver`의 커넥션 풀·`lnpl.networks` SPI 승격** | `HttpNetworkDriver`는 매 호출 연결을 열고 닫는다 — RFC-0037(이슈 #109)이 더한 것은 retry/backoff/jitter/서킷브레이커/경로 템플릿뿐이다. keep-alive 풀이 있는 실드라이버(`urllib3`/`httpx` 기반)를 `lnpl.drivers` 진입점(이슈 #75가 연 경계)으로 등록할 수 있게 SPI 표면을 여는 것은 이슈 #132가 소유한다 |

**소비 측 대칭 경계 (이슈 #118).** 발행 쪽에서 이미 세운 경계 — 코어는 계약
(테이블 스키마, drain/ack 의미론)만 소유하고 실제 브로커 바인딩은 릴레이의
몫이라는 #88 원칙 — 을 소비 쪽에도 그대로 적용한다. 코어가 소유하는 것은
구독 선언(`consume by`) + 인입 엔드포인트(`POST /-/events/<slug>`) +
멱등성/오류-분류 의미론(RFC-0040)뿐이다. 이 계약을 실측하는 레퍼런스
릴레이(`lnpl relay`)는 있지만, brokers(kafka 등)에서 실제로 읽어와 그
엔드포인트를 찌르는 것은 여전히 코어 밖이다 — 드라이버 SPI(#75/#132)가
그렇듯, 실바인딩은 별도 패키지가 소유하는 판단이지 이 계획이 뒤집힌 것이
아니다.

`FakeRepository`의 `rollback`은 위 표에서 뺐다: 이슈 #120부터는 no-op이
아니라 실제로 되돌린다. `begin()`이 `self.rows`의 스냅샷을 뜨고,
`rollback()`이 그 스냅샷으로 복원하며, `commit()`이 스냅샷을 버린다 —
`--backend fake`(스위트 대부분과 로컬 개발이 쓰는 백엔드)에서도 RFC-0032의
"한 워크플로 실행 = 한 트랜잭션" 정책이 실제로 지켜진다.

## 6. 차동 검증과의 관계

fake 백엔드에서의 `EQUIVALENT`는 계속 성립한다. 다만 그 판정이 무엇을 말하는지는
정확히 적어야 한다 — 모드 B는 저장소 상태를 모델링하지 않으므로:

- **기본 입력**: 두 모드는 **저장소 상태가 결과를 결정하지 않는 입력**에서 일치한다.
- **강제 입력**(`--no-row`, 같은 키를 두 번 create): 저장소 차원이 결과를 결정하는
  입력에서의 판정은 **따로** 읽어야 한다.
- **sqlite 경로는 차동 검증 대상이 아니다.** 모드 B가 저장소를 모델링하지 않으므로
  그 차원에 대해 어떤 판정도 낼 수 없다 — 이것은 "일치"가 아니라 **미검증**이다.
- **`--clock real`도 차동 검증 대상이 아니다** — 비결정적이므로 반복 가능한
  비교를 낼 수 없다. `diff`/`spec` 서브커맨드에는 `--clock` 선택자 자체가
  없다(RFC-0003 §Execution Model/Clock, RFC-0029, 이슈 #100).
- **`list where`의 술어도 미검증 차원이다** (이슈 #116, D9). 술어는 저장소에
  쌓인 행 **값**으로 RowSet을 거르는데, RFC-0025 §10이 이미 적었듯 RowSet
  값은 모드 B의 네 관측 클래스(실행 순서+skips, 정책 결과, 관측 신호, 마스킹)
  중 어느 것도 아니다 — `sum`/`count`의 결과가 애초에 비교 대상이 아니었던
  것과 같은 이유다. `differential.compare_observations`는 그래서 네 클래스가
  실제로 일치할 때 `EQUIVALENT`를 계속 낸다(그 판정 자체는 참이다) — 다만
  술어가 있는 `list`를 리포트가 지나칠 때 한 줄을 더 낸다: `note: N \`list
  where\` step(s) — filtered RowSet content is not compared (unverified
  dimension, docs/backends.md §6)`. "일치"가 "걸러진 내용까지 같다"로 읽히지
  않도록 하는 것이 이 줄의 목적이다.
- **`parallel` 블록의 실제 동시성도 미검증 차원이다** (이슈 #108, D8). 모드
  A는 이제 `parallel` 블록의 스텝을 진짜 동시 실행하지만(RFC-0041), 모드 B는
  여전히 순차 실행이다 — RFC-0004 §5(#7)가 이미 미결로 들고 있던 질문 그대로,
  이번 이슈는 모드 A만 바꾸고 모드 B는 손대지 않았다. 네 관측 클래스 중
  "실행 순서"는 완료 순서가 아니라 **선언 순서**로 보고되므로(D6) 실패 없는
  실행에서는 두 모드의 순서 리포트가 우연히 같은 모양으로 나온다 — 하지만
  그것이 "모드 A가 실제로 병렬로 돌았는지"를 검증한 것은 아니다. 벽시계 겹침
  같은 실제 동시성의 증거는 애초에 네 클래스 중 어디에도 속하지 않는다.
  `differential.compare_observations`는 그래서 `parallel` 블록이 있는
  워크플로를 리포트가 지나칠 때 한 줄을 더 낸다: `note: N \`parallel\`
  block(s) — mode B runs them sequentially (unverified dimension,
  docs/backends.md §6)`.

## 7. mode B의 관측 표면 (이슈 #55)

정본은 `rfcs/0022-mode-b-observation-surface.md`다. 여기서는 §6을 읽은 사람이
곧바로 필요한 두 가지만 적는다.

**스킵은 바이너리가 말하지 않는다 — 관측기가 복원한다.** 가드가 거짓이면 `scf.if`가
`lnpl_step`을 호출하지 않으므로 stdout에 그 스텝의 줄이 아예 없다. 부재는 그것이
빠진 목록 없이는 뜻이 없고, 그 목록이 컴파일된 스텝 계획이다.
`backend.restore_skips()` 하나가 그 대조를 하고, 차동 검사와 `lnpl build --run`이
그것을 읽는다. 그래서 `build --run`은 이렇게 말한다:

```
status completed
  (1 step(s) skipped by guard, restored from the compiled plan)
  skipped by `when token.retryBudget > 0`: call token
```

진단은 stderr로 `guard-skipped-steps`(warning)가 나가며, mode A와 달리 **스텝당 한
건**이고 `where`는 워크플로 id다 — mode B의 관측 표면에는 가드 노드 id가 없다.

**`--field`는 비교 가드 전용이다.** refinement 검증은 mode B에서 빌드 시점에
결정되고 그 입력은 파생 sample payload이므로, 어떤 `--field` 값도 refinement를
실패시키지 못한다. `build`는 Validation effect가 있는 워크플로마다 그 사실을
`validation-sample-derived`(info)로 말한다. refinement 집행을 실측하려면
`lnpl run --payload`(mode A)를 쓴다.

여기서 **닫히지 않은 것**(RFC-0022 표 3): `lnpl` 없이 바이너리만 실행하면 스킵은
여전히 침묵하고, `build`에는 `--json`도 `--strict`도 없어서 mode B 스킵을 CI에서
기계 판독하거나 게이트할 수단이 없다.

## 8. SPI: 외부 드라이버 등록 (이슈 #75)

§5가 이미 말했듯 postgres/redis 실드라이버는 코어가 소유하지 않는다 — 계약과
TCK만 코어에 있고, 실제 바인딩은 외부 패키지가 **자기 CI에서 실 서버로**
검증한다("통합 테스트 없는 바인딩 금지"). 이 절은 그 경계가 코드로 어떻게
드러나는지를 적는다: 코어는 `lnpl.drivers` entry-points 그룹을 열어 두고,
`open_repository`가 내장 두 스킴(`fake`/`sqlite`)에서 실패하면 그 그룹에서
스킴명으로 찾는다.

### 등록

외부 패키지의 `pyproject.toml`:

```toml
[project.entry-points."lnpl.drivers"]
postgres = "my_lnpl_postgres:make_driver"
```

`my_lnpl_postgres.make_driver`는 `<arg>`(콜론 뒤 원문 그대로) 하나를 받아
`RepositoryDriver`를 반환하는 콜러블이다. 패키지가 설치돼 있으면
`--backend postgres:<dsn>`이 그 팩토리를 찾아 부른다 — 코어 쪽에 이 스킴에 대한
if문이 하나도 없다.

### 내장 스킴은 절대 가려지지 않는다

`open_repository`는 `fake`/`sqlite`를 entry-points 조회보다 **먼저** 검사한다.
어떤 패키지가 `lnpl.drivers`에 `sqlite`나 `fake`라는 이름으로 등록해도
그 등록은 결코 조회되지 않는다 — 내장이 섀도잉당하는 경로 자체가 없다
(`test_driver_spi.py::BuiltinShadowingTest`).

### 미등록 스킴의 진단

내장에도 없고 등록된 entry-points에도 없는 스킴은 rc 2로 거부되며, 메시지가
**받은 값**·**내장 목록**·**그 순간 실제로 등록된 entry-points 목록**(없으면
"none")을 함께 싣는다 — 오탈자와 "패키지를 설치하지 않았다"를 같은 메시지로
구분할 수 있게.

### entry-point 로드 실패

등록은 됐지만 그 값(`module:attr`)을 import할 수 없는 경우 —
예를 들어 패키지가 제거됐는데 등록 메타데이터만 남은 경우 — `open_repository`는
`ImportError`를 그대로 흘려보내지 않고 `DriverError`로 번역한다(원인 체인
보존). 이 모듈의 "ONE ERROR TYPE OUT" 규칙이 entry-points 경로에도 그대로
적용된다는 뜻이다.

### TCK로 검증하기

외부 드라이버는 `lnpl.testing.RepositoryDriverTCK`를 상속해 자기 CI에서 돌린다:

```python
import unittest
from lnpl.testing import RepositoryDriverTCK

class MyPostgresDriverTCKTest(RepositoryDriverTCK, unittest.TestCase):
    def make_driver(self):
        return MyPostgresDriver(dsn=TEST_DSN)
```

`RepositoryDriverTCK`는 `unittest.TestCase`를 상속하지 않는 순수 믹스인이다
— 구체 클래스가 `unittest.TestCase`와 다중 상속해야 한다. 검증 항목: 읽기·
쓰기·삭제·부재 행의 `None` 반환·중복 create의 `DriverError`, 그리고 읽은 행이
`observed_version` 속성을 갖는 드라이버에 한해 스테일 쓰기가 충돌하는지(이슈
#92 — 이 속성이 없으면 이 케이스는 스킵된다).

**`begin`/`commit`/`rollback`(이슈 #79, RFC-0032) — 이슈 #115로 파괴적 변경됨.**
전에는 셋이 예외 없이 순서대로 호출 가능한지만 확인했고, 기본 계약이 no-op을
허용한다는 이유로 `rollback`이 실제로 되돌리는지는 단언하지 않았다. RFC-0032가
`policy rollback`을 enforced로 올린 이상 그 관용은 계약 위반을 통과시키는
구멍이었다 — 이제 TCK는 `rollback`이 트랜잭션 안에서 만든 행 쓰기와 아웃박스
등록을 실제로 되돌리는지, 그리고 열린 트랜잭션 위의 두 번째 `begin`이
`DriverError`로 거부되는지를 단언한다. **`rollback`을 no-op으로 답하던
드라이버는 이 TCK를 더 이상 통과하지 못한다.** `SqliteRepositoryDriver`가 이
TCK로 검증되는 예는 `impl/tests/test_driver_contract.py::SqliteDriverTCKTest`다.

## 9. SPI: 외부 토큰 프로바이더 등록 (이슈 #119b)

이슈 #119가 지적한 대목: `security role <r>`을 집행하는 역할 클레임이
내장 `hmac` 프로바이더의 자기 발급 토큰에서만 나오면 그건 자기 주장
(self-asserted)이지 신원 근거가 아니다. 이 절이 그 경계를 코드로 어떻게
여는지 적는다 — §8의 `lnpl.drivers`와 같은 형태다: 코어는 `lnpl.tokens`
entry-points 그룹을 열어 두고, `open_token_provider`가 내장 이름(`hmac`)이
아니면 그 그룹에서 이름으로 찾는다.

### 등록

외부 패키지의 `pyproject.toml`:

```toml
[project.entry-points."lnpl.tokens"]
oidc = "my_lnpl_oidc:make_provider"
```

`my_lnpl_oidc.make_provider`는 **인자 없이** 호출되어 `TokenProvider`를
반환하는 콜러블이다 — `lnpl.drivers`의 `factory(<arg>)`(콜론 뒤 원문을
받는 것)와 다르다: 서명 검증 키, JWKS 엔드포인트, 키 로테이션 같은 설정은
패키지 자신의 몫이지, 이 CLI가 파싱해서 넘겨줄 문자열이 아니다(아래 D4
참조). 패키지가 설치돼 있으면 `--token-provider oidc`가 그 팩토리를 찾아
인자 없이 부른다.

### 내장 이름은 섀도잉하면 거부된다

`lnpl.drivers`의 `BuiltinShadowingTest`(§8)는 내장이 **조용히** 이긴다 —
entry-points 조회 자체가 일어나지 않는다. `open_token_provider`는 다르게
움직인다: `--token-provider hmac`을 부를 때 `lnpl.tokens`에 `hmac`이라는
이름으로 등록된 entry-point가 있으면 **`TokenError`로 거부**하고 충돌한
이름과 그 entry-point가 가리키는 모듈을 메시지에 싣는다(`test_token_spi.py`
`BuiltinShadowingTest`). 토큰 신원은 `security role` 집행이 서는
신뢰 근거이므로, 같은 이름을 등록한 패키지가 **조용히 이기거나 조용히
지는 것 둘 다** 여기서는 받아들일 수 없는 결과다 — 그래서 드러나게 실패한다.

### 미등록 이름의 진단

내장에도 없고 등록된 entry-points에도 없는 이름은 `ValueError`로 거부되며,
메시지가 **받은 값**·**내장 목록**(`hmac`)·**그 순간 실제로 등록된
entry-points 목록**(없으면 "none")을 함께 싣는다.

### entry-point 로드 실패

등록은 됐지만 그 값(`module:attr`)을 import할 수 없으면 `open_token_provider`는
`ImportError`를 `DriverError`로 번역한다(원인 체인 보존) — §8과 같은
"ONE ERROR TYPE OUT" 규칙.

### TCK로 검증하기

외부 프로바이더는 `lnpl.testing.TokenProviderTCK`를 상속해 자기 CI에서
돌린다:

```python
import unittest
from lnpl.testing import TokenProviderTCK

class MyOidcProviderTCKTest(TokenProviderTCK, unittest.TestCase):
    def make_provider(self):
        return MyOidcProvider(...)

    def make_foreign_issuer_provider(self):
        return MyOidcProvider(..., issuer="somebody-else")
```

`TokenProviderTCK`는 `RepositoryDriverTCK`와 같은 순수 믹스인이다.
D6(닫힌 목록, 7항목)을 단언한다: ① 유효 토큰 통과, ② 서명 위조 거부,
③ `alg: none` 거부, ④ 기대와 다른 `iss` 거부, ⑤ `aud` 불일치 거부,
⑥ 만료 거부, ⑦ allowlist 밖 alg 거부. ③·⑦이 핵심이다 — 토큰이 자기
알고리즘을 고르게 두는 것이 `alg: none`과 RS256-공개키-를-HMAC-비밀로
쓰는 혼동 공격이 노리는 지점이다(`drivers.py`의 `ACCEPTED_ALGS` 주석).
내장 `HmacTokenProvider`가 이 TCK로 검증되는 예는
`impl/tests/test_token_contract.py::HmacTokenProviderTCKTest`다.

이슈 #115의 교훈이 그대로 적용된다: TCK 자신이 판별력을 갖는지 — 즉 틀린
구현을 실제로 실패시키는지 — 를 참조 구현만으로는 증명하지 못한다.
`impl/tests/test_token_contract.py`의 `_NoSignatureCheckProvider`(서명
검증을 건너뛰는 프로바이더)가 그 음성 통제다: TCK의 서명-위조 케이스를
단독 실행하면 이 프로바이더에서는 **실패**하고 `HmacTokenProvider`에서는
**통과**한다 — 두 결과 모두 `testsRun == 1`을 동반해, 케이스가 조용히
스킵된 것이 아님을 보장한다(`TokenTCKDiscriminatesTest`).

### `--jwks-url`을 넣지 않은 이유 (D4)

RS256/ES256 실구현이 실제 IdP를 상대하려면 대개 JWKS(JSON Web Key Set)
엔드포인트에서 공개키를 조회하고, `kid`(key id) 클레임으로 여러 키 중
하나를 고르고, 그 결과를 캐시하고, 만료·로테이션에 맞춰 다시 조회해야
한다. 이 넷 — 조회·`kid` 선택·캐시·로테이션 — 은 그 자체로 하나의 작은
서브시스템이고, 코어가 떠안으면 두 가지를 동시에 깬다: stdlib-only 원칙
(HTTP 조회와 캐시 정책에 별도 의존이 필요해진다)과 D1이 그은 경계(RS256
서명 검증 자체를 코어가 구현하지 않기로 한 이유와 같은 이유로, JWKS
조회·캐시도 실구현 세부사항이다). 그래서 `--jwks-url` 플래그는 이번
범위에 없다 — `lnpl.tokens` SPI로 등록하는 외부 패키지가 자기 설정으로
그 넷을 소유한다. `open_token_provider`의 factory가 인자를 받지 않는
것(위 "등록" 절)도 같은 결정의 결과다: 코어는 어떤 형태의 JWKS 설정
문자열도 파싱하지 않는다.

## 참고

- 서빙 계층의 상태코드 매핑과 401 판정: `docs/serving.md`
- 선언 ↔ 집행 매트릭스: `docs/ENFORCEMENT-MATRIX.md`
- mode B 관측 계약(스킵 복원·`--field` 도달 범위·잔여): `rfcs/0022-mode-b-observation-surface.md`
- CLI 표면 전체: `plugins/lnpl/skills/lnpl-authoring/cli-surface.md`
