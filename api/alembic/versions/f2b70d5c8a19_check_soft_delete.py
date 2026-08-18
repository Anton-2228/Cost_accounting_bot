"""check soft delete follows its last record

Revision ID: f2b70d5c8a19
Revises: e5a1f83b2c47
Create Date: 2026-08-18 12:00:00.000000

Чек перестаёт быть вечным. До сих пор удаление всех операций, вышедших из чека,
оставляло его строку в БД навсегда: разобранный, он не возвращался в очередь
`/check`, занимал `external_key` — ту же бумажку нельзя было отсканировать
заново — и продолжал висеть строкой на листе-архиве месяца, хотя в реестре от
него ничего не осталось. Теперь чек умирает вслед за последней своей живой
операцией.

Удаление **мягкое**, как у операций: `deleted_at`, строка и `raw_payload`
остаются. Физическое стёрло бы единственный след покупки, а заодно порвало бы
ссылки: операции, вышедшие из чека, тоже удаляются мягко и продолжают на него
смотреть через `fk_records_check_id_checks`.

Отсюда частичная уникальность. `UNIQUE (spreadsheet_id, kind, external_key)`
становится уникальным индексом `WHERE deleted_at IS NULL`: живым может быть один
экземпляр бумажки, а сколько их было в истории документа — не ограничено. Без
этого мягкое удаление означало бы «чек исчез отовсюду, но пересканировать его
нельзя» — состояние хуже прежнего. Тип объекта поэтому меняется: констрейнт
частичным быть не умеет, индекс умеет. Имя сохранено — в PostgreSQL констрейнт и
так реализован индексом, и освободившееся имя занимает новый.

`ix_checks_unprocessed` пересоздаётся с `deleted_at IS NULL` в условии: очередь
разбора не должна показывать то, чего в документе больше нет.

`uq_checks_id_spreadsheet_id` не тронут: на него смотрит составной внешний ключ
`records → checks`, и частичным он быть не может в принципе.

Бэкфилла нет: осиротевшие чеки прежних запусков остаются живыми. Их немного, они
безвредны, а разбирать их значило бы угадывать задним числом, какое удаление
операции было последним.

Откат обратный, и он теряет данные, которых старая схема не умеет хранить.
Мягко удалённый чек в ней невыразим, поэтому такие строки удаляются физически, а
ссылавшиеся на них операции отвязываются (`check_id = NULL`) — иначе внешний ключ
не дал бы удалить ни одной. Сама операция при этом остаётся на месте: теряется
только связь с чеком, которого больше нет.

После этих двух операторов в откате стоит `SET CONSTRAINTS ALL IMMEDIATE`.
`fk_records_check_id_checks` отложенный, поэтому его проверки копятся до конца
транзакции, а PostgreSQL отказывается выполнять DDL на таблице с накопленными
событиями триггеров: `cannot CREATE INDEX "checks" because it has pending trigger
events`. Явная проверка разряжает очередь на месте, где ещё понятно, что именно
проверяется.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b70d5c8a19"
down_revision: str | None = "e5a1f83b2c47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIQUE_KEY = "uq_checks_spreadsheet_id_kind_external_key"
_KEY_COLUMNS = ["spreadsheet_id", "kind", "external_key"]


def upgrade() -> None:
    op.add_column("checks", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.drop_constraint(_UNIQUE_KEY, "checks", type_="unique")
    op.create_index(
        _UNIQUE_KEY,
        "checks",
        _KEY_COLUMNS,
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.drop_index("ix_checks_unprocessed", table_name="checks")
    op.create_index(
        "ix_checks_unprocessed",
        "checks",
        ["spreadsheet_id", "id"],
        unique=False,
        postgresql_where=sa.text("processed_at IS NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.execute(
        "UPDATE records SET check_id = NULL "
        "WHERE check_id IN (SELECT id FROM checks WHERE deleted_at IS NOT NULL)"
    )
    op.execute("DELETE FROM checks WHERE deleted_at IS NOT NULL")
    # Отложенный `fk_records_check_id_checks` копит проверки до конца
    # транзакции, а DDL на таблице с накопленными событиями PostgreSQL не
    # выполняет вовсе. Проверяем сейчас — ниже идут одни только индексы.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")

    op.drop_index("ix_checks_unprocessed", table_name="checks")
    op.create_index(
        "ix_checks_unprocessed",
        "checks",
        ["spreadsheet_id", "id"],
        unique=False,
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    op.drop_index(_UNIQUE_KEY, table_name="checks")
    op.create_unique_constraint(_UNIQUE_KEY, "checks", _KEY_COLUMNS)

    op.drop_column("checks", "deleted_at")
