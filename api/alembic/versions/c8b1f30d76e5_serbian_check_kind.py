"""serbian fiscal check kind

Revision ID: c8b1f30d76e5
Revises: a9d4e07c3b16
Create Date: 2026-09-01 12:00:00.000000

Второй формат чека: `check_kind.SRB_SUF` — сербский фискальный чек ПУРС.

Таблицу `checks` это не меняет вовсе, и в этом весь смысл её устройства: она
хранит сырьё и вид, а интерпретация отложена на разбор. Новый формат добавляет
метку в перечисление — и всё.

`ADD VALUE` выполняется в `autocommit_block`. PostgreSQL запрещает
**использовать** новое значение enum в той же транзакции, где оно добавлено, и
хотя эта ревизия им дальше не пользуется, следующая может — привычку держим
единой с `e5a1f83b2c47`.

Метка дописывается **в конец**: там же она стоит и в `api.enums.CheckKind`.
Схема, построенная миграцией, обязана совпадать со схемой `create_all`, а
порядок меток enum в неё входит.

Откат: удалить значение из enum PostgreSQL не умеет, поэтому тип пересоздаётся
со старым набором меток. Сербские чеки перед этим удаляются — вместе с
операциями, которые из них вышли: `records.check_id` ссылается на `checks`, и
осиротить эту ссылку нельзя.

Между удалением и пересозданием типа стоит `SET CONSTRAINTS ALL IMMEDIATE`, и
без него откат падает — но только на базе, где сербские чеки действительно
есть. `records → checks` объявлен `DEFERRABLE INITIALLY DEFERRED`, поэтому
после `DELETE` в транзакции остаются несработавшие триггеры, а `ALTER TABLE
... ALTER COLUMN TYPE` отказывается менять таблицу с такими: «cannot ALTER
TABLE because it has pending trigger events». Проверено вживую на прогоне с
данными; на пустой базе этой ошибки не увидеть вовсе.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8b1f30d76e5"
down_revision: str | None = "a9d4e07c3b16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_KIND_OLD_LABELS = "'RU_FNS'"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE check_kind ADD VALUE IF NOT EXISTS 'SRB_SUF'")


def downgrade() -> None:
    # Порядок существенен: операции ссылаются на чеки составным внешним ключом,
    # и удалять их надо первыми. Удаление физическое, а не мягкое: строки с
    # меткой, которой после отката не существует, не приводятся к новому типу
    # и роняют `ALTER COLUMN` целиком.
    op.execute(
        "DELETE FROM records WHERE check_id IN "
        "(SELECT id FROM checks WHERE kind = 'SRB_SUF')"
    )
    op.execute("DELETE FROM checks WHERE kind = 'SRB_SUF'")

    # Отложенные внешние ключи обязаны сработать до смены типа колонки:
    # `records → checks` объявлен `INITIALLY DEFERRED`, и оставшиеся после
    # удаления триггеры валят `ALTER COLUMN ... TYPE` с «pending trigger
    # events». Видно это только на базе, где сербские чеки были.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")

    op.execute("ALTER TYPE check_kind RENAME TO check_kind_old")
    op.execute(f"CREATE TYPE check_kind AS ENUM ({_CHECK_KIND_OLD_LABELS})")
    op.execute(
        "ALTER TABLE checks ALTER COLUMN kind TYPE check_kind USING kind::text::check_kind"
    )
    op.execute("DROP TYPE check_kind_old")
