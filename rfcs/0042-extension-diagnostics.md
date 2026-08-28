# RFC-0042: 확장 진단 등록 — 네임스페이스·소유·게이팅

## Status

- Status: **Accepted** (RFC-0042, 2026-08-28)
- Updates: RFC-0021 §Reference-level Specification/코드 → 등급 (정본), RFC-0021 §Reference-level Specification/`--strict[=LEVEL]`

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. 두 절 모두 RFC-0021 이래
갱신된 적이 없다 — RFC-0021 자신이 "새 계약 표면이라 Supersedes도 Updates도
없다"고 적었으므로 이번이 그 첫 갱신이다(규칙 5의 연쇄 갱신 대상이 없다).

이슈 #138의 "RFC 선행 필요" 요청에 대한 응답이다. **이 RFC는 결정만 기록한다
— 코드를 바꾸지 않는다.** 구현은 후속 태스크 t-diag가 이 문서의 결정을
그대로 소비한다.

## Motivation

`impl/lnpl/diagnostics.py`의 `CODES`는 닫힌 튜플이고, 등록 지점은 코어
자신뿐이다. 세 SPI(`lnpl.drivers` · `lnpl.tokens` · `lnpl.exporters`)로
붙는 확장은 값을 돌려주는 콜러블일 뿐, **자기가 들여온 실패 모드를 언어의
어휘로 말할 자리가 없다.**

이슈 #138이 실측으로 든 네 사례가 전부 같은 모양이다 — 컴파일 시점에 알 수
있는 사실인데 지금은 문서에만 있고 진단으로 나오지 않는다:

| 확장 | 알 수 있는 사실 | 오늘의 표현 수단 |
|------|-----------------|------------------|
| kafka 아웃박스 릴레이 드라이버 | at-least-once만 보장 — `emit`이 중복 전달될 수 있다 | 없음 |
| postgres 드라이버 | `READ COMMITTED`인데 워크플로가 더 강한 격리를 가정 | 없음 |
| 외부 토큰 프로바이더 | `role` 클레임을 안 싣는데 `security role admin`이 선언됨 | 없음 |
| 캐시 드라이버 | 프로세스 로컬인데 `performance cache 5m`이 선언됨 | 없음 |

`SEVERITY_OF` 바로 위 주석이 등급 규칙을 이미 한 문장으로 못 박아 뒀다 —
**프로그램을 고치면 이 진단이 사라지는가?** yes → `warning`, no → `info`.
"이 드라이버는 at-least-once다"는 정확히 `info`다: 프로그램을 고쳐도
사라지지 않고, 플랫폼(설치된 확장)이 바뀌어야 사라진다. 규칙이 이미 그
자리를 예약해 뒀는데 등록 경로만 없다.

포스트그레스 확장이 강한 이유는 확장이 트랜잭션·플래너·타입 시스템을
**물려받기** 때문이다. linkly에서 코어의 자산은 진단·집행 매트릭스·차동
검증이고, 지금 확장은 그중 아무것도 물려받지 못한다 — 확장이 늘어도 언어의
설명력은 그대로다.

