"""Подмены внешних зависимостей api.

Внешние клиенты в этом проекте подменяются фейками, а не HTTP-моками: ни
`respx`, ни `pytest-httpx` в зависимостях нет, и заводить их ради одного клиента
незачем — см. `tests/checks_service/fakes.py`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from api.enums import Currency
from api.rates.base import RateUnavailableError


class FakeRateProvider:
    """Источник курсов, отвечающий из заранее заданной таблицы.

    Хранит все запросы: тесты проверяют не только результат, но и **число
    походов**. Дозагрузка курсов обязана ходить один раз на пару «база + день»
    и ни разу — за тем, что уже лежит в кэше; без этой проверки лишний запрос на
    каждую операцию остался бы незамеченным до продакшена.
    """

    def __init__(
        self,
        rates: dict[tuple[Currency, date], dict[Currency, Decimal]] | None = None,
        *,
        default_rate: Decimal | None = None,
    ) -> None:
        self.rates = rates if rates is not None else {}
        #: Курс для пары, которой нет в таблице. `None` — такой пары не бывает,
        #: и запрос о ней должен упасть.
        #:
        #: Дефолт нужен большинству тестов, которые про валюту не написаны
        #: вовсе: лист статистики сводится к евро, поэтому даже проверка знака
        #: у рублёвой операции требует курса. Заряжать его в каждом таком тесте
        #: значило бы утопить их смысл в подготовке.
        self.default_rate = default_rate
        self.calls: list[tuple[Currency, date]] = []
        #: Сколько раз клиент закрывали — чтобы поймать незакрытое соединение.
        self.closed = 0

    def add(self, base: Currency, day: date, quotes: dict[Currency, Decimal]) -> None:
        """Задаёт котировки базовой валюты на день."""
        self.rates[(base, day)] = quotes

    async def rates_on(self, base: Currency, day: date) -> dict[Currency, Decimal]:
        """Котировки из таблицы; отсутствие дня — та же ошибка, что у настоящего."""
        self.calls.append((base, day))
        quotes = self.rates.get((base, day))
        if quotes is not None:
            return dict(quotes)
        if self.default_rate is not None:
            return {
                currency: self.default_rate for currency in Currency if currency is not base
            }
        raise RateUnavailableError(
            "Источник курсов недоступен",
            details={"base": base.value, "day": day.isoformat()},
        )

    async def aclose(self) -> None:
        """Закрывает клиент."""
        self.closed += 1


class BrokenRateProvider:
    """Источник, который всегда недоступен.

    Отдельный класс, а не пустая таблица у :class:`FakeRateProvider`: «курса на
    этот день нет» и «источник лежит» — разные истории, и тест, проверяющий
    падение подсчёта, должен называть ту, которую проверяет.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[Currency, date]] = []

    async def rates_on(self, base: Currency, day: date) -> dict[Currency, Decimal]:
        """Всегда бросает."""
        self.calls.append((base, day))
        raise RateUnavailableError("Источник курсов недоступен")

    async def aclose(self) -> None:
        """Закрывает клиент."""
