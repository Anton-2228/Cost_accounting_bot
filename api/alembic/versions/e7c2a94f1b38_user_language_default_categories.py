"""user language and flagged default categories

Revision ID: e7c2a94f1b38
Revises: d9a3c05e1f47
Create Date: 2026-09-10 12:00:00.000000

Бот заговорил на пяти языках, и две вещи в схеме от этого перестали быть
правдой.

**Язык пользователя.** Он хранится в `users.language`, а не в боте: язык нужен и
тем, кто пишет пользователю не из бота, — уведомлениям и Mini App, — и обязан
пережить отвязку таблицы. Умолчание колонки — английский, на нём бот говорит с
теми, кто язык ещё не выбирал. Но существующие пользователи получают русский:
до этой миграции бот говорил с ними только по-русски, и проснуться с
английским ботом, ничего не нажав, было бы для них поломкой. Поэтому колонка
добавляется с умолчанием `'RU'` — им заполняются уже существующие строки, — и
сразу после этого умолчание меняется на `'EN'`.

**Категории по умолчанию.** Раньше их узнавали по названию:
`НеопределенныеТраты` — корзина, куда уходит всё неразложенное. Теперь в новой
таблице они называются на языке пользователя, и сравнение по одному названию
перестаёт работать. Роль переезжает в флаг `categories.is_default`, одна
категория на вид среди живых (частичный уникальный индекс). Существующим
категориям флаг ставится по старым названиям; таблица, где корзину успели
переименовать, останется без флага — код переживает отсутствие корзины так же,
как переживал его до сих пор.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7c2a94f1b38"
down_revision: str | None = "d9a3c05e1f47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Тип объявлен модульно и с create_type=False по той же причине, что и в
# c05740c0de01: инлайновый sa.Enum внутри add_column пытается выполнить
# CREATE TYPE сам.
LANGUAGE = postgresql.ENUM("RU", "EN", "HI", "ES", "FR", name="language", create_type=False)

_DEFAULT_WHERE = sa.text("is_default AND deleted_at IS NULL")


def upgrade() -> None:
    LANGUAGE.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "users",
        sa.Column("language", LANGUAGE, server_default="RU", nullable=False),
    )
    op.alter_column("users", "language", server_default="EN")

    op.add_column(
        "categories",
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    # Уникальность живого названия в документе гарантирует, что каждой строке
    # условия соответствует не больше одной категории на вид.
    op.execute(
        """
        UPDATE categories
           SET is_default = true
         WHERE deleted_at IS NULL
           AND (
                (kind = 'INCOME' AND title = 'НеопределенныйДоход')
             OR (kind = 'EXPENSE' AND title = 'НеопределенныеТраты')
           )
        """
    )
    op.create_index(
        "ix_categories_default_alive",
        "categories",
        ["spreadsheet_id", "kind"],
        unique=True,
        postgresql_where=_DEFAULT_WHERE,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_categories_default_alive",
        table_name="categories",
        postgresql_where=_DEFAULT_WHERE,
    )
    op.drop_column("categories", "is_default")
    op.drop_column("users", "language")
    LANGUAGE.drop(op.get_bind(), checkfirst=True)
