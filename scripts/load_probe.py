#!/usr/bin/env python3
"""Open-loop HTTP load generator for `lnpl serve` (issue #180). Stdlib only.

Open-loop means one request is fired every 1/rps seconds on its own thread,
whether or not earlier requests have come back. A closed-loop generator would
slow down with the server and hide exactly the queueing collapse this script
exists to show.

Every request becomes one CSV row `t_start,status,latency_ms,error`. After the
run it prints a summary (warm-up excluded) and one line per 10-second bucket:

    total=6000 post_warmup=5500 ok=5500 error_or_non2xx=0
    p50=1.02ms p95=2.48ms p99=6.78ms
    error_rate=0.00%
    bucket=0-10s mean=1.19ms max=10.86ms n=1000
    verdict=STABLE worst_bucket_ratio=1.024x

Buckets are counted from the end of the warm-up, so `0-10s` is the first ten
seconds that count. A bucket's mean and max use 2xx responses only; failed
requests show up in `error_rate` instead.

The last line is the verdict: STABLE when the error rate is 0 and every bucket
mean is at most 2 times the first bucket's mean (docs/postgres-load-ceiling.md),
UNSTABLE otherwise, NO-DATA when nothing counted after the warm-up. The verdict
never changes the exit code.

Exit codes: 0 the run finished (whatever the server answered), 2 invalid
arguments.
"""
import argparse
import csv
import http.client
import math
import threading
import time
import urllib.parse

REQUEST_TIMEOUT_S = 10
JOIN_TIMEOUT_S = 15


