# lnpl — Claude Code plugin

`.lnpl` 소스를 쓰는 동안 linkly의 닫힌 어휘로 라우팅하고, 저장 직후 컴파일 진단을
되돌린다.

## 왜 필요한가

LNPL의 어휘는 닫혀 있고 모델의 학습 데이터에 없다. 그래서 그럴듯한 파일이
**컴파일에 성공한 뒤 아무 일도 하지 않는** 결과가 흔하다:

- `VERB_LEXICON` 밖의 동사는 에러가 아니라 효과 없는 no-op이다 (issue #36)
- `security jwt`·`policy rollback`은 선언돼도 집행되지 않는다 (issue #38)
- `if` / `for` / `while` / `switch`는 문법적으로 표현 불가능하다

`lnpl compile`은 이것들을 진단으로 알려주지만 **stderr에 쓰고 종료 코드 0으로
끝난다** — 보지 않으면 사라진다.

## 구성

| 구성요소 | 하는 일 |
|----------|---------|
| `lnpl-authoring` 스킬 | 어휘 라우팅. 본문은 컴파일러 테이블에서 생성된 `references/` |
| `lnpl-verify` 스킬 | 완료 게이트 — compile 진단 → `spec --run` → (툴체인이 있으면) `diff` |
| `lnpl-spec` 스킬 | 선언에서 spec 케이스를 기계적으로 도출하는 규칙 |
| `lnpl-kb` 스킬 | 설계 결정 전에 KB를 조회(RFC-0005 라우팅) |
| `lnpl-doctor` 스킬 | 설치·버전 불일치 진단 |
| PostToolUse 훅 | `*.lnpl` 저장 직후 `lnpl compile` 진단을 모델에게 전달 |

작성(`lnpl-authoring`) → 검증 도출(`lnpl-spec`) → 완료 판정(`lnpl-verify`)이
한 루프이고, 설계 결정이 필요한 순간마다 `lnpl-kb`가 끼어든다.

어휘 문서는 `scripts/gen_plugin_references.py`의 산출물이고, 손으로 고치면
`impl/tests/test_plugin_references.py`가 실패한다. 정본은 언제나 소스다.

## 설치

```
/plugin marketplace add choiyounggi/linkly
/plugin install lnpl@linkly
```

훅이 동작하려면 `lnpl` CLI가 PATH에 있어야 한다:

```bash
pip install /path/to/linkly
```

문제가 있으면 `lnpl-doctor` 스킬을 쓴다.
