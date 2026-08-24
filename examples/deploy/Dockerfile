# Reference Dockerfile — linkly WSGI production boot (issue #87, consumes #80's
# lnpl.wsgi:build_app()). Not part of the project's own CI/release image; this
# is a documented starting point for operators who want to run a compiled
# .lnpl service under a real WSGI host instead of the `lnpl serve` dev server.
#
# Build (from the repo root, so the "repo" context can supply impl/ + examples/):
#   docker build -f examples/deploy/Dockerfile --build-context repo=. \
#     -t linkly-deploy-smoke examples/deploy
#
# Run:
#   docker run --rm -p 8000:8000 linkly-deploy-smoke
#
# See docs/serving.md "운영 배치" for the env-var contract this image sets
# (LNPL_SOURCE/LNPL_BACKEND/LNPL_JWT_SECRET_ENV/LNPL_CLOCK) and docs/RELEASING.md
# for how this fits the release procedure.

# --- builder: produce the lnpl wheel (data files included — verified #60) ---
FROM python:3.13-slim-bookworm AS builder
WORKDIR /src
COPY --from=repo pyproject.toml README.md LICENSE ./
COPY --from=repo impl ./impl
COPY --from=repo mlir ./mlir
COPY --from=repo kb ./kb
RUN pip wheel --no-deps --wheel-dir /wheels .

# --- runtime: install the wheel + gunicorn (not a project dependency; this
# image is the only place it is installed, per docs/serving.md) ---
FROM python:3.13-slim-bookworm
WORKDIR /app
COPY --from=builder /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl gunicorn && rm -rf /tmp/*.whl
COPY --from=repo examples/linkhub.lnpl ./examples/linkhub.lnpl

ENV LNPL_SOURCE=/app/examples/linkhub.lnpl \
    LNPL_BACKEND=fake \
    LNPL_CLOCK=virtual

EXPOSE 8000
CMD ["gunicorn", "lnpl.wsgi:build_app()", "--bind", "0.0.0.0:8000"]
