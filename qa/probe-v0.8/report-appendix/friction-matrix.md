# friction-matrix — probe-v0.8 (49건 전건)

s1~s5 `FINDINGS.md`의 `### F-` 항목 전건을 심각도·축 **원문 그대로**(재채점 없음)
정규화한 표다. 축·심각도가 스키마(정확히 1개 축, blocker/major/minor 3종)를
벗어나는 원문은 아래 각주와 §7 "케이스 기록 정정 필요"에 남기고, 표에는
그대로 전사했다.

## §1 — 전건 표

| 케이스 | F | 심각도 | 축 | 단계 | 한 줄 | 우회 | 보완 제안 |
|---|---|---|---|---|---|---|---|
| s1 | F-1 | blocker | expr | authoring | Money는 set/가드 산술의 피연산자가 될 수 없다 | 성공 — Integer(센트)로 재선언, Money 구조 상실 | Money를 set 피연산자로 열거나 센트-정수 우회를 공식 패턴으로 문서화 |
| s1 | F-3 | blocker | expr | authoring | 한 실행에서 건드리는 모든 엔티티가 payload 하나의 id를 공유한다 | 성공(6라운드) — `list where` 등가 predicate로 대체, 의미 손실 없음 | find/create에 조회 키 필드를 지정하는 표기(`find product by input.productId`) |
| s1 | F-6 | blocker(주1) | expr | modeA run | Stock.onHand가 실제로 갱신되지 않는다(F-3의 연쇄) | 실패 — 예약합계 동적계산 대안도 가드 제약에 막힘 | F-3이 풀리면 자동 해결 |
| s1 | F-4 | major | doc | modeA/serve run | 업무 규칙 거부(가드 스킵)는 HTTP 200이다 | 부분 — `list where`로 진짜 실패(500) 유도 가능하나 R4/R5/R6엔 미적용, 의미 손실 있음 | `when`에 "게이트 실패 시 4xx" 옵션 |
| s1 | F-5 | minor | doc | modeA run | 반올림 규칙이 s1.md 기대(반올림)와 다르다(플랫폼은 절삭) | 불필요 — 설계상 의도된 차이 | 없음 |
| s1 | F-8 | major | expr | modeA run | 카드 원문(PAN)에서 last4를 서버가 직접 추출할 수 없다 — 클라이언트가 이미 분리해 보낸다고 가정 | 성공(요구를 좁혀서) — 의미 손실: PAN grep→0건 검사가 공허하게 참이 됨(클라이언트가 원문을 애초에 안 보냄), R5의 절반만 증명 | Text 필드에 `slice`/`mask`류 동사를 어휘에 추가 |
| s1 | F-9 | minor | (주3) | modeA run | R6의 원자성 실패 주입을 이 정확한 이음매(Refund 생성→상태 전환 사이)에서 별도로 구성하지 못했다 | 실패(별도 구성 시도 안 함) — A3에서 증명된 동일 메커니즘(policy rollback)으로 대신함 | CancelOrder 안에 `list`+forced-empty-rowset 기법으로 가드용 엔티티를 추가하면 이 이음매를 직접 증명 가능(미검증) |
| s1 | F-10 | (주2) | doc, llm | authoring | `list where` 우변은 이 워크플로가 방금 set한 필드를 참조할 수 있다(가드는 못 한다) | 성공, 의미 손실 없음 | grammar.md/spec.md에 이 비대칭 명시 |
| s1 | F-11 | major | expr | modeA run | 환불 "3회 상한"은 누적 금액 상한과 별개로 집행되지 않는다 | 실패 | F-10 기법으로 count 캡 추가(미검증) |
| s1 | F-17 | minor | doc | spec | `given: stored <Entity> <field> <value>`(색인 없는 형태)는 `list where`에 안 보인다 | 성공, 의미 손실 없음 | spec.md에 "색인 없는 stored는 list 워크플로에서 조용히 무효과"를 경고 |
| s1 | F-18 | major | (주3) | modeA run(증거 절차) | round 1의 A7 증거가 read-back 없이 작성됐고, 사후 재조회에서 실제로 어긋났다 | 실패 — round 1 DB 결측의 근인 미확정 | (케이스 자신에 대한 제안, 플랫폼 아님) 모든 create/update 주장은 sqlite 직접 조회로 맺을 것 |
| s1 | F-12 | blocker | rt | openapi | `lnpl openapi`가 `create ... as` + `respond`에서 크래시한다 | 시도했으나 기각(F-13 유발) | `openapi.py`의 `by_binding`이 `create ... as` 별칭도 인식 |
| s1 | F-13 | blocker | rt | modeA/serve run | (F-12 회피책이 유발) `find`가 방금 `create ... as`로 만든 같은 엔티티를 재조회하면 그 `create` 자체가 허위 충돌로 실패 | 실패 — 발견 즉시 F-12 회피책 철회 | F-12를 고치거나 "이 실행에서 이미 create한 엔티티는 사전 시딩 대상에서 제외" |
| s1 | F-14 | major | ops | serve | 참조 토큰 발급기(`lnpl token`)로는 role 클레임을 넣을 수 없다 | 실패(외부 IdP 필요, 범위 밖) | `lnpl token --role <r>` 최소 플래그 추가 |
| s1 | F-15 | minor | llm | authoring | `pipeline`의 암묵 종결 규칙이 저자 실수를 유발한다 | 성공(빈 `pipeline` 추가), 의미 손실 없음 | `guard-skipped-steps` 경고에 스텝 개수/이름 강조 |
| s1 | F-16 | minor | (주3) | authoring | D4 라운드 로그 형식을 이 케이스가 지키지 않았다 | 성공(round 2 재구성) | 다음 케이스는 처음부터 `- round N:` 접두(플랫폼 문제 아님) |
| s2 | F-1 | blocker | expr | authoring | Decimal/Money 필드는 산술의 대상이 될 수 없다 | 성공 — Integer로 강등(F-2로 이어짐) | Decimal/Money 전용 산술 evaluator를 열거나 "화폐 계산은 언어 밖에서" 명시 |
| s2 | F-2 | blocker | expr | modeA run | Integer 필드도 실수(비정수) 피연산자와의 산술이 런타임에 크래시한다 | 성공 — 곱셈 포기, totalUsd 그대로 복사(의미 손실) | 진단 메시지를 "non-numeric"→"non-integer"로 정정 |
| s2 | F-3 | major | expr, doc | authoring | `set`은 Integer/DateTime 필드만 대상, 문자열 대입은 `format ... from`만 가능하며 정확한 문법은 컴파일러 진단에만 있다 | 성공, 의미 손실 없음 | `references/verbs.md`의 `format` 행에 정확한 문법 한 줄 추가 |
| s2 | F-4 | blocker | rt | failure-branches(B3) | `capability http`의 `retry` 선언이 컴파일·IR엔 반영되나 실행에서 전혀 발동 안 함 | 실패 — 불가로 확정 | `HttpNetworkDriver`가 회복성 코어를 실제 호출하는지 회귀 테스트 필요 |
| s2 | F-5 | blocker | expr, rt | failure-branches(B5) | 응답 본문 형식 검증(비수치 값 거부)을 표현할 방법이 없고, 시도하면 워크플로 전체가 크래시한다 | 실패 — 불가로 확정 | 안전한 `is-numeric` predicate 필요 |
| s2 | F-6 | blocker | expr | outbox-relay(R5) | `emit <eventName>`의 페이로드는 워크플로 입력으로 고정, 서버 계산 필드를 실을 방법이 없다 | 실패 — 시도할 문법 지점 자체가 없음 | `emit <event> with <ref>...` 페이로드 매핑 절 필요 |
| s2 | F-7 | major | rt | idempotency-compensation-correlation(B7) | NetworkCall이 어떤 HTTP 상태에도 예외를 던지지 않아 "N회 연속 실패 후 보상" 사다리를 구성할 방법이 없다 | 부분 성공 — 상태값은 세팅되나 횟수 조건 불가 | NetworkCall 결과를 RunError로 escalate하는 명시적 동사 필요 |
| s2 | F-8 | major | ops | idempotency-compensation-correlation(R9) | correlation id가 6홉 전체를 관통하지 않는다(무관한 식별자 4개로 쪼개짐) | 실패 — 불가 | outbox/CloudEvents 봉투/서빙 로그 3지점에 originating correlation_id 컬럼/필드 필요 |
| s2 | F-9 | minor | expr | outbox-relay(R6) | notifier가 CloudEvents 봉투의 진짜 event_id를 워크플로 안에서 알 수 없다 | 부분 성공(대체 필드로 형태만 맞춤) | 인입 워크플로 input에 `_envelope.id` 예약 필드 추가 |
| s2 | F-10 | minor | diag, ops | modeA run/serve | `guard-skipped-steps` 경고와 event-consume 접속 로그의 `workflow: null`이 정상 분기 관측을 방해한다 | 해당 없음(기능 결함 아님) | 접속 로그의 `workflow` 필드를 event-consume 라우트에서도 채움 |
| s2 | F-11 | minor | doc | openapi | OpenAPI에 event-consume 라우트가 전혀 안 실린다 | 해당 없음 | OpenAPI 확장 필드(`x-lnpl-consumes`)로 이벤트 소비 계약 노출 |
| s3 | F-1 | major | expr | authoring | Money 필드는 `set`이 어떤 형태로도 거부한다 — 집계식만 유일한 쓰기 경로 | 성공 — glue.py가 sqlite payload 직접 갱신, 10k 전량 0불일치 | Money 대상 연산자 없는 순수 복사 `set`만이라도 허용 |
| s3 | F-2 | minor | expr | rerun-oracle | 멱등 재실행에 in-language upsert가 없다(F-1과 같은 근본 원인) | 성공, 의미 손실 없음(10k 50가맹점 재확인) | 명시적 upsert 동사, 또는 Money 필드 한정 재집계-덮어쓰기 문법 |
| s3 | F-3 | minor | doc | authoring | `input.<field>`는 그 이름을 선언한 엔티티가 모듈 안에 하나라도 있어야 한다(문서 없음) | 성공, 의미 손실 없음 | `references/grammar.md`에 이 규칙 한 줄 추가 |
| s3 | F-4 | minor | llm | backfill(R9) | FINDINGS-SCHEMA 판정어휘 4종에 "도구 버그로 무의미해진 하위 항목"을 담을 자리가 없다 | 성공(별도 표기로 흡수) | 판정 어휘에 다섯 번째 값 추가 |
| s3 | F-5 | major | expr | openapi | `expose list <Entity> by <field>`는 Money를 정렬 필드로 거부하고 `desc` 수식어가 없다 | 실패 — 정렬 자체는 불가로 남음 | `desc` 수식어를 열거나 Money를 order-by 허용 타입에 추가 |
| s3 | F-6 | blocker | rt | openapi/serve | `respond`가 `create ... as` 바인딩을 참조하면 `lnpl openapi`(및 `lnpl serve`)가 크래시한다 | 성공(find-바인딩으로 재설계), 의미 손실 없음 | `_response_schema`의 `by_binding` 맵에 `create ... as` 바인딩도 등록 |
| s3 | F-7 | blocker | rt | serve | `find`로 읽은 행에 `set`을 두 번 이상 쓰면 두 번째부터 write conflict로 실패한다 | 실패 — 일반적인 "레코드 일부 필드 갱신" 패턴 자체는 회피 불가 | in-workflow `set` 후 바인딩의 `_version`을 갱신해 다음 낙관적 잠금 검사에 반영 |
| s3 | F-8 | blocker | rt | backfill | `lnpl migrate`가 다개체 모듈에서 조용히 무동작한다(rc=0, "성공" 보고, 아무것도 안 씀) | 성공(직접 SQL 갱신, migrate 자체는 미회복) | `lnpl migrate`의 필드-존재 검사가 다개체 스키마에서 왜 달라지는지 최우선 조사 |
| s3 | F-9 | minor | doc | authoring | `set`/`respond` 대상 바인딩 이름은 camelCase — `find`의 소문자-연결형과 다른 표기 | 성공, 의미 손실 없음 | `naming.md`에 "나중에 참조할 때는 camelCase" 규칙 명시 |
| s3 | F-10 | major | rt | spec | `lnpl spec`에서 `delete`가 실효과 없다(실행은 성공 보고, 행은 그대로) | 실패(spec 안에서 우회 불가, 실제 `lnpl run` 증거로 대체) | `lnpl spec`의 fixture 실행기가 `delete`를 실제 저장소 드라이버와 같은 코드경로로 처리 |
| s4 | F-1 | minor | doc | hardening | `--jwt-secret-env` 최소 시크릿 길이(32바이트) 미문서화 | 성공, 의미 손실 없음 | `--help`/`docs/serving.md`에 HS256 최소 시크릿 길이 명시 |
| s4 | F-2 | major | expr | drivers(R2) | 캐시 **읽기(get)**를 표현할 수 있는 표면 동사가 어휘에 없다 | 시도 안 함(D13 — 언어 표현 불가능한 것을 우회하면 측정 오염) | `check`/`peek` 같은 CacheAccess(get) 표면 동사, 또는 `find ... via cache` 구문 |
| s4 | F-3 | minor | ops | profiles(R5) | `lnpl.toml` 프로파일이 `--cache`/`--rate-limit` 등 절반의 CLI 표면을 커버하지 않음 | 성공, 의미 손실 없음 | toml 폴백 대상을 `serve`의 나머지 CLI 표면으로 확장 |
| s4 | F-4 | minor | doc | docker(R6) | 외부 드라이버의 lnpl 커밋 SHA 직접 참조가 멀티스테이지 빌드에서 git 재요청을 유발 | 성공, 의미 손실 없음 | 드라이버 README에 멀티스테이지 프로덕션 빌드 시 `--no-deps` 필요성 명시 |
| s4 | F-5 | major | ops | docker(R6) | 프로덕션 WSGI 경로(gunicorn)에서 R4 경화 옵션 절반이 적용 불가 | 안 함(설계상 부재) | `build_app()`의 env-var 표면을 `serve` CLI와 동등하게 확장, 또는 nginx 대체 설정 문서화 |
| s4 | F-6 | blocker | perf | load(R7) | 100rps 지속 부하 아래 postgres 백엔드가 ~40초 지점부터 붕괴(p99 5.9초) | 시도 안 함(D13, 완화책은 있음: `--rate-limit`) | postgres 백엔드 지속 부하 상한을 공식 측정·문서화, 근인은 플랫폼팀 조사 필요 |
| s4 | F-7 | minor | ops | drain(R8) | SIGTERM 드레인 경계에서 매 라운드 1건이 손실됨(grace-period 값 무관) | 시도 안 함(애플리케이션 레벨에서 일반적으로 닫을 수 없는 창) | `docs/serving.md` 드레인 절에 경계 레이스를 알려진 한계로 명시 |
| s5 | F-1 | major | doc | lint·type | import-linter의 `forbidden` contract 기본값이 간접(transitive) import까지 검사해 정당한 조립 경로를 위반으로 잡음 | 성공(`allow_indirect_imports=True`), 의미 손실 없음 | (lnpl 무관) lnpl이 팀 경계를 1급 문법으로 제공하면 이런 서드파티 lint 의미론 역설계가 불필요 — S1 비교 포인트 |
| s5 | F-2 | minor | doc | lint·type | `lint-imports`가 cwd 기준으로 설정 파일을 찾아 케이스 루트가 아니면 조용히 실패 | 성공, 의미 손실 없음 | 없음(파이썬 생태계 관례, lnpl 무관) |
| s5 | F-3 | minor | rt | pytest | 테스트 SQL의 ambiguous column name — 두 테이블 같은 컬럼명일 때 JOIN 미명시 시 조용히 거부 | 성공(별칭 부여), 의미 손실 없음 | 정적 스키마 인지 SQL 계층이 있으면 사라짐 — S1 비교 포인트 |
| s5 | F-4 | minor | doc | pytest | FastAPI 번들 TestClient가 설치된 httpx 버전과 충돌 경고(향후 실패 가능성) | 실패(시도 안 함, 지금은 영향 없음) | 없음(lnpl 무관) |
| s5 | F-5 | major | llm | pytest | 자체 검수로는 3건의 테스트 커버리지 갭을 발견하지 못함 — 독립 리뷰(뮤테이션)가 잡음 | 성공(round 23 일괄 수정), 오히려 커버리지 확대 | dev-loop 구현/평가 분리 원칙의 실효성 실증 데이터 — S1의 spec이 같은 자기참조/스킵 결함을 언어 차원에서 막을 수 있는지가 비교 포인트 |

