# 실행 비용 계약 (issue #164)

이 문서는 "보장"에서 시작하지 않는다 — 아래 표는 먼저 **현재 특성**(코드를
읽어 확정한 사실, `status: current`)과 **계약으로 승격할 항목**
(`status: contract`, 이번 표에는 아직 없음)을 구분한다. `status: current`
행은 앞으로 바뀔 수 있고, 바뀌어도 breaking이 아니다 — `docs/compatibility.md`의
계약 목록과 다른 층이다. `evidence` 열이 가리키는 파일:줄을 다시 읽어야 각
행이 여전히 참인지 검증할 수 있다.

정본은 `impl/lnpl/cost_model.py`의 `COST_TABLE`이다. 아래 표는 그 내용을
사람이 읽는 형태로 담을 뿐이며, `impl/tests/test_cost_model.py`가 둘이
어긋나지 않는지 검사한다.

## 연산별 비용

| operation | complexity | status | evidence | note |
|---|---|---|---|---|
| list_where_no_pushdown | O(n) filter, O(n log n) if order by | current | impl/lnpl/repo_policy.py:218-239 | 전체 행 fetch 후 Python에서 필터/정렬, limit은 조기 종료 없이 슬라이스 |
| list_where_pushdown | O(n) — 인덱스 없음, 복잡도 불변 | current | impl/lnpl/drivers.py:394-425 | json_extract 필드에 CREATE INDEX 없음 — pushdown은 IO/전송량 개선일 뿐, SQLite도 풀스캔 |
| order_by | O(n log n) | current | impl/lnpl/repo_policy.py:236 | Python Timsort(무pushdown) 또는 SQLite 외부 정렬(pushdown) — 양쪽 경로 동일 클래스 |
| limit | O(n) (조기 종료 없음) | current | impl/lnpl/repo_policy.py:239 | 필터링된 전체 리스트를 만든 뒤 슬라이스 — limit이 스캔 범위를 줄이지 않음 |
| aggregate_count_sum_avg_min_max | O(n) 단일 패스 | current | impl/lnpl/interp.py:928-1150 | 5종 전부 메모리의 RowSet 위 단일 패스, 별도 정렬 없음 |
| cache_get_set | 드라이버/서버 의존적 — 이 레포가 계약 불가 | current | impl/lnpl/drivers.py:299-306, impl/lnpl/interp.py:278 | 코어에는 FakeCache 참조 구현(O(1) dict)만; 영속 캐시는 외부 바인딩 lnpl-redis(#143, 단일 원자 `SET key value PX ttl_ms` — docs/backends.md:263)로 출하됨. 복잡도는 Redis 서버 특성(GET/SET 평균 O(1))이며 외부 저장소의 특성이라 이 레포의 계약으로 승격할 수 없다 |
| single_row_read | O(log n) 근사(B-tree) | current | impl/lnpl/drivers.py:394-403 | 유일하게 PRIMARY KEY(entity_id,row_key) 인덱스를 타는 행 — 표에서 가장 강한 보장 |

`list_where_pushdown` 행이 `list_where_no_pushdown`과 같은 O(n) 클래스에
머무는 이유(D3)는 `json_extract` 필드에 인덱스가 없기 때문이다 —
드라이버가 predicate를 SQL로 내려보내도(`supports_predicate = True`),
SQLite는 여전히 풀스캔한다. pushdown이 개선하는 것은 스캔 복잡도가 아니라
프로세스 경계를 넘는 전송량(전체 행 대신 필터링된 행만 온다)이다.

## 재생성 / 대조

```
python -c "from lnpl.cost_model import cost_model_document; import json; print(json.dumps(cost_model_document(), indent=2, ensure_ascii=False))"
```

기계 판독 형태(`schemas/cost-model.json`, `lnpl cost` CLI)는 같은 함수
`cost_model_document()`에서 나온다 — 손으로 고치면
`scripts/gen_plugin_references.py --check`가 잡는다.
