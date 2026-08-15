"""Подбор категории и счёта по псевдониму."""

from __future__ import annotations

from telegram_bot.api_client.models import Category, Source

_MAX_HINTS = 15


class AssociationMatcher:
    """Сопоставляет слово пользователя с категорией или счётом.

    Подбор остаётся в боте намеренно: только у него есть полные списки — они же
    нужны, чтобы в ответ на опечатку показать, из чего выбирать.

    Первое совпадение и есть ответ. Дублей не бывает: в схеме
    `category_associations (spreadsheet_id, alias)` и `source_associations` —
    UNIQUE с `CHECK alias = lower(alias)`, а пространства имён у категорий и
    счетов раздельные. Старая версия продолжала перебор после совпадения и
    молча брала последний дубль, то есть при коллизии писала операцию не в ту
    категорию, ничего не сообщая.
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
    def source(alias: str, sources: list[Source]) -> Source | None:
        """Счёт по псевдониму или `None`."""
        needle = alias.strip().lower()
        for source in sources:
            if needle in source.associations:
                return source
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