주1: s1 F-6 원문 심각도는 "blocker 후보"(비표준 표기) — 집계표에서는 blocker로 계수.
주2: s1 F-10 원문은 "심각도 표기 대상 아님"(발견 자체, 결함 아님) — 집계표 "기타" 열로 계수, blocker/major/minor 어디에도 넣지 않음. 축도 2개(doc, llm) 표기 — 집계는 첫 번째 태그(doc)로 계수.
주3: s1 F-9/F-16/F-18 원문 축은 "해당 없음"(각각 검증 커버리지 공백, 자기 절차 위반, 검증 관행에 대한 메모) — 집계표에서는 별도 "기타(축 미표기)" 행으로 계수.
그 외 다중 축 표기(s2 F-3 "expr, doc", F-5 "expr, rt", F-10 "diag, ops")는 첫 번째 태그로 계수했다.
이 표기 불일치들은 §7 "케이스 기록 정정 필요"에도 기록한다(FINDINGS-SCHEMA §2가 "정확히 1개"를 요구).

## §2 — 축×심각도 집계

| 축 | blocker | major | minor | 기타 | 합계 |
|---|---|---|---|---|---|
| expr | 7 | 6 | 2 | 0 | 15 |
| diag | 0 | 0 | 1 | 0 | 1 |
| doc | 0 | 2 | 9 | 1 | 12 |
| rt | 6 | 2 | 1 | 0 | 9 |
| ops | 0 | 3 | 2 | 0 | 5 |
| perf | 1 | 0 | 0 | 0 | 1 |
| llm | 0 | 1 | 2 | 0 | 3 |
| maint | 0 | 0 | 0 | 0 | 0 |
| 기타(축 미표기) | 0 | 1 | 2 | 0 | 3 |
| **합계** | **14** | **15** | **19** | **1** | **49** |

