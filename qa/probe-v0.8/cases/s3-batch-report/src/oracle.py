#!/usr/bin/env python3
"""Independent oracle for R6/C4/C5. Regenerates the dataset from seed.py's own
generator (same seed=42) -- never reads the lnpl store to compute expectations --
then reads lnpl's own Settlement/DailyTotal rows via sqlite for comparison.
"""
import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

from seed import gen_full


def load_store_rows(store: str, entity_id: str) -> dict:
    conn = sqlite3.connect(store)
    rows = {}
    for row_key, payload in conn.execute(
        "select row_key, payload from lnpl_rows where entity_id=?", (entity_id,)
    ):
        rows[row_key] = json.loads(payload)
    conn.close()
    return rows


def expected_monthly(txs, month_key: str):
    """Per-merchant expected Settlement fields for one month, settled-only."""
    by_merchant = defaultdict(list)
    for t in txs:
        if t["monthKey"] == month_key and t["status"] == "settled":
            by_merchant[t["merchant"]].append(t)

    out = {}
    for merchant, rows in by_merchant.items():
        amounts = [Decimal(r["amount"]["amount"]) for r in rows]
        fees_raw = [Decimal(r["fee"]["amount"]) for r in rows]
        gross = sum(amounts)
        fees_sum = sum(fees_raw)
        count = len(rows)
        avg_floor = (gross / count).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        avg_half_up = (gross / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        avg_half_even = (gross / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if count > 1000:
            fees_floor = (gross * Decimal("0.015")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            fees_half_up = (gross * Decimal("0.015")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            fees_half_even = (gross * Decimal("0.015")).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        else:
            fees_floor = fees_half_up = fees_half_even = fees_sum
        out[merchant] = {
            "gross": gross,
            "tx_count": count,
            "max": max(amounts),
            "min": min(amounts),
            "fees_raw": fees_sum,
            "avg": {"floor": avg_floor, "half_up": avg_half_up, "half_even": avg_half_even},
            "fees": {"floor": fees_floor, "half_up": fees_half_up, "half_even": fees_half_even},
            "net": {r: gross - fees_floor if r == "floor" else gross - fees_half_up if r == "half_up" else gross - fees_half_even for r in ("floor", "half_up", "half_even")},
        }
    return out


def cmd_settlement(args):
    _, txs = gen_full(args.size, args.seed)
    expected = expected_monthly(txs, args.month_key)
    actual = load_store_rows(args.store, "entity.settlement")

    mismatches = []
    matched_rule = None
    for rule in ("half_even", "half_up", "floor"):
        rule_mismatches = []
        for merchant, exp in sorted(expected.items()):
            row_key = f"entity.settlement#settlement-{merchant}-{args.month_key}"
            row = actual.get(row_key)
            if row is None:
                rule_mismatches.append((merchant, "missing-row", None, None))
                continue
            checks = [
                ("gross", str(exp["gross"]), row.get("gross", {}).get("amount")),
                ("txCount", exp["tx_count"], row.get("txCount")),
                ("maxTicket", str(exp["max"]), row.get("maxTicket", {}).get("amount")),
                ("minTicket", str(exp["min"]), row.get("minTicket", {}).get("amount")),
                ("avgTicket", str(exp["avg"][rule]), row.get("avgTicket", {}).get("amount")),
                ("fees", str(exp["fees"][rule]), row.get("fees", {}).get("amount")),
                ("net", str(exp["net"][rule]), row.get("net", {}).get("amount")),
            ]
            for field, want, got in checks:
                if str(want) != str(got):
                    rule_mismatches.append((merchant, field, want, got))
        if not rule_mismatches:
            matched_rule = rule
            mismatches = []
            break
        mismatches = rule_mismatches

    print(f"merchants expected: {len(expected)}, settlement rows found: {len(actual)}")
    print(f"matched rounding rule: {matched_rule or 'NONE'}")
    print(f"mismatches: {len(mismatches)}")
    for m in mismatches[:30]:
        print("  ", m)
    return 0 if matched_rule else 1


def cmd_compare_runs(args):
    a = json.loads(open(args.run_a).read())
    b = json.loads(open(args.run_b).read())
    a_by_m = {o["merchant"]: o for o in a}
    b_by_m = {o["merchant"]: o for o in b}
    print(f"run A: {len(a)} rows, run B: {len(b)} rows")
    diffs = []
    for m in sorted(set(a_by_m) | set(b_by_m)):
        ra, rb = a_by_m.get(m), b_by_m.get(m)
        if ra is None or rb is None:
            diffs.append((m, "row-missing-in-one-run"))
            continue
        ba = ra["result"].get("result", {}).get("bindings", {}).get("newSettlement", {})
        bb = rb["result"].get("result", {}).get("bindings", {}).get("newSettlement", {})
        for field in ("gross", "fees", "txCount", "avgTicket", "maxTicket", "minTicket"):
            if json.dumps(ba.get(field), sort_keys=True) != json.dumps(bb.get(field), sort_keys=True):
                diffs.append((m, field, ba.get(field), bb.get(field)))
    print(f"field diffs: {len(diffs)}")
    for d in diffs[:30]:
        print("  ", d)
    return 0 if not diffs else 1


def cmd_daily(args):
    _, txs = gen_full(args.size, args.seed)
    by_merchant = defaultdict(list)
    for t in txs:
        if t["dayKey"] == args.date and t["status"] == "settled":
            by_merchant[t["merchant"]].append(t)
    expected = {
        m: {"gross": sum(Decimal(r["amount"]["amount"]) for r in rows), "count": len(rows)}
        for m, rows in by_merchant.items()
    }
    actual_rows = load_store_rows(args.store, "entity.daily.total")
    actual = {r["merchant"]: r for r in actual_rows.values() if r.get("merchant")}

    mismatches = []
    for merchant, exp in sorted(expected.items()):
        row = actual.get(merchant)
        if row is None:
            mismatches.append((merchant, "missing-row"))
            continue
        got_gross = row.get("gross", {}).get("amount")
        got_count = row.get("count")
        if str(exp["gross"]) != str(got_gross):
            mismatches.append((merchant, "gross", str(exp["gross"]), got_gross))
        if exp["count"] != got_count:
            mismatches.append((merchant, "count", exp["count"], got_count))
    print(f"merchants with settled tx on {args.date}: {len(expected)}, DailyTotal rows matched: {len(actual)}")
    print(f"mismatches: {len(mismatches)}")
    for m in mismatches[:30]:
        print("  ", m)
    return 0 if not mismatches else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--size", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--month-key", default="2026-07")
    ap.add_argument("--compare-runs", nargs=2, metavar=("A", "B"))
    ap.add_argument("--daily", metavar="YYYY-MM-DD")
    args = ap.parse_args()

    if args.compare_runs:
        args.run_a, args.run_b = args.compare_runs
        sys.exit(cmd_compare_runs(args))
    if args.daily:
        args.date = args.daily
        sys.exit(cmd_daily(args))
    sys.exit(cmd_settlement(args))


if __name__ == "__main__":
    main()
