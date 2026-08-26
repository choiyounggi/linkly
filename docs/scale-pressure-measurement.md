# 이름공간 압력 실측 (issue #117)

전역 단일 이름공간이 규모(엔티티 10/30/50)에서 무엇을 먼저 깨뜨리는지, D3(다섯
측정 항목)을 실측한 수치 리포트다. 결론(RFC를 쓸지, "지금은 불필요"로 이슈를
닫을지)은 이 문서가 내리지 않는다 — `.orchestration/plans/t117.md`의 Task 03이
이 수치를 근거로 판정한다.

측정값이 0인 칸은 "0건 관측"(실제로 실행해서 0을 확인)과 "측정 불가/미실행"을
구분해 적는다 — `harness-reverse-controls.md` §5.

## 방법

- 생성기: `scripts/gen_scale_corpus.py` (t117 Task 01, D1/D2/D4; r1 리뷰
  F1 이후 수정 — 아래 "항목 1" 참조).
- 규모: 엔티티 **10 / 30 / 50** (D1). 도메인 5개(`billing` `shipping` `catalog`
  `identity` `support`)에 라운드로빈으로 분배.
- 이름 모델(D2, **r1 F1로 개정**): 도메인마다 **도메인 전용 명사 20개**
  (`DOMAIN_NOUNS`, N과 함께 자라고 서로 겹치지 않음)와, 5개 도메인이
  공유하는 **공용 명사 4개**(`SHARED_NOUNS` = `Order`/`Item`/`Status`/
  `Event`)를 둔다. 도메인마다 엔티티의 **약 1/3**(`SHARED_DRAW_FRACTION`,
  스크립트에 명시)을 공용 풀에서, 나머지를 도메인 전용 풀에서 뽑는다 —
  왜 이렇게 바꿨는지는 항목 1 서두 참조.
- `--disambiguate` 없이 생성한 코퍼스로 **충돌**을(항목 1), `--disambiguate`로
  생성한(=실제로 컴파일되는) 코퍼스로 나머지 네 항목을 측정한다.
- 재현에 쓴 임시 디렉터리는 `.claude/tmp/measure2/`(프로젝트 임시 파일 규약).
  아래 명령을 그대로 실행하면 같은 수치가 재현된다(생성기가 결정적이므로).

```bash
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
SDK="$(xcrun --show-sdk-path)"; export CPATH="$SDK/usr/include"; export LIBRARY_PATH="$SDK/usr/lib"
for N in 10 30 50; do
  .venv/bin/python scripts/gen_scale_corpus.py --entities $N --out .claude/tmp/measure2/nodis_$N --seed 0
  .venv/bin/python scripts/gen_scale_corpus.py --entities $N --out .claude/tmp/measure2/dis_$N --seed 0 --disambiguate
done
```

## 항목 1 — 이름 충돌 빈도 (`--disambiguate` 없이)

**r1 리뷰 F1(blocking)로 방법을 바꿨다.** 이전 버전은 엔티티 전부를 고정
10개짜리 명사 풀에서 **복원추출**했다 — 그러면
`collision_events ≥ N − 10`이 항상 성립하는 **비둘기집 산술**이 되어(N=30→
바닥값 20, N=50→바닥값 40, 리포트 값과 정확히 일치했다), 네임스페이스가
전혀 필요 없는 정상적인 코드베이스(엔티티 50개에 서로 다른 도메인 이름
50개)에서도 같은 수치가 나왔을 것이다 — 측정이 가설을 반증할 수 없었다.

