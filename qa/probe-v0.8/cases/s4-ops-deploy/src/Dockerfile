# s4-ops-deploy app image — derived from examples/deploy/Dockerfile (D16: CMD is
# `lnpl serve`, not gunicorn — docs/serving.md:448-453 scopes --metrics/readyz's
# live jwt-secret-env recheck to the `lnpl serve` path only).
#
# Build (from repo root, so the "repo" build-context can supply impl/):
#   docker build -f qa/probe-v0.8/cases/s4-ops-deploy/src/Dockerfile \
#     --build-context repo=. -t s4-linkhub-app qa/probe-v0.8/cases/s4-ops-deploy/src

FROM python:3.13-slim-bookworm AS builder
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY --from=repo pyproject.toml README.md LICENSE ./
COPY --from=repo impl ./impl
COPY --from=repo mlir ./mlir
COPY --from=repo kb ./kb
RUN pip wheel --no-deps --wheel-dir /wheels .
RUN pip wheel --wheel-dir /wheels \
    "git+https://github.com/choiyounggi/lnpl-postgres@main" \
    "git+https://github.com/choiyounggi/lnpl-redis@main" \
    "git+https://github.com/choiyounggi/lnpl-otel@main"

FROM python:3.13-slim-bookworm
WORKDIR /app
COPY --from=builder /wheels/*.whl /tmp/
# --no-deps: the driver wheels' own METADATA pins `lnpl` via a PEP 508 direct
# git+https URL (their own commit-SHA pin, docs: lnpl-{postgres,redis,otel}
# READMEs "Bumping the pinned lnpl commit") rather than a plain version
# spec — pip's resolver re-fetches that URL via git even when a same-version
# lnpl wheel is already sitting in /tmp, and this runtime stage has no git/
# network egress by design. The full dependency closure (psycopg/redis-py/
# otel SDK/etc.) is already present as separate wheels from the builder's
# `pip wheel` (which resolves it once, with git available) — --no-deps here
# just tells this install not to re-resolve, not to skip anything.
RUN pip install --no-cache-dir --no-deps /tmp/*.whl && rm -rf /tmp/*.whl
COPY linkhub.lnpl ./linkhub.lnpl
COPY lnpl.toml ./lnpl.toml

EXPOSE 8080
# --backend/--trace-exporter are explicit (container-network hostnames
# postgres/otel-collector, not localhost) rather than left to lnpl.toml's
# [prod].backend (which is written for host-side testing, D16 evidence/04).
# --config/--profile prod still applies for log_format (json).
CMD ["lnpl", "serve", "--host", "0.0.0.0", "--port", "8080", \
     "--config", "/app/lnpl.toml", "--profile", "prod", \
     "--backend", "postgres:postgresql://s4user:s4pw@postgres:5432/s4db", \
     "--cache", "redis:redis://redis:6379/0", \
     "--trace-exporter", "otlp", "--trust-incoming-trace", \
     "--rate-limit", "50", "--grace-period", "15", "--metrics", \
     "--jwt-secret-env", "LNPL_JWT_SECRET", "--jwt-issuer", "s4-issuer", \
     "/app/linkhub.lnpl"]
