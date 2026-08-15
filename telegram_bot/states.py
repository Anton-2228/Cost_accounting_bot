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

    # Ожидание слова подтверждения перед отвязкой таблицы (`/table_delete`).
    CONFIRM_DELETE_TABLE = State()