**바뀐 모델**: 도메인마다 전용 명사 20개(N과 함께 자람, 도메인 간 겹치지
않음)를 쓰고, 그 위에 5개 도메인이 **독립적으로** 공유하는 명사 4개
(`Order`/`Item`/`Status`/`Event`)를 얹는다. 도메인마다 엔티티의 약 1/3만
공유 풀에서 뽑는다(`SHARED_DRAW_FRACTION = 1/3`, `scripts/gen_scale_corpus.py`
명시) — "대부분은 도메인 기술 용어를 쓰지만 가끔 일반 명사로 손이 간다"는
모델링 가정이며, 사후에 수치를 보고 고른 값이 아니라 코드를 쓸 때 먼저
정하고 실행한 값이다. 도메인 전용 명사는 서로도, 공유 풀과도 겹치지 않게
직접 골랐다(`impl/tests/test_gen_scale_corpus.py`
`test_domain_pools_do_not_overlap_each_other_or_the_shared_pool`이 핀으로
박는다) — 그래서 관측되는 모든 충돌은 **반드시 4개짜리 공유 풀에서만**
나온다(같은 스위트의 `test_every_collision_is_a_shared_noun_not_pool_exhaustion`
이 매 실행마다 확인한다). 측정은 이전과 같은 방법(`impl.lnpl.parser.parse`로
직접 집계 — `load_sources`는 fail-fast라 빈도를 못 센다)에 더해, 어느
도메인 쌍끼리 겹쳤는지도 센다:

| 규모(N) | 고유 이름 수 | 충돌난 이름 | 충돌 이벤트 수 | 겹친 도메인 쌍 수(전체 C(5,2)=10) |
|---|---|---|---|---|
| 10 | 8 | 2 (`Status`×2, `Order`×2) | **2** | 2 |
| 30 | 23 | 3 (`Status`×3, `Order`×5, `Item`×2) | **7** | 10 (전체) |
| 50 | 39 | 4 (`Status`×3, `Order`×5, `Item`×4, `Event`×3) | **11** | 10 (전체) |

풀 크기가 함께 해석되도록 병기한다: 도메인 전용 풀 20개/도메인(총 100개,
5도메인 × 20 — N=50에서 도메인당 최대 10개만 쓰므로 절반도 안 씀), 공유
풀 **4개**. N=50에서 도메인당 엔티티 10개 중 3개가 공유 풀에서 나온다(생성기
출력의 `pool_report`가 도메인별 `shared_drawn`/`domain_pool_size`를 그대로
찍는다).

**해석**: N=30부터 이미 5개 도메인 쌍 전부(C(5,2)=10)가 공유 명사 하나 이상을
겹쳐 쓴다 — 도메인 전용 이름은 단 한 건도 충돌하지 않았는데도(위 겹침
검사가 확인), 도메인들이 흔한 명사 4개를 각자 독립적으로 재사용하는
것만으로 충분히 발생한다. 이것은 풀 고갈의 인공물이 아니라 **"흔한 명사는
여러 팀이 독립적으로 손을 뻗는다"**는, 이슈 #117이 실제로 우려한 현상 그
자체를 모형화한 결과다.

재현 명령:

```bash
PYTHONPATH=impl .venv/bin/python -c "
import glob, collections, itertools, os
from lnpl.parser import parse
name_domains = collections.defaultdict(set)
names = collections.Counter()
for path in sorted(glob.glob('.claude/tmp/measure2/nodis_$N/*/*.lnpl')):
    domain = os.path.basename(os.path.dirname(path))
    with open(path, encoding='utf-8') as fh:
        for decl in parse(fh.read()):
            if decl.kind == 'entity':
                names[decl.name] += 1
                name_domains[decl.name].add(domain)
dups = {n: c for n, c in names.items() if c > 1}
pairs = set()
for n, doms in name_domains.items():
    if len(doms) > 1:
        for a, b in itertools.combinations(sorted(doms), 2):
            pairs.add((a, b))
print('entities=%d unique_names=%d colliding_names=%d collision_events=%d domain_pairs=%d' % (
    sum(names.values()), len(names), len(dups),
    sum(c - 1 for c in dups.values()), len(pairs)))
"
```
(`$N` = 10/30/50, 코퍼스는 위 "방법" 절의 `nodis_$N`.)

