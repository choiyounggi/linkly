# ROADMAP — LNPP 구현 착수 로드맵

RFC-0001~0006이 설계 계약을 고정한 뒤의 구현 착수 순서. 3 Phase로 나누고 각 Phase에 목표·선행
RFC·산출물·**이진 판정 가능한 완료 기준**·리스크를 적는다.

## 0. 전제와 범위

- **참조 구현 언어 = Rust** (`plans/rfc-suite/plan.md` **D10** — LLVM 바인딩·단일 바이너리 배포).
  RFC 본문은 구현 언어 비종속으로 기술되어 있고, 이 결정은 ROADMAP에만 명시한다.
- **인터프리터 우선** (**D14**) — 네이티브 컴파일 전에 IR 인터프리터를 먼저 만든다. 검증 루프를
  최단화하기 위함이다. LLVM 백엔드는 Phase 2.
- **RFC Status는 전부 `Draft`다.** 이 로드맵은 Accepted를 전제하지 않는다. RFC-0000 §2가 Accepted
  전이 기준을 "Task 09 교차 정합성 체크리스트 전 항목 PASS **+ 소유자 승인**"으로 규정하므로,
  승격은 사용자 리뷰 대상이다.
- **이 문서는 Phase 1 착수 자체를 하지 않는다.** 착수 계획은 별도 문서다.
- 교차 정합성 판정 결과와 이월된 발견은 `docs/CONSISTENCY-CHECK.md`가 소유하며, 이 문서는
  그중 구현에 영향을 주는 것을 **리스크로 인용**한다.

## D20 4종 아티팩트 게이트

**D20**(RFC 채택 요건 — Wasm 표준화 관례 준용)은 기능 채택에 4종 아티팩트를 요구한다. 고정
체크리스트로 못 박고, 매 Phase 종료 시 같은 방식으로 평가한다.

| # | 아티팩트 | 무엇이 통과시키는가 | 적용 |
|---|---------|-------------------|------|
| ① | 명세(Reference-level) | RFC-0001~0006의 `## Reference-level Specification` 절이 존재하고, 구현자가 그 절만으로 구현 가능하다 | RFC 단계 — **충족** |
| ② | 산문 설명(Guide-level) | 같은 6 RFC의 `## Guide-level Explanation` 절이 존재한다 | RFC 단계 — **충족** |
| ③ | 참조 인터프리터 구현 | 모드 A 구현이 `examples/login.lnpl`을 실행한다 | **Phase 1부터** |
| ④ | 테스트 스위트 | `tests/`에 positive 1건 + 고의 파괴 negative 3건 이상이 존재하고 **skip 0건** | **Phase 1부터** |

**게이트 결과는 셋 중 하나로 기록한다. 네 번째 결과는 없다.**

| 결과 | 조건 |
|------|------|
| 통과 | 필수 게이트 4행 전부 통과 |
| 알려진 이슈와 함께 통과 | 게이트가 결함을 드러냈고, 각 이슈가 **소유자의 명시 수락**을 받아 목록에 있다 |
| 차단 | 필수 게이트가 실패했고 수정도 소유자 수락도 없다 |

**skip은 통과가 아니다.** ④에서 skip된 테스트는 미평가 게이트로 세며, 통과 계산에 넣지 않는다.
"아마 괜찮다"는 기록은 게이트 결과가 될 수 없다.

> **2026-07-31 개정 — Phase 1 착수·완료, 결정 3건 변경/해소.**
>
> - **D10 변경**: Phase 1 참조 구현 언어를 Rust → **Python**으로 바꿨다. D10이 Rust를
>   고른 근거는 "LLVM 바인딩 + 단일 바이너리"인데 그것은 Phase 2(네이티브 백엔드)의
>   요구이고, Phase 1은 참조 인터프리터 = **명확성 우선의 실행 가능한 명세**다(D20 ③,
>   WebAssembly 관례). 기존 `scripts/validate_ir.py`와 툴체인이 하나로 유지되는 이점도
>   있다. Phase 2에서 LLVM이 들어올 때 Rust로 간다.
> - **R1 해소**: 닫힌 동사 사전으로 Effect를 결정적 도출(RFC-0002 부록 A.4-③).
> - **R2 해소**: 균일 id 도출 규칙(RFC-0002 부록 A.4-⑦). 골든 19노드 id·순서를 전량 재현.
> - **R6 해소**: RFC-0003에 `transfer` 프리미티브 추가(C8).
> - **골든 예제가 기계 생성으로 전환됐다**: `examples/login.lir.json`은 이제 손으로
>   유지하는 파일이 아니라 `examples/login.lnpl`을 컴파일한 산출물이며, 그 일치를
>   `impl/tests/test_golden.py`가 회귀로 잡는다.
> - **R3·R4·R5도 해소됐다**(2026-07-31 2차): `spec` 매니페스트 생성기 + 러너 신설(R3),
>   `Guard` kind 신설로 가드가 IR에 담김(R4), `Pipeline` 이름 파생·플래그 metric 직렬화·
>   `Workflow.children` 확장·capability 귀속 규칙 확정으로 4공백 해소(R5).
>   **RFC-0002 부록 A.4의 8항이 전부 해소됐고, 전 RFC가 `Accepted`로 승격됐다**
>   (승격 근거: `docs/CONSISTENCY-CHECK.md` §승격 기록).
> - Phase 1 완료 기준 재확인: 골든이 컴파일→실행되고(6 step, SLO 충족), `spec` 4기대
>   전부 통과, 단위 87건 통과, 뮤테이션 14종 전부 RED로 잡힘.

