"""Промпты модели, поднятые из `.txt` в константы.

Промпты — по-английски, а язык ответа называется в них явно: модель одна на
пять языков интерфейса, и промпт на русском тянул бы её отвечать по-русски
там, где пользователь выбрал хинди. Английский здесь не язык пользователя, а
язык инструкции.

Читаются один раз на импорте и с явным `encoding="utf-8"`: `Path.read_text()`
без кодировки берёт локаль системы.

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

#: Что делать с типом, которому не нашлось категории: уйти в корзину, если она
#: у документа есть, либо взять ближайшую из списка.
CATEGORIES_FALLBACK_RULE = _load("CATEGORIES_FALLBACK.txt")
CATEGORIES_NO_FALLBACK_RULE = _load("CATEGORIES_NO_FALLBACK.txt")

__all__ = [
    "CATEGORIES_FALLBACK_RULE",
    "CATEGORIES_NO_FALLBACK_RULE",
    "CATEGORIES_SYSTEM_PROMPT",
    "CATEGORIES_USER_PROMPT",
    "TYPES_SYSTEM_PROMPT",
    "TYPES_USER_PROMPT",
]
