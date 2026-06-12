# syntax=docker/dockerfile:1
# Multi-stage Dockerfile for GenCC-Link.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv" \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /home/app/web
COPY uv.lock pyproject.toml README.md ./

RUN pip install --upgrade pip uv && \
    uv sync --frozen --no-dev --active --no-install-project


FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    GENCC_LINK_HOST=0.0.0.0 \
    GENCC_LINK_PORT=8000 \
    GENCC_LINK_TRANSPORT=unified \
    GENCC_LINK_MCP_PATH=/mcp \
    GENCC_LINK_DATA__DATA_DIR=/app/data \
    TMPDIR=/tmp/gencc-link

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app && \
    mkdir -p /tmp/gencc-link /app/data && \
    chown -R app:app /tmp/gencc-link /app/data /home/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /home/app/web

COPY --chown=app:app ./gencc_link ./gencc_link
COPY --chown=app:app ./server.py ./mcp_server.py ./pyproject.toml ./README.md ./

RUN /opt/venv/bin/pip install . --no-deps

USER app

EXPOSE 8000

# The built SQLite database lives under GENCC_LINK_DATA__DATA_DIR (/app/data).
# Mount a volume there so the ~24MB database persists across container restarts.
# With GENCC_LINK_DATA__AUTO_BOOTSTRAP=true (default) the server downloads the
# GenCC export and builds the database on first use if the volume is empty.
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# Unified transport: FastAPI on / and MCP on /mcp via a single port.
CMD ["python", "server.py", "--transport", "unified", "--host", "0.0.0.0", "--port", "8000"]
