<!-- 생성물 — 손으로 고치지 마라. 정본은 rfcs/0048-collections-non-goal-and-rowset-group-by.md와 rfcs/0058-pipeline-implicit-close-indentation.md이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# 컬렉션이 필요해 보일 때 — 안티패턴과 권장패턴

> lnpl 0.8.0 기준.

`.lnpl`을 쓰다가 "여기 목록/맵이 필요하겠다"는 느낌이 들 때 멈추는 표다 — 그 느낌을 따라가면 파서가 받아주지 않거나(컬렉션 필드는 문법에 없다), 파서가 받아준다 해도 의미가 없는 문장을 쓰게 된다. linkly는 닫힌 어휘라 그럴듯한 낱말이 조용히 아무 일도 하지 않는 쪽이 실패 모드다(RFC-0048).

| 시도하기 쉬운 것 (틀림) | 대신 쓸 것 (맞음) | 근거 |
|---|---|---|
| `tags List<Text>` (field 절 안) | 별도 엔티티 + `list tag where owner == this.id` | RFC-0048 — 컬렉션 필드 영구 비목표 |
| `items Map<Text, Integer>` (field 절 안) | 별도 엔티티 + RowSet 집계 (`sum`/`count`/`avg`/`min`/`max`) | RFC-0048 — 컬렉션 필드 영구 비목표 |
| 각 그룹의 항목 목록을 그대로 반환 | `group by ... aggregate`는 (key, 집계값) 파생 RowSet까지만 낸다 — 그룹별 원본 행 목록이 필요하면 그룹마다 별개의 `list ... where` 질의를 쓴다 | RFC-0048 §Open Questions |

## 조건이 두 단계 이상 이어질 때 — 가드된 파이프라인 연쇄

"확인 → 실행 → 결과를 보고 다음 단계"를 쓸 때 멈추는 표다. 가드는 항목 하나만 소유하므로 단계마다 가드 하나가 `pipeline` 하나를 소유하게 하고, 뒤 가드는 앞 파이프라인이 만든 바인딩을 읽는다. 비교 연산은 바인딩되지 않은 참조에 대해 거짓이므로(RFC-0012 §G12.4) 앞 가드가 거짓이면 뒤 가드도 특별취급 없이 거짓이 된다. 정본 예제는 `examples/staged.lnpl`이다(RFC-0058).

| 들여 쓴 철자 (거부됨) | 대신 쓸 것 | 근거 |
|---|---|---|
| 뒤 가드를 앞 `pipeline`의 스텝 열에 들여 써서 그 단계도 앞 가드 안이라고 표시 | 뒤 가드를 `pipeline` 줄과 같은 열에 쓰고, 그 가드가 소유할 스텝들은 새 `pipeline`으로 묶는다 — `pipeline`은 다음 키워드에서 닫히므로 들여 쓴 가드는 어차피 밖에서 작동한다 | RFC-0058 — §Block structure 3항 c |
