FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY api ./api
COPY alembic.ini ./
COPY scripts ./scripts
RUN chmod +x scripts/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
ENTRYPOINT ["scripts/entrypoint.sh"]
