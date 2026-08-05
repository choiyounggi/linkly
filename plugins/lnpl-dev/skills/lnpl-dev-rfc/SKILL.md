---
name: lnpl-dev-rfc
description: Use when adding, revising, renumbering, or reviewing an RFC in linkly's `rfcs/` directory — the RFC-0007 process rules and the mechanical lint that checks them. Covers numbering, the fixed 7-section template, status vocabulary, and the Supersedes/Updates relations.
---

# RFC를 쓰거나 고칠 때

정본은 `rfcs/0007-rfc-process-v2.md`다. 아래는 그중 **기계적으로 검사 가능한** 부분과
그것을 검사하는 도구다.

```
python scripts/rfc_lint.py
```

exit 0이면 문제 없음. 이 린터는 **테스트 스위트에 걸려 있지 않다** — 기여자가
손으로 돌리는 도구다.

## 번호 (§3)

- 파일명은 `rfcs/NNNN-<kebab-slug>.md`, 4자리 zero-pad
- 신규는 **마지막 번호 + 1**. 0000~0007은 고정 할당이다
- **폐기된 번호도 재사용하지 않는다**
- 갱신(Updates) RFC도 같은 번호 공간을 쓴다 — `0002a` 같은 접미사를 만들지 않는다
- 첫 줄 `# RFC-NNNN: <제목>`의 번호가 파일명과 일치해야 한다

번호를 새로 딸 때는 **먼저 `ls rfcs/`로 실측하라.** 과거에 두 문서가 같은 번호를
주장한 적이 있다 — 병렬 세션이 각자 "다음 번호"를 계산하면 충돌한다.

## 템플릿 (§7)

설계 RFC의 섹션은 이 일곱 개이고, **이름과 순서가 글자 단위로 고정**이다.

```
## Status
## Motivation
## Guide-level Explanation
## Reference-level Specification
## Examples
## Alternatives
## Open Questions
```

§7은 **추가·삭제·개명을 명시적으로 금지**한다. 부록이나 "Implementation Status"
같은 절을 덧붙이지 말고 내용을 기존 일곱 안으로 옮겨라. issue #11이 RFC-0008의
여덟 번째 섹션을 정확히 이 조항으로 지적했다.

RFC-0005가 추가 섹션을 가진 것처럼 보이지만 그것들은 **코드 펜스 안의 예시
문서**다. 섹션을 셀 때 `grep '^## '`를 쓰면 펜스 안을 함께 세어 오독한다 —
린터는 펜스를 건너뛴다.

**프로세스 RFC 면제(§1):** 프로세스 자체를 규정하는 문서(RFC-0000, RFC-0007)는
이 템플릿과 골든 시나리오 규칙을 적용받지 않는다. 린터도 그 둘을 건너뛴다.

## 상태 (§2.1)

`Draft` / `Review` / `Accepted` / `Superseded` 넷뿐이다. 두 표기 형식이 모두 쓰인다:

```
> Status: Superseded (2026-07-31)          # 블록인용 (RFC-0000, RFC-0007)
- Status: **Accepted** (RFC-0012, 2026-08-05)   # Status 섹션 안 (RFC-0001 이후)
```

## 개정 관계 (§2.2)

- **Supersedes** — 전면 대체. 대체된 문서는 편집하지 않고 이력으로 보존한다
- **Updates** — 부분 갱신. 대상 RFC와 **직전 갱신 RFC를 모두** 지목한다.
  연쇄를 밝히지 않으면 어느 텍스트가 이기는지 기계적으로 확인할 수 없다
  (RFC-0012가 이 형식의 예다)

린터는 이 관계를 검사하지 않는다 — 대상의 존재와 연쇄의 정확성은 읽어야 안다.

## 언어 (§4)

본문은 한국어, 식별자·키워드·스키마 필드는 영어.
