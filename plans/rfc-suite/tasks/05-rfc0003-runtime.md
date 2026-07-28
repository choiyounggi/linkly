# Task 05: RFC-0003 Runtime — 실행 모델·메모리 모델·관측성 계약

## Objective
`rfcs/0003-runtime.md`가 존재하고, IR 노드가 런타임에서 어떤 실행 의미를 갖는지
(동시성·메모리·정책 집행·관측성)가 계약 수준으로 정의되어 있다.

## Wiki pages (read these first, only these)
- wiki/infrastructure/observability/logs-metrics-signals.md — use for: 자동 생성되는
  metrics/trace/log의 기본 계약(상관ID 전파, 라벨 카디널리티 제한) 설계

## Inputs
- `rfcs/0001-semantic-ir.md`의 노드 카탈로그, 특히 Effect·Constraint 대분류 (Task 01 산출물)
- plan.md: D12(관측성 계약), 골든 시나리오(Policy retry3/rollback/timeout3s,
  Performance response<50ms·cache5m)

## Steps
1. `rfcs/0003-runtime.md`를 7섹션 템플릿으로 생성, Status=Draft
2. 실행 모델 절: Charter 규정(Async Native, Event Driven, Actor Model, Lock Free)을
   구조화 — `service` 인스턴스 = actor(직렬 메일박스), `workflow` step = await 지점,
   `parallel` 블록 = structured concurrency(전 분기 완료/실패 시 join, 부모 취소 전파).
   개발자에게 thread API를 노출하지 않음을 명시
3. 정책 집행 절: Constraint 노드의 런타임 의미를 표로 —
   `Policy.retry N`(실패 step 재실행, 멱등 Effect에만), `Policy.rollback`
   (Transaction 노드 경계로 보상), `Policy.timeout`(workflow 데드라인, 초과 시
   취소 전파), `Performance.cache`(CacheAccess 노드 TTL), `Performance.response`
   (SLO 선언 — 집행이 아니라 계측·경보 대상임을 명시)
4. 메모리 모델 절: 개발자 비노출 원칙 + 컴파일러가 Stack/Heap/Arena/Pool을 선택할
   때 런타임이 제공해야 하는 프리미티브(arena 수명 = workflow 실행 수명, pool =
   capability 커넥션) 계약만 정의(선택 알고리즘 자체는 RFC-0004 소유)
5. 관측성 절(위키 페이지 적용): 모든 workflow 실행에 trace(span=step), 상관ID 자동
   전파, step별 duration 메트릭 기본 생성. 메트릭 라벨은 `module/service/workflow/
   step/kind`만 허용 — 사용자ID·UUID 등 무한 카디널리티 값 금지. 로그는 구조화
   JSON, Password/Secret 타입 값은 자동 마스킹
6. Examples: 골든 시나리오 Login 1회 실행의 타임라인(6 step의 span 트리,
   timeout 3s 데드라인, cache 5m 적중/미적중 두 경로)

## Deliverables
- `rfcs/0003-runtime.md`

## Verify
- 체크리스트: (a) Effect 대분류의 모든 노드 kind에 실행 의미 정의가 존재
  (b) 골든 시나리오의 Policy·Performance 5개 항목 각각의 런타임 의미가 Examples에
  등장 (c) 메트릭 라벨 허용 목록이 명시되고 금지 예(사용자ID)가 서술됨
  (d) 7섹션 모두 비어있지 않음

## Out of scope
- 최적화 패스·메모리 배치 선택 알고리즘(Task 06), 에이전트가 런타임을 조작하는
  방법(Task 08)