(정정 이력: 통합 리뷰 I5 대응으로 s1 F-8(major/expr)·F-9(minor/기타축)를 추가하며
expr 합계 14→15, 기타(축 미표기) 합계 2→3, 전체 47→49로 갱신했다 — s1 F-8/F-9는
원래 dangling 인용이었으나 통합 단계에서 s1 FINDINGS.md에 실제 헤딩으로
추가됐다, §7 케이스 기록 정정 필요 1–2 참고.)

grand total(49) = `cat qa/probe-v0.8/cases/*/FINDINGS.md \| grep -c '^### F-'` 결과와 일치(§Verify 참고).

## §3 — 교차 클러스터

같은 근인 또는 같은 보완 제안을 공유하는, **서로 다른 케이스 ≥2개**에 걸친
F-항목만 클러스터로 묶는다. 단일 케이스 안에서만 반복되는 패턴(예: s1의
`list where` 관련 F-3/F-10/F-11)은 싱글톤으로 남긴다.

### C1 — Money/Decimal은 산술·갱신의 대상이 될 수 없다(집계식만 예외)
- 구성원: s1 F-1, s2 F-1, s2 F-2, s3 F-1, s3 F-2 (3개 케이스)
- 공유 근인: RFC-0016/0028/0044가 산술 evaluator를 Integer/DateTime(그리고
  집계 컨텍스트의 Money)로만 좁혀 두어, 일반 `set`/가드/재실행(upsert)
  경로에서 Money·Decimal 필드를 전혀 쓸 수 없다.
