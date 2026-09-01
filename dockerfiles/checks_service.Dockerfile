FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY checks_service ./checks_service

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
# Без entrypoint: миграции сервис не применяет, своей базы у него нет.
# Воркеров может быть и несколько — состояния между запросами сервис не держит,
# — но одного хватает: вся работа это несколько HTTP-вызовов на чек (два у
# российского, три у сербского: страница на двух языках и запрос позиций).
CMD ["uvicorn", "checks_service.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1"]