## 항목 2 — 컴파일 벽시계 (`--disambiguate`, 3회 측정 중앙값)

| 규모(N) | 3회 실측(초) | 중앙값 |
|---|---|---|
| 10 | 0.07 / 0.06 / 0.06 | **0.06s** |
| 30 | 0.07 / 0.07 / 0.07 | **0.07s** |
| 50 | 0.08 / 0.08 / 0.08 | **0.08s** |

(r1 이후 재측정 — 절대값은 파일시스템 캐시 상태에 따라 이전 측정(0.40~0.48s)과
다르지만, 증가 폭의 성격은 같다: 10→50에서 +0.02s로 프로세스 시작 오버헤드가
여전히 지배적이다.) 1회 측정은 잡음이라 3회 중앙값을 쓴다(계획 Task 02 step 2).

재현 명령:

```bash
files=(.claude/tmp/measure2/dis_$N/*/*.lnpl)
/usr/bin/time -p .venv/bin/lnpl compile "${files[@]}" -o /tmp/out.lir.json
# 3회 반복, `real` 줄의 중앙값을 쓴다
```

## 항목 3 — IR 바이트 크기

| 규모(N) | `.lir.json` 크기 |
|---|---|
| 10 | 25,221 bytes |
| 30 | 75,846 bytes |
| 50 | 126,741 bytes |

엔티티당 약 2,530바이트로 선형에 매우 가깝다(30/10 = 3.01배, 50/10 = 5.02배 —
엔티티 수 배율 3배/5배와 거의 일치). 이름 모델이 바뀌어도(r1 F1) IR 크기는
엔티티·워크플로 개수에 좌우되므로 이전 측정과 거의 같다.

재현 명령:

```bash
files=(.claude/tmp/measure2/dis_$N/*/*.lnpl)
.venv/bin/lnpl compile "${files[@]}" -o .claude/tmp/measure2/dis_$N.lir.json
wc -c .claude/tmp/measure2/dis_$N.lir.json
```

## 항목 4 — `unknown-entity` 후보 목록 길이

`--disambiguate` 코퍼스(엔티티 이름이 전역 유일 = 실제로 컴파일됨)에 존재하지
않는 엔티티를 참조하는 워크플로 하나를 심어 컴파일했다.

**중요한 실측 사실**: 엔티티가 2개 이상 선언된 모듈에서는 이것이 `warning`
등급 진단(`unknown-entity`, `declarations.md`)이 **아니라** 컴파일을 멈추는
`LowerError`다(`impl/lnpl/lower.py` `_resolve_entity` — 단일-엔티티 폴백
브랜치만 진단을 기록하고 통과시킨다; 2개 이상이면 즉시 예외를 던진다). 그
예외 메시지가 **선언된 엔티티 전부**를 후보로 나열한다 — "후보 목록"이 곧
전체 엔티티 목록이라는 뜻이고, 목록 길이는 항상 그 규모의 엔티티 수와 같다.
이 사실은 이름 모델과 무관하다(후보 목록은 이름 내용이 아니라 엔티티
**개수**로 결정된다) — r1 이후에도 변하지 않는다.

| 규모(N) | rc | 후보 목록 길이(=엔티티 수) | 에러 메시지 바이트 |
|---|---|---|---|
| 10 | 2 (컴파일 실패) | **10** | 345 |
| 30 | 2 (컴파일 실패) | **30** | 765 |
| 50 | 2 (컴파일 실패) | **50** | 1,210 |

50개 규모에서 메시지는 한 줄에 50개 이름이 쉼표로 나열되는 1,210바이트 단일
문자열이다 — "사람이 읽을 만한 길이"의 판정은 Task 03이 이 수치로 내린다.
(이슈 #117 본문은 이걸 `warning` 진단으로 전제했는데, 실측은 엔티티 2개
이상이면 컴파일을 멈추는 하드 에러임을 보였다 — 전제가 틀렸다는 뜻이다.
F2 이슈에 함께 적는다.)

