# REPORT — 런타임 비용 실측 (issue #164)

방법은 [docs/cost-model.md](../../docs/cost-model.md)의 연산별 Big-O 표를
참고한다. 이 수치는 **절대 게이트가 아니다** — 클라우드 러너의 절대시간은
러너마다, 실행마다 흔들린다(CodSpeed 근거, brief 제약). 여기서 보는 것은
상대 추세뿐이다: `list_where_no_pushdown`과 `list_where_pushdown`이 같은
O(n) 클래스에 머무는지(D3), `aggregate`가 `list_where_*`보다 빠르게
스케일하지 않는지(둘 다 O(n)이므로) 같은 방향성.

재현:

```bash
PYTHONPATH=impl .venv/bin/python benchmarks/runtime/run.py
```

매 실행마다 `results.json`을 덮어쓴다 — 재실행 가능성이 핵심이지, 고정된
스냅샷이 아니다.

## 스케일 3종 실측 (초, 3회 반복 중앙값)

| operation | n=100 | n=1000 | n=10000 |
|---|---:|---:|---:|
| list_where_no_pushdown | 0.000008 | 0.000077 | 0.000779 |
| list_where_pushdown | 0.000051 | 0.000540 | 0.005102 |
| aggregate | 0.000033 | 0.000296 | 0.002922 |
| cache_set | 0.000014 | 0.000108 | 0.001271 |
| cache_get | 0.000012 | 0.000113 | 0.001262 |
