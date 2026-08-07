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
| 그 밖의 값 | rc 2. 받은 토큰과 **허용 집합**을 함께 출력한다 — 추론하지 않는다 |

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
    PRIMARY KEY (entity_id, row_key)
)
```

`entity_id`는 **바인딩된 컬럼 값**이지 테이블 이름이 아니다. 엔티티마다 테이블을
만들면 문서에서 온 이름이 SQL **문장 텍스트**에 들어가고, 그것이 인젝션이 필요로
하는 모양이다. 여기서는 문장이 전부 상수이고 변하는 값은 전부 바인드 파라미터다.

### 동시성

- 파일을 **만들 때 한 번**: `journal_mode=WAL`, `synchronous=NORMAL` (파일에 영속)
- **모든 연결**: `busy_timeout=5000` — 잠금을 만나면 즉시 에러 대신 기다린다
- **요청(=Interpreter)마다 새 연결**을 열고 `finally`에서 닫는다. 연결 열기는
  ~0.05ms라 풀이 사줄 것이 없고, 연결이 스레드를 넘지 않는 것이 `ThreadingHTTPServer`
  아래에서 락 없이 안전한 이유다.

### 시드와 flush

`seed()`는 **없을 때만 삽입**(`INSERT OR IGNORE`)한다. 그래야 `repo_policy`의 시드
규칙(과 그 위에 선 모드 B의 정적 판정)이 영속 저장소에서도 그대로 성립하면서,
앞선 실행이 쓴 행을 덮지 않는다.

`persist()`는 RFC-0015의 `set`이 **바인딩된 행에 쓴 값**을 디스크로 내린다. fake는
바인딩된 dict가 곧 저장된 행이라 no-op이지만, 실제 저장소에서 이 flush가 없으면
갱신이 실행 중에만 보이고 끝나서 사라진다.

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

## 5. 이 구현이 하지 않는 것

무엇이 남았는지 적지 않으면 남은 것이 된 것처럼 읽힌다.

| 하지 않는 것 | 왜 |
|--------------|-----|
| **`redis` 실제 바인딩** | RFC-0003의 cache TTL이 주입된 **가상 시계**(스텝당 5ms) 단위다. 프로세스를 넘으면 새 시계가 0에서 시작하므로 영속된 항목은 언제나 신선해 보인다 — 만료 계약이 거짓인 저장소가 된다. `CacheDriver` 계약은 정의돼 있고 `FakeCache`가 그 구현이다 |
| **워크플로 단위 트랜잭션 경계** | 드라이버는 **연산마다 커밋**한다. 경계만 만들고 보상 로직이 없으면 `policy rollback`이 집행되는 것처럼 읽히면서, 실패한 실행이 앞선 쓰기를 남긴다 |
| **refresh 토큰·회전·폐기 목록** | 셋 다 서버 측 세션 저장소를 요구한다. 저장소 없는 refresh는 수명만 긴 액세스 토큰에 다른 이름을 붙인 것이다. 폐기 간극 = 액세스 토큰 수명 |
| **postgres / redis 서버 바인딩** | 이 계획을 세운 머신에 서버도 드라이버도 없었다(`psql`·`redis-server` 없음, `psycopg2`·`redis` 미설치). 통합 테스트로 뒷받침할 수 없는 바인딩은 주장일 뿐이다 |
| **모드 B(네이티브)의 부수효과** | 모드 B는 구조 트레이스 전용이라는 계약이 그대로다. 어댑터는 모드 B에 아무것도 하지 않는다 |

## 6. 차동 검증과의 관계

fake 백엔드에서의 `EQUIVALENT`는 계속 성립한다. 다만 그 판정이 무엇을 말하는지는
정확히 적어야 한다 — 모드 B는 저장소 상태를 모델링하지 않으므로:

- **기본 입력**: 두 모드는 **저장소 상태가 결과를 결정하지 않는 입력**에서 일치한다.
- **강제 입력**(`--no-row`, 같은 키를 두 번 create): 저장소 차원이 결과를 결정하는
  입력에서의 판정은 **따로** 읽어야 한다.
- **sqlite 경로는 차동 검증 대상이 아니다.** 모드 B가 저장소를 모델링하지 않으므로
  그 차원에 대해 어떤 판정도 낼 수 없다 — 이것은 "일치"가 아니라 **미검증**이다.

## 참고

- 서빙 계층의 상태코드 매핑과 401 판정: `docs/serving.md`
- 선언 ↔ 집행 매트릭스: `docs/ENFORCEMENT-MATRIX.md`
- CLI 표면 전체: `plugins/lnpl/skills/lnpl-authoring/cli-surface.md`
