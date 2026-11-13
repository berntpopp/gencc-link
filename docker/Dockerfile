# syntax=docker/dockerfile:1
# Multi-stage Dockerfile for GenCC-Link.

FROM python:3.14-slim@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv" \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /home/app/web
COPY uv.lock pyproject.toml README.md ./

# Install uv from a digest-pinned image layer (reproducible, supply-chain
# anchored) instead of a floating pip-based installer bootstrap.
COPY --from=ghcr.io/astral-sh/uv:0.8.7@sha256:1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab /uv /usr/local/bin/uv

RUN uv sync --frozen --no-dev --active --no-install-project


FROM python:3.14-slim@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4 AS prepared


# Public release identity. Release automation supplies all three values from the
# validated source tag/commit and build record; defaults identify a local build.
ARG APP_VERSION=0.0.0
ARG VCS_REF=0000000000000000000000000000000000000000
ARG BUILD_DATE=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="GenCC-Link" \
      org.opencontainers.image.description="FastAPI and MCP server for GenCC gene-disease validity data" \
      org.opencontainers.image.source="https://github.com/berntpopp/gencc-link" \
      org.opencontainers.image.url="https://github.com/berntpopp/gencc-link" \
      org.opencontainers.image.documentation="https://github.com/berntpopp/gencc-link#readme" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="GeneFoundry" \
      org.genefoundry.research-use-only="true" \
      org.genefoundry.data-policy="code-only"
ENV VCS_REF="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    GENCC_LINK_HOST=0.0.0.0 \
    GENCC_LINK_PORT=8000 \
    GENCC_LINK_TRANSPORT=unified \
    GENCC_LINK_MCP_PATH=/mcp \
    GENCC_LINK_DATA__DATA_DIR=/data \
    # The gencc-data-init sidecar restores the pinned, digest-verified data
    # release into /data/<digest>/ and selects it via /data/current; the server
    # only reads it (see docs/data-lifecycle.md). No upstream download at boot.
    GENCC_LINK_DATA__DB_FILENAME=current/gencc.sqlite \
    GENCC_LINK_DATA__AUTO_BOOTSTRAP=false \
    GENCC_LINK_DATA__REFRESH_ENABLED=false \
    TMPDIR=/tmp

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --only-upgrade --no-install-recommends \
    openssl \
    libssl3t64 \
    openssl-provider-legacy \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app && \
    mkdir -p /tmp /data && \
    chown -R app:app /tmp /data /home/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /home/app/web

COPY --chown=app:app ./gencc_link ./gencc_link
COPY --chown=app:app ./server.py ./mcp_server.py ./pyproject.toml ./README.md ./
RUN /opt/venv/bin/pip install . --no-deps

RUN rm -rf /root/.cache/pip \
           /usr/local/lib/python*/ensurepip \
           /usr/local/lib/python*/site-packages/pip \
           /usr/local/lib/python*/site-packages/pip-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* \
           /opt/venv/lib/python*/site-packages/pip \
           /opt/venv/lib/python*/site-packages/pip-*.dist-info \
           /opt/venv/bin/pip /opt/venv/bin/pip3 /opt/venv/bin/pip3.* \
    && find / -xdev -type d -name __pycache__ -prune -exec rm -rf '{}' + \
    && find / -xdev -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
RUN find / -xdev -perm /6000 -exec chmod a-s '{}' + \
    && test -z "$(find / -xdev -perm /6000 -print -quit)"
RUN actual="$(find / -xdev -type f -links +1 -printf '%i %p\n' | sort -k2,2)" \
    && expected="$(printf '%s %s\n%s %s\n' \
         "$(stat -c '%i' /usr/bin/perl)" /usr/bin/perl \
         "$(stat -c '%i' /usr/bin/perl5.40.1)" /usr/bin/perl5.40.1 | sort -k2,2)" \
    && { test "$actual" = "$expected" || { printf 'unexpected hardlinks:\n%s\n' "$actual"; exit 1; }; } \
    && rm -f /usr/bin/perl5.40.1

FROM scratch AS production
COPY --from=prepared / /

ARG APP_VERSION=0.0.0
ARG VCS_REF=0000000000000000000000000000000000000000
ARG BUILD_DATE=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="GenCC-Link" \
      org.opencontainers.image.description="FastAPI and MCP server for GenCC gene-disease validity data" \
      org.opencontainers.image.source="https://github.com/berntpopp/gencc-link" \
      org.opencontainers.image.url="https://github.com/berntpopp/gencc-link" \
      org.opencontainers.image.documentation="https://github.com/berntpopp/gencc-link#readme" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="GeneFoundry" \
      org.genefoundry.research-use-only="true" \
      org.genefoundry.data-policy="code-only"
ENV VCS_REF="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    GENCC_LINK_HOST=0.0.0.0 \
    GENCC_LINK_PORT=8000 \
    GENCC_LINK_TRANSPORT=unified \
    GENCC_LINK_MCP_PATH=/mcp \
    GENCC_LINK_DATA__DATA_DIR=/data \
    # The gencc-data-init sidecar restores the pinned, digest-verified data
    # release into /data/<digest>/ and selects it via /data/current; the server
    # only reads it (see docs/data-lifecycle.md). No upstream download at boot.
    GENCC_LINK_DATA__DB_FILENAME=current/gencc.sqlite \
    GENCC_LINK_DATA__AUTO_BOOTSTRAP=false \
    GENCC_LINK_DATA__REFRESH_ENABLED=false \
    TMPDIR=/tmp
WORKDIR /home/app/web

USER app

EXPOSE 8000

# The restored data release lives under GENCC_LINK_DATA__DATA_DIR (/data),
# written by `gencc-link-data materialize-data` (init sidecar) and mounted
# read-only into the server.
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# Unified transport: FastAPI on / and MCP on /mcp via a single port.
CMD ["python", "server.py", "--transport", "unified", "--host", "0.0.0.0", "--port", "8000"]
