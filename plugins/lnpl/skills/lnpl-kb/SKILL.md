---
name: lnpl-kb
description: Use before making an architecture, naming, performance, security, testing, concurrency, database, or cloud decision in a `.lnpl` module — routes to linkly's knowledge base instead of guessing. The KB is built for agent lookup (RFC-0005) and is keyed by trigger phrases.
---

# 결정하기 전에 KB를 조회한다

linkly는 설계 결정의 근거를 저장소 안에 갖고 있다. `.lnpl`에서 무언가를
**선택**해야 할 때 — 이름, 경계, 예산, 기제 — 추측하지 말고 먼저 찾는다.

## 쓰는 법

```
lnpl kb --route "<지금 내려는 결정>"    # 트리거 매칭 → 문서 id
lnpl kb --load <문서 id>                # 본문
lnpl kb                                 # 전체 인덱스 (id / 카테고리 / 트리거)
```

`--route`는 문서 id만 준다. 본문은 매칭된 뒤에만 읽는다 — RFC-0005의 3단
progressive disclosure이고, 그래서 인덱스를 통째로 읽을 필요가 없다.

## 언제 조회하는가

| 지금 정하려는 것 | 카테고리 |
|------------------|----------|
| 서비스·모듈 경계, 계층 구조 | architecture |
| entity·필드·워크플로 이름 | naming |
| 응답 예산, 캐싱, 쿼리 비용 | performance |
| 인증·인가·토큰·비밀값 | security |
| 테스트 수준, 케이스 최소셋 | testing |
| `parallel` 분기, fan-out/merge | concurrency |
| 스키마·인덱스·트랜잭션 | database |
| capability 프로비저닝, 배포 대상 | cloud |
| 재사용할 구현 패턴 | patterns |
| 피해야 할 것 | antipatterns |
| 표기 스타일 | style |
| capability 바인딩별 지침 | framework |

## 규칙

- 매칭이 없으면 `(no match — the KB has nothing for that)`가 나온다. 그때는
  **KB에 근거가 없다는 사실을 밝히고** 진행한다. 없는 근거를 지어내지 않는다.
- 로드한 문서의 id를 근거로 인용한다 — 나중에 그 결정을 되짚을 수 있어야 한다.
- KB가 말하는 것과 다르게 가려면, 왜 다른지를 먼저 말한다.
- KB 문서를 쓰거나 고칠 때, 런타임 강제를 전제로 한 서술에는 집행 등급
  (enforced/measured/unenforced)을 병기한다 — 등급 정의는
  `docs/ENFORCEMENT-MATRIX.md`를 따른다.