재현 명령:

```bash
cp -r .claude/tmp/measure2/dis_$N .claude/tmp/measure2/unk_$N
printf 'workflow ProbeUnknownEntity\n    find nonexistentnoun\n' \
  > .claude/tmp/measure2/unk_$N/_probe.lnpl
files=(.claude/tmp/measure2/unk_$N/*/*.lnpl .claude/tmp/measure2/unk_$N/_probe.lnpl)
.venv/bin/lnpl compile "${files[@]}" -o /tmp/out.lir.json   # rc 2, 메시지가 후보를 나열
```

## 항목 5 — OpenAPI `components/schemas` 이름 충돌

| 규모(N) | 스키마 이름 충돌 |
|---|---|
| 10 | **0건 관측** |
| 30 | **0건 관측** |
| 50 | **0건 관측** |

세 규모 모두 `lnpl openapi`가 rc 0으로 끝나고 `schemas` 개수가 엔티티 수와
정확히 일치했다(충돌 0). 이유를 구조적으로 확인했다: `impl/lnpl/openapi.py`의
"name collision in components/schemas" 검사(`generate()`, `impl/lnpl/openapi.py`
근처 200행)에 **도달하기 전에** `load_sources`(파일 간)와 `lower()`(같은
파일 내)가 **이름 종류(엔티티/refinement) 구분 없이** 먼저 전역 유일성을
강제한다 — 별도 프로브로 확인:

- 파일 간 엔티티-refinement 동명 충돌 → `load_sources`가 즉시
  `duplicate declaration 'Order'` (rc 2), openapi 단계에 도달하지 않음.
- 같은 파일 내 엔티티-refinement 동명 충돌 → `lower()`가 즉시
  `'Order' is already a semantic type, ...` (rc 2), 역시 도달하지 않음.

