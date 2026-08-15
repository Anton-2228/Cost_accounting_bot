FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY telegram_bot ./telegram_bot

ENV PATH="/app/.venv/bin:$PATH"

# Порт notify-сервера, на который api толкает уведомления. Наружу он не
# публикуется: доступ только из docker-сети.
EXPOSE 8002

CMD ["python", "-m", "telegram_bot.main"]
