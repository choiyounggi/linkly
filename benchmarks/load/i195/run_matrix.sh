#!/usr/bin/env bash
# Issue #195 load session runner. Run from the repository root of a worktree whose
# .venv has lnpl, gunicorn==26.2.0, psycopg[binary]==3.3.6 and lnpl-postgres (14b113e).
# The session that was made ran inside the t195-load Linux container, driven by
# benchmarks/load/i195/run_linux.sh, which passes T195_DSN (host t195-pg:5432),
# T195_LADDER "50 100 200 400", T195_CTRL_RATE 400 and T195_REFINE_RATES
# "100 110 120 130 140 150" through env; the defaults below are the macOS-host
# rehearsal values (postgres on localhost:15495) and are NOT what was run
# (docs/gunicorn-load-measurement.md, "Reproduction").
#
# Usage: bash benchmarks/load/i195/run_matrix.sh <out-dir> <scratch-dir>
# Order: session control, refinement control, lnpl serve + postgres at the refine rates (100-150 rps in the container run),
# 18 gunicorn cells, per-worker state check, session control.
# Exit: 0 done, 3 harness fault (a server did not boot or the seed failed),
#       4 a session control was not STABLE (session INVALID),
#       5 the refinement control was not STABLE (refinement INVALID).
# T195_VENV, T195_DSN, T195_LADDER, T195_CTRL_RATE, T195_REFINE_RATES, T195_POINT_S and T195_REFINE_S override the venv and
# the measurement constants for a rehearsal only; session.log records the
# values actually used.
set -u

