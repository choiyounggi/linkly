<!-- 생성물 — 손으로 고치지 마라. 정본은 rfcs/0048-collections-non-goal-and-rowset-group-by.md이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# 컬렉션이 필요해 보일 때 — 안티패턴과 권장패턴

> lnpl 0.8.0 기준.

`.lnpl`을 쓰다가 "여기 목록/맵이 필요하겠다"는 느낌이 들 때 멈추는 표다 — 그 느낌을 따라가면 파서가 받아주지 않거나(컬렉션 필드는 문법에 없다), 파서가 받아준다 해도 의미가 없는 문장을 쓰게 된다. linkly는 닫힌 어휘라 그럴듯한 낱말이 조용히 아무 일도 하지 않는 쪽이 실패 모드다(RFC-0048).

| 시도하기 쉬운 것 (틀림) | 대신 쓸 것 (맞음) | 근거 |
|---|---|---|
| `tags List<Text>` (field 절 안) | 별도 엔티티 + `list tag where owner == this.id` | RFC-0048 — 컬렉션 필드 영구 비목표 |
| `items Map<Text, Integer>` (field 절 안) | 별도 엔티티 + RowSet 집계 (`sum`/`count`/`avg`/`min`/`max`) | RFC-0048 — 컬렉션 필드 영구 비목표 |
| 각 그룹의 항목 목록을 그대로 반환 | `group by ... aggregate`는 (key, 집계값) 파생 RowSet까지만 낸다 — 그룹별 원본 행 목록이 필요하면 그룹마다 별개의 `list ... where` 질의를 쓴다 | RFC-0048 §Open Questions |
