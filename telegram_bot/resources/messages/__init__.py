"""Тексты сообщений бота, поднятые из `.txt` в константы.

Тексты лежат отдельно от кода, чтобы правка формулировки не была правкой
логики. Читаются один раз на импорте.

`encoding="utf-8"` обязателен и не является перестраховкой: файлы целиком
кириллические, а `Path.read_text()` без кодировки берёт локаль системы. В
старой версии тринадцать таких вызовов работали лишь потому, что в контейнере
случайно оказалась UTF-8-локаль.
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).parent


def _load(name: str) -> str:
    """Читает файл сообщения."""
    return (_HERE / name).read_text(encoding="utf-8").strip()


HELP_MESSAGE = _load("HELP.txt")
HELP_COMMANDS_MESSAGE = _load("HELP_COMMANDS.txt")

WELCOME_MESSAGE = _load("WELCOME.txt")
MENU_MESSAGE = _load("MENU.txt")

ASK_TITLE_MESSAGE = _load("ASK_TITLE.txt")
ASK_RESET_DAY_MESSAGE = _load("ASK_RESET_DAY.txt")
ASK_TIMEZONE_MESSAGE = _load("ASK_TIMEZONE.txt")
ASK_EMAIL_MESSAGE = _load("ASK_EMAIL.txt")
CREATING_TABLE_MESSAGE = _load("CREATING_TABLE.txt")

ASK_ACCESS_EMAIL_MESSAGE = _load("ASK_ACCESS_EMAIL.txt")
EMAIL_ADDED_MESSAGE = _load("EMAIL_ADDED.txt")
SYNC_REQUESTED_MESSAGE = _load("SYNC_REQUESTED.txt")

ASK_UNLINK_CONFIRM_MESSAGE = _load("ASK_UNLINK_CONFIRM.txt")
UNLINK_CANCELLED_MESSAGE = _load("UNLINK_CANCELLED.txt")
TABLE_UNLINKED_MESSAGE = _load("TABLE_UNLINKED.txt")

CHECK_QUEUE_EMPTY_MESSAGE = _load("CHECK_QUEUE_EMPTY.txt")
ASK_CHECK_DELETE_MESSAGE = _load("ASK_CHECK_DELETE.txt")
CHECK_BROKEN_MESSAGE = _load("CHECK_BROKEN.txt")
CHECK_AI_UNAVAILABLE_MESSAGE = _load("CHECK_AI_UNAVAILABLE.txt")
CHECK_ASK_TYPES_MESSAGE = _load("CHECK_ASK_TYPES.txt")
CHECK_ASK_CATEGORIES_MESSAGE = _load("CHECK_ASK_CATEGORIES.txt")
CHECK_ASK_SOURCE_MESSAGE = _load("CHECK_ASK_SOURCE.txt")
CHECK_LOST_MESSAGE = _load("CHECK_LOST.txt")
CHECK_STALE_BUTTON_MESSAGE = _load("CHECK_STALE_BUTTON.txt")
CHECK_NO_CATEGORY_MESSAGE = _load("CHECK_NO_CATEGORY.txt")
CHECK_DELETED_MESSAGE = _load("CHECK_DELETED.txt")
CHECK_SKIPPED_MESSAGE = _load("CHECK_SKIPPED.txt")

SETTINGS_ADMIN_MESSAGE = _load("SETTINGS_ADMIN.txt")
SETTINGS_STUB_MESSAGE = _load("SETTINGS_STUB.txt")
ASK_LLM_TELEGRAM_ID_MESSAGE = _load("ASK_LLM_TELEGRAM_ID.txt")
BAD_TELEGRAM_ID_MESSAGE = _load("BAD_TELEGRAM_ID.txt")

CANCELLED_MESSAGE = _load("CANCELLED.txt")
CANCEL_STALE_MESSAGE = _load("CANCEL_STALE.txt")
UNKNOWN_MESSAGE = _load("UNKNOWN.txt")
DIALOG_IN_PROGRESS_MESSAGE = _load("DIALOG_IN_PROGRESS.txt")
#: Та же подсказка для мастера создания таблицы: кнопки «Отмена» у него нет, и
#: звать нажать несуществующее было бы хуже молчания.
DIALOG_IN_PROGRESS_NO_EXIT_MESSAGE = _load("DIALOG_IN_PROGRESS_NO_EXIT.txt")

__all__ = [
    "ASK_ACCESS_EMAIL_MESSAGE",
    "ASK_CHECK_DELETE_MESSAGE",
    "ASK_EMAIL_MESSAGE",
    "ASK_LLM_TELEGRAM_ID_MESSAGE",
    "ASK_RESET_DAY_MESSAGE",
    "ASK_TIMEZONE_MESSAGE",
    "ASK_TITLE_MESSAGE",
    "ASK_UNLINK_CONFIRM_MESSAGE",
    "BAD_TELEGRAM_ID_MESSAGE",
    "CANCELLED_MESSAGE",
    "CANCEL_STALE_MESSAGE",
    "CHECK_AI_UNAVAILABLE_MESSAGE",
    "CHECK_ASK_CATEGORIES_MESSAGE",
    "CHECK_ASK_SOURCE_MESSAGE",
    "CHECK_ASK_TYPES_MESSAGE",
    "CHECK_BROKEN_MESSAGE",
    "CHECK_DELETED_MESSAGE",
    "CHECK_LOST_MESSAGE",
    "CHECK_NO_CATEGORY_MESSAGE",
    "CHECK_QUEUE_EMPTY_MESSAGE",
    "CHECK_SKIPPED_MESSAGE",
    "CHECK_STALE_BUTTON_MESSAGE",
    "CREATING_TABLE_MESSAGE",
    "DIALOG_IN_PROGRESS_MESSAGE",
    "DIALOG_IN_PROGRESS_NO_EXIT_MESSAGE",
    "EMAIL_ADDED_MESSAGE",
    "HELP_COMMANDS_MESSAGE",
    "HELP_MESSAGE",
    "MENU_MESSAGE",
    "SETTINGS_ADMIN_MESSAGE",
    "SETTINGS_STUB_MESSAGE",
    "SYNC_REQUESTED_MESSAGE",
    "TABLE_UNLINKED_MESSAGE",
    "UNKNOWN_MESSAGE",
    "UNLINK_CANCELLED_MESSAGE",
    "WELCOME_MESSAGE",
]
