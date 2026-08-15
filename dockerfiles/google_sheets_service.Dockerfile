FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY google_sheets_service ./google_sheets_service

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
# Без entrypoint: миграции сервис не применяет, своей базы у него нет.
# Строго один воркер — фоновый цикл живёт в процессе, и второй разбирал бы
# очередь параллельно, удваивая расход квоты Google без всякой пользы.
CMD ["uvicorn", "google_sheets_service.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1"]
