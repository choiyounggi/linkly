---
id: style-declaration-format
category: Style
triggers:
  - `.lnpl` 소스를 포맷할 때
  - 들여쓰기가 의미가 있는지 확인할 때
  - step 라인을 어떻게 쓸지
  - indentation
  - formatting
  - step line
  - merge
version: 0.1.0
status: verified
sources:
  - rfcs/0002-syntax.md#block-structure-d5-개정판
  - https://arxiv.org/html/2508.13666
---
# declaration format

**들여쓰기는 의미가 없다.** 블록은 키워드가 구획하고 파서는 선행 공백을 무시한다.
그래서 포맷은 사람과 LLM의 가독성 문제이고, 문법 오류의 원인이 될 수 없다.

이렇게 쓴다:

- **관례는 4칸, 탭은 금지.** 탭은 렉서가 거부한다(포맷이 의미가 없는 언어에서 탭/스페이스
  혼용은 순수한 시각적 혼란이다).
- **한 줄 한 선언.** 라인이 그 자체로 유효성 판정 가능해야 스트리밍 생성 중 어느 지점에서
  끊겨도 그 앞까지가 완결된 접두사가 된다.
- **step은 동사 선두, 1~4토큰.** `validate input`·`authenticate`. 5토큰 이상이나 동사가
  앞에 없는 자유 텍스트는 문법 오류다.
- **`parallel`만 `merge`로 닫는다.** 다른 블록은 다음 키워드에서 닫히므로 닫는 표기를
  쓰지 않는다.
- **주석은 `#`.** 포맷팅 토큰이 코드 토큰의 ~24.5%를 차지한다는 실측이 이 문법의 설계
  근거이므로, 장식용 구분선 주석은 그 이득을 되돌린다.