def positive_float(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("%r is not a number" % text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(
            "%r is not a positive finite number" % text)
    return value


def non_empty_url(text):
    if not text.strip():
        raise argparse.ArgumentTypeError("the URL is empty")
    return text


def percentile(sorted_vals, p):
    """Linear-interpolated percentile of an already sorted list; None if empty."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _is_ok(status):
    return isinstance(status, int) and 200 <= status < 300


def summarize(rows, warmup):
    """Counts, error rate (percent) and latency percentiles after the warm-up.

    Percentiles cover every post-warm-up request, failed ones included, so a
    request that timed out still shows up in the tail.
    """
    post_warmup = [r for r in rows if r[0] >= warmup]
    ok = sum(1 for r in post_warmup if _is_ok(r[1]))
    errors = len(post_warmup) - ok
    latencies = sorted(r[2] for r in post_warmup)
    return {
        "total": len(rows),
        "post_warmup": len(post_warmup),
        "ok": ok,
        "errors": errors,
        "error_rate": (errors / len(post_warmup) * 100) if post_warmup else None,
        "p50": percentile(latencies, 0.50),
        "p95": percentile(latencies, 0.95),
        "p99": percentile(latencies, 0.99),
    }


def bucket_table(rows, warmup, seconds, bucket_s=10):
    """Per-bucket `(bucket_start, mean_ms, max_ms, sample_count)` of 2xx rows.

    `bucket_start` is seconds since the end of the warm-up. Bucket 0 covers
    `[warmup, warmup + bucket_s)`; the last bucket may be shorter. A bucket
    with no 2xx sample is `(bucket_start, None, None, 0)`.
    """
    count = max(0, math.ceil((seconds - warmup) / bucket_s))
    samples = [[] for _ in range(count)]
    for t_start, status, latency_ms, _error in rows:
        if t_start < warmup or not _is_ok(status):
            continue
        index = int((t_start - warmup) // bucket_s)
        if index < count:
            samples[index].append(latency_ms)
    table = []
    for index, values in enumerate(samples):
        start = index * float(bucket_s)
        if values:
            table.append((start, sum(values) / len(values), max(values), len(values)))
        else:
            table.append((start, None, None, 0))
    return table


def format_bucket(bucket, bucket_s):
    start, mean_ms, max_ms, n = bucket
    label = "bucket=%d-%ds" % (start, start + bucket_s)
    if n == 0:
        return "%s mean=- max=- n=0" % label
    return "%s mean=%.2fms max=%.2fms n=%d" % (label, mean_ms, max_ms, n)


STABLE_RATIO = 2.0


def stability_verdict(summary, buckets):
    """`(verdict, worst_ratio)` for one run, by the rule in docs/postgres-load-ceiling.md.

    STABLE when the error rate is 0 and every 10-second bucket mean is at most
    STABLE_RATIO times the first bucket's mean. NO-DATA when nothing counted
    after the warm-up. A bucket with no 2xx sample makes the run UNSTABLE with
    no ratio, because flatness cannot be shown for it.
    """
    if not summary["post_warmup"] or not buckets:
        return "NO-DATA", None
    means = [bucket[1] for bucket in buckets]
    first = means[0]
    if first is None or first <= 0 or any(mean is None for mean in means):
        return "UNSTABLE", None
    worst = max(means) / first
    if summary["errors"] == 0 and worst <= STABLE_RATIO:
        return "STABLE", worst
    return "UNSTABLE", worst


def format_verdict(verdict, worst_ratio):
    ratio = "-" if worst_ratio is None else "%.3fx" % worst_ratio
    return "verdict=%s worst_bucket_ratio=%s" % (verdict, ratio)


def write_csv(rows, f):
    w = csv.writer(f)
    w.writerow(["t_start", "status", "latency_ms", "error"])
    w.writerows(rows)


def build_parser():
    ap = argparse.ArgumentParser(
        description="Open-loop HTTP load generator: fires --rps requests per "
                    "second for --seconds, writes one CSV row per request, and "
                    "prints p50/p95/p99, error rate and 10-second bucket means.")
    ap.add_argument("--url", required=True, type=non_empty_url)
    ap.add_argument("--rps", type=positive_float, default=100.0,
                    help="requests per second (default 100)")
    ap.add_argument("--seconds", type=positive_float, default=60.0,
                    help="how long to fire (default 60)")
    ap.add_argument("--warmup", type=positive_float, default=5.0,
                    help="leading seconds left out of the summary (default 5)")
    ap.add_argument("--method", default="GET")
    ap.add_argument("--body", default=None, help="request body, sent as JSON")
    ap.add_argument("--out", required=True, help="CSV file to write")
    return ap


def _fire(url, method, body, t_start, rows, lock):
    parsed = urllib.parse.urlsplit(url)
    status = None
    error = ""
    t0 = time.monotonic()
    try:
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port,
                                          timeout=REQUEST_TIMEOUT_S)
        try:
            headers = {"Content-Type": "application/json"} if body else {}
            conn.request(method, parsed.path or "/", body=body, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            resp.read()
        finally:
            conn.close()
    except Exception as exc:
        error = type(exc).__name__ + ":" + str(exc)
    latency_ms = (time.monotonic() - t0) * 1000
    with lock:
        rows.append((t_start, status, round(latency_ms, 3), error))


def run_load(url, rps, seconds, method, body):
    """Fire the load and return the rows, sorted by `t_start`."""
    interval = 1.0 / rps
    rows = []
    lock = threading.Lock()
    threads = []
    t_run_start = time.monotonic()
    next_fire = t_run_start
    end_at = t_run_start + seconds
    while True:
        now = time.monotonic()
        if now >= end_at:
            break
        th = threading.Thread(target=_fire, daemon=True,
                              args=(url, method, body, now - t_run_start, rows, lock))
        th.start()
        threads.append(th)
        next_fire += interval
        sleep_for = next_fire - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
    for th in threads:
        th.join(timeout=JOIN_TIMEOUT_S)
    with lock:
        return sorted(rows, key=lambda r: r[0])


def main(argv=None):
    args = build_parser().parse_args(argv)
    body = args.body.encode() if args.body else None
    rows = run_load(args.url, args.rps, args.seconds, args.method, body)

    with open(args.out, "w", newline="") as f:
        write_csv(rows, f)

    s = summarize(rows, args.warmup)
    print("total=%d post_warmup=%d ok=%d error_or_non2xx=%d"
          % (s["total"], s["post_warmup"], s["ok"], s["errors"]))
    if s["post_warmup"]:
        print("p50=%.2fms p95=%.2fms p99=%.2fms" % (s["p50"], s["p95"], s["p99"]))
        print("error_rate=%.2f%%" % s["error_rate"])
    buckets = bucket_table(rows, args.warmup, args.seconds)
    for bucket in buckets:
        print(format_bucket(bucket, 10))
    print(format_verdict(*stability_verdict(s, buckets)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
