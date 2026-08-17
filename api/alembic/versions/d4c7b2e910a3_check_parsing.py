"""check parsing: processed_at, records.check_id, zero-amount records

Revision ID: d4c7b2e910a3
Revises: b1e6a4c7d905
Create Date: 2026-08-16 12:00:00.000000

Разбор чека: `checks` → типы товаров → категории → операции реестра.

Признак разбора — `checks.processed_at` плюс `records.check_id`. Отдельного
статуса нет: разбор либо записал операции и проставил метку одной транзакцией,
либо не сделал ни того, ни другого.

Внешний ключ `records → checks` составной и отложенный по той же причине, что
`periods`/`categories`/`sources`: при удалении документа Postgres каскадно
удаляет и чеки, и операции, а порядок между каскадами не определён. `ondelete`
не ставится намеренно — удалять разрешено только неразобранный чек, у которого
операций нет по определению.

`ck_records_amount_not_zero` снимается: позиция чека с нулевой ценой законна
(«второй товар в подарок»), а отбросить её нельзя — сумма записанных позиций
перестала бы сходиться с итогом чека, которым разбор себя проверяет.

`records.check_json` удаляется: копия расшифровки в каждой позиции была дублем
строки `checks`, и с появлением `check_id` от неё не осталось смысла.

Партиальный индекс `ix_checks_unprocessed` написан руками: автогенерация
Alembic частичные индексы не видит, и без явной записи схема в проде разошлась
бы с той, на которой зелены тесты.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4c7b2e910a3"
down_revision: str | None = "b1e6a4c7d905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("checks", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_checks_unprocessed",
        "checks",
        ["spreadsheet_id", "id"],
        unique=False,
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    # Цель составного внешнего ключа: PostgreSQL требует UNIQUE ровно по тому
    # набору колонок, на который ссылается FK. Данные это не ограничивает — id
    # и так первичный ключ.
    op.create_unique_constraint(
        "uq_checks_id_spreadsheet_id",
        "checks",
        ["id", "spreadsheet_id"],
    )

    op.add_column("records", sa.Column("check_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_records_check_id_checks",
        "records",
        "checks",
        ["check_id", "spreadsheet_id"],
        ["id", "spreadsheet_id"],
        deferrable=True,
        initially="DEFERRED",
    )

    # Имя без префикса: соглашение `ck_%(table_name)s_%(constraint_name)s`
    # достроит его само, а готовое имя превратилось бы в двойной префикс.
    op.drop_constraint("amount_not_zero", "records", type_="check")
    op.drop_column("records", "check_json")


def downgrade() -> None:
    op.add_column("records", sa.Column("check_json", sa.Text(), nullable=True))
    # Нулевые операции к этому моменту уже могли быть записаны, и ограничение
    # на них не встанет. Это не недосмотр: откат снимает саму возможность
    # хранить такие строки, и решать, что с ними делать, придётся руками.
    op.create_check_constraint("amount_not_zero", "records", "amount <> 0")

    op.drop_constraint("fk_records_check_id_checks", "records", type_="foreignkey")
    op.drop_column("records", "check_id")

    op.drop_constraint("uq_checks_id_spreadsheet_id", "checks", type_="unique")
    op.drop_index("ix_checks_unprocessed", table_name="checks")
    op.drop_column("checks", "processed_at")
