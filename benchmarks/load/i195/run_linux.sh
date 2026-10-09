#!/usr/bin/env bash
# Issue #195 Linux-container load session (ruling 4). Run from the repository root of the t195 worktree.
# Images used: python:3.13-slim-bookworm (+ curl, procps -> local image t195-load) and postgres:16.
# Usage: bash benchmarks/load/i195/run_linux.sh up | precheck <rate> | session <ladder> <control-rate> <refine-rates> | down
#   up        network t195-net, postgres t195-pg, image t195-load, container t195-load (worktree at /src,
#             lnpl-postgres at /lnpl-postgres, both read-only; benchmarks/load/i195/linux at /out), venv + installs
#   precheck  benchmarks/load/i195/precheck_linux.sh <rate> /out/precheck inside t195-load
#   session   benchmarks/load/i195/run_matrix.sh /out /work/tmp inside t195-load, with T195_ values set
#   down      remove t195-load, t195-pg, t195-net, their anonymous volumes and the t195-load image (by exact name)
# The postgres container publishes no host port; the DSN host is t195-pg:5432.
set -u
ROOT=$(pwd)
PGSRC=${T195_PGSRC:-/Users/choeyeong-gi/Desktop/workspace/lnpl-postgres}
LINUX_OUT="$ROOT/benchmarks/load/i195/linux"
DSN="postgresql://t195:t195pw@t195-pg:5432/t195db"

in_box() { docker exec -w /work t195-load "$@"; }

case "${1:-}" in
  up)
    mkdir -p "$LINUX_OUT"
    docker network create t195-net > /dev/null || exit 3
    docker run -d --name t195-pg --network t195-net -e POSTGRES_USER=t195 -e POSTGRES_PASSWORD=t195pw \
      -e POSTGRES_DB=t195db postgres:16 > /dev/null || exit 3
    # curl and procps on top of python:3.13-slim-bookworm; the only image built
    ctx=$(mktemp -d "$ROOT/.claude/tmp/t195-img.XXXXXX") || exit 3
    printf 'FROM python:3.13-slim-bookworm\nRUN apt-get update -qq && apt-get install -y -qq --no-install-recommends curl procps ca-certificates && rm -rf /var/lib/apt/lists/*\n' > "$ctx/Dockerfile"
    docker build -q -t t195-load "$ctx" > /dev/null || exit 3
    rm -r "$ctx"
    docker run -d --name t195-load --network t195-net \
      -v "$ROOT:/src:ro" -v "$PGSRC:/lnpl-postgres:ro" -v "$LINUX_OUT:/out" \
      t195-load sleep infinity > /dev/null || exit 3
    docker exec t195-load sh -c '
      set -e
      mkdir -p /work /work-pg
      cd /src && tar --exclude=./.git --exclude=./.venv --exclude=./.claude --exclude=./.worktrees \
        --exclude=./.orchestration --exclude=./benchmarks/load -cf - . | tar -xf - -C /work
      mkdir -p /work/benchmarks/load/i195 /work/tmp
      cp /src/benchmarks/load/i195/*.sh /work/benchmarks/load/i195/
      cd /lnpl-postgres && tar --exclude=./.git --exclude=./build --exclude=./graphify-out -cf - . | tar -xf - -C /work-pg
      python -m venv /work/venv
      /work/venv/bin/pip install -q /work gunicorn==26.2.0 "psycopg[binary]==3.3.6"
      /work/venv/bin/pip install -q --no-deps /work-pg
    ' || exit 3
    for _ in $(seq 1 60); do
      docker exec t195-pg pg_isready -U t195 -d t195db -h 127.0.0.1 > /dev/null 2>&1 && break
      sleep 1
    done
    docker exec t195-pg pg_isready -U t195 -d t195db -h 127.0.0.1 || exit 3
    in_box /work/venv/bin/gunicorn --version
    ;;
  precheck)
    in_box bash benchmarks/load/i195/precheck_linux.sh "${2:?rate}" /out/precheck
    ;;
  session)
    pgc=$(git -C "$PGSRC" rev-parse --short HEAD)
    dockerline="$(docker info --format 'Docker Desktop {{.ServerVersion}}, VM cpus={{.NCPU}} mem={{.MemTotal}} bytes, kernel {{.KernelVersion}}')"
    docker exec -w /work \
      -e T195_VENV=/work/venv -e T195_DSN="$DSN" -e T195_LADDER="${2:?ladder}" -e T195_CTRL_RATE="${3:?control rate}" \
      -e T195_REFINE_RATES="${4:?refine rates}" -e T195_LNPL_COMMIT="$(git rev-parse HEAD)" -e T195_PG_COMMIT="$pgc" \
      -e T195_HOST_UPTIME="$(uptime)" -e T195_HOST_DOCKER="$dockerline" \
      t195-load bash benchmarks/load/i195/run_matrix.sh /out /work/tmp
    rc=$?
    echo "host uptime at end: $(uptime)" >> "$LINUX_OUT/session.log"
    exit "$rc"
    ;;
  down)
    docker rm -f -v t195-load t195-pg > /dev/null 2>&1
    docker network rm t195-net > /dev/null 2>&1
    docker rmi t195-load > /dev/null 2>&1
    ;;
  *)
    echo "usage: run_linux.sh up | precheck <rate> | session <ladder> <control-rate> <refine-rates> | down" >&2
    exit 2
    ;;
esac
