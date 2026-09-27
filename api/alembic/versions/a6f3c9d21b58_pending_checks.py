"""pending checks

Revision ID: a6f3c9d21b58
Revises: f1d8b3a6c52e
Create Date: 2026-09-27 21:00:00.000000

Отложенные чеки: отсканированы, но внешний сервис их пока не отдал (сербский
чек без состава — касса ещё не передала его в налоговую). Раньше такой чек
жил только в памяти Mini App и пропадал вместе с ней.

Отдельная таблица, а не статус в `checks`: чек там всегда полный, и разбору не
приходится уметь работать с получеками. Строка исчезает, когда чек сохранён,
или когда пользователь удалил её сам.

`notification_kind` получает `PENDING_CHECK` — судьба отложенного чека: фон
его добавил или сдался. Метка дописывается **в конец**, как и в
`api.enums.NotificationKind`. `ADD VALUE` — в `autocommit_block`, привычку
держим единой с `e5a1f83b2c47`.

Откат: таблица удаляется, уведомления этого вида удаляются, тип пересоздаётся
со старым набором меток.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6f3c9d21b58"
down_revision: str | None = "f1d8b3a6c52e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOTIFICATION_KIND_OLD_LABELS = (
    "'TABLE_READY', 'IMPORT_OK', 'IMPORT_ERROR', 'SYNC_FAILED', 'ROLLOVER'"
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE notification_kind ADD VALUE IF NOT EXISTS 'PENDING_CHECK'")

    op.create_table(
        "pending_checks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("spreadsheet_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="check_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("qr_raw", sa.Text(), nullable=False),
        sa.Column("external_key", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "window_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["spreadsheet_id"],
            ["spreadsheets.id"],
            name=op.f("fk_pending_checks_spreadsheet_id_spreadsheets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pending_checks")),
        sa.UniqueConstraint(
            "spreadsheet_id",
            "kind",
            "external_key",
            name="uq_pending_checks_spreadsheet_id_kind_external_key",
        ),
    )
    op.create_index(
        "ix_pending_checks_due",
        "pending_checks",
        ["next_attempt_at"],
        unique=False,
        postgresql_where="expired_at IS NULL",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pending_checks_due",
        table_name="pending_checks",
        postgresql_where="expired_at IS NULL",
    )
    op.drop_table("pending_checks")

    op.execute("DELETE FROM user_notifications WHERE kind = 'PENDING_CHECK'")
    op.execute("ALTER TYPE notification_kind RENAME TO notification_kind_old")
    op.execute(f"CREATE TYPE notification_kind AS ENUM ({_NOTIFICATION_KIND_OLD_LABELS})")
    op.execute(
        "ALTER TABLE user_notifications ALTER COLUMN kind "
        "TYPE notification_kind USING kind::text::notification_kind"
    )
    op.execute("DROP TYPE notification_kind_old")
