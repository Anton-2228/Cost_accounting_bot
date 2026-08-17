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

ASK_TITLE_MESSAGE = _load("ASK_TITLE.txt")
ASK_RESET_DAY_MESSAGE = _load("ASK_RESET_DAY.txt")
ASK_TIMEZONE_MESSAGE = _load("ASK_TIMEZONE.txt")
ASK_EMAIL_MESSAGE = _load("ASK_EMAIL.txt")
CREATING_TABLE_MESSAGE = _load("CREATING_TABLE.txt")

ASK_ACCESS_EMAIL_MESSAGE = _load("ASK_ACCESS_EMAIL.txt")
EMAIL_ADDED_MESSAGE = _load("EMAIL_ADDED.txt")
SYNC_REQUESTED_MESSAGE = _load("SYNC_REQUESTED.txt")

ASK_DELETE_CONFIRM_MESSAGE = _load("ASK_DELETE_CONFIRM.txt")
DELETE_CANCELLED_MESSAGE = _load("DELETE_CANCELLED.txt")
TABLE_DELETED_MESSAGE = _load("TABLE_DELETED.txt")

CHECK_QUEUE_EMPTY_MESSAGE = _load("CHECK_QUEUE_EMPTY.txt")
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

CANCELLED_MESSAGE = _load("CANCELLED.txt")
NOTHING_TO_CANCEL_MESSAGE = _load("NOTHING_TO_CANCEL.txt")
UNKNOWN_MESSAGE = _load("UNKNOWN.txt")
DIALOG_IN_PROGRESS_MESSAGE = _load("DIALOG_IN_PROGRESS.txt")

__all__ = [
    "ASK_ACCESS_EMAIL_MESSAGE",
    "ASK_DELETE_CONFIRM_MESSAGE",
    "ASK_EMAIL_MESSAGE",
    "ASK_RESET_DAY_MESSAGE",
    "ASK_TIMEZONE_MESSAGE",
    "ASK_TITLE_MESSAGE",
    "CANCELLED_MESSAGE",
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
    "DELETE_CANCELLED_MESSAGE",
    "DIALOG_IN_PROGRESS_MESSAGE",
    "EMAIL_ADDED_MESSAGE",
    "HELP_COMMANDS_MESSAGE",
    "HELP_MESSAGE",
    "NOTHING_TO_CANCEL_MESSAGE",
    "SYNC_REQUESTED_MESSAGE",
    "TABLE_DELETED_MESSAGE",
    "UNKNOWN_MESSAGE",
]
