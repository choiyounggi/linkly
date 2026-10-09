#!/usr/bin/env python3
"""Drives MonthlySettlement/ReplaceSettlement once per merchant (R3/R4/R5/R6 @ 10k).

lnpl 0.8.0 has no in-language per-group loop (no `group by` -- Draft/unimplemented,
RFC-0048 -- and no for-each-row-in-RowSet construct, RFC-0025). Producing one
Settlement row per merchant therefore requires an external driver calling the
workflow once per merchant id -- this script IS that driver, and its existence
is itself part of the FINDINGS record (F-... "group by absence"), not a bypass
of any computation: each merchant's own gross/fees/count/avg/max/min is still
computed in-language, by the invocation this script issues for that merchant.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[5]
LNPL = str(WORKTREE / ".venv" / "bin" / "lnpl")
HERE = Path(__file__).resolve().parent


def merchants(store: str):
    import sqlite3

    conn = sqlite3.connect(store)
    ids = [
        row[0]
        for row in conn.execute(
            "select row_key from lnpl_rows where entity_id='entity.merchant' order by row_key"
        )
    ]
    conn.close()
    return ids


def run_one(store: str, workflow: str, merchant: str, month_key: str, month_iso: str) -> dict:
    payload = {
        "id": f"settlement-{merchant}-{month_key}",
        "merchant": merchant,
        "month": month_iso,
        "status": "settled",
        "monthKey": month_key,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=str(WORKTREE / ".claude" / "tmp" / "s3")) as f:
        json.dump(payload, f)
        payload_path = f.name
    proc = subprocess.run(
        [
            LNPL, "run",
            str(HERE / "domain.lnpl"), str(HERE / "settlement.lnpl"),
            "--workflow", workflow,
            "--backend", f"sqlite:{store}",
            "--payload", payload_path,
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    Path(payload_path).unlink(missing_ok=True)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {"parse_error": True, "stdout": proc.stdout[-500:], "stderr": proc.stderr[-500:]}
    return {"merchant": merchant, "rc": proc.returncode, "result": result}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--month-key", default="2026-07")
    ap.add_argument("--month-iso", default="2026-07-01T00:00:00Z")
    ap.add_argument("--pass", dest="which_pass", choices=["first", "replace"], default="first")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    workflow = "wf.monthly.settlement" if args.which_pass == "first" else "wf.replace.settlement"
    outcomes = []
    for m in merchants(args.store):
        outcomes.append(run_one(args.store, workflow, m, args.month_key, args.month_iso))

    Path(args.out).write_text(json.dumps(outcomes, indent=2, sort_keys=True))
    ok = sum(1 for o in outcomes if o["rc"] == 0)
    failed = [o["merchant"] for o in outcomes if o["rc"] != 0]
    print(f"{args.which_pass}: {ok}/{len(outcomes)} completed, failed={failed}", file=sys.stderr)


if __name__ == "__main__":
    main()
