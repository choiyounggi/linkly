#!/usr/bin/env python3
"""R7 perf: 3 reps at each of 1k/10k, one 100k attempt with a 600s timeout.

No pushdown on/off CLI switch exists in lnpl 0.8.0 (`lnpl run --help` has no
such flag; docs/backends.md §8's `supports_predicate` is a driver-class
constant, not a runtime toggle) -- recorded as "switch absent" per the round-1
review's instruction, not silently skipped.
"""
import statistics
import subprocess
import sys
import time
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[5]
LNPL = str(WORKTREE / ".venv" / "bin" / "lnpl")
HERE = Path(__file__).resolve().parent
TMP = WORKTREE / ".claude" / "tmp" / "s3"


def run_once(store: str, payload_path: str, timeout=None):
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            [
                LNPL, "run",
                str(HERE / "domain.lnpl"), str(HERE / "settlement.lnpl"),
                "--workflow", "wf.monthly.settlement",
                "--backend", f"sqlite:{store}",
                "--payload", payload_path,
            ],
            capture_output=True, text=True, timeout=timeout,
        )
        elapsed = time.perf_counter() - start
        return elapsed, proc.returncode
    except subprocess.TimeoutExpired:
        return None, "timeout"


def bench_size(n: int, reps: int = 3):
    store = str(TMP / f"bench_{n}.db")
    Path(store).unlink(missing_ok=True)
    subprocess.run([str(WORKTREE / ".venv" / "bin" / "python3"), str(HERE / "seed.py"), "--size", str(n), "--store", store], check=True, capture_output=True)
    payload_path = str(TMP / f"bench_{n}_payload.json")
    Path(payload_path).write_text(
        '{"id": "bench-%d", "merchant": "M01", "month": "2026-07-01T00:00:00Z", "status": "settled", "monthKey": "2026-07"}' % n
    )
    times = []
    for i in range(reps):
        # each rep needs a fresh row key (create fails on conflict) -- vary id
        Path(payload_path).write_text(
            '{"id": "bench-%d-%d", "merchant": "M01", "month": "2026-07-01T00:00:00Z", "status": "settled", "monthKey": "2026-07"}' % (n, i)
        )
        elapsed, rc = run_once(store, payload_path)
        print(f"  size={n} rep={i} real={elapsed:.4f}s rc={rc}", file=sys.stderr)
        times.append(elapsed)
    return times


def bench_100k(timeout_s: int = 600):
    n = 100000
    store = str(TMP / f"bench_{n}.db")
    Path(store).unlink(missing_ok=True)
    print(f"seeding {n} rows...", file=sys.stderr)
    t0 = time.perf_counter()
    subprocess.run([str(WORKTREE / ".venv" / "bin" / "python3"), str(HERE / "seed.py"), "--size", str(n), "--store", store], check=True, capture_output=True)
    seed_elapsed = time.perf_counter() - t0
    payload_path = str(TMP / f"bench_{n}_payload.json")
    Path(payload_path).write_text(
        '{"id": "bench-100k-1", "merchant": "M01", "month": "2026-07-01T00:00:00Z", "status": "settled", "monthKey": "2026-07"}'
    )
    elapsed, rc = run_once(store, payload_path, timeout=timeout_s)
    return seed_elapsed, elapsed, rc


def main():
    print("=== 1k ===", file=sys.stderr)
    t1k = bench_size(1000)
    print("=== 10k ===", file=sys.stderr)
    t10k = bench_size(10000)
    print("=== 100k (single attempt, 600s cap) ===", file=sys.stderr)
    seed_100k, elapsed_100k, rc_100k = bench_100k()

    print(f"1k  raw={[f'{t:.4f}' for t in t1k]} median={statistics.median(t1k):.4f}")
    print(f"10k raw={[f'{t:.4f}' for t in t10k]} median={statistics.median(t10k):.4f}")
    ratio = statistics.median(t10k) / statistics.median(t1k) if statistics.median(t1k) > 0 else float("inf")
    print(f"10k/1k median ratio: {ratio:.2f} (linear would be ~10 if dominated by table scan; <<10 implies pushdown/index, not a full scan)")
    print(f"100k seed_time={seed_100k:.2f}s run={'timeout' if elapsed_100k is None else f'{elapsed_100k:.4f}s'} rc={rc_100k}")
    print("pushdown on/off/misspelled-control: switch absent -- no CLI flag or driver-level toggle exists in lnpl 0.8.0 (checked `lnpl run --help`, docs/backends.md §3/§8: `supports_predicate` is a driver-class constant, not a runtime option)")


if __name__ == "__main__":
    main()
