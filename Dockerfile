FROM python:3.12-slim AS base

LABEL maintainer="OSOP Contributors <hello@osop.ai>"
LABEL org.opencontainers.image.source="https://github.com/osop/osop-mcp"
LABEL org.opencontainers.image.description="OSOP MCP Server"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system --gid 1001 osop && \
    adduser --system --uid 1001 --ingroup osop osop

COPY pyproject.toml README.md ./
COPY server/ ./server/
COPY tools/ ./tools/
COPY tools.json ./
COPY __main__.py ./

RUN pip install --no-cache-dir .

USER osop

ENTRYPOINT ["python", "__main__.py"]
