"""Тесты `/add`: необязательный день первым аргументом.

Ни сети, ни Redis, ни Telegram: api подменён фейком. Предмет проверки — то, что
появилось вместе с днём и чего не видно в тестах самого разбора:

* день доезжает до api датой, а не числом;
* без дня api получает пустоту и ставит сегодня сам;
* границы периода спрашиваются **только** когда день прислан: `/add` — самая
  частая команда, и лишний круг по сети на каждой трате ничего бы не добавил;
* период, сменившийся между чтением границ и записью, объясняется пользователю.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message
from aiogram.types import User as TelegramUser

from telegram_bot.access import AccessGuard
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.errors import ApiError, ApiValidationError
from telegram_bot.api_client.models import (
    Category,
    CategoryKind,
    Currency,
    Period,
    PeriodStatus,
    Record,
)
from telegram_bot.commands.manager import Manager
from telegram_bot.commands.record_add import RecordAddCommand
from telegram_bot.enums import CommandName
from telegram_bot.errors import DAY_OUTSIDE_PERIOD_REASON
from telegram_bot.i18n import t
from telegram_bot.notifications import NotificationCatchUp
from tests.telegram_bot.conftest import FakeLanguages, make_category
from tests.telegram_bot.test_menu_command import (
    FakeAiogram,
    FakeCatchUp,
    FakeSpreadsheets,
    _spreadsheet,
)

#: Тот же пользователь, что у остальных тестов команд.
_USER_ID = 11

_CATEGORIES = [
    make_category(category_id=1, title="Продукты", associations=["продукты", "еда"]),
    make_category(
        category_id=2,
        title="Зарплата",
        kind=CategoryKind.INCOME,
        associations=["зарплата", "зп"],
    ),
]

#: Период, начинающийся не первого числа: в нём видно, что число месяца
#: разбирается обходом окна, а не приставляется к текущему месяцу.
_PERIOD = Period(
    id=1,
    start_date=date(2026, 7, 25),
    end_date=date(2026, 8, 25),
    status=PeriodStatus.OPEN,
)


def _typed(text: str) -> Message:
    """Набранная пользователем команда."""
    return Message(
        message_id=1,
        date=datetime(2026, 8, 10, tzinfo=UTC),
        chat=Chat(id=_USER_ID, type="private"),
        from_user=TelegramUser(id=_USER_ID, is_bot=False, first_name="Тест"),
        text=text,
    )


class FakeRecords:
    """Записанные операции и то, с чем их просили записать."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        #: Ошибка, которой api ответит на запись.
        self.error: ApiError | None = None

    async def create(self, spreadsheet_id: int, **kwargs: Any) -> Record:
        if self.error is not None:
            raise self.error
        self.created.append(kwargs)
        added_at = kwargs.get("added_at") or date(2026, 8, 10)
        return Record(
            id=42,
            period_id=_PERIOD.id,
            category_id=kwargs["category_id"],
            amount=-kwargs["amount"],
            currency=kwargs["currency"],
            added_at=added_at,
            notes=kwargs["notes"],
        )


#: Окно вокруг **настоящего** сегодня: нужно там, где проверяется запрет
#: датировать вперёд. Зашитое окно `_PERIOD` целиком в прошлом, и завтрашнего
#: дня в нём нет вовсе — отказ пришёл бы не по той причине.
def _live_period() -> Period:
    """Период, начавшийся неделю назад: в нём есть и прошлое, и будущее."""
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    start = today - timedelta(days=7)
    return Period(
        id=2,
        start_date=start,
        end_date=start + timedelta(days=30),
        status=PeriodStatus.OPEN,
    )


class FakePeriods:
    """Границы текущего периода и счётчик походов за ними."""

    def __init__(self, period: Period | None = None) -> None:
        self.calls = 0
        self.period = period if period is not None else _PERIOD

    async def current(self, spreadsheet_id: int) -> Period:
        self.calls += 1
        return self.period


class FakeCatalog:
    """Справочник категорий."""

    async def categories(self, spreadsheet_id: int, *, only_active: bool = True) -> list[Category]:
        return list(_CATEGORIES)


class FakeApi:
    """Шлюз api из клиентов, которые нужны `/add`."""

    def __init__(self, records: FakeRecords, periods: FakePeriods) -> None:  # noqa: D107
        self.spreadsheets = FakeSpreadsheets(_spreadsheet())
        self.records = records
        self.periods = periods
        self.catalog = FakeCatalog()


