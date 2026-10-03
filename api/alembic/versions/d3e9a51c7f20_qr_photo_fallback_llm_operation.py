"""qr photo fallback llm operation

Revision ID: d3e9a51c7f20
Revises: a6f3c9d21b58
Create Date: 2026-10-02 18:30:00.000000

`llm_operation` получает `QR_PHOTO_FALLBACK`: checks_service зовёт модель
прочитать QR с фото чека, когда zxing не справился, и расход на это пишется в
`llm_usages` наравне с разбором. Метка дописывается **в конец**, как и в
`api.enums.LlmOperation`. `ADD VALUE` — в `autocommit_block`, как в
`a6f3c9d21b58`.

Откат: строки учёта этого вида удаляются, тип пересоздаётся со старым набором
меток.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e9a51c7f20"
down_revision: str | None = "a6f3c9d21b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LLM_OPERATION_OLD_LABELS = "'SUGGEST_PRODUCT_TYPES', 'SUGGEST_CATEGORIES'"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE llm_operation ADD VALUE IF NOT EXISTS 'QR_PHOTO_FALLBACK'")


def downgrade() -> None:
    op.execute("DELETE FROM llm_usages WHERE operation = 'QR_PHOTO_FALLBACK'")
    op.execute("ALTER TYPE llm_operation RENAME TO llm_operation_old")
    op.execute(f"CREATE TYPE llm_operation AS ENUM ({_LLM_OPERATION_OLD_LABELS})")
    op.execute(
        "ALTER TABLE llm_usages ALTER COLUMN operation "
        "TYPE llm_operation USING operation::text::llm_operation"
    )
    op.execute("DROP TYPE llm_operation_old")