즉 **현재 아키텍처에서 `openapi.py`의 스키마-충돌 검사는 도달 불능이다** —
그 앞의 두 단계가 이미 모든 이름 충돌(종류 무관)을 막기 때문이다. "50까지
안 터짐"이 아니라 "이 파이프라인 구조에서는 터질 수 없다"가 정확한 서술이다.
tech-debt로 [issue #122](https://github.com/choiyounggi/linkly/issues/122)에
등재했다 — RFC-0033이 채택되면 이 검사가 되살아나야 한다(r1 F2).

재현 명령:

```bash
files=(.claude/tmp/measure2/dis_$N/*/*.lnpl)
.venv/bin/lnpl openapi "${files[@]}" -o /tmp/out.openapi.json
python3 -c "import json; d=json.load(open('/tmp/out.openapi.json')); print(len(d['components']['schemas']))"
# 도달 불능 구조 확인:
printf 'entity Order\n    field\n        id UUID\n\nworkflow F\n    find order\n' > /tmp/a.lnpl
printf 'refine Order of Text\n    maxLength 10\n' > /tmp/b.lnpl
.venv/bin/lnpl compile /tmp/a.lnpl /tmp/b.lnpl -o /tmp/x.lir.json   # rc 2, load_sources가 잡음
```

## D7 — 골든 IR 재생성 비용 산정 (구현하지 않음, 산정만)

`derive_id`(node id 파생 함수)가 네임스페이스를 담게 될 경우 바뀔 골든
`.lir.json` 픽스처를 파일 수·id 필드 수로 산정한다. **실제로 재생성하지
않는다** — 산정만 한다(범위 밖: `<scope_boundaries>`).

테스트 스위트가 바이트 비교하는 골든 IR은 `examples/*.lir.json` 5개뿐이다
(`impl/tests/fixtures.py`의 `*_LIR` 상수, `impl/tests/test_golden.py`가 소비).
`qa/` 아래의 다른 `.lir.json`들은 QA 케이스 증거물이지 스위트가 바이트
비교하는 골든 픽스처가 아니라서 이 산정에서 뺐다.

| 골든 파일 | id 필드 수 |
|---|---|
| `examples/login.lir.json` | 19 |
| `examples/linkhub.lir.json` | 24 |
| `examples/checkout.lir.json` | 20 |
| `examples/guarded.lir.json` | 17 |
| `examples/shorten.lir.json` | 23 |
| **합계 (5 파일)** | **103** |

이 103은 상한 추정이다 — 실제로는 선언 이름이 파생 경로에 들어가는 id만
바뀌지만("R2: 선언의 full node id"), 몇 개가 안 바뀌는지는 `derive_id`의
구체적 네임스페이스 인코딩 방식이 정해져야 알 수 있다(→ 그 방식은 Task 03이
"필요" 결론일 때만 RFC 미결 질문 ②에서 정한다). 지금 산정은 "재생성 검토
대상"의 상한이다: 파일 5개, id 필드 최대 103개.

재현 명령:

```bash
grep -c '"id":' examples/login.lir.json examples/linkhub.lir.json \
  examples/checkout.lir.json examples/guarded.lir.json examples/shorten.lir.json
```

## 결론 (Task 03)

### 판정 기준 (수치를 보기 전에 고정 — `.orchestration/plans/t117-tasks/03-conclusion.md` step 1 그대로)

다음 넷을 **전부** 만족해야 "지금은 불필요":

1. 50개 규모에서 이름 충돌 빈도가 **0**
2. `unknown-entity` 후보 목록이 사람이 읽을 만한 길이
3. 컴파일 시간이 선형에 가깝다
4. OpenAPI 스키마 충돌이 없다

**하나라도 깨지면 → "필요."**

### 판정

**"필요"** — 위 1번이 실측에서 깨진다. (r1 F1 반영: 항목 1의 방법을 고쳐
재측정한 뒤에도 결론은 바뀌지 않았다 — 아래가 새 근거다.)

- 조건 1 (충돌 빈도 0): **깨짐.** N=50에서 충돌 이벤트 **11건**(항목 1
  표, r1 이후 재측정). 도메인 전용 이름(20개/도메인, N과 함께 자람)은
  단 한 건도 충돌하지 않았다 — 충돌은 전부 5개 도메인이 독립적으로
  재사용하는 4개짜리 공유 명사(`Order`/`Item`/`Status`/`Event`)에서만
  났고, N=30부터 이미 도메인 쌍 10개(C(5,2)) 전부가 겹쳤다. 이슈 #117이
  우려한 정확히 그 시나리오("흔한 명사를 여러 도메인이 독자적으로
  쓴다")가 이 규모에서 실제로 관측된다 — 그리고 이번에는 그 관측이 생성기
  파라미터(명사 풀 크기)가 아니라 도메인 간 독립적 재사용에서 나온다는
  것을 항목 1의 회귀 테스트(`test_every_collision_is_a_shared_noun_not_pool_exhaustion`)
  로 매 실행마다 확인한다.
- 조건 2 (후보 목록 가독성): **경계.** N=50에서 `unknown-entity`류 에러가
  선언된 엔티티 **50개 전부**를 한 줄(1,210바이트)로 나열한다(항목 4).
  이 수치는 이름 모델과 무관하므로(엔티티 개수만 반영) r1 전후로 성격이
  바뀌지 않았다.
- 조건 3 (컴파일 시간 선형성): **안 깨짐.** 0.06s → 0.08s, 완만함(항목 2,
  r1 이후 재측정 — 절대값은 환경 캐시 상태에 따라 달라지지만 완만함은
  동일).
- 조건 4 (OpenAPI 충돌 없음): **안 깨짐.** 0건, 게다가 구조적으로 도달
  불능(항목 5).

넷 중 하나(조건 1)가 명확히 깨졌으므로 규칙대로 "필요"다. 조건 3·4가
문제없다고 해서 "필요"를 "불필요"로 뒤집지 않는다 — 판정 기준은 AND이지
다수결이 아니다. 재측정으로 결론이 바뀌었다면 그대로 "불필요"로 뒤집고
RFC-0033을 지웠을 것이다(r1 리뷰가 명시적으로 요구한 절차) — 실제로는
바뀌지 않았을 뿐이다.

**증거로서 무엇에 무게를 두는가**: "11건"이라는 크기 자체는
`SHARED_DRAW_FRACTION`(1/3)과 공유 풀 크기(4개)라는, 이 측정이 정한
모델링 파라미터에 좌우된다 — 다른 비율을 골랐으면 다른 숫자가 나왔을
것이다. 그래서 이 판정이 실제로 딛고 서는 근거는 그 크기가 아니라 두
가지다: ① **도메인 쌍 커버리지** — N=30부터 이미 도메인 쌍 10개
(C(5,2)) 전부가 공유 명사 하나 이상을 겹쳐 썼다(비율을 낮춰도 도메인
수가 5개인 한 이 커버리지가 빠르게 포화된다는 구조는 남는다), ② **도메인
전용 이름의 충돌 0건**이라는 통제(control) — 이름이 부족해서가 아니라
독립적인 흔한-명사 재사용만으로 이 정도가 난다는 것을 직접 확인한다.
이 둘이 "필요"를 떠받치고, "11"이라는 숫자 자체는 그 결론의 크기가
아니라 존재를 보여주는 예시로 읽어야 한다.

### 선택안

이슈 #117의 (a) 디렉터리=네임스페이스 + (b) `internal/` 가시성 규약을
채택하고, (c) `use` 키워드 도입은 기각을 유지한다 — `rfcs/0033-namespace-directories.md`
(`Updates: RFC-0031 §Guide-level Explanation, §Reference-level
Specification > load_sources`). 미결 질문 3개(짧은 이름 해소/`derive_id`
+ 골든 재생성 비용/OpenAPI 스키마명)에 전부 답이 있다(RFC-0033
§Reference-level Specification).

**골든 IR 재생성 비용**(D7, 이 문서 위 절 인용): 이 RFC를 받아들이는
시점의 실질 비용은 **0**이다 — 5개 골든 예제 전부가 네임스페이스 없는
단일 파일 컴파일이고, `derive_id`의 네임스페이스 인자가 없을 때
(namespace=None) 오늘과 바이트 동일하도록 설계했다(RFC-0033
§Reference-level Specification > `derive_id`). 앞서 산정한 상한(파일
5개, id 필드 103개)은 "다섯 예제를 전부 네임스페이스 레이아웃으로
마이그레이션했을 때"의 상한이지, 이 RFC를 승인하는 즉시 드는 비용이
아니다.

### 언제 다시 재보아야 하는가

RFC-0033이 실제로 구현되기 전까지는 이 문서의 수치가 유효하다. 구현 뒤
재측정이 필요한 시점:

- 도메인 수가 5개를 넘거나(예: 마이크로서비스가 10개 이상), 엔티티 규모가
  **100개**를 넘어설 때 — 이 문서는 최대 50까지만 쟀다.
  `scripts/gen_scale_corpus.py --entities 100 --out ... [--disambiguate]`로
  같은 5항목을 다시 잰다.
  RFC-0033 §Open Questions ①(네임스페이스 깊이 2단계 초과)이 실제로
  필요해지는지도 그 시점에 함께 본다.
- `internal/` 채택 이후 실사용에서 가시성 위반 에러 빈도가 실제로
  얼마나 나는지 — 이 문서는 그 항목을 측정하지 않았다(RFC-0033
  §Reference-level Specification의 설계일 뿐, 구현·실사용 데이터 없음).
