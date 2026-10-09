#!/usr/bin/env bash
# Issue #195 go/no-go pre-check, run inside the t195-load container from /work.
# Usage: bash benchmarks/load/i195/precheck_linux.sh <rate> <out-dir>
# Fake backend, gunicorn gthread 4 workers x 4 threads. Two 55 s runs at <rate>; PASS when
# both end in verdict=STABLE and the longest request of both is under 1000 ms.
# Exit 0 PASS, 1 FAIL, 3 harness fault.
set -u
RATE=${1:?usage: precheck_linux.sh <rate> <out-dir>}
OUT=${2:?usage: precheck_linux.sh <rate> <out-dir>}
ROOT=$(pwd)
PY="$ROOT/venv/bin/python"
GUNICORN="$ROOT/venv/bin/gunicorn"
BODY='{"id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","url":"https://example.com/postgres-load-probe","title":"postgres load probe fixture","owner":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","savedAt":"2026-01-01T00:00:00Z","visits":0}'
PORT=18195
LOG="$OUT/precheck-$RATE.log"
mkdir -p "$OUT" "$ROOT/tmp"
: > "$LOG"

LNPL_SOURCE="$ROOT/examples/linkhub.lnpl" LNPL_BACKEND=fake "$GUNICORN" "lnpl.wsgi:build_app()" \
  --bind "127.0.0.1:$PORT" --workers 4 --worker-class gthread --threads 4 \
  --no-control-socket > "$OUT/precheck-$RATE.server.log" 2>&1 &
PID=$!
ready=no
for _ in $(seq 1 100); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/-/healthz"; then ready=yes; break; fi
  sleep 0.1
done
if [ "$ready" = no ]; then echo "harness fault: server did not boot" >> "$LOG"; kill -TERM "$PID"; wait "$PID"; exit 3; fi
curl -s -o /dev/null -X POST "http://127.0.0.1:$PORT/link-hub-service/save-bookmark" \
  -H 'Content-Type: application/json' -d "$BODY"
g=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/link-hub-service/get-bookmark" \
  -H 'Content-Type: application/json' -d "$BODY")
echo "seed get=$g load=$(cut -d' ' -f1-3 /proc/loadavg)" >> "$LOG"
if [ "$g" != 200 ]; then echo "harness fault: seed" >> "$LOG"; kill -TERM "$PID"; wait "$PID"; exit 3; fi

pass=yes
for run in 1 2; do
  echo "precheck run=$run rate=$RATE seconds=55 warmup=5 started=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
  start=$(wc -l < "$LOG")
  "$PY" scripts/load_probe.py --url "http://127.0.0.1:$PORT/link-hub-service/get-bookmark" \
    --rps "$RATE" --seconds 55 --warmup 5 --method POST --body "$BODY" \
    --out "$ROOT/tmp/precheck.csv" >> "$LOG" 2>&1
  tail -n +"$((start + 1))" "$LOG" > "$ROOT/tmp/precheck-run.txt"
  tail -n 1 "$ROOT/tmp/precheck-run.txt" | grep -q '^verdict=STABLE ' || pass=no
  longest=$(grep -o 'max=[0-9.]*ms' "$ROOT/tmp/precheck-run.txt" | sed 's/max=//; s/ms//' | sort -n | tail -n 1)
  echo "precheck run=$run longest_request_ms=${longest:-none}" >> "$LOG"
  awk -v m="${longest:-1e9}" 'BEGIN { exit !(m < 1000) }' || pass=no
  sleep 5
done
kill -TERM "$PID"; wait "$PID"
if [ "$pass" = yes ]; then echo "PRECHECK rate=$RATE PASS" >> "$LOG"; exit 0; fi
echo "PRECHECK rate=$RATE FAIL" >> "$LOG"; exit 1
