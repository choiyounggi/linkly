# KB 팩 — 코어를 포크하지 않는 확장 (이슈 #137)

**정본은 코드다.** 계약은 `impl/lnpl/kb.py`의 `KnowledgeBase`와 그 docstring이고,
이 문서는 그것을 사람이 읽는 형태로 옮기면서 **왜 그렇게 정했는지**를 적는다.
둘이 갈라지면 코드가 옳다.

`CHARTER.md`가 KB를 "Language보다 중요하다"고 규정하지만, 이 이슈 전까지 KB는
단일 루트였다 — 조직이 사내 아키텍처 가이드나 팀 명명 규약을 얹으려면 코어
KB 문서 전체를 통째로 포크해야 했다. 팩은 그 확장 경로다: 코어는 그대로 두고,
별도 디렉터리(팩)를 KB에 레이어링한다.

## 1. 팩의 모양

팩은 코어 `kb/`와 같은 레이아웃이다 — RFC-0005의 카테고리 디렉터리 + 카테고리별
`index.md` 라우팅 테이블 + 문서 `.md` 파일. 다른 점은 루트에 `pack.toml` 매니페스트가
있다는 것뿐이다:

```toml
# pack.toml
name = "acme-compliance"
version = "1.2.0"
doc_id_prefix = "acme"
categories = ["Compliance"]
```

- `name`/`version`/`doc_id_prefix` 필수, `categories`는 선택(팩이 코어 12개 밖의
  새 카테고리를 쓸 때만).
- `doc_id_prefix`는 `^[a-z][a-z0-9-]*$`를 만족해야 하고 `lnpl`·`core`를 쓸 수 없다
  (코어 자신의 이름과의 충돌 예약).
- 팩이 내는 모든 문서 id는 자기 `doc_id_prefix + "-"`로 시작해야 한다 —
  ESLint의 `플러그인명/규칙명`과 같은 논리: 소유자가 이름에 박혀 있어야
  누가 낸 지침인지 id만 보고 안다.

## 2. 발견 경로 (3중, 병합 순서 고정)

```
코어(항상 먼저) -> lnpl.kb entry-points(이름순) -> LNPL_KB_PACKS -> --kb-pack
```

### entry-points로 등록

외부 패키지의 `pyproject.toml`:

```toml
[project.entry-points."lnpl.kb"]
acme-compliance = "acme_kb_pack:pack_root"
```

`acme_kb_pack.pack_root`는 인자 없이 팩 루트 디렉터리 경로(문자열)를 반환하는
콜러블이다. 패키지가 설치돼 있으면 `lnpl kb`가 자동으로 찾는다 — 코어 쪽에
이 팩에 대한 if문이 하나도 없다.

### 로컬 팩 (설치 없이)

```bash
lnpl kb --kb-pack /path/to/acme-compliance --route "audit log retention"
# 또는
LNPL_KB_PACKS=/path/to/acme-compliance:/path/to/another-pack lnpl kb --lint
```

`--kb-pack`은 반복 가능하고, 선언 순서가 우선순위다. `LNPL_KB_PACKS`는
`os.pathsep`(POSIX면 `:`) 구분 목록.

## 3. 충돌 규칙 — 병합하지 않고 거부한다

OPA 다중 번들의 `roots` 모델을 그대로 빌린다: 번들마다 자기가 소유하는 범위를
선언하고, 범위가 겹치면 로드 자체를 거부한다("roots are not overlapping ...
will result in an error" — `openpolicyagent.org/docs/management-bundles`).
병합 우선순위를 발명하지 않는 쪽이 이긴다 — 설치 순서에 따라 라우팅 결과가
달라지는 것은 재현 불가능한 지침이기 때문이다.

| 상황 | 결과 |
|------|------|
| 팩 문서 id가 **코어** id와 같다 | 코어가 이긴다. 팩 문서는 조용히 무시된다 — 내장이 절대 가려지지 않는다는 점에서 드라이버 SPI(`docs/backends.md` §8)와 같은 규율 |
| 두 팩의 `doc_id_prefix`가 같거나 한쪽이 다른 쪽의 접두다 | `KbError` — **KB 구성 시점에** 죽는다. 어느 팩 문서도 아직 읽지 않은 상태 |
| 팩 문서 id가 자기 `doc_id_prefix + "-"`로 시작하지 않는다 | `KbError` — 인덱스 빌드 시점에 죽는다 |

`KbError` 메시지는 드라이버 SPI miss와 같은 triple을 싣는다: 받은 값 · 코어
(내장) · 그 순간 등록된 팩 목록(없으면 "none") — 오탈자와 "팩을 안 얹었다"를
같은 메시지로 구분할 수 있게.

## 4. `load()`의 `path` 필드 — 팩 문서는 팩 루트 기준

코어 문서의 `path`는 그대로다 — 레포 루트 기준 상대경로, 팩 이전과 바이트
동일. 팩 문서는 레포 밖에 있을 수 있으므로 레포 루트 기준 계산이 무의미하다
(`../../../...`처럼 나온다). 대신 **자기 팩 루트 기준 상대경로**를 쓰고,
`doc["pack"] = <팩 이름>`을 함께 실어 어느 루트를 기준으로 풀어야 하는지
알려준다. 코어 문서에는 `pack` 키가 아예 없다 — 그 자체가 판별자다.

절대경로는 쓰지 않는다: 머신에 종속된 값이라 결정성과 이식성을 깬다. OPA
번들이 번들 내부 주소를 번들-상대로 쓰는 것과 같은 논리다.

```python
doc = kb.load("acme-compliance-audit-log")
doc["pack"]  # "acme-compliance"
doc["path"]  # "compliance/acme-compliance-audit-log.md" — 팩 루트 기준
```

## 5. `CATEGORIES` 확장

코어 12개 카테고리 상수는 불변이다. `KnowledgeBase.categories()`가 코어 ∪
로드된 팩이 선언한 카테고리의 합집합을 반환하고, `index()` 무결성 검사와
`kb --lint`가 그 합집합을 기준으로 검증한다 — 팩이 `categories = ["Compliance"]`를
선언하면 그 카테고리를 쓰는 팩 문서가 lint를 통과한다.

## 6. 하지 않는 것

중앙 KB 레지스트리·팩 배포 인프라는 이 범위가 아니다. 파이썬 패키징(entry-points)과
디렉터리 경로면 충분하고, 코어가 두 번째 패키지 매니저를 만들 이유가 없다.

관련: `impl/lnpl/kb.py`, `impl/tests/test_kb_packs.py`, 이슈 #137, `docs/backends.md`
§8(entry-points SPI의 자매 패턴).
