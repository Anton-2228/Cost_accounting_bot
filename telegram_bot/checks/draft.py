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
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from telegram_bot.api_client.models import Currency


class DraftItem(BaseModel):
    """Одна позиция чека в процессе разбора."""

    model_config = ConfigDict(extra="ignore")

    name: str
    amount: Decimal
    #: Цена из чека, если её правили. `None` — не правили: так пометка о правке
    #: сама исчезает, когда пользователь набрал исходное число обратно, а
    #: черновик, начатый до появления правки цены, читается без миграции.
    original_amount: Decimal | None = None
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
    #: Позиция исключена из записи: операции по ней не будет. Тип и категория
    #: при этом сохраняются — повторное «!1» обязано вернуть позицию готовой,
    #: а не отправить её выясняться к модели заново.
    deleted: bool = False
    #: Тип, из которого выведена текущая категория. По нему возврат к типам
    #: отличает позицию, чей тип изменился, от той, что уже разложена: вторую
    #: пересчитывать нельзя — ручная правка категории иначе затирается.
    category_for_type: str | None = None


class CheckDraft(BaseModel):
    """Разбираемый чек целиком."""

    model_config = ConfigDict(extra="ignore")

    check_id: int
    retail_place: str = ""
    #: Время покупки строкой ISO (`2026-07-25T15:07`). Форматируется при показе,
    #: а не при записи: язык может смениться посреди разбора, а черновик живёт в
    #: FSM дольше одного сообщения.
    purchased_at: str = ""
    total: Decimal = Decimal("0")
    #: Валюта чека: её определяет формат, и в черновик она попадает затем, что
    #: суммы показываются пользователю. `StrEnum` переживает `mode="json"` без
    #: правки `dump`/`load`. Рубль по умолчанию — для черновика сломанного
    #: чека, где формат прочитать не удалось и показывать всё равно нечего.
    currency: Currency = Currency.RUB
    #: День текущего периода, которым датировать операции чека. Настоящая
    #: `date`, а не строка, как `purchased_at` выше: ту бот получает из чека и
    #: только показывает, а эту он сам вычисляет и сам же отправляет в api, и
    #: хранение строкой заставило бы разбирать её дважды. `mode="json"` пишет её
    #: ISO-строкой, `model_validate` читает обратно — `dump`/`load` не в курсе.
    #:
    #: `None` значит «стадия дня ещё не проходилась»; черновик, записанный до
    #: появления стадии, читается с этим значением и без миграции.
    added_at: date | None = None
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

    def alive(self) -> list[DraftItem]:
        """Позиции, которые станут операциями.

        Удалённая позиция остаётся в `items` и остаётся на своём номере: её
        показывают зачёркнутой, и повторное «!1» обязано вернуть ту же самую.
        Из записи она уходит только здесь.
        """
        return [item for item in self.items if not item.deleted]

    def excluded(self) -> list[DraftItem]:
        """Удалённые позиции — для строки-сводки под списком."""
        return [item for item in self.items if item.deleted]

    def untyped(self) -> list[int]:
        """Номера позиций без типа.

        Удалённые считаются наравне с остальными: тип им всё равно нужен —
        вернуть позицию можно в любой момент, и она обязана вернуться готовой.
        """
        return [number for number, item in enumerate(self.items, 1) if not item.product_type]

    def types(self) -> list[str]:
        """Назначенные типы без повторов, в порядке появления."""
        return list(dict.fromkeys(item.product_type for item in self.items if item.product_type))

    def learned(self) -> Sequence[tuple[str, str]]:
        """Пары «товар → тип», которые кэш увидит впервые или иначе.

        Позиция, чей тип совпал с кэшем, сюда не попадает: сообщать «запомнил»
        о том, что и так было известно, — шум. Удалённая не попадает тем более:
        её никто не записывал, и кэш на стороне api о ней не узнает.
        """
        return [
            (item.name, item.product_type)
            for item in self.alive()
            if item.product_type and item.product_type != item.cached_type
        ]
