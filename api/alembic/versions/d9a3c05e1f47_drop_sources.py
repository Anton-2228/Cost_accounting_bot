"""drop sources, transfers and the bills sheet

Revision ID: d9a3c05e1f47
Revises: c8b1f30d76e5
Create Date: 2026-09-09 12:00:00.000000

Счёт удаляется из системы целиком. Единственное, что он реально давал операции,
— валюту, и её теперь называет пользователь (`/add валюта сумма категория`) либо
задаёт формат чека. Всё остальное, что на счёте держалось, — начальный остаток,
вычисляемый баланс, переводы между счетами — учёту в его нынешнем виде не нужно.

Уходит четыре вещи разом, и это одно изменение, а не четыре: без счетов ни одна
из них невыразима.

* `sources` и `source_associations` — сам справочник и его псевдонимы;
* `transfers` — перевод есть движение между двумя счетами, и оба его составных
  внешних ключа ведут в `sources`. Придумывать ему новый смысл значило бы
  делать новую функциональность под видом удаления;
* `records.source_id` — операция больше не принадлежит счёту. `records.currency`
  **остаётся**: валюта была свойством самой суммы и до этой миграции, и лист
  статистики по-прежнему сводит её к одной валюте по курсу дня;
* `sheet_target.BILLS` — лист счетов в Google-документе больше не создаётся.

Значение выпиливается из типа, а не оставляется неиспользуемым: схема обязана
совпадать с той, что даёт `create_all` (это проверяется сравнением `pg_dump`), а
мёртвая метка в `api.enums.SheetTarget` пережила бы своё единственное
объяснение.

**Грабли те же, что в `e5a1f83b2c47`.** `ALTER TYPE ... DROP VALUE` в PostgreSQL
не существует, поэтому тип пересоздаётся целиком. Перед `ALTER COLUMN ... TYPE`
снимаются **все** CHECK по колонке `target`, а не только те, что эта ревизия
меняет: текст условия хранится с привязкой к типу, и в уцелевшем условии
литералы остались бы старого типа — `ALTER COLUMN` упал бы с «operator does not
exist: sheet_target = sheet_target_old».

Бэкфилла нет ни в одну сторону. База пересоздаётся, а угадывать задним числом,
с какого счёта была сделана операция, всё равно нечем: в `downgrade`
`records.source_id` возвращается **nullable**, иначе непустая таблица не приняла
бы `NOT NULL` без выдуманного счёта.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9a3c05e1f47"
down_revision: str | None = "c8b1f30d76e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Типы объявлены модульно и с create_type=False по той же причине, что и в
# c05740c0de01: инлайновый sa.Enum внутри create_table пытается выполнить
# CREATE TYPE сам.
ENTITY_STATUS = postgresql.ENUM("ACTIVE", "INACTIVE", name="entity_status", create_type=False)
CURRENCY = postgresql.ENUM("RUB", "USD", "EUR", "RSD", name="currency", create_type=False)

#: Таблицы, где `target` ограничен «периодный адресат ⇔ период проставлен».
_PERIOD_TARGET_TABLES = ("sheet_sync_tasks", "sheet_mappings")

#: Периодные адресаты. Набор не меняется — `BILLS` в него и не входил, — но
#: ограничение приходится снимать и ставить заново вокруг пересоздания типа.
_PERIOD_TARGETS = "'OPERATIONS', 'STATISTICS', 'CHECKS'"

_SHEET_TARGET_LABELS = "'STRUCTURE', 'CATEGORIES', 'OPERATIONS', 'STATISTICS', 'CHECKS'"
_SHEET_TARGET_LABELS_WITH_BILLS = (
    "'STRUCTURE', 'CATEGORIES', 'BILLS', 'OPERATIONS', 'STATISTICS', 'CHECKS'"
)


def upgrade() -> None:
    # Сначала `records`: пока её внешний ключ смотрит на `sources`, `DROP TABLE`
    # не проходит. `transfers` по той же причине уходит раньше самого счёта.
    op.drop_index(
        "ix_records_source_id_alive",
        table_name="records",
        postgresql_where="deleted_at IS NULL",
    )
    op.drop_constraint("fk_records_source_id_sources", "records", type_="foreignkey")
    op.drop_column("records", "source_id")

    op.drop_table("transfers")
    op.drop_table("source_associations")
    op.drop_table("sources")

    # Строки очереди и соответствий листов с этим адресатом надо убрать до
    # пересоздания типа: `USING target::text::sheet_target` на значении,
    # которого в новом типе нет, падает.
    op.execute("DELETE FROM sheet_sync_tasks WHERE target = 'BILLS'")
    op.execute("DELETE FROM sheet_mappings WHERE target = 'BILLS'")

    _drop_target_constraints()
    _replace_enum(
        "sheet_target",
        _SHEET_TARGET_LABELS,
        columns=(("sheet_sync_tasks", "target"), ("sheet_mappings", "target")),
    )
    _add_target_constraints("kind <> 'IMPORT' OR target = 'CATEGORIES'")


def downgrade() -> None:
    _drop_target_constraints()
    _replace_enum(
        "sheet_target",
        _SHEET_TARGET_LABELS_WITH_BILLS,
        columns=(("sheet_sync_tasks", "target"), ("sheet_mappings", "target")),
    )
    _add_target_constraints("kind <> 'IMPORT' OR target IN ('CATEGORIES', 'BILLS')")

    op.create_table(
        "sources",
        sa.Column("spreadsheet_id", sa.BigInteger(), nullable=False),
        sa.Column("status", ENTITY_STATUS, server_default="ACTIVE", nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("currency", CURRENCY, nullable=False),
        sa.Column(
            "start_balance",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["spreadsheet_id"],
            ["spreadsheets.id"],
            name=op.f("fk_sources_spreadsheet_id_spreadsheets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("id", "spreadsheet_id", name="uq_sources_id_spreadsheet_id"),
    )
    op.create_index(
        "ix_sources_spreadsheet_id_alive",
        "sources",
        ["spreadsheet_id", "id"],
        unique=False,
        postgresql_where="deleted_at IS NULL",
    )
    op.create_index(
        "ix_sources_title_alive",
        "sources",
        ["spreadsheet_id", sa.literal_column("lower(title)")],
        unique=True,
        postgresql_where="deleted_at IS NULL",
    )

    op.create_table(
        "source_associations",
        sa.Column("spreadsheet_id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.String(length=64), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
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
        sa.CheckConstraint(
            "alias = lower(alias)",
            name=op.f("ck_source_associations_alias_lowercase"),
        ),
        sa.CheckConstraint(
            "length(alias) > 0",
            name=op.f("ck_source_associations_alias_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "spreadsheet_id"],
            ["sources.id", "sources.spreadsheet_id"],
            name="fk_source_associations_source_id_sources",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_associations")),
        sa.UniqueConstraint(
            "spreadsheet_id",
            "alias",
            name="uq_source_associations_spreadsheet_id_alias",
        ),
    )
    op.create_index(
        "ix_source_associations_source_id",
        "source_associations",
        ["source_id"],
        unique=False,
    )

    op.create_table(
        "transfers",
        sa.Column("spreadsheet_id", sa.BigInteger(), nullable=False),
        sa.Column("period_id", sa.BigInteger(), nullable=False),
        sa.Column("from_source_id", sa.BigInteger(), nullable=False),
        sa.Column("to_source_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("added_at", sa.Date(), nullable=False),
        sa.Column(
            "notes",
            sa.String(length=512),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name=op.f("ck_transfers_amount_positive")),
        sa.CheckConstraint(
            "from_source_id <> to_source_id",
            name=op.f("ck_transfers_sources_differ"),
        ),
        sa.ForeignKeyConstraint(
            ["from_source_id", "spreadsheet_id"],
            ["sources.id", "sources.spreadsheet_id"],
            name="fk_transfers_from_source_id_sources",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["period_id", "spreadsheet_id"],
            ["periods.id", "periods.spreadsheet_id"],
            name="fk_transfers_period_id_periods",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["spreadsheet_id"],
            ["spreadsheets.id"],
            name=op.f("fk_transfers_spreadsheet_id_spreadsheets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_source_id", "spreadsheet_id"],
            ["sources.id", "sources.spreadsheet_id"],
            name="fk_transfers_to_source_id_sources",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transfers")),
    )
    for column in ("from_source_id", "to_source_id"):
        op.create_index(
            f"ix_transfers_{column}_alive",
            "transfers",
            [column],
            unique=False,
            postgresql_where="deleted_at IS NULL",
        )
    op.create_index(
        "ix_transfers_period_id_alive",
        "transfers",
        ["period_id", "id"],
        unique=False,
        postgresql_where="deleted_at IS NULL",
    )

    # Nullable, в отличие от прежней схемы: чем заполнить колонку у операций,
    # переживших upgrade, не знает никто, а выдуманный «счёт по умолчанию» был
    # бы неправдой в реестре.
    op.add_column("records", sa.Column("source_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_records_source_id_sources",
        "records",
        "sources",
        ["source_id", "spreadsheet_id"],
        ["id", "spreadsheet_id"],
        initially="DEFERRED",
        deferrable=True,
    )
    op.create_index(
        "ix_records_source_id_alive",
        "records",
        ["source_id"],
        unique=False,
        postgresql_where="deleted_at IS NULL",
    )


def _drop_target_constraints() -> None:
    """Снимает все CHECK по колонке `target` — см. грабли в докстринге."""
    for table in _PERIOD_TARGET_TABLES:
        # Имя без префикса: соглашение `ck_%(table_name)s_%(constraint_name)s`
        # достроит его само, а готовое имя дало бы двойной префикс.
        op.drop_constraint("period_matches_target", table, type_="check")
    op.drop_constraint("import_target", "sheet_sync_tasks", type_="check")


def _add_target_constraints(import_target: str) -> None:
    """Возвращает те же CHECK после пересоздания типа."""
    for table in _PERIOD_TARGET_TABLES:
        op.create_check_constraint(
            "period_matches_target",
            table,
            f"(target IN ({_PERIOD_TARGETS})) = (period_id IS NOT NULL)",
        )
    op.create_check_constraint("import_target", "sheet_sync_tasks", import_target)


def _replace_enum(
    name: str,
    labels: str,
    *,
    columns: Sequence[tuple[str, str]],
) -> None:
    """Пересоздаёт enum с другим набором меток.

    Единственный способ убрать значение: `ALTER TYPE ... DROP VALUE` в
    PostgreSQL не существует ни в одной версии.
    """
    op.execute(f"ALTER TYPE {name} RENAME TO {name}_old")
    op.execute(f"CREATE TYPE {name} AS ENUM ({labels})")
    for table, column in columns:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE {name} USING {column}::text::{name}"
        )
    op.execute(f"DROP TYPE {name}_old")
