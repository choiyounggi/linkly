# RFC-0000: RFC Process

> Status: Accepted (2026-07-31) — 교차 정합성 전항 통과 + 소유자 승인.

## 1. 목적

이 문서는 LNPP 설계 RFC(0001~0006 및 이후 신규 RFC)가 따를 프로세스를 정의한다 —
수명주기, 번호 체계, 문서 언어 규칙, 골든 시나리오 규칙, 그리고 모든 RFC가 복사해
사용할 고정 7섹션 템플릿(§6).

- 정본 관계: `CHARTER.md`는 0단계 비전 문서(수정 금지·원문 보존)이고, 정본 설계는
  `rfcs/`의 RFC들이다. 용어 정의의 정본은 `docs/GLOSSARY.md`.
- 이 문서 자체는 프로세스 문서이므로 §6의 7섹션 템플릿을 따르지 않는다.
  템플릿은 RFC-0001부터 적용된다.

## 2. RFC 수명주기

모든 RFC는 다음 4단계를 순서대로 거친다:

`Draft → Review → Accepted → Superseded`

| 단계 | 의미 | 전이 기준 |
|------|------|-----------|
| Draft | 작성 중. 모든 신규 RFC의 초기 상태 | 작성 완료 + 자체 검증(각 RFC의 실패 가능한 검증) 통과 시 Review로 |
| Review | 교차 정합성 검토 대상 | Task 09 교차 정합성 체크리스트 전 항목 PASS + 소유자 승인 시 Accepted로 |
| Accepted | 채택 — 구현이 따라야 할 계약 | 대체 RFC가 Accepted되면 Superseded로 |
| Superseded | 신규 RFC로 대체됨 | 종결 상태. `Superseded-by:` 링크 필수, 대체 RFC 쪽 `Supersedes:` 역링크 권장 |

- 상태는 각 RFC의 `## Status` 섹션 첫 줄에 표기한다(§6 템플릿 참조).
- Accepted RFC의 실질 변경은 수정이 아니라 새 RFC로 대체(Supersede)한다.

## 3. 번호 체계

번호 0000~0006은 고정 할당이며 재사용·재배정하지 않는다:

| 번호 | 주제 |
|------|------|
| 0000 | RFC Process (이 문서) |
| 0001 | Semantic IR |
| 0002 | Syntax |
| 0003 | Runtime |
| 0004 | Compiler |
| 0005 | Knowledge Base |
| 0006 | Agent Protocol |

- 신규 RFC는 **0007부터 순차 증가**로 부여한다. 폐기(Superseded)된 번호도 재사용 금지.
- 파일명 규칙: `rfcs/NNNN-<kebab-slug>.md` — 번호는 4자리 zero-pad
  (예: `rfcs/0001-semantic-ir.md`, `rfcs/0007-new-topic.md`).

## 4. 문서 언어 규칙

- **한국어 본문 + 영어 식별자**: 산문은 한국어로 쓰고, 키워드·타입명·스키마
  필드명·코드 식별자·섹션 헤딩(§6의 7섹션)은 영어를 사용한다.
- 언어 워킹네임은 **LNPL**(소스 확장자 `.lnpl`)이다. 추후 개명 가능성이 있으므로
  각 RFC 본문에서 언어명을 처음 언급할 때 워킹네임임을 명시한다.

## 5. 골든 시나리오 규칙

- 모든 RFC의 `## Examples` 섹션은 골든 시나리오 **"Login"**을 사용한다.
- 정본 정의는 `plans/rfc-suite/plan.md` §골든 시나리오 "Login" — **참조만 하고
  재정의하지 않는다**(사본 발산 방지). RFC는 자기 관점의 표현(문법, IR, 런타임 계약,
  KB 참조, 에이전트 메시지)으로 같은 시나리오를 나타내야 한다.
- 시나리오 구성요소를 바꾸고 싶다면 정본을 소유한 계획 문서 개정이 선행되어야 한다.

## 6. RFC 템플릿

신규 RFC는 아래 블록을 그대로 복사해 시작한다. 7개 섹션의 이름과 순서는 고정이며
글자 단위로 일치해야 한다(섹션 추가·삭제·개명 금지).

```markdown
# RFC-NNNN: <제목>

## Status

- Status: Draft <!-- Draft | Review | Accepted | Superseded -->
- Supersedes: <대체하는 RFC 번호 — 없으면 줄 삭제>
- Superseded-by: <이 RFC를 대체한 RFC 번호 — 없으면 줄 삭제>

## Motivation

<이 RFC가 필요한 이유 — 해결하려는 문제, Charter/상위 RFC와의 연결>

## Guide-level Explanation

<이미 채택된 것처럼 사용자 관점의 산문 설명 — 예제 중심, 신규 참여자 대상>

## Reference-level Specification

<정밀 명세 — 형식 정의·스키마·계약. 구현자가 이 절만으로 구현 가능해야 함>

## Examples

<골든 시나리오 "Login" 사용 필수 — RFC-0000 §5 골든 시나리오 규칙 참조>

## Alternatives

<검토 후 기각한 대안과 기각 사유>

## Open Questions

<이 RFC에서 미결로 남기는 질문 — 후속 RFC 또는 ROADMAP으로 넘길 항목>
```