- 공유 보완 제안: Money/Decimal 전용 산술 evaluator(최소 곱셈 1건)를 열거나,
  최소한 연산자 없는 순수 복사 `set`을 허용한다.

### C2 — `create ... as` 바인딩이 OpenAPI/serve 응답 스키마 해석기에 등록돼 있지 않다
- 구성원: s1 F-12, s3 F-6 (2개 케이스)
- 공유 근인: `_response_schema`의 `by_binding` 조회가 `find` 바인딩만 알고
  `create ... as` 별칭 바인딩을 모른다(RFC-0030 §2가 문서화한 계약과 모순).
- 공유 보완 제안: `by_binding` 맵에 `create ... as` 바인딩도 등록한다.

### C3 — 같은 실행(요청) 안에서 방금 만든/갱신한 행의 상태가 갱신되지 않는다
- 구성원: s1 F-13, s3 F-7 (2개 케이스)
- 공유 근인: 인터프리터가 in-workflow에서 이미 create/set한 행의 내부 상태
  (사전 시딩 스킵 여부, 낙관적 잠금 `_version`)를 그 실행 안에서 갱신하지
  않아, 뒤이은 `find`나 두 번째 `set`이 자기 자신과 충돌한다.
- 공유 보완 제안: in-workflow 쓰기(생성/수정) 직후 해당 바인딩의 내부 상태를
  즉시 갱신해 같은 실행 안의 다음 연산이 이를 반영하게 한다.

### C4 — 업무/네트워크 실패를 호출자에게 보이는 실패 신호로 승격할 방법이 없다
- 구성원: s1 F-4, s2 F-7 (2개 케이스)
- 공유 근인: 가드 거부는 설계상 HTTP 200(`skipped` 목록)으로 나가고,
  NetworkCall은 어떤 HTTP 상태에도 예외를 던지지 않는다 — 둘 다 "이 결과를
  실패로 승격한다"는 명시적 언어 동사가 없다.
- 공유 보완 제안: `when`에 "게이트 실패 시 4xx" 선언 옵션 또는 NetworkCall
  결과를 RunError로 escalate하는 명시적 동사 — 근본적으로는 같은 종류의
  갭(조건부 실패의 외부 가시화)이다.

나머지 38개 F-항목(s1 F-8·F-9 포함)은 다른 케이스와 근인·보완 제안을 공유하지 않아 싱글톤으로
남긴다(같은 케이스 안에서의 연쇄는 클러스터가 아니다 — 예: s1 F-3→F-6, s1
F-12→F-13은 이미 각 F-항목 설명에 "…의 연쇄"로 표시돼 있다).
