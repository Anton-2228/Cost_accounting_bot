# Базовый образ берётся с Docker Hub, а не с ghcr.io/astral-sh/uv, и это
# вынужденно: из сети прод-хоста ghcr.io недоступен — провайдер режет и резолв
# имени, и само соединение, поэтому сборка падала на первом же шаге, при чтении
# метаданных образа. Docker Hub оттуда работает: с него и так приходят postgres,
# redis, prometheus и grafana.
#
# uv поэтому ставится отдельным шагом из PyPI и ЗАКРЕПЛЁННОЙ версией. Версия
# ровно та, которой собран uv.lock (формат 1, revision 3): `uv sync --frozen`
# ниже обязан прочитать lock как есть, не пересчитывая его. Меняешь версию —
# убедись, что lock всё ещё читается, иначе сборка встанет на несовпадении
# формата.
FROM python:3.12-slim-bookworm

RUN pip install --no-cache-dir uv==0.11.16

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
