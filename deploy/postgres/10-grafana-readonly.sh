#!/bin/sh
# Заводит роль grafana_ro. Штатно запускается сам — одноразовым сервисом
# `grafana-db-init` из docker-compose.yml, который ждёт, пока api накатит
# миграции. Тот же файл можно запустить и руками, из контейнера базы:
#
#   docker compose exec db sh /opt/sql/10-grafana-readonly.sh
#
# Хуком initdb он быть не может: тот выполняется при создании кластера, когда
# таблиц ещё нет, и GRANT на них уронил бы инициализацию базы целиком. Отсюда и
# зависимость от api: права выдаются на конкретные таблицы, а создаёт их
# alembic.
#
# Пароль берётся из окружения (env/postgres.env), а не из аргументов: в
# аргументах он был бы виден в `ps` любому, кто заглянет в контейнер.
set -eu

if [ -z "${GRAFANA_DB_PASSWORD:-}" ]; then
    echo "GRAFANA_DB_PASSWORD не задан в env/postgres.env" >&2
    echo "Без пароля роль осталась бы с пустым — Grafana подключилась бы, и не она одна." >&2
    exit 1
fi

# Внутри контейнера базы psql ходит локальным сокетом и пароля не спрашивает. Из
# отдельного контейнера (сервис grafana-db-init) нужны адрес и пароль владельца
# базы — PGHOST задаёт compose, пароль лежит в том же env-файле.
if [ -n "${PGHOST:-}" ]; then
    PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
    export PGPASSWORD
fi

psql -v ON_ERROR_STOP=1 \
     -v grafana_password="$GRAFANA_DB_PASSWORD" \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -f /opt/sql/grafana_readonly.sql

echo "Роль grafana_ro готова: SELECT по users, spreadsheets, checks, records."
