"""Промпты модели, поднятые из `.txt` в константы.

Читаются один раз на импорте и с явным `encoding="utf-8"` — по той же причине,
что и тексты сообщений: файлы целиком кириллические, а `Path.read_text()` без
кодировки берёт локаль системы.

Промпта «достать реквизиты из текста чека» здесь нет и не будет: реквизиты
разбирает `checks_service/formats/ru_fns/parser.py` из QR-строки. Вместе с этим
вызовом исчез целый класс ошибок — недетерминированный ответ модели на месте
данных, которые лежат в строке готовыми.
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).parent


def _load(name: str) -> str:
    """Читает файл промпта."""
    return (_HERE / name).read_text(encoding="utf-8").strip()


TYPES_SYSTEM_PROMPT = _load("TYPES_SYSTEM.txt")
TYPES_USER_PROMPT = _load("TYPES_USER.txt")

CATEGORIES_SYSTEM_PROMPT = _load("CATEGORIES_SYSTEM.txt")
CATEGORIES_USER_PROMPT = _load("CATEGORIES_USER.txt")

__all__ = [
    "CATEGORIES_SYSTEM_PROMPT",
    "CATEGORIES_USER_PROMPT",
    "TYPES_SYSTEM_PROMPT",
    "TYPES_USER_PROMPT",
]
