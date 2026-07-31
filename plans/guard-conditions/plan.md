# guard-conditions — 이슈 #3 (RFC-0002 OQ② 확정 + 모드 B `until`)

Goal: 가드 조건식의 문법을 **평가기가 구현하는 닫힌 집합**으로 확정하고, 파서가 그
집합 밖을 거부하게 하며, `when`/`until`을 **양 모드에서 실제로 평가**해 `lnpl diff`가
가드를 쓰는 프로그램에 대해 EQUIVALENT를 보고하게 한다.

수용 기준(이슈 #3 원문):
1. 파서가 평가기 없는 조건을 거부한다 — 런타임에 반드시 실패하는 `Guard`로 파싱되는
   프로그램이 존재하지 않는다.
2. `when`과 `until`을 모두 쓰는 소스에 대해 `lnpl diff` → `EQUIVALENT`.
3. `until`이 모드 B에서 컴파일되고, 종료 한계가 현재의 2중 한계와 같은 정밀도로
   서술된다.
4. `mutation_check.py`에 "조건 결과 반전"·"평가 불가 조건 수용" 추가 후 둘 다 RED.
5. 가드를 쓰는 골든 인접 예제로 differential이 가드 실행을 실제 커버.

Stack: Python 3.9+ — **`.venv/bin/python` 필수**(brew llvm이 `python3`를 3.14로 바꿈),
`PYTHONPATH=impl`, unittest. MLIR 툴체인 `/opt/homebrew/opt/llvm/bin`(22.1.8).
Baseline: HEAD `4832352`, working tree clean 상태에서 시작.

## 착수 전에 발견한 것 두 가지 (계획을 바꾼다)

**① RFC-0000에 부분 개정 메커니즘이 없다.** `Superseded`는 **RFC 전체**의 종결
상태이고(§2 상태표 + `Superseded-by:`), 한 절만 고치는 관계가 정의돼 있지 않다. 이
이슈가 실제로 바꾸는 것은 RFC-0002의 `Condition` 생산 규칙 1개와 RFC-0003 §Guard 1개
절인데, 그것 때문에 두 RFC를 통째로 재서술하는 것은 비례하지 않고 재서술 과정에서
무관한 조항이 표류할 위험이 크다. 그리고 그 비용이 크면 결국 "Accepted를 그냥
편집하자"는 압력이 되어 방금 확정한 결정 A(예외 없음)를 무너뜨린다. → **RFC-0000을
먼저 대체해 IETF식 `Updates` 관계를 신설한다**(Task 01). RFC-0000은 프로세스 문서라
짧아서 전체 대체가 실제로 가능하다. 이 메커니즘은 이슈 #2의 RFC-0006 권한 구멍 개정도
같이 푼다.

**② RFC-0003 §Guard의 "두 경계로 유계"가 구현과 다르다.** 명세는 ① workflow 데드라인
② 라운드 상한이고 "어느 쪽이든 먼저 닿으면 중단하고 WARN"이다. 구현은
`if con["timeout_ms"] is None or rounds >= _UNTIL_ROUND_CAP: break`이라서 실제 동작은:
`timeout` 미선언 시 **1라운드 후 중단**(그런데 로그는 "hit its round cap"이라 사실과
다르다), `timeout` 선언 시 라운드만 세고 **데드라인을 루프에서 전혀 보지 않는다**.
즉 명세가 말하는 두 경계 중 어느 것도 서술대로 구현돼 있지 않다. 수용 기준 3이 요구하는
"같은 정밀도의 서술"은 이 불일치를 먼저 없애야 성립한다(Task 04·05).

## Decisions

dev-loop wiki 라우팅: 이 작업은 언어·컴파일러 설계라 wiki 10도메인 중 대응 페이지가
없다(`testing`만 부분 해당). 따라서 대부분 `[no-wiki]`이며, 근거는 이 레포의 RFC
본문과 실측이다. 아래 `[no-wiki]` 항목은 wiki-ingest 후보가 아니다 — 이 레포 고유
설계 결정이기 때문.

| # | Decision | Choice | 근거 |
|---|----------|--------|------|
| G1 | 부분 개정 메커니즘 | **RFC-0007로 RFC-0000을 대체**하고 `Updates:`/`Updated-by:` 관계를 신설한다. 규칙: 신규 RFC는 대상 RFC의 **절 단위**를 명시해 갱신할 수 있고(`Updates: RFC-0002 §Full grammar/Condition`), 대상 RFC는 `Accepted`를 유지한 채 해당 절 머리에 `> 갱신됨: RFC-XXXX` 포인터만 얻는다. 전체 대체(Supersedes)는 계약 전면 교체일 때만 | RFC-0000 §2에 부분 관계 부재(실측). IETF RFC 2026 이후의 Updates/Obsoletes 구분이 정확히 이 문제를 위한 것. `[no-wiki]` |
| G2 | 조건식 문법 | **닫힌 2형태만**: ① 존재 검사 `<field> exists` / `<field> missing` ② 비교식 `<field> <comparator> <Integer\|Duration>`. comparator는 닫힌 집합 `<` `<=` `>` `>=` `==` `!=`. 그 밖(1~4토큰 자유 구, and/or/not, 멤버십)은 **문법에서 제거** | 이슈 수용 기준 ①. 플랫폼 자신의 원칙과 동형 — 닫힌 동사 사전(R1)이 Effect 도출을 결정적으로 만든 것과 같은 이유로 조건도 닫아야 모드 B가 컴파일할 수 있다 |
| G3 | 제거되는 생산 규칙 | RFC-0002 `Condition ::= Comparison \| Word Word? Word? Word?`에서 **`Word Word? Word? Word?` 대안을 삭제**하고 `Condition ::= Presence \| Comparison`, `Presence ::= CamelName ('exists'\|'missing')`로 대체. `exists`/`missing`은 예약어에 추가 | "평가기가 구현하지 않는 생산 규칙은 실행 불가 프로그램을 쓰라는 초대"(이슈 #3 본문). 파서 거부가 수용 기준 ① |
| G4 | 논리 결합(and/or/not) | **이번 개정에 넣지 않는다.** RFC-0007(=신 프로세스) 위에서 RFC-0008의 Open Question으로 남긴다 | 모드 B가 조건을 실제로 평가해야 하므로 표현력 확장은 네이티브 평가 경로를 함께 늘린다. 2형태로 EQUIVALENT를 먼저 세운 뒤 확장하는 것이 검증 가능한 순서 |
| G5 | IR `Guard.condition`의 형태 | **정규화된 문자열을 유지한다**(구조화 객체로 바꾸지 않는다). 대신 `impl/lnpl/condition.py`의 `parse_condition(text) -> Condition` **한 함수만이** 그 문자열을 해석하는 유일한 지점이 된다(파서·lowering·mode A·mode B 전부 이 함수를 쓴다) | 구조화하면 RFC-0001 노드 카탈로그(Guard 필드)까지 대체 대상이 되어 스키마·세 번째 RFC로 번진다. 이슈 #3이 지목한 참조는 RFC-0002·0003뿐. 단 "IR에 재파싱 대상 문자열을 두는 것"은 IR이 허브라는 주장과 긴장이 있으므로 RFC-0008 Open Question으로 **명시 기록**한다. 재파싱이 두 게이트에서 갈라지는 위험은 SSOT 함수 1개로 막는다(직전 커밋에서 리뷰·apply 게이트가 서로 다른 질문을 해 뚫린 것과 같은 부류의 실수 방지) |
| G6 | `until` 종료 경계 (명세 정정) | 두 경계를 **둘 다 항상** 적용한다: ① 매 라운드 시작 전 `clock.now >= deadline`이면 중단 ② `rounds >= 16`이면 중단. `timeout` 미선언 시에도 라운드 상한은 그대로 16이다(현행처럼 1라운드로 줄지 않는다). 중단 사유를 구분해 WARN에 남긴다(`reason="deadline"` \| `reason="round_cap"`) | RFC-0003 §Guard 본문("어느 쪽이든 먼저 닿으면")이 이미 이것을 말한다 — 구현이 명세를 따라가는 수정이다. 발견 ② 참조 |
| G7 | 라운드 상한의 위치 | `_UNTIL_ROUND_CAP = 16`을 **RFC-0008에 상수로 명문화**하고 구현이 그것을 인용한다. 모드 A·B가 같은 값을 쓰지 않으면 EQUIVALENT가 성립할 수 없으므로 계약 값이다 | 수용 기준 ②③. 현재는 구현 상수일 뿐 명세에 값이 없다 |
| G8 | 모드 B가 payload를 얻는 방법 | 조건이 참조하는 필드를 컴파일러가 수집해 **`lnpl_run`의 추가 i64 파라미터**로 만들고, `main`이 `argv`에서 읽어 넘긴다. 존재 검사는 0/1, 비교식은 정수(Duration은 ms 정수)로 인코딩한다. 파라미터 순서는 조건 참조 필드의 **정렬된 이름 순**으로 고정 | 현재 `lnpl_run(%skip : i32)` + `argv[1]`이 이미 이 모양이다(실측 backend.py:129,188) — 확장이지 재설계가 아니다. **핵심 변화**: 지금은 조건의 *불리언 결과*를 호출자가 공급하지만, 이후에는 *피연산자 값*만 공급하고 비교·분기·루프는 컴파일된 코드가 수행한다. 그것이 "네이티브 바이너리가 조건을 스스로 판정한다"의 실질 |
| G9 | 모드 B `when` | `arith.cmpi`로 컴파일된 조건 + `scf.if`. 기존 `%skip` 파라미터는 **제거**한다(조건이 컴파일되므로 불필요) | G8. `lnpl build --skip`도 함께 제거 대상 — 조건을 손으로 몰아주던 우회로였다 |
| G10 | 모드 B `until` | `scf.while`: before 영역이 컴파일된 조건의 **부정** + 라운드 카운터 `< 16`을, after 영역이 피가드 항목과 `rounds+1`을 담는다. 데드라인은 모드 B에 시계가 없으므로 **라운드 상한만** 유효하고, 그 비대칭을 RFC-0008에 명시한다 | `until`은 조건이 성립할 때까지 반복이고 피연산자는 호출 시 고정이므로, 라운드 상한이 없으면 컴파일된 루프는 종료하지 않는다 — 두 경계를 요구하는 RFC-0003의 논거가 모드 B에서 그대로 재현된다 |
| G11 | differential 등가 판정 대상 | 기존 4분류(실행 순서·정책 결과·관측 신호·마스킹)에 **`until` 라운드 수**와 **skip 집합**을 실행 순서 분류 안에서 비교한다(새 분류를 만들지 않는다) | 등가는 관측 가능한 4분류로만 정의돼 있다(RFC-0004). 라운드 수는 실행 순서에 그대로 드러나므로 분류 신설 없이 커버된다 |
| G12 | 새 예제 | `examples/guarded.lnpl` + 기계 생성물 `examples/guarded.lir.json`. **기존 `examples/login.*`는 무변경**(골든) | 수용 기준 ⑤. 골든 무변경은 이 레포의 상시 규율 |
| G13 | 예제 시나리오 | `when tokenCache missing` 가드가 붙은 step 1개 + `until retryBudget == 0` 가드가 붙은 step 1개를 갖는 workflow. 두 조건이 G2의 두 형태를 각각 1개씩 실증한다 | 수용 기준 ②가 "both a `when` and an `until`"을 요구 |

## Task order

| Task | Depends on | Parallel-ok |
|------|-----------|-------------|
| 01-rfc-process-updates-relation | — | — |
| 02-rfc-guard-conditions | 01 | — |
| 03-condition-parser | 02 | — |
| 04-mode-a-evaluation | 03 | 05와 parallel-ok 아님(G6이 05의 전제) |
| 05-mode-b-lowering | 04 | — |
| 06-guarded-example-and-differential | 05 | — |
| 07-mutations-and-docs | 06 | — |

01이 먼저인 이유: 02가 쓸 `Updates:` 관계가 01에서 생긴다. 03이 02 뒤인 이유: 파서가
거부할 대상이 02에서 확정된다. 04가 05 앞인 이유: G6의 두 경계 의미를 모드 A에서
확정해야 05가 같은 값으로 컴파일할 수 있고, 그래야 06의 EQUIVALENT가 의미를 갖는다.

## 이 계획이 건드리지 않는 것

- `examples/login.lnpl` / `login.lir.json` / `login.spec.json` / `login.openapi.json`
- RFC-0001(노드 카탈로그) — G5가 그 대체를 피하는 결정이다
- 이슈 #1의 커스텀 `lnpl` dialect — 01의 `Updates` 관계와 02의 조건 문법이 그 작업의
  전제이므로 순서상 이 계획 뒤다
- 이슈 #2의 RefactoringAgent — 01이 만드는 메커니즘을 쓰지만 별도 계획