## Phase 1 — MVP: 파서 + IR 인터프리터

### 목표

`.lnpl` 소스를 파싱해 `.lir.json`을 산출하고, IR 인터프리터(모드 A)로 골든 시나리오 "Login"을
실행한다. capability(`postgres`·`redis`·`jwt`)는 인메모리 fake로 대체한다.

이 인터프리터의 목적은 **성능이 아니라 실행 가능한 명세**다 — WebAssembly 참조 인터프리터 관례
(명확성·단순성 우선)를 따른다(**D20**, `rfcs/0004-compiler.md:271` "모드 A … 목적은 성능이 아니라
실행 가능한 명세").

### 선행 RFC

| RFC | 무엇을 소비하는가 |
|-----|------------------|
| RFC-0001 + 부록 A | 노드 카탈로그 19 kind, Semantic Type 18종, 구조 규칙 6종, `.lir.json` 직렬화·스키마 |
| RFC-0002 + 부록 A | EBNF 51 생산규칙, 키워드 카탈로그, lowering 매핑 51행 |
| RFC-0003 | Effect 6종 실행 의미, Policy·Performance 집행, arena·pool 프리미티브, Observability |
| RFC-0004 (S1~S3, 모드 A) | 파이프라인 S1~S3, 문서 수준 불변식 V1~V5, 고수준 패스 3종, 컴파일 컨텍스트 |

### 산출물

- Rust `.lnpl` 파서 (S1 Semantic Parser)
- `.lir.json` 생성기 + S2 IR Validator(문서 수준 불변식 V1~V5)
- IR 인터프리터 (모드 A — S3까지 수행 후 IR + 컴파일 컨텍스트 직접 실행)
- **`tests/` 디렉토리 신설** (공식 테스트 스위트 — D20 ④)

### 완료 기준

전 항목이 이진 판정 또는 측정 임계값이다.

| # | 기준 | 판정 방법 |
|---|------|----------|
| 1 | `examples/login.lnpl`을 파싱해 산출한 `.lir.json`이 스키마 검증을 통과한다 | `python3 scripts/validate_ir.py <산출파일>` → exit 0 |
| 2 | 산출 `.lir.json`이 `examples/login.lir.json`과 동일하다 | RFC 8785 canonical form 비교(RFC-0001 부록 A.3)로 바이트 동일. **조건부** — 리스크 R1·R2 미해소 시 이 기준은 성립하지 않는다(아래) |
| 3 | 실행 타임라인이 RFC-0003 §Examples 타임라인 A와 4점에서 일치한다 | ⓐ step 실행 순서가 `wf.login.step.1`→`.6` ⓑ `retry 3`의 재시도 판정이 "도달 전 실패 + `read` 멱등 → 재시도 허용" ⓒ `cache 5m` TTL의 소유가 `perf.login`(CacheAccess `set`이 TTL을 스스로 정하지 않음) ⓓ `response < 50ms`가 **집행되지 않음**(55ms 실행도 차단되지 않음) |
| 4 | 타임라인 C(재시도 소진)가 재현된다 | 초기 1회 + retry 3회 = 4회 실패 후 workflow가 `Failed`로 종결하고, `rollback` 평가 결과가 no-op이다(커밋된 선행 Transaction 0건) |
| 5 | 타임라인 B(캐시 적중)가 재현된다 | TTL 5m 내 재실행 시 step 3이 적중 경로로 가고, 적중/미적중이 오류가 아닌 두 정상 경로로 관측된다 |
| 6 | Observability 계약이 이행된다 | 메트릭 라벨이 `module/service/workflow/step/kind` 5개뿐이고, `password` 값이 로그·trace·에러·직렬화 출력에 평문으로 0건 등장한다 |
| 7 | `tests/`가 존재하고 스위트가 실패할 수 있다 | positive 1건(골든) + 고의 파괴 negative 3건 이상이 전부 red를 낸다. skip 0건 |
| 8 | D20 게이트 ③④가 기록된다 | 게이트 체크리스트 4행이 `통과 / 알려진 이슈와 함께 통과 / 차단` 중 하나로 문서에 기록됨 |

### 리스크

`rfcs/0002-syntax.md` 부록 A.4의 미해소 공백 8항과 각 RFC Open Questions에서 인용한다.

| # | 리스크 | 원천 | 왜 Phase 1인가 |
|---|--------|------|---------------|
| **R1** | 골든 IR 19노드 중 **3노드에 표면 표기가 없다** — `wf.login.step.1.check`(Validation)·`.2.repo`(RepositoryCall)·`.3.cache`(CacheAccess). 파싱만으로는 16노드까지만 나오므로 **완료 기준 2가 그대로는 성립하지 않는다** | A.4-③ (`rfcs/0002-syntax.md:490`) — "이 3종은 선언된 의도로부터 컴파일러·에이전트가 도출하는 노드다". 해소 소유자: RFC-0002 개정(표면 표기 신설) 또는 RFC-0004(도출 패스 규정) | **Phase 1 최대 리스크.** 골든 실행이 이 3노드를 필요로 한다(`.1.check`가 Validation, `.2.repo`가 저장소 읽기, `.3.cache`가 캐시 쓰기). 착수 전 소유자 결정이 필요하다 |
| **R2** | 노드 `id` **도출 규칙이 없다** — `LoginService`→`svc.login`(접미사 제거), `UserCreated`→`event.user.created`(PascalCase 분해)가 기계 규칙으로 자명하지 않다. 형식(dot-path 정규식)만 규정돼 있다 | A.4-⑦ (`:494`) — 해소 소유자에 **"ROADMAP Phase 1 파서 구현"이 명시**됨 | 해소 소유자가 이 Phase를 직접 지목한다. 완료 기준 2(바이트 동일)가 id 도출에 직접 의존한다 |
| **R3** | `spec`·`given`·`when`·`expect`·`PhraseLine`에 대응 IR kind가 없다 — 테스트 명세는 IR 노드가 아니라 테스트 스위트 아티팩트로 산출한다 | A.4-② (`:489`) — 해소 소유자 **"ROADMAP Phase 1(`tests/` 신설)"** | 완료 기준 7과 직결. `spec` 절을 파싱해 무엇으로 산출할지가 `tests/` 설계를 정한다 |
| **R4** | `when`·`repeat`·`until` 가드가 lowering에서 **소실**된다 — 대응 IR kind가 없고 RFC-0003도 가드의 실행 의미를 규정하지 않는다 | A.4-① (`:488`). 해소 소유자: RFC-0001 개정(조건·가드 kind 신설) + RFC-0003(평가 의미) | 골든 시나리오에는 가드가 없어 완료 기준을 막지 않으나, **문법 전량 파서**에는 필요하다. `docs/CONSISTENCY-CHECK.md` C6 인접 발견 ②가 이 공백이 GLOSSARY `Lowering`의 "의미 보존"과 긴장 관계임을 등재했다 |
| **R5** | 문법 전량 구현 시 부딪히는 4공백: `PipelineBlock`이 이름 토큰을 갖지 않는데 IR `Pipeline`은 `name` 필수 / 값 없는 Performance metric 3종(`parallel`·`prefetch`·`batch`)이 `value` 필수 때문에 직렬화 불가 / workflow 직속 `ParallelBlock`·`PipelineBlock`의 소유 경로 미해소 / R3 capability 귀속이 Service 1개로만 실증된 잠정 규칙 | A.4-④⑤⑥⑧ (`:491, :492, :493, :495`) | 골든에는 출현하지 않으므로 완료 기준을 막지 않는다. 골든 외 소스를 파싱하는 순간 4건 전부 발생한다 |
| **R6** | **heap 프리미티브의 런타임 계약이 없다** — RFC-0003 §Memory Model은 arena·pool 2종만 계약으로 정의하는데 RFC-0004는 배치 대상으로 Heap을 선택한다. arena 수명을 넘기는 값의 할당·해제 책임과 수명 종료 시점이 미정이다 | `docs/CONSISTENCY-CHECK.md` **C8**(FINDING). 해소 소유자: RFC-0003 개정 | 인터프리터가 arena 수명을 넘기는 값을 어떻게 다룰지 계약이 없다. 골든 시나리오에는 Heap 사례가 없어(`rfcs/0004-compiler.md:398` "이 시나리오에는 발생하지 않는다") 완료 기준을 막지 않지만, 인터프리터 메모리 모델 설계에는 결정이 필요하다 |
| **R7** | 런타임 계약의 미결 4항: actor 메일박스 백프레셔(bounded 여부·거부 형태) / 분산 actor 배치·라우팅 / EventEmit 전달 보장의 구현(transactional outbox 채택 여부) / 캐시 스탬피드 보호(single-flight·stale-while-revalidate) | RFC-0003 Open Questions ①②③④ (`rfcs/0003-runtime.md:317-327`) | ①은 pool의 fail-fast 계약과 정렬이 필요하다고 RFC 자신이 적는다. ③은 골든에 EventEmit이 없어 Phase 1을 막지 않는다 |
| **R8** | IR 측 미결 3항: 제네릭·컬렉션 타입(List/Map/Optional) 부재 / 바이너리 직렬화 포맷 / IR 버전 마이그레이션 절차 | RFC-0001 Open Questions ①②③ (`rfcs/0001-semantic-ir.md:290-296`) | 골든은 18종 타입만 쓰므로 막히지 않는다. ③은 Phase 1 산출 `.lir.json`이 `lir_version: "0.1"`에 고정되므로 개정 시 이행 절차가 필요해진다 |
| **R9** | step 토큰 상한(동사 선두 1~4토큰)이 **실측 없는 설계 가설**이다 | RFC-0002 Open Questions ① (`rfcs/0002-syntax.md:586-590`) — "참조 인터프리터(plan.md D14·D20) 단계에서 **실측 후 재검토한다**" | RFC가 재검토 시점으로 이 Phase를 지목한다. 파서 구현이 실측 기회다 |
| **R10** | MLIR/LLVM 버전 고정 정책 미결 — 다만 형태는 정해져 있다(레포에 커밋된 핀 파일 하나를 정본으로 하고 CI가 그 파일을 읽는다) | RFC-0004 Open Questions ① (`rfcs/0004-compiler.md:429-432`) | Phase 1은 LLVM을 쓰지 않으므로 막히지 않는다. **Phase 2 착수 전에 핀 파일을 만들어 두는 것이 이 Phase의 준비 항목이다** |

> **2026-07-31 Phase 2 1차 조각 완료.** 모드 B가 실제 네이티브 바이너리를 산출하고,
> 모드 A/B 차동 검증이 관측 가능 4종(실행 순서·정책 결과·관측성 신호·마스킹)에 대해
> EQUIVALENT를 확인했다. OpenAPI 자동생성도 동작한다. **남은 조각: 커스텀 `lnpl`
> dialect(S4)** — C++ TableGen 빌드가 필요해 이번 조각에서 제외했고, 이탈을 RFC-0004
> Open Questions 앞에 기록했다.
>
> 환경 부작용 1건: `brew install llvm`이 의존성으로 `python@3.14`를 설치해 기본
> `python3`가 3.9.6 → 3.14.6으로 바뀌었고, 3.14는 PEP 668 externally-managed라
> `pip --user`가 막힌다. 그래서 프로젝트를 `.venv`로 고정했다(README 참조) — PATH가
> 무엇을 가리키든 검증이 같게 돌아간다.

## Phase 2 — LLVM 백엔드(모드 B) + 자동 생성물 1종(OpenAPI)

### 목표

`lnpl` MLIR dialect를 만들고 S4~S7 progressive lowering으로 네이티브 바이너리를 산출한다
(**D18**). Architecture Optimizer의 자동 생성물 중 **OpenAPI 문서** 1종을 구현한다. 두 실행 모드가
관측 가능한 동작에서 동등함을 차동 검증으로 확인한다.

### 선행 RFC

| RFC | 무엇을 소비하는가 |
|-----|------------------|
| RFC-0004 전량 | S4~S7 하강, `lnpl.node_id` 역추적 규칙 4종, 자동 최적화 9종의 발생 레벨, 실행 모드 동등성 |
| RFC-0003 | 관측 가능한 동작 4종(S5~S7이 보존해야 하는 것), structured concurrency 4조건 |
| RFC-0001 부록 A | Semantic Type 18종의 내장 validation rule(OpenAPI 생성 원천) |
| Phase 1 산출물 | 모드 A 인터프리터(차동 검증의 한쪽), `tests/` 스위트 |

### 산출물

- `lnpl` MLIR dialect + S4 변환 (`lnpl.node_id` attribute + MLIR Location 이중 경로)
- S5 표준 dialect 하강(`func`·`scf`·`async`·`memref`·`arith`·`vector`) → S6 LLVM dialect → S7 네이티브
- Architecture Optimizer의 OpenAPI 문서 생성
- 차동(differential) 검증 하네스

### 완료 기준

| # | 기준 | 판정 방법 |
|---|------|----------|
| 1 | **모드 A/B 동등성** — 같은 `examples/login.lir.json`을 두 모드로 실행해 동등성 대상 4종이 일치한다 | 4종 = ⓐ 실행 순서(step 순서, structured concurrency의 join·취소 전파) ⓑ 정책 집행 결과(retry 판정, rollback 경계, timeout 시 종결 상태) ⓒ 관측성 신호(trace 구조, 상관ID 전파, 메트릭 라벨 집합, 로그 레벨) ⓓ 마스킹. 차동 검증 하네스 exit 0 (`rfcs/0004-compiler.md:274-285`) |
| 2 | **하네스가 실패할 수 있음을 증명한다** | RFC-0004 `:291-295`의 고의 불일치 3케이스에서 대조가 **red**를 낸다: ⓐ S3-2가 데이터 의존이 있는 두 step의 `children` 순서를 바꾸는 잘못된 최적화 ⓑ 모드 B에서만 retry 백오프 대기를 제거 ⓒ 모드 B에서만 마스킹 필터를 우회. **3케이스 중 하나라도 green이면 하네스 결함이며 Phase 2는 미완료다** |
| 3 | 역추적이 보존된다 | 최종 산출물의 임의 지점에서 원 IR 노드 id를 **최소 1개 이상** 얻을 수 있다(`rfcs/0004-compiler.md:171-172`의 판정 문장) |
| 4 | 역추적 규칙 4종이 지켜진다 | 1:1 변환은 id 그대로 / 다:1 병합은 **전 id 보존**(하나만 남기고 축약하지 않음) / 1:다 확장은 생성된 전 op이 같은 id / S5~S7에서 op이 소멸해도 진단·디버그 정보가 해소하는 id는 유지 |
| 5 | 노드 id 안정성이 지켜진다 | 재명명 0건, 삭제한 id의 재사용 0건, 신규 노드 id가 `^[a-z][a-z0-9]*(\.[a-z0-9]+)*$`에 적합 |
| 6 | OpenAPI 문서가 Semantic Type의 validation rule을 반영한다 | `entity.user` 4필드 각각: `id` UUID = RFC 4122 canonical 형식 / `email` Email = RFC 5322 addr-spec / `password` Password = **응답 스키마에 미노출** / `createdAt` DateTime = RFC 3339. 생성된 문서가 OpenAPI 스키마 검사를 통과 |
| 7 | Constraint 값이 불변이다 | S3 전 구간에서 Policy·Security·Performance 노드의 값 변경 0건(S3 불변조건 ④) |

### 리스크

| # | 리스크 | 원천 | 영향 |
|---|--------|------|------|
| ~~**R11**~~ | ~~동등성 판정선이 문서에서 갈린다~~ → **해소됨(리스크 아님)**. 동등성 비대상 목록이 배치의 *선택*을 비대상으로 열거해 §두 모드에서의 동일 관측과 어긋났던 문제. 비대상을 "메모리 배치의 **실현 방식**(S5~S7 하강의 레지스터·스택 슬롯 승격)"으로 좁히고 "배치의 선택 자체는 S3 공유이므로 비대상이 아니다"를 명문화해 해소 | `docs/CONSISTENCY-CHECK.md` **C9 부류②** — 모순 확정 후 **최소 수정으로 해소 완료**(`rfcs/0004-compiler.md:282-285`) | **완료 기준 1의 판정선이 확정됐다**: 모드 B가 배치 *선택*을 바꾸면 계약 위반이다(S3 공유). 달라도 되는 것은 그 선택의 *실현 방식*뿐이다. 차동 검증 하네스는 이 기준으로 판정한다 |
| **R12** | MLIR/LLVM 버전 고정 정책 미결 | RFC-0004 OQ ① (`:429-432`) | 형태는 정해져 있으므로(커밋된 핀 파일 1개 + CI가 읽음) Phase 1 준비 항목(R10)에서 만들어 두면 해소된다 |
| **R13** | `lnpl` dialect 커스텀 op 목록 미확정 + MLIR Location 구성 방식 미결(`lnpl.node_id` attribute 이름은 확정) | RFC-0004 OQ ② (`:433-435`) | S4 설계의 직접 입력. 역추적 이중 경로 중 Location 쪽이 미정이므로 완료 기준 3·4의 구현 방식이 열려 있다 |
| **R14** | 디버그 정보 포맷 미결 — IR 노드 id ↔ DWARF 매핑 방식 | RFC-0004 OQ ④ (`:438`) | **S7 불변조건이 이것에 의존한다**고 RFC가 명시한다. 완료 기준 3의 S7 구간이 이 결정을 기다린다 |
| **R15** | 자동 최적화 9종의 알고리즘 상세 미결(정의 1줄과 발생 레벨까지만 고정) | RFC-0004 OQ ⑤ (`:439-440`) | 9종 구현 시점의 설계 부담. 완료 기준에 9종 구현이 없으므로 이 Phase를 막지 않는다 |
| **R16** | escape analysis 정밀도 한계 — Semantic IR v0.1에 값의 명시적 데이터 흐름 노드가 없어 판정이 step 경계 기준의 보수적 근사에 머문다. 판정 불가는 Arena 폴백 | RFC-0004 OQ ⑥ (`:441-444`) — "명시적 데이터 흐름 표현을 IR에 도입할지는 RFC-0001의 개정 사항이며, 도입 전까지 Stack 승격 범위는 좁게 유지된다" | Stack 승격이 좁아 최적화 이득이 제한된다. 정확성 리스크는 아니다(폴백이 보수적이므로) |
| **R17** | 증분 컴파일의 단위 미결 — 노드 id가 안정적이라 id 단위 캐시가 가능해 보이나, 컴파일 컨텍스트가 노드 간 결정에 의존할 때의 무효화 범위가 미결 | RFC-0004 OQ ③ (`:436-437`) | 빌드 시간에만 영향. 완료 기준을 막지 않는다 |
| **R18** | **제네릭·컬렉션 타입 부재** — List·Map·Optional이 Semantic Type 시스템에 없다 | RFC-0001 OQ ① (`rfcs/0001-semantic-ir.md:290-291`) | **완료 기준 6에 영향.** 골든의 `entity.user` 4필드는 전부 단일 타입이라 통과하지만, 배열·맵 필드를 가진 Entity의 OpenAPI 스키마는 생성할 수 없다 |
| **R19** | 값 없는 Performance metric 3종의 직렬화 불가 | A.4-⑤ (`rfcs/0002-syntax.md:492`) | Performance 예산을 소비하는 최적화(O6 Prefetch·O8 Cache Optimization)가 `prefetch`·`batch` 선언을 읽을 수 없다 |
| **R20** | 문법 표면 표기가 없는 Effect 3종(R1)이 미해소면, 모드 B가 컴파일할 IR도 도출 경로에 의존한다 | A.4-③ (`:490`) — 해소 소유자에 **RFC-0004(도출 패스 규정)**가 포함됨 | Phase 1에서 R1을 어떻게 해소했는지가 이 Phase의 S1~S3 입력을 정한다 |

## Phase 3 — KB 시드 12카테고리 + 에이전트 2종 프로토콜 왕복

### 목표

Knowledge Base를 12카테고리 각 1문서로 시드하고, Planner·Coder 2종 에이전트로 RFC-0006
프로토콜의 1사이클 왕복을 데모한다.

### 선행 RFC

| RFC | 무엇을 소비하는가 |
|-----|------------------|
| RFC-0005 | 문서 스키마(frontmatter 6종), 카테고리 12종, 3단 progressive disclosure 라우팅, 소비 인터페이스 3종, 갱신 수명주기 |
| RFC-0006 | 역할 9종의 IR 접근권, JSON-RPC 메서드 8종, `_meta` 3필드, 구조화 오류, 멱등키·데드라인·재시도, 태스크 수명주기 6상태 |
| RFC-0001 | IR 조각(`ir_fragment`) 교환 형식 |
| Phase 1 산출물 | `.lir.json` 생성기(`ir.get`·`ir.propose`의 대상) |

### 산출물

- `kb/INDEX.md`(루트 라우팅 인덱스) + 12 카테고리 `index.md` + 카테고리당 문서 1건(총 12문서)
- Planner·Coder 2종 에이전트
- JSON-RPC 2.0 엔드포인트(메서드 8종: `agent.card`·`agent.dispatch`·`agent.report`·`ir.get`·
  `ir.propose`·`kb.route`·`kb.load`·`kb.verify`)

### 완료 기준

| # | 기준 | 판정 방법 |
|---|------|----------|
| 1 | KB 12문서가 스키마에 적합하다 | 각 문서가 frontmatter 필수 6종(`id`/`category`/`triggers`/`version`/`status`/`sources`)을 갖고, `id`가 카테고리 소문자 접두이며 KB 전역 유일, `triggers` ≥1, `sources` ≥1, `version`이 semver, 본문 ≤500줄. 검사 스크립트 exit 0 |
| 2 | 12카테고리가 Charter 표기 그대로 고정돼 있다 | `Architecture`·`Naming`·`Performance`·`Security`·`Testing`·`Concurrency`·`Database`·`Cloud`·`Patterns`·`AntiPatterns`·`Style`·`Framework` 12개 디렉토리가 소문자명으로 존재하고, 각 디렉토리에 `index.md` 1개 + 문서 1개 이상 |
| 3 | 3단 progressive disclosure가 지켜진다 | `kb.route`가 **라우팅 인덱스 정보만으로** 매칭한다(문서 본문 로드 0건) / 인덱스에 문서 본문 내용 0건 / `resources/`로의 직접 라우팅 0건(진입점은 언제나 본문) |
| 4 | RFC-0006 §Examples 6교환이 실제 왕복으로 재현된다 | ① `agent.card`(Architect 능력 공표) ② `agent.dispatch`(Planner→Architect 위임) ③ `ir.propose`(Architect의 IR 제안) ④ `kb.route`→`kb.load`(Coder의 KB 라우팅) ⑤ `agent.report`(Reviewer 승인 + 상태 통지) ⑥ 실패 2종(`ir_invalid`·`internal`). 6교환 전부 성공 |
| 5 | 태스크 수명주기가 전이한다 | `submitted`→`working`→`completed` 전이가 일어나고, **전이마다** `task.status` 통지가 발행된다. 종결 상태(`completed`·`failed`·`canceled`) 이후 전이 0건 |
| 6 | `_meta` 3필드가 강제된다 | `deadline`·`correlation_id`는 8메서드 전부에서 필수 / `idempotency_key`는 `agent.dispatch`·`ir.propose`에서만 필수. 누락 요청이 거부된다 |
| 7 | `kb_pins`가 우회 불가하다 | `agent.report`의 `kb_pins`가 필수이고, KB 미사용 시 **빈 배열 `[]`이 명시**된다. 필드 생략으로 핀 검증을 우회하는 경로 0건 |
| 8 | `kb.*` 3종의 형태가 명세와 일치한다 | `kb.route` params `{ task_description, _meta }` → result `[doc_id]` / `kb.load` `{ doc_id, _meta }` → `document` / `kb.verify` `{ doc_id, version, _meta }` → `bool`. 세 응답 모두 `_meta`를 반향하지 않는다(result 형태는 RFC-0005 소유) |
| 9 | 역할별 제안 범위가 강제된다 | Planner·Reviewer·ReleaseAgent의 `ir.propose` 시도가 거부되고, Coder의 제안이 Behavior·Effect로 제한된다. 읽기는 9역할 전부 `전체` |

### 리스크

| # | 리스크 | 원천 | 영향 |
|---|--------|------|------|
| **R21** | KB 저장소의 동기화·배포 미결 — 여러 에이전트가 분산돼 있을 때 동일 KB 스냅샷을 보게 하는 방법(복제·버전 태깅·CDN) | RFC-0005 OQ ① (`rfcs/0005-knowledge-base.md:284-286`) — "소비 연산의 전송은 RFC-0006이 정의하지만, **저장소 운영 방식은 ROADMAP에서 다룬다**" | RFC가 이 문서를 해소 소유자로 지목한다. 단일 노드 데모는 막히지 않으나, "모든 Agent가 동일한 KB를 사용한다"(GLOSSARY)를 분산 환경에서 보장하려면 결정이 필요하다 |
| **R22** | 임베딩 기반 보조 라우팅 도입 여부 미결 — 결정론 요건(`kb.route`가 인덱스 정보만으로 매칭)과의 절충 | RFC-0005 OQ ② (`:287-288`) | 완료 기준 3이 결정론 쪽을 요구하므로 이 Phase는 인덱스 라우팅만 구현한다. 재현율 한계는 남는다 |
| **R23** | 카테고리 개정 절차 미결 — Charter 12종 고정 전제에서 새 카테고리 수요가 확인될 때의 경로(Supersede 필요 여부) | RFC-0005 OQ ③ (`:289-291`) | 12종 시드에는 영향 없다. 시드 후 실사용에서 부딪힌다 |
| **R24** | **에이전트 인증·권한 집행 메커니즘 미정** — RFC-0006은 역할별 접근권을 *정의*하지만 인증 주체와 집행 메커니즘은 정의하지 않는다 | RFC-0006 OQ ① (`rfcs/0006-agent-protocol.md:855-857`) | **완료 기준 9에 직접 타격.** "역할별 제안 범위가 강제된다"를 무엇이 강제하는지가 미정이므로, 데모는 신뢰 전제(에이전트가 자기 역할을 정직하게 신고) 위에서만 성립한다 |
| **R25** | HITL 승인 UX 미결 — `input-required` 상태에서 사람이 개입하는 표면(승인 화면·알림 경로·대기 만료 처리) | RFC-0006 OQ ② (`:858-860`) | 완료 기준 5는 `submitted`→`working`→`completed` 경로만 요구하므로 `input-required`를 지나지 않는다. 실사용 파이프라인에는 필요하다 |
| **R26** | A2A/MCP 공식 호환 범위 미결 — "정렬"을 어디까지 밀어 실제 A2A 클라이언트가 LNPP 에이전트를 그대로 호출하게 할지(Agent Card 스키마 완전 준수·A2A 메서드명 채택 여부) | RFC-0006 OQ ③ (`:861-864`) — "완전 호환은 이 프로토콜의 메서드명을 A2A 것으로 바꾸는 문제가 된다" | 메서드 8종 고정과 충돌할 수 있다. 완료 기준은 자체 메서드명 기준이므로 막히지 않는다 |
| **R27** | **외부 발신 취소 표면이 없다** — `canceled` 진입 경로가 데드라인 경과·상위 전파·담당 에이전트의 확정 보고 셋뿐이고, 사용자·오케스트레이터가 취소를 **개시**하는 메서드가 메서드 8종 고정 때문에 없다 | RFC-0006 OQ ④ (`:865-869`) | 완료 기준 5가 취소 경로를 요구하지 않으므로 막히지 않는다. 장기 실행 태스크의 운영에는 9번째 메서드 또는 `agent.dispatch` 재호출 의미론 결정이 필요하다 |
| **R28** | 절대 데드라인의 시계 동기 가정 — RFC 3339 절대 시각 전파는 홉 간 시계 동기를 전제한다. 드리프트 큰 환경의 보정(단조 시계 병용·상대 잔여시간 폴백) 미결 | RFC-0006 OQ ⑤ (`:870-872`) | 단일 노드 데모는 영향 없다. 분산 배포 시 데드라인 오판이 발생한다 |
| **R29** | 표현식 표기 미정으로 `BusinessRule.expression`이 v0.1에서 비어 있다(`GoalLine`은 `name`=`statement`만 채운다) | RFC-0002 OQ ②③ (`rfcs/0002-syntax.md:591-595`) + 부록 A.5 (`:497-504`) | KB 문서가 지시하는 비즈니스 규칙을 IR의 형식 표현으로 옮길 수 없다. `statement` 산문으로만 남는다 |
| **R30** | 가드 조건식의 표현력 한계 — `Condition`이 비교식 + 1~4토큰 구가 전부이며 부정·논리 결합(and/or)·멤버십 검사가 없다 | RFC-0002 OQ ② (`:591-592`) | 에이전트가 생성하는 `.lnpl`의 표현력 상한. R4(가드 소실)와 겹친다 |

## 리스크 원천 색인

A.4 8공백 · 6 RFC의 Open Questions 27항 · CONSISTENCY-CHECK의 발견 2건을 전량 Phase에 매핑한다.
어느 원천도 "언급 없음"으로 남지 않는다.

### RFC-0002 부록 A.4 — 미해소 lowering 공백 8항 (`rfcs/0002-syntax.md:486-495`)

| 원천 | 내용 요약 | 해소 소유자(원문) | 인용 Phase |
|------|----------|------------------|-----------|
| A.4-① | 가드(`when`/`repeat`/`until`)·`Condition`에 대응 IR kind 없음 | RFC-0001 개정 + RFC-0003 | Phase 1 (R4), Phase 3 (R30) |
| A.4-② | `spec`/`given`/`when`/`expect`/`PhraseLine`에 대응 kind 없음 | **ROADMAP Phase 1(`tests/` 신설)** | Phase 1 (R3) |
| A.4-③ | `Validation`·`RepositoryCall`·`CacheAccess`의 표면 표기 없음 | RFC-0002 개정 또는 RFC-0004 | Phase 1 (R1), Phase 2 (R20) |
| A.4-④ | `PipelineBlock`에 이름 토큰 없음 / IR `Pipeline.name` 필수 | RFC-0002 개정 또는 RFC-0001 개정 | Phase 1 (R5) |
| A.4-⑤ | 값 없는 Performance metric 3종 직렬화 불가 | RFC-0001 부록 A(스키마 개정) | Phase 1 (R5), Phase 2 (R19) |
| A.4-⑥ | workflow 직속 Concurrency·Pipeline의 소유 경로 미해소 | RFC-0001 개정 또는 RFC-0002 개정 | Phase 1 (R5) |
| A.4-⑦ | 노드 `id` 도출 규칙 없음 | RFC-0001 개정 또는 **ROADMAP Phase 1 파서 구현** | Phase 1 (R2) |
| A.4-⑧ | R3(capability 귀속)이 Service 1개로만 실증된 잠정 규칙 | RFC-0002 개정 또는 RFC-0001 | Phase 1 (R5) |

### Open Questions 27항

| RFC | 항 | 인용 Phase |
|-----|----|-----------|
| RFC-0001 (4항) | ① 제네릭/컬렉션 타입 | Phase 1 (R8), Phase 2 (R18) |
| | ② 바이너리 직렬화 포맷 | Phase 1 (R8) |
| | ③ IR 버전 마이그레이션 | Phase 1 (R8) |
| | ④ 노드 카탈로그 확장 절차 | Phase 1 (R8 — 카탈로그 개정이 필요해지는 시점) |
| RFC-0002 (5항) | ① step 토큰 상한이 실측 없는 가설 | Phase 1 (R9 — RFC가 이 Phase를 재검토 시점으로 지목) |
| | ② 가드 조건식의 표현력 | Phase 3 (R30) |
| | ③ refinement 타입의 표면 표기 | Phase 3 (R29) |
| | ④ Duration 단위 확장·필드 optional 표기 | Phase 1 (R5 — 문법 전량 구현 시) |
| | ⑤ goal 절의 lowering 대상 | **해소됨** — 부록 A.5가 `BusinessRule`로 확정(`:497-504`) |
| RFC-0003 (4항) | ① actor 메일박스 백프레셔 | Phase 1 (R7) |
| | ② 분산 actor | Phase 1 (R7 — 단일 노드 전제의 한계) |
| | ③ EventEmit 전달 보장의 구현 | Phase 1 (R7) |
| | ④ 캐시 스탬피드 보호 | Phase 1 (R7) |
| RFC-0004 (6항) | ① MLIR/LLVM 버전 고정 정책 | Phase 1 (R10 준비), Phase 2 (R12) |
| | ② `lnpl` dialect op 목록·Location 표기 | Phase 2 (R13) |
| | ③ 증분 컴파일의 단위 | Phase 2 (R17) |
| | ④ 디버그 정보 포맷(DWARF 매핑) | Phase 2 (R14) |
| | ⑤ 자동 최적화 9종 알고리즘 상세 | Phase 2 (R15) |
| | ⑥ escape analysis 정밀도 | Phase 2 (R16) |
| RFC-0005 (3항) | ① KB 저장소 동기화·배포 | Phase 3 (R21 — RFC가 ROADMAP을 소유자로 지목) |
| | ② 임베딩 기반 보조 라우팅 | Phase 3 (R22) |
| | ③ 카테고리 개정 절차 | Phase 3 (R23) |
| RFC-0006 (5항) | ① 에이전트 인증·권한 | Phase 3 (R24) |
| | ② HITL 승인 UX | Phase 3 (R25) |
| | ③ A2A/MCP 공식 호환 범위 | Phase 3 (R26) |
| | ④ 외부 발신 취소 표면 | Phase 3 (R27) |
| | ⑤ 절대 데드라인의 시계 동기 가정 | Phase 3 (R28) |

### `docs/CONSISTENCY-CHECK.md`의 발견

| 원천 | 내용 | 해소 소유자 | 인용 Phase |
|------|------|-------------|-----------|
| C8 (FINDING) | heap 프리미티브의 런타임 계약 부재 | RFC-0003 개정 | Phase 1 (R6) |
| C9 부류② (해소 완료) | 동등성 비대상 목록과 §두 모드에서의 동일 관측의 어긋남 | Task 09가 최소 수정으로 해소(`rfcs/0004-compiler.md:282-285`) | Phase 2 R11 — **리스크에서 해제** |
| C6 인접 발견 ① | 무수식 `Pipeline`의 3의미 | `docs/GLOSSARY.md` 개정 | 구현 영향 없음 — 등재만 |
| C6 인접 발견 ② | `Lowering`의 "의미 보존"과 A.4-① 가드 소실의 긴장 | A.4-①과 동일 소유자 | Phase 1 (R4) |

### 모호어 감사

**D13**(완료 기준은 이진 판정 문장 또는 측정 임계값)의 이행을 기계로 확인한다:

이 절은 검사 대상 문자열을 **인용**하므로, 문서 전역 grep은 이 절 안의 정규식 리터럴을 함께
잡는다(자기 참조). 따라서 판정은 **본문 스코프**(이 절 앞)로 한다. 두 명령이 함께 있어야 판정이
성립한다 — 첫째는 본문에 모호어가 없음을, 둘째는 전역 히트가 **전부 이 절 안에만** 있음을 보인다.

```sh
# ① 본문(이 절 앞) 모호어 — 0건이어야 한다
$ awk '/^### 모호어 감사/{exit} {print}' docs/ROADMAP.md \
    | grep -cE '적절히|적당히|충분히|가능하면|필요시|등등|기타'
0

# ② 전역 히트 중 이 절 시작행보다 앞에 있는 것 — 0건이어야 한다 (①의 독립 교차확인)
$ S=$(grep -n '^### 모호어 감사' docs/ROADMAP.md | cut -d: -f1)
$ grep -nE '적절히|적당히|충분히|가능하면|필요시|등등|기타' docs/ROADMAP.md \
    | awk -F: -v s="$S" '$1<s' | wc -l
0
```

**본문 모호어 0건.** 각 Phase의 완료 기준은 `exit 0` / `일치한다` / `0건` / `≥N` / 명시된 값
비교로만 서술되어, 작성자가 아닌 사람이 읽고 통과·실패를 이진으로 답할 수 있다.

②는 행 번호로 판정하므로 이 절의 인용이 몇 개로 늘어도 값이 흔들리지 않는다. 전역 히트 수를
고정 숫자로 적으면 이 절을 한 번 더 편집할 때마다 그 숫자가 거짓이 되므로 적지 않는다.

(자기 참조 함정의 기록: 최초 작성은 전역 grep 결과를 "출력 없음 — 0건"으로 적었으나 실측은
1건이었고, 그 1건을 인용해 고치자 히트가 다시 늘었다. 검사 명령을 문서에 인용하면 그 인용이
검사에 걸린다 — 같은 함정을 `docs/CONSISTENCY-CHECK.md`의 C5 음성 대조와 C8 N3 전수 검색에서도
만났고, 세 곳 모두 기준을 완화하지 않고 **스코프를 좁히거나 행 번호로 판정**해 해소했다.)
