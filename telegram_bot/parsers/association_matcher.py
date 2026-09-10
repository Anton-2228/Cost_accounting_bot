"""Подбор категории по псевдониму."""

from __future__ import annotations

from telegram_bot.api_client.models import Category

_MAX_HINTS = 15


class AssociationMatcher:
    """Сопоставляет слово пользователя с категорией.

    Подбор остаётся в боте намеренно: только у него есть полный список — он же
    нужен, чтобы в ответ на опечатку показать, из чего выбирать.

    Первое совпадение и есть ответ. Дублей не бывает: в схеме
    `category_associations (spreadsheet_id, alias)` — UNIQUE с
    `CHECK alias = lower(alias)`. Старая версия продолжала перебор после
    совпадения и молча брала последний дубль, то есть при коллизии писала
    операцию не в ту категорию, ничего не сообщая.
    """

    @staticmethod
    def category(alias: str, categories: list[Category]) -> Category | None:
        """Категория по псевдониму или `None`."""
        needle = alias.strip().lower()
        for category in categories:
            if needle in category.associations:
                return category
        return None

    @staticmethod
    def hint(titles: list[str]) -> str:
        """Строка-подсказка «из чего выбирать».

        Список обрезается: у документа с полусотней категорий подсказка иначе
        не поместилась бы в сообщение Telegram, а первые несколько названий уже
        объясняют, что от пользователя хотят.
        """
        if not titles:
            return ""
        shown = ", ".join(titles[:_MAX_HINTS])
        tail = " и другие" if len(titles) > _MAX_HINTS else ""
        return f"{shown}{tail}"
