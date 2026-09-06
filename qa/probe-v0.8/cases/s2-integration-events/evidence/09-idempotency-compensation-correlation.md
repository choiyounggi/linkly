§B6 — 멱등 소비 (같은 이벤트 2회 relay)

## 명령

동일 CloudEvents envelope(`id: "evt-b6-fixed"`)을 `/-/events/order-placed`에
두 번 직접 POST(자연 relay는 첫 ack 이후 같은 행을 재드레인하지 않으므로
직접 POST로 "같은 이벤트 재전달"을 재현 — RFC-0040 §6이 계약하는 지점은
CloudEvents `id` 자체이지 outbox seq가 아니다):

```
$ curl -X POST http://127.0.0.1:42302/-/events/order-placed -d '{"id":"evt-b6-fixed", ...}'
→ 200, correlation_id=req-dbe548e67297, bindings.n.status=delivered
$ curl (같은 body 재전송)
→ 200, correlation_id=req-dbe548e67297  (첫 응답과 바이트 동일 — 재실행 없이 재생)
```

hook 스텁 로그(`evidence/stub-hook-b6.log`):
```
2026-09-05T16:58:36.329498+00:00 POST /hook 200 12
```
(1줄 — 2번째 POST에서 hook은 호출되지 않음)

notifier 저장소: `entity.notification#o-b6` **1행**.

**판정: 충족** — Notification 1행, 웹훅 호출 1회. `idempotency_begin`이
"done" 상태를 CloudEvents `id`로 재생한다는 RFC-0040 §6 계약이 그대로
실측됨(같은 correlation_id가 재생되는 것으로 실행 자체가 재발생하지
않았음을 교차 확인).

---

§B7 — 보상 (hook 500 연속)

## 명령

```
$ curl -X POST http://127.0.0.1:48404/-/events/order-placed \
    -d '{"id":"evt-b7-1", "data":{"id":"o-b7-1", ...}}'
→ 200, bindings.n.status=needsManual, hookResult.status=500
$ curl -X POST .../-/events/order-placed -d '{"id":"evt-b7-2", "data":{"id":"o-b7-2", ...}}'
→ 200, bindings.n.status=needsManual, hookResult.status=500
```
hook 스텁 로그: 2줄, 둘 다 500 — 각 이벤트당 정확히 1회씩.

**핵심 구조적 관측**: 우리 워크플로 설계(`when hookResult.status != 200 →
format needsManual`)에서는 `call Hook`이 500을 받아도 **스텝 자체가
실패하지 않는다**(§task03의 B4/B2 실측과 동일 원리 — NetworkCall은 어떤
HTTP 상태에도 예외를 던지지 않는다). 그래서 워크플로가 항상 `status:
completed`로 끝나고, 인입 라우트는 **항상 200**을 반환한다 — RFC-0040 §7의
3갈래 분류(`NetworkCall 실패 → 503 + Retry-After` → 릴레이가 재시도)가
**발동할 조건 자체가 없다**. `needsManual`은 매번 **1회 실패만으로** 바로
세팅되고("3회 연속"이 아니라 "1회"), relay가 503을 보고 다음 폴링에서 같은
이벤트를 다시 미는 재시도 사다리는 이 설계로는 절대 관측되지 않는다.

우회 검토: 언어에 명시적 "fail"/"abort" 동사가 없다(VERB_LEXICON에 없음 —
`return`/`log`/`send`/`notify`/`verify`처럼 no-op). 실행을 진짜로 실패시키는
경로는 `validate` 거부·`create` 충돌·읽기 실패(RunError)뿐이고, 이들은
"웹훅이 500"이라는 사실 자체와 무관하다 — 웹훅 상태를 이 세 경로 중
하나로 변환할 방법이 없다(가드가 참조할 수 있는 게 `hookResult.status`
뿐이고, 그 값을 갖고 워크플로를 실패시키는 유일한 방법이 R4에서 이미
크래시로 확인된 "비수치 비교"뿐인데, 그건 제어된 3-스트라이크가 아니라
즉시 크래시다).

