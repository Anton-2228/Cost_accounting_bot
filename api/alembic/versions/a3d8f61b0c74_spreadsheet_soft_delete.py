"""spreadsheet soft delete

Revision ID: a3d8f61b0c74
Revises: f2b70d5c8a19
Create Date: 2026-08-19 12:00:00.000000

`/table_delete` удалял документ физически — каскадом от `users`, — и вместе с ним
исчезала вся история: операции, чеки, периоды. Пока историю никто не считал, это
было терпимо; учёт денег, потраченных на модель, делает это неприемлемым: сумма
за прошлый месяц не должна меняться задним числом оттого, что кто-то отвязал
таблицу.

Поэтому у `spreadsheets` появляется `deleted_at`, а команда становится
отвязыванием. Пользователь не удаляется вовсе.

Уникальность `user_id` при этом обязана стать **частичной**: отвязанные документы
того же пользователя остаются в таблице, и обычный `UNIQUE` не дал бы завести
следующий документ ни одному вернувшемуся пользователю. Имя сохраняется прежним —
гарантия та же, просто суженная до живых строк.

`google_spreadsheet_id` остаётся уникальным глобально: отвязанный документ
продолжает держать свой файл, и двух документов на один Google-файл быть не
должно.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d8f61b0c74"
down_revision: str | None = "f2b70d5c8a19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "spreadsheets",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("uq_spreadsheets_user_id", "spreadsheets", type_="unique")
    op.create_index(
        "uq_spreadsheets_user_id",
        "spreadsheets",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # Отвязанные документы физически удаляются: обычный UNIQUE по `user_id`
    # иначе не создать, а второй живой документ у пользователя невозможен по
    # построению — значит лишними могут быть только мёртвые строки.
    op.execute(sa.text("DELETE FROM spreadsheets WHERE deleted_at IS NOT NULL"))

    op.drop_index("uq_spreadsheets_user_id", table_name="spreadsheets")
    op.create_unique_constraint("uq_spreadsheets_user_id", "spreadsheets", ["user_id"])
    op.drop_column("spreadsheets", "deleted_at")
