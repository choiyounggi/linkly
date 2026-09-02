#!/usr/bin/env python3
"""benchmarks/runtime/run.py — issue #164 runtime cost benchmark.

Measures 5 operations from docs/cost-model.md at N=100/1000/10000: `list
where` with and without driver pushdown, a `sum` aggregate, and cache
get/set. Each (operation, n) pair is timed 3 times; the reported `seconds`
is the median. Rewrites `results.json`/`REPORT.md` on every run — the point
is re-run-ability, not a frozen snapshot (D5: no CI gate, no absolute-time
assertion; see docs/cost-model.md for the Big-O this is meant to track the
*direction* of, not prove).

    PYTHONPATH=impl .venv/bin/python benchmarks/runtime/run.py
"""
import json
import os
import statistics
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "impl"))

from lnpl.condition import Aggregate, Ref              # noqa: E402
from lnpl.drivers import SqliteRepositoryDriver         # noqa: E402
from lnpl.interp import Clock, FakeCache, eval_aggregate  # noqa: E402
from lnpl.repo_policy import apply_predicate            # noqa: E402

CLAUDE_TMP = os.path.join(REPO_ROOT, ".claude", "tmp")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

N_SCALES = (100, 1000, 10000)
OPERATIONS = ("list_where_no_pushdown", "list_where_pushdown", "aggregate",
             "cache_set", "cache_get")
REPEATS = 3


def _order_rows(n):
    return [{"id": str(i), "amount": i} for i in range(n)]


def _time_it(fn, repeats=REPEATS):
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def _measure_list_where_no_pushdown(n):
    rows = _order_rows(n)
    predicate = [("amount", ">", n // 2)]
    return _time_it(lambda: apply_predicate(rows, predicate=predicate))


def _measure_list_where_pushdown(n):
    os.makedirs(CLAUDE_TMP, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="cost_bench_", suffix=".db", dir=CLAUDE_TMP)
    os.close(fd)
    os.remove(path)  # SqliteRepositoryDriver creates its own file
    driver = SqliteRepositoryDriver(path)
    try:
        driver.seed({"entity.order":
                    {str(i): {"id": str(i), "amount": i} for i in range(n)}})
        predicate = [("amount", ">", n // 2)]
        return _time_it(lambda: driver.query("entity.order", predicate=predicate))
    finally:
        driver._conn.close()
        if os.path.exists(path):
            os.remove(path)


def _measure_aggregate(n):
    rowsets = {"order": [{"amount": i} for i in range(n)]}
    agg = Aggregate(func="sum", ref=Ref(name="order.amount"))
    return _time_it(lambda: eval_aggregate(agg, "sum order.amount", rowsets))


def _measure_cache_set(n):
    cache = FakeCache(Clock())

    def do_sets():
        for i in range(n):
            cache.set("k%d" % i, i, ttl_ms=60000)

    return _time_it(do_sets)


def _measure_cache_get(n):
    cache = FakeCache(Clock())
    for i in range(n):
        cache.set("k%d" % i, i, ttl_ms=60000)

    def do_gets():
        for i in range(n):
            cache.get("k%d" % i)

    return _time_it(do_gets)


_MEASURERS = {
    "list_where_no_pushdown": _measure_list_where_no_pushdown,
    "list_where_pushdown": _measure_list_where_pushdown,
    "aggregate": _measure_aggregate,
    "cache_set": _measure_cache_set,
    "cache_get": _measure_cache_get,
}


def measure(operation, n):
    """One `{"operation", "n", "seconds"}` record — the median of `REPEATS`
    timed runs of `operation` at scale `n`. `ValueError` for any operation
    outside `OPERATIONS` (no silent 0)."""
    if operation not in _MEASURERS:
        raise ValueError("unknown benchmark operation: %r" % operation)
    seconds = _MEASURERS[operation](n)
    return {"operation": operation, "n": n, "seconds": seconds}


def run_all(n_scales=N_SCALES):
    return [measure(operation, n) for n in n_scales for operation in OPERATIONS]


def results_document(results):
    return {
        "_generated": {
            "by": "benchmarks/runtime/run.py",
            "source": "benchmarks/runtime/run.py:run_all()",
            "hand_edit": False,
        },
        "measured_at": "manual re-run — see git log",
        "results": results,
    }


def _report_table(results):
    by_key = {(r["operation"], r["n"]): r["seconds"] for r in results}
    lines = ["| operation | n=100 | n=1000 | n=10000 |", "|---|---:|---:|---:|"]
    for op in OPERATIONS:
        cells = " | ".join("%.6f" % by_key[(op, n)] for n in N_SCALES)
        lines.append("| %s | %s |" % (op, cells))
    return "\n".join(lines)


def write_report(results):
    table = _report_table(results)
    text = """# REPORT — 런타임 비용 실측 (issue #164)

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

""" + table + "\n"
    report_path = os.path.join(BASE_DIR, "REPORT.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return report_path


def main():
    results = run_all()
    doc = results_document(results)
    results_path = os.path.join(BASE_DIR, "results.json")
    with open(results_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    write_report(results)
    print("wrote %s and REPORT.md" % results_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