**판정**: needsManual 상태 자체(값 설정)는 **충족** — 세 번째 시나리오
(다음 이벤트가 계속 전달됨)도 **충족**(o-b7-2가 o-b7-1과 무관하게 정상
처리됨, 큐가 멈추지 않음). 그러나 "3회 연속 실패 후"라는 **횟수 조건**은
**불가** — NetworkCall이 HTTP 상태와 무관하게 워크플로를 실패시키지 않는
설계라서 RFC-0040 §7의 503-재시도 사다리 자체가 이 언어의 저작 표면에서
발동될 방법이 없다(축 rt, severity major — 값 자체는 되지만 그 값에
이르는 "3연속" 프로토콜은 표현 불가).

---

§R9 — correlation id 추적

주문 o-1(task 04, evidence/03-run.md·08-outbox-relay.md와 동일 실행)을
6홉에 걸쳐 추적:

| hop | 로그 소스 | correlation id 존재? | UTC 타임스탬프 |
|-----|-----------|----------------------|-----------------|
| 1. orders-lite `lnpl run` | run 결과 JSON `trace.correlation_id` | `cid-0001`(CLI가 명시적으로 안 넘기면 고정 기본값 — docs/backends.md L191) | (run 시각, trace에 포함) |
| 2. outbox 행 | `lnpl_outbox.emission_id` | **다른 값**: `wf.create.order.step.7.emit#1` — hop 1의 `cid-0001`과 무관한 별개 식별자 | `created_at=1788627344032`(ms epoch) |
| 3. relay가 만드는 CloudEvents 봉투 | `id` 필드 | **또 다른 값**: `outbox-1`(seq 기반, RFC-0040 §8) — hop 1/2 어느 것과도 안 겹침 | relay 실행 시각(로그 없음 — `lnpl relay --once`는 stdout에 "acked 1 emission(s)"만 냄, 타임스탬프 미기록) |
| 4. notifier `/-/events/order-placed` 접속 로그 | `--log-format json`의 `correlation_id` | **네 번째 값**: `req-b977c0fcddcb`(서버가 요청마다 새로 채번 — docs/serving.md: "실행 전 거절이 아닌 한 응답 본문과 같은 id, 외부에서 새로 채번하지 않는다"고 되어 있지만 실측은 매 HTTP 요청마다 새 id를 만든다는 뜻이지 hop 1의 cid를 이어받지 않는다) | 접속 로그 JSON에 타임스탬프 필드 없음(duration_ms만 있음) — 상대 순서만 로그 파일 append 순서로 추정 |
| 5. stub-b1(fx) 액세스 로그 | 없음 — 타임스탬프·메서드·경로·상태만 | **없음**(스텁은 lnpl 밖 코드 — 애초에 correlation id를 모른다) | `2026-09-05T16:46:23Z`형 ISO 8601 (스텁 자체 로거) |
| 6. stub-hook 액세스 로그 | 없음 | **없음**(위와 동일 이유) | ISO 8601 |

**최초로 끊기는 지점: hop 1→2(orders-lite 실행 → outbox 행)** — outbox
스키마(`lnpl_outbox`)에는애초에 correlation id를 실을 컬럼이 없다
(`seq/emission_id/event/payload/created_at/delivered_at` 6컬럼,
docs/backends.md §3) — `emission_id`는 correlation id가 아니라
effect-id 기반 카운터다. 그래서 하나의 논리적 주문 처리 흐름이 실제로는
**서로 무관한 4개의 식별자**(cid-0001 / emission_id / CloudEvents id /
req-id)로 쪼개져 있고, 이들을 잇는 조인 키는 오직 **비즈니스 값**
(`order.id = "o-1"`, 데이터 payload에 실려 우연히 통과함)뿐이다 —
플랫폼이 제공하는 관측 메커니즘이 아니라, 우리가 payload에 넣은 도메인
필드 하나가 우연히 6홉 전체에 살아남은 것.

**판정**: R9은 **불가** — "하나의 correlation id로 이어진 로그·트레이스"는
없다. 대신 order_id 하나가 (우연히, 저작자가 payload를 그렇게 설계했기
때문에) 6홉 중 4홉에 나타나 수동 조인이 가능하다는 것이 현재 최선이다.
축 ops(관측 공백), severity major.
