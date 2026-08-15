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
