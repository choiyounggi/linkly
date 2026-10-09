# docker/Dockerfile — official release image (issue #190). Runtime only: the
# lnpl runtime + gunicorn, no example source baked in. Operators mount their
# own .lnpl source and set LNPL_SOURCE (see docs/serving.md). Built and
# pushed by .github/workflows/release.yml's `image` job on every release
# tag. examples/deploy/Dockerfile is a separate, unrelated reference image
# (see its own header) that bakes in examples/linkhub.lnpl for a quick local
# experiment — this file supersedes nothing there.
#
# Build (from the repo root):
#   docker build -f docker/Dockerfile -t linkly:local .
# Run (mount a source, set LNPL_SOURCE):
#   docker run --rm -p 8000:8000 \
#     -v "$PWD/examples/linkhub.lnpl:/data/linkhub.lnpl:ro" \
#     -e LNPL_SOURCE=/data/linkhub.lnpl \
#     linkly:local

FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed AS builder
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY impl ./impl
COPY mlir ./mlir
COPY kb ./kb
RUN pip wheel --no-deps --wheel-dir /wheels .

FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed
WORKDIR /app
COPY --from=builder /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl gunicorn && rm -rf /tmp/*.whl
RUN useradd --system --no-create-home --uid 1000 linkly && chown linkly:linkly /app
ENV HOME=/app
USER linkly

EXPOSE 8000
ENTRYPOINT ["gunicorn", "lnpl.wsgi:build_app()", "--bind", "0.0.0.0:8000"]
