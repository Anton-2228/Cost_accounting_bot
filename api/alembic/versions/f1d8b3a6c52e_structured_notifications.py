"""notifications carry a code and params instead of text

Revision ID: f1d8b3a6c52e
Revises: e7c2a94f1b38
Create Date: 2026-09-10 13:00:00.000000

Уведомление перестаёт быть готовой русской фразой. Бот говорит на пяти языках,
и фраза, собранная api в момент события, была бы на одном из них для всех.
Теперь строка хранит код (`table_ready`, `import_error.unknown_id`, …) и данные
для подстановки, а текст на языке пользователя собирает бот.

С уже накопленными строками обходимся так:

* **история** остаётся читаемой: старый текст переезжает в `params.text` с
  кодом `legacy`. Колонка `text` уходит, но то, что пользователю когда-то
  писали, в базе остаётся — ради этого `delivered_at` и заводился;
* **недоставленное** на момент миграции помечается доставленным. Это единицы
  строк, чаще ноль, а показать их по-новому нечем: кода у готовой фразы нет,
  и угадывать его по тексту значило бы писать разбор русского языка ради
  одного деплоя.

`code` добавляется с временным умолчанием `'legacy'` — им заполняются
существующие строки, — и умолчание тут же снимается: у новой строки код
обязан быть назван явно.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1d8b3a6c52e"
down_revision: str | None = "e7c2a94f1b38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_notifications",
        sa.Column("code", sa.String(length=64), server_default="legacy", nullable=False),
    )
    op.alter_column("user_notifications", "code", server_default=None)
    op.add_column(
        "user_notifications",
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute("UPDATE user_notifications SET params = jsonb_build_object('text', text)")
    op.execute("UPDATE user_notifications SET delivered_at = now() WHERE delivered_at IS NULL")
    op.drop_column("user_notifications", "text")


def downgrade() -> None:
    op.add_column("user_notifications", sa.Column("text", sa.Text(), nullable=True))
    # Новые строки своего текста не имеют: вместо него остаётся хотя бы код,
    # иначе `NOT NULL` не встанет.
    op.execute("UPDATE user_notifications SET text = COALESCE(params->>'text', code)")
    op.alter_column("user_notifications", "text", nullable=False)
    op.drop_column("user_notifications", "params")
    op.drop_column("user_notifications", "code")
