-- Роль для Grafana: только чтение и только по перечисленным таблицам.
--
-- Запускается РУКАМИ и ПОСЛЕ миграций (см. README, раздел «Наблюдение»).
-- Хуком /docker-entrypoint-initdb.d он быть не может: хуки выполняются при
-- создании кластера, когда схемы ещё нет — её накатывает alembic из контейнера
-- api, то есть позже. GRANT на несуществующую таблицу — ошибка, а ошибка в
-- хуке роняет инициализацию базы целиком.
--
-- Скрипт идемпотентен: повторный запуск — штатный способ сменить пароль роли и
-- доспать права после миграции, добавившей таблицу в список ниже.
--
-- Миграцией alembic это быть не может по трём причинам. Миграция несла бы
-- пароль, а значит api получил бы в окружение чужой секрет. Роли живут на
-- уровне кластера, Base.metadata о них не знает, а тесты строят схему через
-- create_all и миграцию не выполнили бы никогда. И downgrade либо уронил бы
-- роль под живым подключением Grafana, либо солгал бы пустым телом.

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
        CREATE ROLE grafana_ro LOGIN;
    END IF;
END
$$;

-- Пароль задаётся отдельно от создания: при повторном запуске роль уже есть, и
-- CREATE ROLE не выполнится, а пароль обязан сойтись с env/grafana.env в любом
-- случае. Заодно это единственный способ его сменить — перезапустить скрипт.
ALTER ROLE grafana_ro WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    PASSWORD :'grafana_password';

GRANT CONNECT ON DATABASE :"DBNAME" TO grafana_ro;
GRANT USAGE   ON SCHEMA public      TO grafana_ro;

-- Таблицы перечислены поимённо, а не ALL TABLES, и ALTER DEFAULT PRIVILEGES
-- сознательно не выдаётся. Следующая таблица — llm_usages с расходами на
-- модель, user_notifications, spreadsheet_accesses — не должна становиться
-- видимой Grafana сама собой, молча, в момент применения миграции. Понадобится
-- новая — её добавят сюда осознанно.
GRANT SELECT ON TABLE
    public.users,
    public.spreadsheets,
    public.checks,
    public.records
TO grafana_ro;

-- Запись невыразима. REVOKE избыточен для роли, которой ничего и не выдавали, и
-- стоит здесь на случай, если когда-то выдали: скрипт приводит права к
-- описанному состоянию, а не дополняет их.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA public FROM grafana_ro;
REVOKE CREATE ON SCHEMA public FROM grafana_ro;
