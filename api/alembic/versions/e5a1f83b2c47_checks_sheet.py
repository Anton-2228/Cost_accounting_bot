"""checks sheet target and import success notification

Revision ID: e5a1f83b2c47
Revises: d4c7b2e910a3
Create Date: 2026-08-16 15:00:00.000000

Два новых значения перечислений и следствие одного из них.

`sheet_target.CHECKS` — лист-архив разобранных чеков: строка на чек, в ней
расшифровка целиком. Лист принадлежит месяцу, как реестр и статистика, поэтому
двустороннее ограничение «периодные адресаты ровно те, у кого есть период»
пополняется третьим значением. Двусторонность существенна: односторонняя
формулировка пропустила бы задачу `CHECKS` без периода, та не схлопнулась бы по
уникальному ключу с нормальной и осталась бы висеть навсегда.

`notification_kind.IMPORT_OK` — подтверждение прочитанного листа. До сих пор
импорт сообщал о себе только ошибкой, и пользователь, поправивший опечатку в
`Categories`, не имел способа убедиться, что правку увидели.

Оба `ALTER TYPE ... ADD VALUE` выполняются в `autocommit_block`. PostgreSQL
запрещает **использовать** новое значение enum в той же транзакции, где оно
добавлено, а следующим шагом идёт `CHECK` с литералом `'CHECKS'`, который к
этому типу и приводится. Без отдельной транзакции миграция падает с «unsafe use
of new value of enum type».

Откат сложнее наката: удалить значение из enum PostgreSQL не умеет вовсе.
Поэтому тип пересоздаётся — переименование, `CREATE TYPE` со старым набором
меток, перевод колонок через `USING ...::text::<новый>`, `DROP` старого. Строки
с новыми значениями перед этим удаляются: задача перерисовки восстановится
следующей же правкой, уведомление — сообщение, которое пользователь уже прочёл.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a1f83b2c47"
down_revision: str | None = "d4c7b2e910a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Таблицы, где адресат листа ограничен парой «периодный ⇔ есть период».
_PERIOD_TARGET_TABLES = ("sheet_sync_tasks", "sheet_mappings")

_PERIOD_TARGETS_NEW = "'OPERATIONS', 'STATISTICS', 'CHECKS'"
_PERIOD_TARGETS_OLD = "'OPERATIONS', 'STATISTICS'"

_SHEET_TARGET_OLD_LABELS = (
    "'STRUCTURE', 'CATEGORIES', 'BILLS', 'OPERATIONS', 'STATISTICS'"
)
_NOTIFICATION_KIND_OLD_LABELS = (
    "'TABLE_READY', 'IMPORT_ERROR', 'SYNC_FAILED', 'ROLLOVER'"
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # `CHECKS` дописывается в конец — там же он стоит и в `SheetTarget`.
        op.execute("ALTER TYPE sheet_target ADD VALUE IF NOT EXISTS 'CHECKS'")
        # `IMPORT_OK` — с явным `BEFORE`: в `NotificationKind` он стоит рядом с
        # `IMPORT_ERROR`, а `ADD VALUE` без указания места дописал бы его в
        # конец. Схема, построенная миграцией, обязана совпадать со схемой
        # `create_all` — это сверяется `pg_dump`-ом обеих схем и diff-ом.
        op.execute(
            "ALTER TYPE notification_kind "
            "ADD VALUE IF NOT EXISTS 'IMPORT_OK' BEFORE 'IMPORT_ERROR'"
        )

    _replace_period_constraints(_PERIOD_TARGETS_NEW)


def downgrade() -> None:
    op.execute("DELETE FROM sheet_sync_tasks WHERE target = 'CHECKS'")
    op.execute("DELETE FROM sheet_mappings WHERE target = 'CHECKS'")
    op.execute("DELETE FROM user_notifications WHERE kind = 'IMPORT_OK'")

    # Снимаются **все** ограничения по колонке `target`, а не только то, что
    # эта ревизия трогала. Текст условия хранится с привязкой к типу, и после
    # переименования литералы в уцелевшем условии остаются старого типа:
    # `ALTER COLUMN ... TYPE` падает с «operator does not exist: sheet_target =
    # sheet_target_old». Проверено вживую на прогоне `downgrade base`.
    _drop_period_constraints()
    op.drop_constraint("import_target", "sheet_sync_tasks", type_="check")

    _shrink_enum(
        "sheet_target",
        _SHEET_TARGET_OLD_LABELS,
        columns=(("sheet_sync_tasks", "target"), ("sheet_mappings", "target")),
    )
    _shrink_enum(
        "notification_kind",
        _NOTIFICATION_KIND_OLD_LABELS,
        columns=(("user_notifications", "kind"),),
    )

    op.create_check_constraint(
        "import_target",
        "sheet_sync_tasks",
        "kind <> 'IMPORT' OR target IN ('CATEGORIES', 'BILLS')",
    )
    _add_period_constraints(_PERIOD_TARGETS_OLD)


def _replace_period_constraints(targets: str) -> None:
    """Переписывает ограничение «периодный адресат ⇔ период проставлен»."""
    _drop_period_constraints()
    _add_period_constraints(targets)


def _drop_period_constraints() -> None:
    """Снимает ограничение с обеих таблиц."""
    for table in _PERIOD_TARGET_TABLES:
        # Имя без префикса: соглашение `ck_%(table_name)s_%(constraint_name)s`
        # достроит его само, а готовое имя дало бы двойной префикс.
        op.drop_constraint("period_matches_target", table, type_="check")


def _add_period_constraints(targets: str) -> None:
    """Ставит ограничение с указанным набором периодных адресатов."""
    for table in _PERIOD_TARGET_TABLES:
        op.create_check_constraint(
            "period_matches_target",
            table,
            f"(target IN ({targets})) = (period_id IS NOT NULL)",
        )


def _shrink_enum(
    name: str,
    labels: str,
    *,
    columns: Sequence[tuple[str, str]],
) -> None:
    """Пересоздаёт enum с сокращённым набором меток.

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