class Harness:
    """`/add` с подменённым api."""

    def __init__(self, period: Period | None = None) -> None:
        self.aiogram = FakeAiogram()
        self.records = FakeRecords()
        self.periods = FakePeriods(period)
        api = cast("ApiGateway", FakeApi(self.records, self.periods))
        catch_up = cast("NotificationCatchUp", FakeCatchUp())
        access = AccessGuard(frozenset({_USER_ID}), frozenset())
        self.manager = Manager(access, self.aiogram, FakeLanguages())
        self.manager.register(
            {CommandName.ADD: RecordAddCommand(self.manager, api, self.aiogram, catch_up)}
        )
        self.state = FSMContext(
            storage=MemoryStorage(),
            key=StorageKey(bot_id=1, chat_id=_USER_ID, user_id=_USER_ID),
        )

    async def add(self, args: str) -> None:
        """Набирает `/add` с аргументами."""
        command = CommandObject(prefix="/", command=CommandName.ADD, args=args)
        await self.manager.launch(
            CommandName.ADD, _typed(f"/add {args}"), self.state, command=command
        )


class TestDay:
    """День первым словом."""

    async def test_day_reaches_api_as_a_date(self) -> None:
        """До api день доезжает датой периода, а не числом месяца."""
        harness = Harness()
        await harness.add("3 евро 500 еда обед")

        assert harness.records.created == [
            {
                "category_id": 1,
                "amount": Decimal("500"),
                "currency": Currency.EUR,
                "notes": "обед",
                "added_at": date(2026, 8, 3),
            }
        ]

    async def test_day_is_shown_back_to_the_user(self) -> None:
        """В подтверждении стоит выбранный день, а не сегодняшний."""
        harness = Harness()
        await harness.add("3 евро 500 еда")

        assert harness.aiogram.said(t("format.record.date", date="03.08.2026"))

    async def test_without_a_day_the_date_is_left_to_api(self) -> None:
        """Без числа api получает пустоту и ставит сегодня сам."""
        harness = Harness()
        await harness.add("евро 500 еда")

        assert harness.records.created[0]["added_at"] is None


class TestPeriodIsFetchedLazily:
    """Границы периода — только тогда, когда они нужны."""

    async def test_day_needs_the_period(self) -> None:
        harness = Harness()
        await harness.add("3 евро 500 еда")

        assert harness.periods.calls == 1

    @pytest.mark.parametrize("args", ["евро 500 еда", "500 еда обед", "евра 500 еда"])
    async def test_everything_else_does_not(self, args: str) -> None:
        """Ни обычная строка, ни ошибочная за периодом не ходят.

        Строка «500 еда обед» тут не случайна: три цифры днём не считаются, и
        привычный отказ про валюту она получает не заплатив за это кругом по
        сети.
        """
        harness = Harness()
        await harness.add(args)

        assert harness.periods.calls == 0


class TestRefusals:
    """Отказы."""

    async def test_day_outside_the_period_is_not_written(self) -> None:
        """Чужой день — отказ с границами периода, записи нет."""
        harness = Harness()
        await harness.add("0 евро 500 еда")

        assert harness.records.created == []
        assert harness.aiogram.said("25.07.2026")

    async def test_rolled_over_period_is_explained(self) -> None:
        """Период сменился между чтением границ и записью.

        Перерисовывать `/add` нечего — диалога у него нет, и весь ответ на гонку
        это текст общего перехвата ошибок api.
        """
        harness = Harness()
        harness.records.error = ApiValidationError(
            422,
            code="business_rule_violated",
            details={"reason": DAY_OUTSIDE_PERIOD_REASON},
        )
        await harness.add("3 евро 500 еда")

        assert harness.aiogram.said(t("errors.validation.day_outside_period"))


class TestFutureDay:
    """Ненаступивший день.

    Датировать вперёд нельзя не из строгости: лист статистики сводит суммы к
    одной валюте по курсу на день операции, а курса на будущий день нет ни у
    одного источника. Такая операция доехала бы до реестра, а перерисовка листа
    падала бы до самого этого дня — вместе со всеми операциями листа, в том
    числе записанными верно.
    """

    async def test_tomorrow_is_not_written(self) -> None:
        """Завтрашнее число внутри периода отвергается без похода за записью."""
        harness = Harness(_live_period())
        tomorrow = datetime.now(ZoneInfo("Europe/Moscow")).date() + timedelta(days=1)

        await harness.add(f"{tomorrow.day} евро 500 еда")

        assert harness.records.created == []

    async def test_today_is_written(self) -> None:
        """Сегодня — последний допустимый день, а не первый запрещённый."""
        harness = Harness(_live_period())
        today = datetime.now(ZoneInfo("Europe/Moscow")).date()

        await harness.add(f"{today.day} евро 500 еда")

        assert harness.records.created[0]["added_at"] == today

    async def test_yesterday_is_written(self) -> None:
        """Прошлый день периода запрет не трогает — ради него всё и затевалось."""
        harness = Harness(_live_period())
        yesterday = datetime.now(ZoneInfo("Europe/Moscow")).date() - timedelta(days=1)

        await harness.add(f"{yesterday.day} евро 500 еда")

        assert harness.records.created[0]["added_at"] == yesterday
