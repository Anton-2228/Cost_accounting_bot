"""llm usages

Revision ID: b6e2c04f7a18
Revises: a3d8f61b0c74
Create Date: 2026-08-19 13:00:00.000000

Разбор чека дважды обращается к модели, и до сих пор нигде не оставалось следа,
во что это обошлось: блок `usage` ответа провайдера выбрасывался целиком.
Таблица отвечает на один вопрос — сколько денег ушло и на что.

Стоимость приезжает от провайдера (`usage.cost` у OpenRouter), а не считается по
своему прайс-листу, поэтому `cost` допускает NULL: пусто означает «провайдер не
прислал», и это обязано отличаться от нуля. Точность своя, `Numeric(18, 10)`, —
денежные `Numeric(14, 2)` округлили бы каждый вызов в ноль.

`entity_kind` + `entity_id` — не внешний ключ намеренно: модель зовётся до того,
как появилась хоть одна операция реестра, и одно обращение покрывает сразу все
позиции чека. `CHECK` следит лишь за тем, чтобы пара была заполнена целиком или
не заполнена вовсе.

Внешний ключ на документ с `ON DELETE CASCADE` при этом безопасен: отвязывание
документа стало мягким предыдущей ревизией, и каскад больше не срабатывает.

Типы объявлены модульно и с `create_type=False` по той же причине, что и в
b1e6a4c7d905; `DROP TYPE` в `downgrade` идёт строго после `DROP TABLE`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6e2c04f7a18"
down_revision: str | None = "a3d8f61b0c74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LLM_OPERATION = postgresql.ENUM(
    "SUGGEST_PRODUCT_TYPES",
    "SUGGEST_CATEGORIES",
    name="llm_operation",
    create_type=False,
)
LLM_ENTITY_KIND = postgresql.ENUM("CHECK", name="llm_entity_kind", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    LLM_OPERATION.create(bind, checkfirst=True)
    LLM_ENTITY_KIND.create(bind, checkfirst=True)

    op.create_table(
        "llm_usages",
        sa.Column("spreadsheet_id", sa.BigInteger(), nullable=False),
        sa.Column("operation", LLM_OPERATION, nullable=False),
        sa.Column("entity_kind", LLM_ENTITY_KIND, nullable=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Numeric(precision=18, scale=10), nullable=True),
        sa.Column("raw_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(entity_kind IS NULL) = (entity_id IS NULL)",
            name=op.f("ck_llm_usages_entity_pair"),
        ),
        sa.ForeignKeyConstraint(
            ["spreadsheet_id"],
            ["spreadsheets.id"],
            name=op.f("fk_llm_usages_spreadsheet_id_spreadsheets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_usages")),
    )
    op.create_index(
        "ix_llm_usages_spreadsheet_id_created_at",
        "llm_usages",
        ["spreadsheet_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_llm_usages_spreadsheet_id_created_at", table_name="llm_usages")
    op.drop_table("llm_usages")

    bind = op.get_bind()
    LLM_ENTITY_KIND.drop(bind, checkfirst=True)
    LLM_OPERATION.drop(bind, checkfirst=True)
