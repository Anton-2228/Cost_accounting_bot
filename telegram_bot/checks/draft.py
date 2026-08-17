"""Черновик разбора чека: то, что живёт между сообщениями диалога.

Черновик целиком лежит в FSM-данных, и больше нигде. Словаря
`self.temp_data[user_id]` на экземпляре команды, как в старой версии, здесь нет
и быть не может: он не чистился при `state.clear()`, тёк на весь срок жизни
процесса и после перезапуска расходился с состоянием.

Отсюда требование к модели: она обязана пережить сериализацию в хранилище
состояний. Поэтому суммы едут строкой (`mode="json"`), а не `Decimal`, — и
превращаются обратно при чтении, ни разу не побывав `float`.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class DraftItem(BaseModel):
    """Одна позиция чека в процессе разбора."""

    model_config = ConfigDict(extra="ignore")

    name: str
    amount: Decimal
    #: Тип, назначенный сейчас: кэшем, моделью или правкой пользователя.
    product_type: str | None = None
    #: Что лежало в кэше на момент показа. Нужно ровно для одного: сказать
    #: «Запомнил: молоко → молочка» только про те позиции, где тип изменился.
    cached_type: str | None = None
    category_id: int | None = None
    category_title: str | None = None
    #: Категория выведена из закреплённого типа, а не подсказана моделью.
    #: Различие видно в списке: проверять глазами стоит только второе.
    category_confirmed: bool = False


class CheckDraft(BaseModel):
    """Разбираемый чек целиком."""

    model_config = ConfigDict(extra="ignore")

    check_id: int
    retail_place: str = ""
    purchased_at: str = ""
    total: Decimal = Decimal("0")
    items: list[DraftItem] = []

    def dump(self) -> dict[str, Any]:
        """Представление для FSM-данных: только то, что переживёт хранилище."""
        return self.model_dump(mode="json")

    @classmethod
    def load(cls, raw: object) -> CheckDraft | None:
        """Восстанавливает черновик из FSM-данных.

        `None`, если данных нет или они не той формы: диалог могли начать до
        перезапуска, и отсутствие ключа — рабочий случай, а не повод уронить
        обработчик.
        """
        if not isinstance(raw, dict):
            return None
        try:
            return cls.model_validate(raw)
        except ValueError:
            return None

    def item(self, number: int) -> DraftItem | None:
        """Позиция по номеру, который видит пользователь (с единицы)."""
        if 1 <= number <= len(self.items):
            return self.items[number - 1]
        return None

    def untyped(self) -> list[int]:
        """Номера позиций без типа."""
        return [number for number, item in enumerate(self.items, 1) if not item.product_type]

    def types(self) -> list[str]:
        """Назначенные типы без повторов, в порядке появления."""
        return list(dict.fromkeys(item.product_type for item in self.items if item.product_type))

    def learned(self) -> Sequence[tuple[str, str]]:
        """Пары «товар → тип», которые кэш увидит впервые или иначе.

        Позиция, чей тип совпал с кэшем, сюда не попадает: сообщать «запомнил»
        о том, что и так было известно, — шум.
        """
        return [
            (item.name, item.product_type)
            for item in self.items
            if item.product_type and item.product_type != item.cached_type
        ]
