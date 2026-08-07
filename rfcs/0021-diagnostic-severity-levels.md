# RFC-0021: 진단 등급과 `--strict` 문턱

## Status

- Status: **Accepted** (RFC-0021, 2026-08-07)

새 계약 표면이라 Supersedes도 Updates도 없다. 진단 채널 자체(RFC-0009 계열의
`impl/lnpl/diagnostics.py`)와 `--strict`(이슈 #45)의 기존 의미는 그대로 두고,
**어떤 진단이 종료 코드를 움직이는가**만 호출자가 고를 수 있게 넓힌다.

번호가 0021인 이유: 0020은 같은 웨이브의 이슈 #54가 점유했다. RFC-0007 §3은
번호 재사용을 금지한다.

## Motivation

2026-08-07 재측정이 같은 결함을 네 번 보고했다(`qa/rerun/REPORT.md` §6.2).

| 근거 | 심각도 | 관측 |
|------|--------|------|
| r3 N-4 | **major** | 정당한 `on schedule daily` 선언이 `declared-not-enforced`를 내므로 `--strict`가 **전 런 rc=2** — #49의 스케줄 선언과 #45의 게이트가 상호 배타 |
| r1 N-1 | minor | `performance response < 50ms`(SLO 서술)도 같은 이유로 게이트와 양립 불가 |
| r4 N-1 | info | perf 경고가 상존하는 소스에선 전 런 rc=2라, 가드 스킵 감지에 `--strict`를 쓸 수 없다 |
| r3 F-8 | 부분 | 진단의 기계 판독 채널 부재 — CI가 등급별로 게이트를 걸 수단이 없다 |

이 워크트리에서 재현한 실측(`.venv/bin/lnpl compile <src> --strict`):

| 소스 | 방출 진단 | `--strict` | 무인자 |
|------|-----------|-----------|--------|
| `on schedule daily at 00:00 UTC` | `declared-not-enforced` | **rc=2** | rc=0 |
| `performance / response < 50ms` | `declared-measured-only` | **rc=2** | rc=0 |
| `frobnicate Report`(오타) | `unknown-verb` | **rc=2** | rc=0 |
| `examples/shorten.lnpl` | 위 3종 전부 | **rc=2** | rc=0 |

**세 소스가 게이트에게 구별되지 않는다**는 것이 결함의 전부다.

원인은 등급 축의 부재가 아니었다. `Diagnostic`에는 `severity` 필드가 **처음부터
있었다.** 그러나 방출 지점 다섯 곳이 전부 `severity="warning"` 리터럴을 넘겼기
때문에 그 필드는 상수였고, **0비트를 날랐다.** 부풀린 등급이 그 필드를 읽는 모든
소비자의 신호를 파괴한다는 말의 극단이 이것이다 — 모두가 같은 값이면 `--strict`는
선택할 것이 없다.

## Guide-level Explanation

진단에 등급이 생겼다. 등급은 한 질문이 정한다:

> **프로그램을 고치면 이 진단이 사라지는가?**

- **사라진다 → `warning`.** 저자가 의도하지 않았을 수 있고, 고치는 것은 저자
  몫이다. 오타 동사를 지우거나, 가드가 왜 거짓이었는지 보면 된다.
- **사라지지 않는다 → `info`.** 프로그램은 옳고, 플랫폼이 그것으로 무엇을 하는지
  진술하는 중이다. 어떤 편집도 이 줄을 없애지 못하고 플랫폼이 바뀌어야 없어진다.

보고는 그대로다(#38의 요지). 바뀐 것은 **게이팅**뿐이다.

`--strict`는 이제 문턱을 받는다.

```
lnpl compile app.lnpl --strict            # 진단이 하나라도 있으면 rc 2 (기존 그대로)
lnpl compile app.lnpl --strict=warning    # warning 이상만 rc 2
lnpl compile app.lnpl --strict=error      # 예약 — 오늘 아무것도 일치하지 않는다
```

스케줄 선언을 쓰면서 CI 게이트를 켜려면 `--strict=warning`을 쓴다. 이것이 r3 N-4의
상호 배타를 푸는 방법이다.

**무인자 `--strict`는 한 글자도 바뀌지 않았다.** 그 플래그는 v0.3.0에 이미
출하됐고, 기본값을 `warning`으로 낮추면 이미 걸어둔 CI 게이트가 **조용히 게이팅을
멈춘다.** 게이트가 조용히 사라지는 것은 게이트가 너무 시끄러운 것보다 나쁘다.

## Reference-level Specification

### 등급 사다리

`SEVERITIES = ("info", "warning", "error")`. **튜플 순서가 곧 서열**이고, 문턱
비교는 `SEVERITIES.index()`다. 이 순서를 바꾸면 CLI의 모든 문턱이 뒤집힌다.

### 코드 → 등급 (정본)

`impl/lnpl/diagnostics.py`의 `SEVERITY_OF`가 정본이며 `CODES`를 정확히 덮는다.

| 코드 | 등급 | 근거 |
|------|------|------|
| `unknown-verb` | `warning` | 어휘 밖 동사 — 동사를 고치면 사라진다 |
| `guard-skipped-steps` | `warning` | 이 런에서 선언된 스텝이 실행되지 않았다 — 런마다 다르고 payload에 달렸다 |
| `declared-not-enforced` | `info` | ENFORCEMENT 행렬의 UNENFORCED 진술 — 편집으로 사라지지 않는다 |
| `declared-measured-only` | `info` | 같은 행렬의 MEASURED 진술 |
| `authorization-not-verified` | `info` | `security role`/`jwt`가 UNENFORCED인 것의 런타임 얼굴 — 저자가 고칠 수 없다 |

`error`는 **예약**이다. 오늘 어떤 코드도 매핑되지 않으며, 그 사실을
`test_diagnostics_channel.py`가 `assertNotIn("error", SEVERITY_OF.values())`로
고정한다. 처음 error를 쓰는 사람은 그 테스트에서 멈춰 `--strict=error`의 의미를
정하게 된다.

### 등급은 레코드가 아니라 표가 정한다

`Diagnostic.severity`는 필드가 아니라 `SEVERITY_OF[self.code]`를 읽는 **파생
property**다. 따라서 등급이 어긋난 레코드를 **구성할 방법이 없다.**
`Diagnostics.add()`는 `severity` 인자를 받지 않으며 키워드 전용이다:

```python
def add(self, *, code, where, subject, message): ...
```

키워드 전용인 이유는 `severity`가 두 번째 위치에 있었기 때문이다. 벌거벗은 `*`가
없으면 낡은 위치 인자 호출이 등급 문자열을 `where`에 조용히 바인딩한다.

이것은 모듈 docstring의 "no new machinery"와 정합한다 — 두 번째 레코드 타입도,
누산기도, 사람용 포매터도 늘지 않았다. 이미 있던 축이 상수를 벗은 것뿐이다.

### `--strict[=LEVEL]`

- argparse: `nargs="?", const="info", default=None, type=_strict_level`.
- 무인자 `--strict` ≡ `--strict=info` ≡ v0.3.0 동작.
- `_strict_rc`는 `rc == 0`일 때만 승격한다(불변). 문턱 이상 등급이 하나라도 있으면 rc 2.
- rc 어휘 불변: `0` 성공 / `1` 실행·spec 실패 / `2` 컴파일·조작 에러·strict 게이트 / `3` 런타임 / `4` 백엔드.
- `choices=`를 쓰지 않는다. `nargs="?"` 때문에 `lnpl compile --strict src.lnpl`이
  **경로를 등급으로 삼키는데**, argparse 기본 메시지는 등급 목록만 나열하고 저자는
  자기 파일이 왜 등급이어야 하는지 알 수 없다. `type=`이 거부하며 교정 지시를 준다:

```
lnpl compile: error: argument --strict: takes one of info, warning, error, not
'src.lnpl' — write `--strict=<level>`, or put `--strict` after the source if you
meant the bare flag
```

### 기계 판독 채널 (r3 F-8)

`lnpl run <src> --json`의 출력 객체가 `diagnostics` 배열을 나른다. 원소는
`code` / `severity` / `where` / `subject` / `message` 다섯 키이고, 레코드에서
기계적으로 파생된다. 진단이 없으면 **키가 사라지지 않고 `[]`가 된다** — 소비자가
키 존재로 분기하지 않게 하기 위해서다.

**`compile`과 `spec`은 나르지 않는다.** 그 stdout은 IR 문서와 매니페스트, 즉
산출물이다. 키를 더하면 골든 `.lir.json` 계약이 깨지고, 애초에 진단을 stderr로
보낸 이유(산출물 오염 금지)를 정면으로 어긴다. 이 비대칭은 실수가 아니라 결정이다.

`format_lines`는 여전히 **유일한 사람용 포매터**다. `to_records`는 사람용 렌더링을
하지 않으므로 두 번째 포매터가 아니다.

## Examples

r3 N-4 재현의 before/after. 소스는 스케줄 선언 하나뿐인 모듈이다.

```
service Rollup
entity Report
    field
        id UUID
event DailyRollup on schedule daily at 00:00 UTC
workflow GetReport
    read Report
```

| 커맨드 | before | after |
|--------|--------|-------|
| `compile s.lnpl` | rc 0 | rc 0 |
| `compile s.lnpl --strict` | rc 2 | **rc 2** (불변 — 출하된 계약) |
| `compile s.lnpl --strict=warning` | (문법 없음) | **rc 0** ← 상호 배타 해소 |
| `compile s.lnpl --strict=error` | (문법 없음) | rc 0 |

같은 문턱에서 오타는 여전히 막힌다 — 게이트가 살아 있다는 대조군이다:

```
$ lnpl compile typo.lnpl --strict=warning
warning: unknown-verb [line 8] frobnicate — `frobnicate Report` is outside
VERB_LEXICON: this step derives no Effect and runs as a descriptive no-op
0 info, 1 warning(s), 0 error(s)
$ echo $?
2
```

보고 자체는 등급과 무관하게 그대로 나간다. `--strict=warning`을 준 스케줄 모듈도
stderr에 같은 줄을 낸다:

```
info: declared-not-enforced [event.daily.rollup] event schedule — declared but
unenforced: no scheduler runs it; ... issue #26 (the serving layer) owns the executor
1 info, 0 warning(s), 0 error(s)
```

기계 판독 채널:

```
$ lnpl run examples/shorten.lnpl --json | jq '[.diagnostics[] | .severity] | group_by(.)'
[["info","info"],["warning","warning"]]
```

## Alternatives

**직교 2축(의도 / 실수)을 세운다.** 검토했고 버렸다. r1 N-1과 r3 N-4는 같은 코드
경로에서 나온다 — `lower.py:_declaration_diagnostics()`가 `ENFORCEMENT` 행렬을
조회해 방출하며, 둘의 차이는 행렬의 status 값(measured/unenforced)뿐이다. 관측된
네 마찰이 전부 "프로그램을 고치면 사라지는가"라는 **하나의 전순서**로 갈린다.
직교 축은 어느 마찰도 더 잘 풀지 못하면서 레코드에 필드를 늘리고, 모듈 docstring의
"no new machinery"와 충돌한다.

**무인자 `--strict`의 기본을 `warning`으로 낮춘다.** 인체공학은 낫지만, 이미
출하된 게이트를 **조용히** 약화시킨다. 업그레이드한 사용자는 자기 CI가 더 이상
오타를 잡지 못한다는 사실을 아무 신호 없이 잃는다. 낮추는 쪽이 편해질 여지는
`--strict=warning`을 문서로 안내하는 것으로 충분하다.

**선언 단위 승인 문법 — 미해결.** "의도한 선언은 등급을 전역으로 낮추는 방식이
아니라 **선언 단위 명시적 승인**으로 억제해야 한다"는 원칙이 있다(예:
`on schedule daily acknowledged`). 그 원칙은 옳고 이 RFC는 그것을 대체하지
않는다. 다만 승인 문법은 **소스 레벨 새 문법**이라 `parser.py`/`lexer.py`를
건드리고, 그 자체로 별도 RFC 사안이다. 이 RFC가 세우는 등급 축은 그 후속의
대체물이 아니라 **전제**다 — 승인 문법이 생기면 "무엇을 승인하는가"의 단위가
여기서 정의된 등급이 된다. Open Questions 참조.

**진단 JSON을 전 커맨드 공통 플래그(`--diagnostics-json`)로 신설한다.**
표면이 늘고 Wave 4(#56)의 문서화 부담이 커지는 데 비해, `run --json`이 이미 기계
채널이라 얻는 것이 적다. `compile`/`spec`의 stdout은 산출물이라 어차피 실을 수
없다.

## Open Questions

1. **선언 단위 승인 문법.** 위 Alternatives의 미해결 항목. 어떤 토큰을 쓸지
   (`acknowledged` / `known-unenforced` / 절 단위 표기), 승인이 IR에 남아야 하는지,
   승인된 선언이 `info`조차 내지 않아야 하는지 아니면 등급만 더 낮아지는지가
   전부 열려 있다. 후속 이슈 대상이다.
2. **`error` 등급의 첫 사용자.** 오늘 예약이다. 컴파일 타임 거부는 이미 예외를
   던지므로(RFC-0019 계열) 진단이 아니고, 따라서 `error`가 무엇을 위한 자리인지는
   실제 요구가 나올 때 정해야 한다.
3. **`guard-skipped-steps`의 등급.** `warning`으로 두었다 — r4 N-1이 이 진단을
   `--strict`로 감지하고 싶어 했기 때문이다. 다만 가드가 거짓인 것은 정상 동작일
   수도 있어서(캐시 히트 스킵 등), 스킵이 상존하는 워크로드에서 r3 N-4와 같은
   상호 배타가 재현될 여지가 있다. 그런 실측이 나오면 이 행을 다시 본다.
4. **mode B 비대칭.** 진단은 mode A에서만 나온다(r1 N-2). 등급 축은 그 비대칭을
   건드리지 않았다 — mode B가 진단을 표면화하게 되면 등급도 함께 따라가야 한다.
