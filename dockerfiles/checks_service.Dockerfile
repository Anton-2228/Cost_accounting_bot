# Базовый образ с Docker Hub и uv из PyPI закреплённой версией — ghcr.io из
# сети прод-хоста недоступен. Почему именно так, подробно — в api.Dockerfile.
FROM python:3.12-slim-bookworm

RUN pip install --no-cache-dir uv==0.11.16

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
#
# ВНИМАНИЕ: воркер здесь ровно один ещё и потому, что у сервиса есть метрики, а
# они живут в памяти процесса. Второй воркер заведёт свои счётчики, скрейп будет
# попадать в случайный, и метрики молча поделятся — без ошибок и без единого
# признака в логах. Добавляешь воркеров — заводи PROMETHEUS_MULTIPROC_DIR и
# сборщик prometheus_client.multiprocess (см. checks_service/metrics.py).
CMD ["uvicorn", "checks_service.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1"]
