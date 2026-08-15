#!/usr/bin/env bash
# Точка входа контейнера api: дождаться Postgres, применить миграции, стартовать.
set -euo pipefail

echo "Ожидание Postgres ${POSTGRES_HOST}:${POSTGRES_PORT}..."
python - <<'PY'
import os
import socket
import time

host = os.environ["POSTGRES_HOST"]
port = int(os.environ["POSTGRES_PORT"])
deadline = time.monotonic() + 60

while time.monotonic() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit(f"Postgres {host}:{port} не отвечает за 60 секунд")
PY
echo "Postgres доступен"

# Схема приводится к актуальной здесь и только здесь. Приложение никогда не
# вызывает create_all: прежняя версия делала это на каждом старте, из-за чего
# изменение модели молча не применялось к уже существующей таблице.
echo "Применение миграций..."
alembic upgrade head

echo "Запуск api"
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
