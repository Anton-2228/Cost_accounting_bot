"""sheet sync task lease

Revision ID: 7f3c1d9a4b02
Revises: c05740c0de01
Create Date: 2026-08-12 22:40:00.000000

Захват задачи очереди получил срок: `claim` отбирает не только строки с
`claimed_at IS NULL`, но и те, чей захват просрочен. Партиальный индекс с
условием `claimed_at IS NULL` такую выборку больше не покрывает, поэтому он
заменяется на составной по `(claimed_at, next_attempt_at)`.

Изменение только индексное: колонок и типов не добавляется, срок аренды живёт
константой в коде.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f3c1d9a4b02"
down_revision: str | None = "c05740c0de01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_sheet_sync_tasks_claimable",
        table_name="sheet_sync_tasks",
        postgresql_where="claimed_at IS NULL",
    )
    op.create_index(
        "ix_sheet_sync_tasks_claimable",
        "sheet_sync_tasks",
        ["claimed_at", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sheet_sync_tasks_claimable", table_name="sheet_sync_tasks")
    op.create_index(
        "ix_sheet_sync_tasks_claimable",
        "sheet_sync_tasks",
        ["next_attempt_at"],
        unique=False,
        postgresql_where="claimed_at IS NULL",
    )
