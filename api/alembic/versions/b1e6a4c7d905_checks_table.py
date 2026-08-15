"""checks table replaces check queue

Revision ID: b1e6a4c7d905
Revises: 7f3c1d9a4b02
Create Date: 2026-08-15 12:00:00.000000

Очередь `check_queue_items` хранила сырую строку и наполнялась внешним
слушателем, которого больше нет. Её место занимает `checks`: чек ложится в БД
уже расшифрованным, вместе с QR-строкой, видом формата и ответом внешнего
сервиса целиком.

Ни даты, ни суммы, ни валюты отдельными колонками нет: форматов чеков будет
больше одного, и у каждого реквизиты свои. Дедупликацию обеспечивает
`external_key`, содержимое которого вычисляет парсер формата (для ФНС —
«ФН:ФД:ФП»); БД не знает ни одного формата, но два одинаковых ключа одного вида
в одном документе невыразимы.

`DROP TYPE` для нового enum стоит в `downgrade` строго после `DROP TABLE`: пока
на тип ссылается колонка, удалить его нельзя.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1e6a4c7d905"
down_revision: str | None = "7f3c1d9a4b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Тип объявлен модульно и с create_type=False по той же причине, что и в
# c05740c0de01: инлайновый sa.Enum внутри create_table пытается выполнить
# CREATE TYPE сам, и автогенерация вставляет его с чужой MetaData.
CHECK_KIND = postgresql.ENUM("RU_FNS", name="check_kind", create_type=False)


def upgrade() -> None:
    CHECK_KIND.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "checks",
        sa.Column("spreadsheet_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", CHECK_KIND, nullable=False),
        sa.Column("qr_raw", sa.Text(), nullable=False),
        sa.Column("external_key", sa.Text(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["spreadsheet_id"],
            ["spreadsheets.id"],
            name=op.f("fk_checks_spreadsheet_id_spreadsheets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checks")),
        sa.UniqueConstraint(
            "spreadsheet_id",
            "kind",
            "external_key",
            name="uq_checks_spreadsheet_id_kind_external_key",
        ),
    )
    op.create_index("ix_checks_spreadsheet_id", "checks", ["spreadsheet_id", "id"], unique=False)

    op.drop_index("ix_check_queue_items_spreadsheet_id", table_name="check_queue_items")
    op.drop_table("check_queue_items")


def downgrade() -> None:
    op.create_table(
        "check_queue_items",
        sa.Column("spreadsheet_id", sa.BigInteger(), nullable=False),
        sa.Column("check_text", sa.Text(), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["spreadsheet_id"],
            ["spreadsheets.id"],
            name=op.f("fk_check_queue_items_spreadsheet_id_spreadsheets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_check_queue_items")),
    )
    op.create_index(
        "ix_check_queue_items_spreadsheet_id",
        "check_queue_items",
        ["spreadsheet_id", "id"],
        unique=False,
    )

    op.drop_index("ix_checks_spreadsheet_id", table_name="checks")
    op.drop_table("checks")
    CHECK_KIND.drop(op.get_bind(), checkfirst=True)