OUT=${1:?usage: run_matrix.sh <out-dir> <scratch-dir>}
TMPD=${2:?usage: run_matrix.sh <out-dir> <scratch-dir>}
ROOT=$(pwd)
VENV=${T195_VENV:-$ROOT/.venv}
PY="$VENV/bin/python"
GUNICORN="$VENV/bin/gunicorn"
LNPL="$VENV/bin/lnpl"
SRC="$ROOT/examples/linkhub.lnpl"
DSN=${T195_DSN:-postgresql://t195:t195pw@localhost:15495/t195db}
BODY='{"id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","url":"https://example.com/postgres-load-probe","title":"postgres load probe fixture","owner":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","savedAt":"2026-01-01T00:00:00Z","visits":0}'
PORT=18195
LADDER=${T195_LADDER:-50 100 200}
CTRL_RATE=${T195_CTRL_RATE:-200}
REFINE_RATES=${T195_REFINE_RATES:-110 120 130 140}
POINT_S=${T195_POINT_S:-55}
REFINE_S=${T195_REFINE_S:-90}
WARMUP=5
SESSION="$OUT/session.log"
PID=""

mkdir -p "$OUT" "$TMPD"

utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

wait_ready() { # <port>
  local i
  for i in $(seq 1 100); do
    if curl -s -o /dev/null "http://127.0.0.1:$1/-/healthz"; then return 0; fi
    sleep 0.1
  done
  echo "wait_ready gave up after $i polls" >&2
  return 1
}

stop_server() {
  kill -TERM "$PID" 2>/dev/null
  wait "$PID"
  PID=""
}

seed() { # <port> <log>: save once (200 or 409), then get-bookmark must answer 200
  local base="http://127.0.0.1:$1/link-hub-service" s g
  s=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$base/save-bookmark" \
    -H 'Content-Type: application/json' -d "$BODY")
  g=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$base/get-bookmark" \
    -H 'Content-Type: application/json' -d "$BODY")
  echo "seed save=$s get=$g" >> "$2"
  [ "$g" = 200 ] && { [ "$s" = 200 ] || [ "$s" = 409 ]; }
}

probe() { # <log> <port> <rate> <seconds> <header>; 0 when the verdict line is STABLE
  echo "$5 started=$(utc)" >> "$1"
  "$PY" scripts/load_probe.py --url "http://127.0.0.1:$2/link-hub-service/get-bookmark" \
    --rps "$3" --seconds "$4" --warmup "$WARMUP" --method POST --body "$BODY" \
    --out "$TMPD/last.csv" >> "$1" 2>&1
  tail -n 1 "$1" | grep -q '^verdict=STABLE '
}

start_gunicorn() { # <backend spec> <workers> <class> <threads> <server log>
  LNPL_SOURCE="$SRC" LNPL_BACKEND="$1" "$GUNICORN" "lnpl.wsgi:build_app()" \
    --bind "127.0.0.1:$PORT" --workers "$2" --worker-class "$3" --threads "$4" \
    --no-control-socket >> "$5" 2>&1 &
  PID=$!
}

boot_and_seed() { # <port> <log>
  if ! wait_ready "$1"; then
    echo "harness fault: server did not boot" >> "$2"; stop_server; exit 3
  fi
  if ! seed "$1" "$2"; then
    echo "harness fault: seed or probe failed" >> "$2"; stop_server; exit 3
  fi
}

session_control() { # <label>
  echo "uptime $(uptime)" >> "$SESSION"
  start_gunicorn fake 4 gthread 4 "$OUT/control-$1.server.log"
  boot_and_seed "$PORT" "$SESSION"
  if ! probe "$SESSION" "$PORT" "$CTRL_RATE" "$POINT_S" \
      "control $1 backend=fake workers=4 class=gthread threads=4 rate=$CTRL_RATE seconds=$POINT_S warmup=$WARMUP"; then
    stop_server; echo "SESSION INVALID: control $1 not STABLE" >> "$SESSION"; exit 4
  fi
  stop_server
}

refinement() {
  local log="$OUT/serve-fake-control.log" rate port=18181
  echo "uptime $(uptime)" >> "$SESSION"
  : > "$log"
  "$LNPL" serve --host 127.0.0.1 --port "$port" --cache fake "$SRC" \
    > "$OUT/serve-fake-control.server.log" 2>&1 &
  PID=$!
  boot_and_seed "$port" "$log"
  if ! probe "$log" "$port" 140 "$REFINE_S" \
      "control refinement backend=fake server=lnpl-serve rate=140 seconds=$REFINE_S warmup=$WARMUP"; then
    stop_server; echo "REFINEMENT INVALID: control not STABLE" >> "$SESSION"; exit 5
  fi
  stop_server
  for rate in $REFINE_RATES; do
    port=$((port + 1))
    log="$OUT/serve-postgres-$rate.log"
    : > "$log"
    "$LNPL" serve --host 127.0.0.1 --port "$port" --cache fake --backend "postgres:$DSN" "$SRC" \
      > "$OUT/serve-postgres-$rate.server.log" 2>&1 &
    PID=$!
    boot_and_seed "$port" "$log"
    probe "$log" "$port" "$rate" "$REFINE_S" \
      "point backend=postgres server=lnpl-serve rate=$rate seconds=$REFINE_S warmup=$WARMUP" || true
    stop_server
  done
}

cell() { # <name> <backend spec> <workers> <class>
  local threads=1 rate log slog
  [ "$4" = gthread ] && threads=4
  log="$OUT/gunicorn-$1-w$3-$4.log"
  slog="$OUT/gunicorn-$1-w$3-$4.server.log"
  : > "$log"; : > "$slog"
  start_gunicorn "$2" "$3" "$4" "$threads" "$slog"
  boot_and_seed "$PORT" "$log"
  for rate in $LADDER; do
    if ! probe "$log" "$PORT" "$rate" "$POINT_S" \
        "point backend=$1 workers=$3 class=$4 threads=$threads rate=$rate seconds=$POINT_S warmup=$WARMUP"; then
      break
    fi
    sleep 2
  done
  stop_server
}

per_worker_state() {
  local log="$OUT/per-worker-state.log" slog="$OUT/per-worker-state.server.log" n
  : > "$log"; : > "$slog"
  echo "metrics: gunicorn fake workers=2 class=sync LNPL_METRICS=1, seed, 100 get-bookmark requests, 10 scrapes of /-/metrics" >> "$log"
  LNPL_METRICS=1 LNPL_SOURCE="$SRC" LNPL_BACKEND=fake "$GUNICORN" "lnpl.wsgi:build_app()" \
    --bind "127.0.0.1:$PORT" --workers 2 --worker-class sync --no-control-socket >> "$slog" 2>&1 &
  PID=$!
  boot_and_seed "$PORT" "$log"
  for n in $(seq 1 100); do
    curl -s -o /dev/null -X POST "http://127.0.0.1:$PORT/link-hub-service/get-bookmark" \
      -H 'Content-Type: application/json' -d "$BODY"
  done
  echo "requests sent after the seed: $n" >> "$log"
  for n in $(seq 1 10); do
    echo "scrape $n: $(curl -s "http://127.0.0.1:$PORT/-/metrics" | grep '^lnpl_workflow_runs_total' | tr '\n' ' ')" >> "$log"
  done
  stop_server
  echo "rate limit: gunicorn fake workers=2 class=sync LNPL_RATE_LIMIT=20, load_probe 100 rps for 10 s" >> "$log"
  LNPL_RATE_LIMIT=20 LNPL_SOURCE="$SRC" LNPL_BACKEND=fake "$GUNICORN" "lnpl.wsgi:build_app()" \
    --bind "127.0.0.1:$PORT" --workers 2 --worker-class sync --no-control-socket >> "$slog" 2>&1 &
  PID=$!
  if ! wait_ready "$PORT"; then echo "harness fault: server did not boot" >> "$log"; stop_server; exit 3; fi
  {
    "$PY" scripts/load_probe.py --url "http://127.0.0.1:$PORT/link-hub-service/get-bookmark" \
      --rps 100 --seconds 10 --warmup 0.001 --method POST --body "$BODY" --out "$TMPD/rl.csv" 2>&1
    echo "status histogram (count status):"
    awk -F, 'NR > 1 {print $2}' "$TMPD/rl.csv" | sort | uniq -c
  } >> "$log"
  stop_server
}

{
  echo "session start $(utc)"
  if [ "$(uname)" = Linux ]; then
    echo "environment: Docker Linux container (T195_ prefixed values come from benchmarks/load/i195/run_linux.sh)"
    echo "host uptime at start: ${T195_HOST_UPTIME:-unknown}"
    echo "host docker: ${T195_HOST_DOCKER:-unknown}"
    echo "nproc $(nproc)"
    grep '^MemTotal' /proc/meminfo
    echo "uname -r $(uname -r)"
    grep '^PRETTY_NAME' /etc/os-release
    for k in net.core.somaxconn net.ipv4.ip_local_port_range net.ipv4.tcp_fin_timeout; do
      echo "$k = $(cat "/proc/sys/$(echo "$k" | tr . /)")"
    done
    echo "postgres $("$PY" -c "import psycopg; c = psycopg.connect('$DSN'); print(c.execute('select version()').fetchone()[0])")"
  else
    sw_vers
    sysctl hw.ncpu hw.memsize kern.ipc.somaxconn kern.num_taskthreads net.inet.ip.portrange.first net.inet.ip.portrange.last
    echo "docker server $(docker version --format '{{.Server.Version}}')"
    echo "postgres $(docker exec t195-pg psql -U t195 -d t195db -t -c 'select version();' | head -n 1)"
  fi
  "$PY" --version
  "$GUNICORN" --version
  "$PY" -m pip show psycopg lnpl-postgres | grep -E '^(Name|Version):'
  echo "lnpl commit ${T195_LNPL_COMMIT:-$(git rev-parse HEAD)}"
  echo "lnpl-postgres commit ${T195_PG_COMMIT:-$(git -C /Users/choeyeong-gi/Desktop/workspace/lnpl-postgres rev-parse --short HEAD)}"
  echo "gunicorn defaults kept: --timeout 30 --backlog 2048 (kernel cap: somaxconn above)"
  echo "ladder=$LADDER point_seconds=$POINT_S refine_seconds=$REFINE_S warmup=$WARMUP repetitions=1"
  echo "control_rate=$CTRL_RATE refine_rates=$REFINE_RATES"
} > "$SESSION" 2>&1

session_control start
refinement
"$PY" -c "from lnpl.drivers import open_repository; open_repository('postgres:$DSN').close(); print('postgres tables ready')" >> "$SESSION" 2>&1
for backend in fake sqlite postgres; do
  case $backend in
    fake) spec=fake ;;
    sqlite) spec="sqlite:$TMPD/i195.db" ;;
    postgres) spec="postgres:$DSN" ;;
  esac
  for workers in 1 2 4; do
    for class in sync gthread; do
      echo "uptime $(uptime)" >> "$SESSION"
      cell "$backend" "$spec" "$workers" "$class"
    done
  done
done
per_worker_state
session_control end
echo "session end $(utc)" >> "$SESSION"