**현황 재집계(D7).** 이슈 #138 본문은 CODES를 "15개"로 인용하지만
2026-08-07(RFC-0021 accept) 이후 여러 RFC(guard-orphaned-steps 계열,
RFC-0025의 aggregation-orphaned-list, #98의 event-source-\*,
#95/#101/#85/#112/#109/#111/#118 각각의 코드)가 늘려 온 것이 각기 기록되어
있다. `impl/lnpl/diagnostics.py:40`의 `CODES`를 직접 재집계하면 **18개**다
— 이슈의 수치는 낡았고, 이 RFC는 이슈를 인용하지 않고 산출물에서 직접 센
수치를 쓴다.

3rd party 확장이 아직 0건인 지금이 프리픽스 소유 규칙을 정할 수 있는 유일한
시점이다. Roslyn의 진단 프리픽스 논의(dotnet/roslyn#40351)가 반면교사다 —
1st party 프리픽스(`CA`/`CS`/`RS`/`IDE`/`SA`)는 표로 관리되지만 3rd party에는
지침이 없어 지금도 충돌한다. 처음부터 정하지 않으면 나중에는 못 정한다.

## Guide-level Explanation

확장이 등록하는 진단 코드는 **`<prefix>/<code>`** 형태다 — 구분자는 `/`
(ESLint의 `plugin/rule` 컨벤션을 그대로 가져온다). **bare(무슬래시) 코드는
영구히 코어 전용이다** — `CODES`가 지금 담고 있는 18개도, 앞으로 코어가
추가할 것도 전부 bare로 남는다. 확장은 bare를 등록할 수 없다.

`prefix`는 확장이 엔트리포인트에 등록한 그 이름 자체다 — 별도로 선언하지
않는다, 등록명이 곧 prefix다. 형태는 `^[a-z][a-z0-9-]{1,15}$`. `lnpl`과
`core`는 예약어라 어떤 확장도 가질 수 없다. **한 prefix는 한 소유자만
가진다** — 이미 등록된 prefix로 다른 확장이 로드되면 로드 시점에 거부한다
(중복 등록 오류). Roslyn이 놓친 바로 그 지점이다: 1st party만 예약 표를
관리하고 3rd party 사이의 충돌은 아무도 막지 않는다. linkly는 처음부터
"한 prefix, 한 소유자"를 로드 시점 불변식으로 건다.

**확장은 `info`/`warning`만 쓸 수 있다.** `error`를 선언하면 등록 시점에
거부한다. 근거: 확장이 `error`를 쓸 수 있으면 확장을 설치하는 행위가 기존
프로그램의 컴파일을 실패시킬 수 있고, 같은 소스의 rc가 무엇이 설치돼
있는지에 따라 달라진다 — `docs/compatibility.md` §1이 이미 rc를 공표된
계약으로 못 박은 것, 그리고 `--backend` 기본값이 `fake`인 비파괴 원칙과
정면으로 충돌한다.

**확장 진단은 `--strict` 게이팅에 기본·유일 규칙으로 불참한다.** 이슈
#138의 결정 3은 "참여해야 한다 — 참여하지 않으면 장식이다"라고 제안했다.
이 RFC는 그 제안을 검토하고 **다르게 결정한다**: D3가 severity 상한에 쓴
논리(설치된 확장에 따라 같은 소스의 rc가 달라지면 안 된다)가 `--strict`
참여에도 그대로 적용된다 — 확장 진단이 문턱을 움직이면, 확장을 설치하는
행위 자체가 CI를 조용히 빨갛게 만들 수 있고 그 실패는 프로그램이 아니라
설치 목록에서 온다. §1이 rc를 계약으로 공표한 이상, 그 계약의 의미가 확장
설치 여부로 갈라지게 둘 수 없다. 다만 이슈의 우려("참여 안 하면 장식")도
근거가 있으므로, opt-in 참여를 영구히 닫지는 않는다 — 실제 소비자가 생긴
뒤 별도 RFC로 재론한다(아래 "하지 않는 것", Open Questions 1).

**확장은 컴파일된 IR 문서와 자기 설정만 본다.** 소스 텍스트에는 접근하지
못한다 — 주면 파서를 두 번째로 구현하게 만드는 길이고, 이슈가 명시적으로
막았다. `line` 정보는 IR 노드의 `line`(RFC-0024)에서 온다.

**`docs/compatibility.md` §1과의 정합.** 새 진단 `code` 추가는 이미 §1이
breaking이 아니라고 적어 뒀으므로 네임스페이스 신설 자체는 그 보장 안에
든다. 다만 확장 `code`의 존속·재의미부여는 코어의 보증 밖이라는 문장을 §1에
명시한다 — 코어가 보증하는 것은 다섯 키 봉투 형태뿐이다.

**하지 않는 것.**

- **동사 어휘는 열지 않는다.** 확장이 `VERB_LEXICON`에 낱말을 더할 수
  있게 하면 LLM이 환각한 동사가 어느 환경에서는 파싱되고 어느 환경에서는
  안 되는 상태가 되어 linkly의 유일한 방어선이 무너진다. 이 RFC가 여는
  것은 진단 어휘뿐이다 — 확장은 언어에 낱말을 더하지 않고, 언어가 이미
  아는 것에 대해 더 말할 수 있게 될 뿐이다(이슈 #138 명시).
- **`--strict` opt-in 참여 플래그는 신설하지 않는다.** 위에서 논증한 대로
  기본은 불참이다. `--strict-ignore <prefix>/*` 같은 이스케이프도, 참여
  자체도 이 RFC의 범위가 아니다 — 실제 확장 소비자가 관측된 뒤 별도 RFC로
  정한다.
- **집행 매트릭스와의 연결은 잇지 않는다.** 설치된 드라이버가 자기 집행
  상태를 신고해 `declarations.md`의 매트릭스를 런타임 실측으로 렌더링하는
  것(이슈 #138 후속 항목 6)은 이 RFC에서 결정하지 않는다 — 진단 등록이
  먼저이고, 매트릭스 연결은 별도 이슈다.

## Reference-level Specification

### RFC-0021 §Reference-level Specification/코드 → 등급 (정본) (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0021 §Reference-level
Specification/코드 → 등급 (정본)의 치환 후 최종 텍스트다. 첫 문단의 표
(대표 5개 코드 예시)와 `error` 예약을 설명하는 문단은 바뀌지 않는다 — 이
RFC는 그 뒤에 확장 네임스페이스 문단 하나를 더할 뿐이다.

> `impl/lnpl/diagnostics.py`의 `SEVERITY_OF`가 **bare(무슬래시) 코드**의
> 정본이며 `CODES`를 정확히 덮는다. `CODES`는 여전히 닫힌 튜플이고 코어
> 전용이다.
>
> | 코드 | 등급 | 근거 |
> |------|------|------|
> | `unknown-verb` | `warning` | 어휘 밖 동사 — 동사를 고치면 사라진다 |
> | `guard-skipped-steps` | `warning` | 이 런에서 선언된 스텝이 실행되지 않았다 — 런마다 다르고 payload에 달렸다 |
> | `declared-not-enforced` | `info` | ENFORCEMENT 행렬의 UNENFORCED 진술 — 편집으로 사라지지 않는다 |
> | `declared-measured-only` | `info` | 같은 행렬의 MEASURED 진술 |
> | `authorization-not-verified` | `info` | `security role`/`jwt`가 UNENFORCED인 것의 런타임 얼굴 — 저자가 고칠 수 없다 |
>
> `error`는 **예약**이다. 오늘 어떤 코드도 매핑되지 않으며, 그 사실을
> `test_diagnostics_channel.py`가 `assertNotIn("error", SEVERITY_OF.values())`로
> 고정한다. 처음 error를 쓰는 사람은 그 테스트에서 멈춰 `--strict=error`의
> 의미를 정하게 된다.
>
> **확장 코드 네임스페이스 (RFC-0042).** bare 옆에 `<prefix>/<code>` 형태의
> 별도 네임스페이스가 있다 — 구분자는 `/`(ESLint의 `plugin/rule` 컨벤션).
> `prefix`는 확장이 엔트리포인트에 등록한 이름 그 자체이고
> `^[a-z][a-z0-9-]{1,15}$`를 만족해야 한다. `lnpl`·`core`는 예약어라 어떤
> 확장도 prefix로 가질 수 없다. 한 prefix는 한 소유자만 가진다 — 이미
> 등록된 prefix로 다른 확장이 로드되면 로드 시점에 거부한다(중복 등록
> 오류). `<prefix>/<code>`는 `CODES`에 들어가지 않는다 — 확장 자신의
> 등록 시점 선언이 그 코드의 정본이다. 등급은 확장이 스스로 선언하되
> `info`/`warning`만 쓸 수 있다 — `error`를 선언하면 등록 시점에 거부한다
> (근거: Guide-level Explanation, §Motivation의 rc 계약 논증과 동일).

### RFC-0021 §Reference-level Specification/`--strict[=LEVEL]` (치환 후 최종 텍스트)

아래는 같은 절의 치환 후 최종 텍스트다. argparse 규격·rc 어휘·에러 메시지
문단은 바뀌지 않는다 — 마지막에 확장 코드의 게이팅 불참 규칙 한 문단을
더한다.

> - argparse: `nargs="?", const="info", default=None, type=_strict_level`.
> - 무인자 `--strict` ≡ `--strict=info` ≡ v0.3.0 동작.
> - `_strict_rc`는 `rc == 0`일 때만 승격한다(불변). 문턱 이상 등급이
>   하나라도 있으면 rc 2.
> - rc 어휘 불변: `0` 성공 / `1` 실행·spec 실패 / `2` 컴파일·조작 에러·
>   strict 게이트 / `3` 런타임 / `4` 백엔드.
> - `choices=`를 쓰지 않는다. `nargs="?"` 때문에 `lnpl compile --strict
>   src.lnpl`이 **경로를 등급으로 삼키는데**, argparse 기본 메시지는 등급
>   목록만 나열하고 저자는 자기 파일이 왜 등급이어야 하는지 알 수 없다.
>   `type=`이 거부하며 교정 지시를 준다:
>
> ```
> lnpl compile: error: argument --strict: takes one of info, warning, error, not
> 'src.lnpl' — write `--strict=<level>`, or put `--strict` after the source if you
> meant the bare flag
> ```
>
> **확장 코드는 이 문턱 비교에 참여하지 않는다(RFC-0042, 기본·유일
> 규칙).** `_strict_rc`가 승격 여부를 계산할 때 `<prefix>/<code>` 형태의
> 진단은 건너뛴다 — `<prefix>/<code>`가 아무리 높은 등급이어도 `--strict`의
> rc를 움직이지 않는다. 참여를 여는 opt-in 플래그는 이 RFC가 신설하지
> 않는다(§Guide-level Explanation "하지 않는 것", Open Questions 1).

### 확장 진단의 입력 — 컴파일된 IR과 자기 설정만 (D5, 신규)

확장 진단기는 두 가지만 받는다: `lnpl compile`이 이미 내는 IR 문서(`line`
필드 포함, RFC-0024)와 그 확장 자신의 설정. **소스 텍스트는 받지 않는다.**
파서를 두 번째로 구현하게 만들지 않기 위해서다 — linkly의 파서는 하나이고,
확장은 그 결과물 위에서만 말한다.

## Examples

구현은 t-diag가 하므로 아래는 이 RFC가 확정한 계약이 적용됐을 때의
**설계 예시**다 — 오늘 실행되는 명령이 아니다.

`kafka` 드라이버가 `kafka/at-least-once`를 `info`로 등록했다고 하자
(§Motivation의 첫 사례):

```
$ lnpl compile app.lnpl
info: kafka/at-least-once [line 12] emit userCreated — the installed kafka
outbox relay guarantees at-least-once delivery only; userCreated may be
delivered more than once
0 info, 1 warning(s), 0 error(s)   # 코어 warning 하나가 이미 있었다고 가정
$ echo $?
0
```

같은 소스에 `--strict=info`를 주면, bare 코드는 문턱을 움직이지만
`kafka/at-least-once`는 움직이지 않는다:

```
$ lnpl compile app.lnpl --strict=info
info: kafka/at-least-once [line 12] emit userCreated — ...
0 info, 1 warning(s), 0 error(s)
$ echo $?
2   # bare warning 하나 때문 — kafka/at-least-once는 이 rc에 관여하지 않는다
```

`kafka` 확장이 `error` 등급을 선언하려 하면 로드 시점에 거부된다:

```
$ lnpl compile app.lnpl
lnpl: extension 'kafka' registered diagnostic 'kafka/at-least-once' with
severity 'error' — extensions may declare 'info' or 'warning' only
(RFC-0042). Refusing to load.
```

두 번째 확장이 이미 등록된 `kafka` prefix로 로드를 시도하면:

```
lnpl: prefix 'kafka' is already owned by the extension registered as
'kafka' — one prefix, one owner (RFC-0042). Refusing to load.
```

## Alternatives

**구분자를 `/` 대신 `.`으로.** 검토했고 버렸다. linkly의 노드 id가 이미
`.`을 다단어 이름의 구분자로 쓴다(`entity.order.item`, RFC-0012) —
`kafka.at-least-once`는 그 어휘와 시각적으로 섞여 "이게 노드 id인가 진단
코드인가"를 매번 되묻게 만든다. `/`는 이 레포 어디에도 그런 의미가 없고,
ESLint의 `plugin/rule`이 이미 같은 문제(소유자/항목)를 같은 구분자로
풀어 뒀다.

**네임스페이스를 열지 않고 단일 레지스트리로 유지.** 검토했고 버렸다 —
등록 순서에 따라 다른 확장의 코드가 같은 문자열을 두고 충돌할 수 있고,
Roslyn #40351이 바로 그 상태에서 프리픽스 소유 지침 없이 3rd party가
난립해 지금도 못 푼다. 3rd party가 0건인 지금이 이 규칙을 정할 유일한
기회라는 것이 이슈 #138의 논지이기도 하다.

**prefix를 별도 필드로 선언(등록명과 분리).** 검토했고 버렸다 — 등록명과
다른 prefix를 선언할 수 있게 하면 "코드에 적힌 이름"과 "실제로 로드된
확장"이 갈릴 수 있어 소유 판별이 간접적이 된다. 엔트리포인트 등록명을
그대로 prefix로 쓰면 "누가 이 코드를 냈는가"가 등록 그 자체에서 기계적으로
드러난다.

**확장에 `error`를 허용.** 검토했고 버렸다 — Motivation·Guide-level
Explanation에 이미 적은 대로, 확장 설치가 기존 프로그램의 rc를 바꿀 수
있으면 `docs/compatibility.md` §1의 rc 계약과 `--backend fake` 기본값의
비파괴 원칙 둘 다와 충돌한다.

**확장 진단을 `--strict`에 기본 참여시킨다(이슈 #138의 제안).** 검토하고
버렸다 — 이슈는 "참여하지 않으면 장식"이라고 주장하지만, 참여를 기본으로
하면 확장을 설치하는 행위만으로 이미 통과하던 CI가 빨개질 수 있고, 그
실패의 원인이 프로그램이 아니라 설치 목록에 있다는 점에서 D3(severity 상한)
가 `error`를 막은 것과 동일한 문제를 문턱 참여 쪽에서 재현한다. 다만
"장식이 된다"는 우려도 근거가 있으므로 영구히 닫지 않고 opt-in으로
재론 가능하게 열어 둔다(Open Questions 1).

**opt-in 참여 플래그(`--strict-ignore <prefix>/*` 등)를 지금 같이
정한다.** 검토했고 버렸다 — 오늘은 실제 확장 소비자가 0건이라 이스케이프가
막아야 할 실제 마찰을 아직 모른다. 마찰 없이 플래그 문법부터 정하면
RFC-0021이 등급 축 신설 때 겪은 실수(방출 지점이 상수를 넘겨 필드가
0비트를 나른 것)와 같은 종류의 위험 — 쓰이지 않는 문법을 먼저 얹는 것 —
를 반복한다.

## Open Questions

1. **`--strict` opt-in 참여 플래그.** §Guide-level Explanation "하지 않는
   것", Alternatives에서 미룬 항목. 어떤 문법(`--strict-ignore
   <prefix>/*`, prefix별 개별 문턱, 다른 형태)일지, 참여 단위가 prefix
   전체인지 코드 단위인지가 전부 열려 있다. 실제 확장 소비자가 생긴 뒤
   별도 RFC로 정한다.
2. **집행 매트릭스와의 연결(이슈 #138 후속 항목 6).** 설치된 드라이버가
   자기 집행 상태를 신고해 `declarations.md`의 매트릭스를 런타임 실측으로
   렌더링하는 것은 이 RFC의 범위 밖이다. 진단 등록이 먼저이고, 매트릭스
   연결은 별도 이슈로 다룬다.
3. **중복 등록 거부의 정확한 메커니즘.** "로드 시점에 거부한다"는 계약만
   이 RFC가 정한다 — 세 SPI(`lnpl.drivers`/`lnpl.tokens`/`lnpl.exporters`)
   중 어디서 prefix 레지스트리를 두는지, 로드 순서가 비결정적일 때 어느
   쪽이 이기는지(선착순 vs 알파벳순 vs 오류) 같은 세부는 구현(t-diag)의
   몫이다.
4. **`error`가 확장에 영구히 닫혀 있는가.** RFC-0021이 이미 bare `error`도
   예약(첫 사용자 미정)으로 남겨 뒀다. 이 RFC는 확장에는 지금 닫지만,
   "영구히"가 맞는 판단인지는 실사용이 나온 뒤 재론할 수 있다 — bare
   `error`의 첫 사용자가 정해지는 시점과 무관하게 별도로 열린 질문이다.
