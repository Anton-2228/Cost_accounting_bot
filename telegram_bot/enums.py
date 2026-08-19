"""Перечисления бота: ключи FSM-данных и имена команд."""

from __future__ import annotations

from enum import StrEnum


class FsmDataKeys(StrEnum):
    """Ключи промежуточных данных диалога.

    Всё промежуточное живёт здесь, в FSM-данных, и больше нигде. В старой
    версии рядом с FSM жил словарь `self.temp_data[user_id]` на экземпляре
    команды: он не чистился при `state.clear()`, тёк на весь срок жизни
    процесса и после перезапуска расходился с состоянием — обращение к нему
    давало `KeyError` там, где состояние выглядело корректным.
    """

    TITLE = "title"
    RESET_DAY = "reset_day"
    TIMEZONE = "timezone"

    # Разбор чека.
    CHECK_DRAFT = "check_draft"
    #: Чеки, пропущенные в этой сессии. Причина, по которой очередь не
    #: зацикливается: пропущенный чек остаётся `processed_at IS NULL` и иначе
    #: возвращался бы «следующим» бесконечно.
    SKIPPED_CHECK_IDS = "skipped_check_ids"
    SAVED_COUNT = "saved_count"


class CommandName(StrEnum):
    """Ключи, по которым `Manager` находит команду.

    Значение совпадает с командой Telegram без слеша: `/add` → `add`.
    Совпадение не случайно — оно избавляет от второй таблицы соответствий,
    которую пришлось бы держать синхронной вручную.

    Имена классов и файлов команд при этом остаются описательными
    (`RecordAddCommand` в `commands/record_add.py`): они называют предметное
    действие, а не строку, которую набирает пользователь. Строку можно
    переименовать, не трогая ни одного класса.
    """

    START = "start"
    HELP = "help"
    CANCEL = "cancel"

    ADD = "add"
    DEL = "del"
    ADD_TRANS = "add_trans"
    DEL_TRANS = "del_trans"

    TABLE = "table"
    TABLE_SYNC = "table_sync"
    TABLE_EMAIL = "table_email"
    TABLE_UNLINK = "table_unlink"

    CHECK = "check"
    CHECK_SKIP = "check_skip"
    CHECK_DEL = "check_del"
