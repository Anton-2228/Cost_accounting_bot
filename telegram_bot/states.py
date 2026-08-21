"""FSM-состояния бота.

Один `StatesGroup` на весь бот: состояний немного, и разбиение по группам
только добавило бы способов сослаться не туда.

Состояния заводятся **только** под многошаговые диалоги. Ошибка команды
состояние не ставит никогда: в старой версии ответ на неудачный `/sync`
переводил пользователя в `CORRECT_TABLE`, где все команды, кроме самого
`/sync`, отвечали «Исправьте таблицу», и выйти оттуда было нельзя — даже
удалить таблицу.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class States(StatesGroup):
    """Состояния многошаговых диалогов."""

    # Мастер создания таблицы: название → день сброса → часовой пояс → почта.
    CREATE_TABLE_TITLE = State()
    CREATE_TABLE_RESET_DAY = State()
    CREATE_TABLE_TIMEZONE = State()
    CREATE_TABLE_EMAIL = State()

    # Ожидание почты для выдачи доступа (`/table_email`).
    ADD_EMAIL = State()

    # Ожидание слова подтверждения перед отвязкой таблицы (`/table_unlink`).
    CONFIRM_UNLINK_TABLE = State()

    # Ожидание telegram id, чьи траты на модель показать (`/settings`).
    SETTINGS_ASK_TELEGRAM_ID = State()

    # Разбор чека: типы товаров → категории → счёт (`/check`).
    # Три стадии, а не одна: правка типа меняет то, о чём спрашивать дальше, и
    # смешивать их в одном сообщении значило бы просить пользователя держать
    # весь чек в голове.
    CHECK_TYPES = State()
    CHECK_CATEGORIES = State()
    CHECK_SOURCE = State()
