"""Тесты диалога разбора чека.

Ни сети, ни Redis, ни Telegram: api и модель подменены фейками, состояние — в
`MemoryStorage`. Предмет проверки — то, ради чего диалог и переписан:

* очередь не зацикливается, а пропущенный чек возвращается следующей сессией;
* правка типа у **уже знакомого** товара доезжает до `commit` (в старой версии
  она молча терялась);
* отказ модели не роняет диалог и не оставляет пользователя в состоянии.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message
from aiogram.types import User as TelegramUser
from dateutil.relativedelta import relativedelta

from telegram_bot.access import AccessGuard
from telegram_bot.ai import AiClient, AiUnavailableError, LlmUsage
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.checks import CommitItem, NewProductType
from telegram_bot.api_client.errors import ApiUnavailableError, ApiValidationError
from telegram_bot.api_client.models import (
    CashedRecord,
    Category,
    Check,
    CheckKind,
    LlmEntityKind,
    LlmOperation,
    NotificationKind,
    Period,
    PeriodStatus,
    Record,
)
from telegram_bot.checks.models import currency_of
from telegram_bot.commands.cancel import CancelCommand
from telegram_bot.commands.check import CheckCommand
from telegram_bot.commands.check_delete import CheckDeleteCommand
from telegram_bot.commands.check_skip import CheckSkipCommand
from telegram_bot.commands.manager import Manager
from telegram_bot.commands.menu import MenuCommand
from telegram_bot.enums import CommandName
from telegram_bot.errors import DAY_OUTSIDE_PERIOD_REASON
from telegram_bot.i18n import Language, LocaleFormat, t
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.states import States
from tests.telegram_bot.conftest import FakeLanguages, make_category

_USER_ID = 7
_CHAT_ID = 7

#: Надписи кнопок и отказов — из русского каталога: язык тестов бота русский
#: (см. `conftest.py`), а сверять с каталогом надёжнее, чем с копией строки.
CANCEL_BUTTON_TEXT = t("buttons.cancel")
_DONE_BUTTON = t("buttons.check.done")
_BACK_BUTTON = t("buttons.check.back_to_types")
_BACK_TO_CATEGORIES_BUTTON = t("buttons.check.back_to_categories")
SKIP_BUTTON = t("buttons.check.skip")
DELETE_BUTTON = t("buttons.check.delete")
_CONFIRM_BUTTON = t("buttons.check_delete.confirm")
_DECLINE_BUTTON = t("buttons.check_delete.decline")
TABLE_CREATING_MESSAGE = t("errors.table_creating")
_TOKEN = "123456:AAHtesttesttesttesttesttesttesttest"

_FOOD = make_category(category_id=1, title="Еда", associations=["еда", "продукты"])
_FOOD.product_types.append("молочка")
_BASKET = make_category(
    category_id=2, title="НеопределенныеТраты", associations=["прочее"], is_default=True
)


def _payload(*items: tuple[str, int]) -> dict[str, Any]:
    """Сырьё чека ФНС с указанными позициями."""
    return {
        "code": 1,
        "data": {
            "json": {
                "operationType": 1,
                "totalSum": sum(amount for _, amount in items),
                "retailPlace": "Пятёрочка",
                "items": [{"name": name, "sum": amount} for name, amount in items],
            }
        },
    }


def _check(check_id: int, *items: tuple[str, int]) -> Check:
    """Неразобранный чек."""
    return Check(
        id=check_id,
        kind=CheckKind.RU_FNS,
        qr_raw="t=20260725T1507&s=129.90&fn=1&i=1&fp=1",
        raw_payload=_payload(*items),
        fetched_at=datetime(2026, 7, 25, 15, 8, tzinfo=UTC),
    )


class FakeAiogram(AiogramWrapper):
    """Обёртка aiogram без единого обращения к Telegram.

    Наследование, а не утиный фейк: команды типизированы `AiogramWrapper`, и
    подмена обязана оставаться ею же, иначе проверка типов ничего не проверяет.
    """

    def __init__(self) -> None:
        bot = Bot(token=_TOKEN)
        router = Router()
        super().__init__(bot, router, Dispatcher())
        self.sent: list[str] = []
        self.keyboards: list[InlineKeyboardMarkup] = []
        #: Сообщения, у которых сняли клавиатуру.
        self.cleared: list[int] = []

    async def answer_message(self, message: Message, text: str) -> Message:
        self.sent.append(text)
        return message

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        keyboard: InlineKeyboardMarkup | None = None,
        parse_mode: str | None = None,
    ) -> Message:
        self.sent.append(text)
        if keyboard is not None:
            self.keyboards.append(keyboard)
        return _message(text)

    async def clear_keyboard(self, chat_id: int, message_id: int) -> None:
        """Гасит клавиатуру: помнит, у какого сообщения её сняли."""
        self.cleared.append(message_id)

    async def answer_callback(self, callback: CallbackQuery, text: str | None = None) -> None:
        if text is not None:
            self.sent.append(text)

    @property
    def last(self) -> str:
        """Последнее отправленное сообщение."""
        return self.sent[-1] if self.sent else ""

    def said(self, fragment: str) -> bool:
        """Было ли сказано что-то, содержащее фрагмент."""
        return any(fragment in text for text in self.sent)

    def button_data(self, label: str) -> str:
        """`callback_data` кнопки с такой надписью на последней клавиатуре.

        По надписи, а не по месту в ряду: рядов теперь несколько, и «Готово»
        уже не единственная кнопка блока.
        """
        for row in self.keyboards[-1].inline_keyboard:
            for button in row:
                if button.text == label:
                    return button.callback_data or ""
        raise AssertionError(f"Кнопки «{label}» нет на последней клавиатуре")

    def labels(self) -> list[str]:
        """Надписи кнопок последней клавиатуры, сверху вниз."""
        return [
            button.text for row in self.keyboards[-1].inline_keyboard for button in row
        ]

    def rows(self) -> list[list[str]]:
        """Надписи последней клавиатуры, разложенные по рядам."""
        return [[button.text for button in row] for row in self.keyboards[-1].inline_keyboard]


class FakeSpreadsheets:
    """Клиент документов: один пользователь, один документ.

    `google_id` пуст — документ ещё создаётся: строки в базе есть, а таблицы в
    Google нет.
    """

    def __init__(self, google_id: str = "google-1") -> None:
        self._google_id = google_id

    async def by_telegram_id(self, telegram_id: int) -> Any:
        from telegram_bot.api_client.models import Spreadsheet

        return Spreadsheet(
            id=10,
            google_spreadsheet_id=self._google_id,
            title="Тест",
            reset_day=15,
            timezone="Europe/Moscow",
        )


class FakeCatalog:
    """Справочник документа."""

    def __init__(self, categories: list[Category]) -> None:
        self._categories = categories

    async def categories(self, spreadsheet_id: int, *, only_active: bool = True) -> list[Category]:
        return list(self._categories)


class FakeChecks:
    """Очередь чеков, кэш типов и запись."""

    def __init__(self, checks: list[Check], cached: dict[str, str]) -> None:
        self.checks = checks
        self.cached = cached
        self.committed: list[dict[str, Any]] = []
        self.deleted: list[int] = []
        #: Отказ, который `commit` бросит один раз вместо записи. Одноразовый
        #: намеренно: проверять восстановление после отказа имеет смысл только
        #: тогда, когда следующая попытка проходит.
        self.commit_error: Exception | None = None
        #: Обращения к очереди. Нужны одному тесту: api отдаёт её и неготовому
        #: документу, и не дойти до неё должен сам бот.
        self.listed: list[int] = []

    async def list_unprocessed(self, spreadsheet_id: int) -> list[Check]:
        self.listed.append(spreadsheet_id)
        return [check for check in self.checks if check.processed_at is None]

    async def delete(self, spreadsheet_id: int, check_id: int) -> None:
        self.deleted.append(check_id)
        self.checks = [check for check in self.checks if check.id != check_id]

    async def cashed_records(self, spreadsheet_id: int) -> list[CashedRecord]:
        return [
            CashedRecord(id=index, product_name=name, product_type=product_type)
            for index, (name, product_type) in enumerate(self.cached.items(), 1)
        ]

    async def commit(
        self,
        spreadsheet_id: int,
        *,
        check_id: int,
        items: Any,
        new_product_types: Any = (),
        added_at: date | None = None,
    ) -> list[Record]:
        if self.commit_error is not None:
            error, self.commit_error = self.commit_error, None
            raise error
        self.committed.append(
            {
                "check_id": check_id,
                "items": list(items),
                "new_product_types": list(new_product_types),
                "added_at": added_at,
            }
        )
        self.checks = [check for check in self.checks if check.id != check_id]
        return [
            Record(
                id=index,
                period_id=1,
                category_id=item.category_id,
                amount=-item.amount,
                currency=currency_of(CheckKind.RU_FNS),
                added_at=datetime(2026, 7, 26, tzinfo=UTC).date(),
                notes="",
                from_check=True,
            )
            for index, item in enumerate(items, 1)
        ]


class FakeLlmUsages:
    """Учёт обращений к модели: запоминает замеры либо отказывает."""

    def __init__(self, *, broken: bool = False) -> None:
        self.broken = broken
        self.recorded: list[dict[str, Any]] = []

    async def record(
        self,
        spreadsheet_id: int,
        *,
        usage: LlmUsage,
        operation: LlmOperation,
        entity_kind: LlmEntityKind | None = None,
        entity_id: int | None = None,
    ) -> None:
        if self.broken:
            raise ApiUnavailableError(503, code="unavailable", details={})
        self.recorded.append(
            {
                "spreadsheet_id": spreadsheet_id,
                "operation": operation,
                "entity_kind": entity_kind,
                "entity_id": entity_id,
                "usage": usage,
            }
        )


class FakePeriods:
    """Текущий период документа.

    Окно строится от **настоящего** сегодня, а не от даты, которой харнесс
    подписывает сообщения. Иначе умолчание стадии дня — сегодня, прижатое к
    границам, — упиралось бы в край зашитого окна, и проверки начинали бы
    врать в зависимости от дня прогона.

    Границы считаются по тому же `reset_day=15`, что отдаёт `FakeSpreadsheets`,
    так что окно всегда содержит сегодня и всегда длиной ровно месяц.
    """

    def __init__(self) -> None:
        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
        start = today.replace(day=15)
        if today.day < 15:
            start -= relativedelta(months=1)
        self.start_date = start
        self.end_date = start + relativedelta(months=1)
        #: Обращения за периодом. Нужны тестам восстановления после отказа: там
        #: важно, что границы перечитаны, а не взяты из черновика.
        self.asked: list[int] = []

    async def current(self, spreadsheet_id: int) -> Period:
        self.asked.append(spreadsheet_id)
        return Period(
            id=1,
            start_date=self.start_date,
            end_date=self.end_date,
            status=PeriodStatus.OPEN,
        )

    def day_of(self, number: int) -> date:
        """Дата внутри окна по числу месяца — то же, что считает бот."""
        for shift in range((self.end_date - self.start_date).days):
            day = self.start_date + timedelta(days=shift)
            if day.day == number:
                return day
        raise AssertionError(f"дня {number} нет в окне периода")


class FakeApi:
    """Шлюз api целиком."""

    def __init__(
        self,
        checks: FakeChecks,
        catalog: FakeCatalog,
        llm_usages: FakeLlmUsages | None = None,
        google_id: str = "google-1",
    ) -> None:
        self.spreadsheets = FakeSpreadsheets(google_id)
        self.catalog = catalog
        self.checks = checks
        self.periods = FakePeriods()
        self.llm_usages = llm_usages or FakeLlmUsages()


def make_usage(total_tokens: int = 30, cost: str | None = "0.0004212") -> LlmUsage:
    """Замер, какой отдал бы провайдер."""
    return LlmUsage(
        model="anthropic/claude-sonnet-4.5",
        prompt_tokens=total_tokens - 10,
        completion_tokens=10,
        total_tokens=total_tokens,
        cost=Decimal(cost) if cost is not None else None,
        raw={"total_tokens": total_tokens, "cost": cost},
    )


class FakeAi:
    """Модель: заранее заданные ответы либо отказ.

    Отдаёт пару «ответ + замер» ровно как настоящий клиент: замер уезжает в
    учёт наружу, а не пишется внутри клиента.
    """

    def __init__(
        self,
        types: dict[int, str] | None = None,
        categories: dict[int, str] | None = None,
        *,
        broken: bool = False,
        usage: LlmUsage | None = None,
    ) -> None:
        self.types = types or {}
        self.categories = categories or {}
        self.broken = broken
        #: Замер, который «провайдер» вернул вместе с ответом. `None`
        #: означает, что не вернул вовсе, — учитывать тогда нечего.
        self.usage: LlmUsage | None = usage if usage is not None else make_usage()
        self.type_calls: list[list[str]] = []
        self.category_calls: list[list[str]] = []
        #: Язык, на котором просили новые типы, и корзина, названная модели.
        self.type_languages: list[Language] = []
        self.default_categories: list[str | None] = []

    async def suggest_types(
        self,
        products: Any,
        known_types: Any,
        *,
        language: Language,
    ) -> tuple[dict[int, str], LlmUsage | None]:
        if self.broken:
            raise AiUnavailableError("нет связи")
        self.type_calls.append(list(products))
        self.type_languages.append(language)
        return dict(self.types), self.usage

    async def suggest_categories(
        self,
        product_types: Any,
        categories: Any,
        *,
        default_category: str | None = None,
    ) -> tuple[dict[int, str], LlmUsage | None]:
        if self.broken:
            raise AiUnavailableError("нет связи")
        self.category_calls.append(list(product_types))
        self.default_categories.append(default_category)
        return dict(self.categories), self.usage


class FakeCatchUp:
    """Дочитка уведомлений: в этих тестах ей нечего доставлять."""

    #: Что дочитка отдаёт вызывающему. По умолчанию — ничего: почти каждому
    #: тесту доставлять нечего, а `TABLE_READY` подставляют те, кто проверяет
    #: меню после готовности таблицы.
    delivered: tuple[NotificationKind, ...] = ()

    async def deliver(self, spreadsheet_id: int, chat_id: int) -> list[NotificationKind]:
        return list(self.delivered)


def _message(text: str) -> Message:
    """Сообщение от пользователя."""
    return Message(
        message_id=1,
        date=datetime(2026, 7, 26, tzinfo=UTC),
        chat=Chat(id=_CHAT_ID, type="private"),
        from_user=TelegramUser(id=_USER_ID, is_bot=False, first_name="Тест"),
        text=text,
    )


def _callback(data: str) -> CallbackQuery:
    """Нажатие кнопки «Готово»."""
    return CallbackQuery(
        id="1",
        from_user=TelegramUser(id=_USER_ID, is_bot=False, first_name="Тест"),
        chat_instance="instance",
        data=data,
        message=_message("список"),
    )


class Harness:
    """Собранный диалог: менеджер, команды и фейки под рукой."""

    def __init__(
        self,
        *,
        checks: list[Check],
        cached: dict[str, str] | None = None,
        ai: FakeAi | None = None,
        categories: list[Category] | None = None,
        llm_usages: FakeLlmUsages | None = None,
        google_id: str = "google-1",
    ) -> None:
        self.aiogram = FakeAiogram()
        self.checks = FakeChecks(checks, cached or {})
        self.catalog = FakeCatalog(categories or [_FOOD, _BASKET])
        self.ai = ai or FakeAi()
        self.llm_usages = llm_usages or FakeLlmUsages()
        fake_api = FakeApi(self.checks, self.catalog, self.llm_usages, google_id)
        #: Периоды нужны тестам стадии дня: по ним считается ожидаемая дата и
        #: проверяется, что границы перечитаны, а не взяты из черновика.
        self.periods = fake_api.periods
        api = cast("ApiGateway", fake_api)
        catch_up = cast("NotificationCatchUp", FakeCatchUp())

        self.manager = Manager(AccessGuard(frozenset({_USER_ID})), self.aiogram, FakeLanguages())
        command = CheckCommand(
            self.manager,
            api,
            self.aiogram,
            catch_up,
            cast("AiClient", self.ai),
        )
        arguments = (self.manager, api, self.aiogram, catch_up)
        self.manager.register(
            {
                CommandName.CHECK: command,
                CommandName.CHECK_SKIP: CheckSkipCommand(*arguments, command),
                CommandName.CHECK_DEL: CheckDeleteCommand(*arguments, command),
                # Отмена возвращает в меню, и без него ветка обрывается на
                # полпути — там же, где пользователь ждёт экран.
                CommandName.CANCEL: CancelCommand(*arguments),
                CommandName.MENU: MenuCommand(*arguments),
            }
        )
        self.state = FSMContext(
            storage=MemoryStorage(),
            key=StorageKey(bot_id=1, chat_id=_CHAT_ID, user_id=_USER_ID),
        )

    async def send(self, text: str, name: str = CommandName.CHECK) -> None:
        """Отправляет сообщение пользователя команде."""
        await self.manager.launch(name, _message(text), self.state)

    async def press_done(self) -> None:
        """Нажимает последнюю показанную кнопку «Готово»."""
        await self.press(_DONE_BUTTON)

    async def press(self, label: str) -> None:
        """Нажимает кнопку последнего блока по её надписи.

        Команда находится по префиксу `callback_data` — тем же правилом, по
        которому её находит `main`.
        """
        await self.press_data(self.aiogram.button_data(label))

    async def press_data(self, data: str) -> None:
        """Нажимает кнопку с явной `callback_data`: для устаревших кнопок."""
        prefix = data.split(":", maxsplit=1)[0]
        # Префиксы, не совпадающие с ключом команды: «Готово» и «К типам»
        # обслуживает сам разбор, и `main` разводит их тем же правилом.
        name = CommandName.CHECK if prefix in {"check_done", "check_back"} else prefix
        await self.manager.launch_callback(name, _callback(data), self.state)

    async def current_state(self) -> str | None:
        """Текущее FSM-состояние."""
        return await self.state.get_state()


async def _walk_to_commit(harness: Harness) -> None:
    """Проходит все три стадии без правок: третье «Готово» и записывает чек.

    День не вводится: на стадии дня уже стоит умолчание, и «Готово» принимает
    его, — так проходит и живой пользователь, которого день разбора устраивает.
    """
    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()
    await harness.press_done()


async def test_whole_check_reaches_commit() -> None:
    """Чек проходит обе стадии и уезжает в api одним запросом.

    Тип из кэша берётся без модели, незнакомый — у неё; категорию для нового
    типа спрашивают отдельно и только про сам тип, а не про каждую позицию.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990), ("конфеты", 4000))],
        cached={"молоко": "молочка"},
        ai=FakeAi(types={1: "сладости"}, categories={1: "Еда"}),
    )

    await _walk_to_commit(harness)

    assert harness.ai.type_calls == [["конфеты"]]
    # Новые типы просят на языке пользователя, а не на языке бота.
    assert harness.ai.type_languages == [Language.RU]
    assert harness.ai.category_calls == [["сладости"]]

    committed = harness.checks.committed
    assert len(committed) == 1
    assert committed[0]["check_id"] == 1
    assert committed[0]["items"] == [
        CommitItem(
            product_name="молоко",
            product_type="молочка",
            category_id=_FOOD.id,
            amount=Decimal("89.90"),
        ),
        CommitItem(
            product_name="конфеты",
            product_type="сладости",
            category_id=_FOOD.id,
            amount=Decimal("40.00"),
        ),
    ]
    # «Молочка» у категории уже есть, а «сладости» она видит впервые.
    assert committed[0]["new_product_types"] == [
        NewProductType(category_id=_FOOD.id, product_type="сладости")
    ]
    assert harness.aiogram.said("Записано операций: 2")
    assert await harness.current_state() is None


async def test_both_model_calls_are_accounted() -> None:
    """Каждый вызов модели уезжает в учёт отдельной строкой.

    Две стадии — два разных вопроса с разной ценой, и складывать их в одну
    строку значило бы потерять единственное различие, ради которого учёт и
    ведётся. Замер привязывается к разбираемому чеку: записей реестра в этот
    момент ещё не существует.
    """
    harness = Harness(
        checks=[_check(1, ("конфеты", 4000))],
        ai=FakeAi(types={1: "сладости"}, categories={1: "Еда"}),
    )

    await _walk_to_commit(harness)

    recorded = harness.llm_usages.recorded
    assert [item["operation"] for item in recorded] == [
        LlmOperation.SUGGEST_PRODUCT_TYPES,
        LlmOperation.SUGGEST_CATEGORIES,
    ]
    assert {item["entity_kind"] for item in recorded} == {LlmEntityKind.CHECK}
    assert {item["entity_id"] for item in recorded} == {1}
    assert recorded[0]["spreadsheet_id"] == 10
    assert recorded[0]["usage"].cost == Decimal("0.0004212")


async def test_check_is_parsed_even_if_accounting_fails() -> None:
    """Отказ учёта не роняет разбор: деньги уже потрачены, чек важнее.

    Строка статистики — единственное, что теряется; пользователь не должен
    узнать об этом вовсе.
    """
    harness = Harness(
        checks=[_check(1, ("конфеты", 4000))],
        ai=FakeAi(types={1: "сладости"}, categories={1: "Еда"}),
        llm_usages=FakeLlmUsages(broken=True),
    )

    await _walk_to_commit(harness)

    assert harness.llm_usages.recorded == []
    assert len(harness.checks.committed) == 1
    assert harness.aiogram.said("Записано операций: 1")


async def test_usage_without_cost_is_still_accounted() -> None:
    """Провайдер без цены учитывается по токенам, а не пропускается.

    Пустая стоимость означает «неизвестно»: выбрасывать такую строку значило бы
    занижать сумму ровно на неизвестное.
    """
    harness = Harness(
        checks=[_check(1, ("конфеты", 4000))],
        ai=FakeAi(
            types={1: "сладости"},
            categories={1: "Еда"},
            usage=make_usage(cost=None),
        ),
    )

    await _walk_to_commit(harness)

    assert len(harness.llm_usages.recorded) == 2
    assert harness.llm_usages.recorded[0]["usage"].cost is None


async def test_missing_usage_is_not_recorded() -> None:
    """Ответ без `usage` не порождает строку учёта: учитывать нечего."""
    harness = Harness(
        checks=[_check(1, ("конфеты", 4000))],
        ai=FakeAi(types={1: "сладости"}, categories={1: "Еда"}),
    )
    harness.ai.usage = None

    await _walk_to_commit(harness)

    assert harness.llm_usages.recorded == []
    assert len(harness.checks.committed) == 1


async def test_unavailable_model_is_not_accounted() -> None:
    """Несостоявшийся вызов в учёт не попадает: провайдер за него не выставит счёт."""
    harness = Harness(
        checks=[_check(1, ("конфеты", 4000))],
        ai=FakeAi(broken=True),
    )

    await harness.send("/check")

    assert harness.llm_usages.recorded == []
    assert await harness.current_state() is None


async def test_edited_cached_type_reaches_commit() -> None:
    """Правка типа у знакомого товара доезжает до `commit`.

    Именно это молча терялось в старой версии: тип, исправленный у товара с
    уже распознанным типом, никуда не записывался.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990))],
        cached={"молоко": "молочка"},
        ai=FakeAi(categories={1: "Еда"}),
    )

    await harness.send("/check")
    assert harness.ai.type_calls == []  # товар знаком, модель не звали

    await harness.send("1 - сыры")
    await harness.press_done()
    await harness.press_done()
    await harness.press_done()
    await harness.send("карта")

    items = harness.checks.committed[0]["items"]
    assert [item.product_type for item in items] == ["сыры"]
    assert harness.checks.committed[0]["new_product_types"] == [
        NewProductType(category_id=_FOOD.id, product_type="сыры")
    ]
    assert harness.aiogram.said("Запомнил: молоко → сыры")


async def test_unready_table_stops_before_the_queue() -> None:
    """Пока документа нет, разбор не начинается вовсе.

    Дыра, которую 409 от api не закрывает: очередь чеков он отдаёт и неготовому
    документу — проверка готовности стоит только на записи. Без остановки здесь
    пользователь прошёл бы все три стадии и оплатил бы два вызова модели, чтобы
    получить отказ на последнем шаге.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990))],
        cached={"молоко": "молочка"},
        google_id="",
    )

    await harness.send("/check")

    assert harness.aiogram.said(TABLE_CREATING_MESSAGE)
    assert harness.checks.listed == []
    assert harness.ai.type_calls == []
    assert await harness.current_state() is None


async def test_skipped_check_returns_in_next_session() -> None:
    """Пропуск ничего не сохраняет: чек вернётся при следующем `/check`.

    Список пропущенных живёт в FSM ровно поэтому — без него «следующим»
    бесконечно оказывался бы тот же самый чек.
    """
    harness = Harness(checks=[_check(1, ("молоко", 8990))], cached={"молоко": "молочка"})

    await harness.send("/check")
    await harness.press(SKIP_BUTTON)

    assert harness.checks.deleted == []
    assert harness.checks.committed == []
    assert harness.aiogram.said("Пропущено: 1")
    assert await harness.current_state() is None

    harness.aiogram.sent.clear()
    await harness.send("/check")
    assert harness.aiogram.said("молоко")


async def test_deleted_check_leaves_the_queue() -> None:
    """Кнопка «Удалить» убирает чек и показывает следующий — после вопроса."""
    harness = Harness(
        checks=[_check(1, ("молоко", 8990)), _check(2, ("хлеб", 4000))],
        cached={"молоко": "молочка", "хлеб": "выпечка"},
    )

    await harness.send("/check")
    await harness.press(DELETE_BUTTON)

    # Первое нажатие только спрашивает: кнопка стоит вплотную к «Отложить», и
    # промах между ними означал бы разные вещи.
    assert harness.checks.deleted == []
    assert harness.aiogram.said("Удалить этот чек?")

    await harness.press(_CONFIRM_BUTTON)

    assert harness.checks.deleted == [1]
    assert harness.aiogram.said("хлеб")


async def test_declined_deletion_returns_to_the_stage() -> None:
    """Отказ от удаления возвращает блок стадии, а не оставляет чек без кнопок.

    Подтверждение съело клавиатуру стадии: не вернув её, бот запер бы
    пользователя с чеком, который нельзя ни разобрать, ни бросить.
    """
    harness = Harness(checks=[_check(1, ("молоко", 8990))], cached={"молоко": "молочка"})

    await harness.send("/check")
    await harness.press(DELETE_BUTTON)
    await harness.press(_DECLINE_BUTTON)

    assert harness.checks.deleted == []
    assert await harness.current_state() == States.CHECK_TYPES.state
    assert harness.aiogram.rows() == [
        [_DONE_BUTTON],
        [SKIP_BUTTON, DELETE_BUTTON],
        [CANCEL_BUTTON_TEXT],
    ]


async def test_every_stage_can_drop_the_check() -> None:
    """«Отложить» и «Удалить» есть на каждой стадии, а не только на первой.

    Заметить «этот чек лишний» можно и на категориях: уводить за таким
    решением обратно в начало значило бы просить пройти разбор ещё раз, чтобы
    от него отказаться.
    """
    harness = Harness(checks=[_check(1, ("молоко", 8990))], cached={"молоко": "молочка"})

    await harness.send("/check")
    assert harness.aiogram.rows() == [
        [_DONE_BUTTON],
        [SKIP_BUTTON, DELETE_BUTTON],
        [CANCEL_BUTTON_TEXT],
    ]

    await harness.press_done()
    # На второй стадии появляется возврат — своим рядом под «Готово»: с первой
    # возвращаться некуда, а со второй есть куда.
    assert harness.aiogram.rows() == [
        [_DONE_BUTTON],
        [_BACK_BUTTON],
        [SKIP_BUTTON, DELETE_BUTTON],
        [CANCEL_BUTTON_TEXT],
    ]

    await harness.press_done()
    # На третьей — тот же набор, но возврат ведёт к категориям и называется
    # иначе. «Отложить» и «Удалить» на месте и здесь.
    assert await harness.current_state() == States.CHECK_DAY.state
    assert harness.aiogram.rows() == [
        [_DONE_BUTTON],
        [_BACK_TO_CATEGORIES_BUTTON],
        [SKIP_BUTTON, DELETE_BUTTON],
        [CANCEL_BUTTON_TEXT],
    ]

    await harness.press_done()
    # Стадий три, и «Готово» третьей записывает чек: дальше спрашивать нечего,
    # и ветка кончается вместе с очередью.
    assert harness.checks.committed != []
    assert await harness.current_state() is None


async def test_cancel_leaves_the_check_unprocessed() -> None:
    """«Отмена» выходит из разбора, ничего не записывая и не удаляя."""
    harness = Harness(checks=[_check(1, ("молоко", 8990))], cached={"молоко": "молочка"})

    await harness.send("/check")
    await harness.press(CANCEL_BUTTON_TEXT)

    assert await harness.current_state() is None
    assert harness.checks.committed == []
    assert harness.checks.deleted == []


async def test_model_failure_does_not_trap_the_user() -> None:
    """Отказ модели — сообщение и выход, а не молчание и застрявшее состояние.

    Чек остаётся неразобранным: ничего не записано, и `/check` покажет его
    снова.
    """
    harness = Harness(checks=[_check(1, ("конфеты", 4000))], ai=FakeAi(broken=True))

    await harness.send("/check")

    assert harness.aiogram.said("Подсказки недоступны")
    assert await harness.current_state() is None
    assert harness.checks.committed == []


async def test_button_of_previous_check_is_ignored() -> None:
    """Кнопка от другого чека к текущему не применяется.

    В старой версии callback-обработчики не фильтровались по состоянию, и
    кнопка предыдущего чека оставалась живой.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990)), _check(2, ("хлеб", 4000))],
        cached={"молоко": "молочка", "хлеб": "выпечка"},
    )

    await harness.send("/check")
    stale = harness.aiogram.button_data(_DONE_BUTTON)
    await harness.press(SKIP_BUTTON)

    harness.aiogram.sent.clear()
    await harness.press_data(stale)

    assert harness.aiogram.said("от другого чека")
    assert await harness.current_state() == States.CHECK_TYPES.state


async def test_stale_delete_button_does_not_delete() -> None:
    """Кнопка «Удалить» от прошлого чека не сносит разбираемый сейчас.

    Номер чека едет в `callback_data` каждой кнопки ветки ровно поэтому: без
    него нажатая на прошлом блоке кнопка применилась бы к текущему чеку.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990)), _check(2, ("хлеб", 4000))],
        cached={"молоко": "молочка", "хлеб": "выпечка"},
    )

    await harness.send("/check")
    stale = harness.aiogram.button_data(DELETE_BUTTON)
    await harness.press(SKIP_BUTTON)

    await harness.press_data(stale)

    assert harness.checks.deleted == []
    assert harness.aiogram.said("от другого чека")


async def test_broken_receipt_keeps_delete_reachable() -> None:
    """Нечитаемый чек не выкидывает из разбора: его можно убрать.

    Кнопки живут только внутри состояний разбора, и выйди бот из них — чек
    застрял бы в очереди навсегда. Текст отказа при этом свой: он называет
    причину, которой у общей формулировки нет.
    """
    broken = Check(
        id=1,
        kind=CheckKind.RU_FNS,
        qr_raw="t=20260725T1507&s=1.00&fn=1&i=1&fp=1",
        raw_payload={"code": 1, "data": {}},
        fetched_at=datetime(2026, 7, 25, 15, 8, tzinfo=UTC),
    )
    harness = Harness(checks=[broken])

    await harness.send("/check")
    assert await harness.current_state() == States.CHECK_TYPES.state
    # Разбирать нечего, и «Готово» вести некуда: только судьба чека и выход.
    assert harness.aiogram.rows() == [[SKIP_BUTTON, DELETE_BUTTON], [CANCEL_BUTTON_TEXT]]

    await harness.press(DELETE_BUTTON)
    await harness.press(_CONFIRM_BUTTON)
    assert harness.checks.deleted == [1]


async def test_unknown_category_edit_is_explained() -> None:
    """Правка несуществующей категорией объясняется, а не проглатывается."""
    harness = Harness(
        checks=[_check(1, ("молоко", 8990))],
        cached={"молоко": "молочка"},
        ai=FakeAi(categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.press_done()

    harness.aiogram.sent.clear()
    await harness.send("1 - несуществующая")

    assert harness.aiogram.said("Есть такие:")
    assert await harness.current_state() == States.CHECK_CATEGORIES.state


async def test_menu_button_opens_the_queue() -> None:
    """Кнопка меню «Обработать чеки» начинает сессию так же, как `/check`.

    Черновика в этот момент нет, и спрашивать о нём нельзя: кнопка приходит
    снаружи любого состояния.
    """
    harness = Harness(checks=[_check(1, ("молоко", 8990))], cached={"молоко": "молочка"})

    await harness.press_data(f"{CommandName.CHECK}:run")

    assert harness.aiogram.said("молоко")
    assert await harness.current_state() == States.CHECK_TYPES.state


async def test_menu_returns_when_the_queue_ends() -> None:
    """Конец очереди возвращает в меню, а не оставляет итог без действий."""
    harness = Harness(
        checks=[_check(1, ("молоко", 8990))],
        cached={"молоко": "молочка"},
        ai=FakeAi(categories={1: "Еда"}),
    )

    await _walk_to_commit(harness)

    assert harness.aiogram.said("Записано операций: 1")
    assert harness.aiogram.last == t("text.menu")
    assert await harness.current_state() is None


async def test_empty_queue_also_returns_to_the_menu() -> None:
    """Меню приходит и тогда, когда разбирать было нечего вовсе."""
    harness = Harness(checks=[])

    await harness.send("/check")

    assert harness.aiogram.said(t("text.check_queue_empty"))
    assert harness.aiogram.last == t("text.menu")


async def test_deleted_item_does_not_become_a_record() -> None:
    """«!2» убирает позицию из записи, а сам чек записывается целиком.

    Чек при этом не удаляется и помечается разобранным: сырьё остаётся в базе,
    ключ среди живых строк занят, и повторный скан той же бумажки по-прежнему
    отвергается.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990), ("пакет", 700))],
        cached={"молоко": "молочка", "пакет": "упаковка"},
        ai=FakeAi(categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.send("!2")
    await harness.press_done()
    await harness.press_done()
    await harness.press_done()

    committed = harness.checks.committed
    assert len(committed) == 1
    assert [item.product_name for item in committed[0]["items"]] == ["молоко"]
    assert harness.checks.deleted == []
    assert harness.aiogram.said("Записано операций: 1")


async def test_repeated_bang_returns_the_item() -> None:
    """Повторное «!2» возвращает позицию — с прежним типом и категорией.

    Отдельного синтаксиса возврата нет намеренно: «!2» дважды — это «убрал» и
    «передумал», и второе не должно отправлять позицию выясняться заново.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990), ("пакет", 700))],
        cached={"молоко": "молочка", "пакет": "упаковка"},
        ai=FakeAi(categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.send("!2")
    await harness.send("!2")
    await harness.press_done()
    await harness.press_done()
    await harness.press_done()

    items = harness.checks.committed[0]["items"]
    assert [item.product_name for item in items] == ["молоко", "пакет"]
    assert [item.product_type for item in items] == ["молочка", "упаковка"]


async def test_delete_works_on_the_categories_stage() -> None:
    """Убрать позицию можно и на второй стадии, а не только на первой.

    Заметить лишнюю строку можно в любой момент разбора, и отправлять за этим
    в начало значило бы просить пройти его заново.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990), ("пакет", 700))],
        cached={"молоко": "молочка", "пакет": "упаковка"},
        ai=FakeAi(categories={1: "Еда", 2: "Еда"}),
    )

    await harness.send("/check")
    await harness.press_done()
    await harness.send("!2")
    await harness.press_done()
    await harness.press_done()

    assert [item.product_name for item in harness.checks.committed[0]["items"]] == ["молоко"]


async def test_deleted_item_teaches_nothing() -> None:
    """Удалённая позиция не заводит тип и не попадает в «Запомнил».

    Закрепить за категорией тип ради строки, которой не будет, значило бы
    притянуть по нему следующие чеки.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990), ("конфеты", 4000))],
        cached={"молоко": "молочка"},
        ai=FakeAi(types={1: "сладости"}, categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.send("!2")
    await harness.press_done()
    await harness.press_done()
    await harness.press_done()

    assert harness.checks.committed[0]["new_product_types"] == []
    assert not harness.aiogram.said("Запомнил: конфеты")


async def test_check_without_a_single_item_is_not_recorded_nor_deleted() -> None:
    """Чек, из которого убрали всё, остаётся в очереди.

    Записывать нечего, а удалить — значило бы освободить ключ среди живых
    строк и разрешить той же бумажке отсканироваться заново.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990))],
        cached={"молоко": "молочка"},
        ai=FakeAi(categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.send("!1")
    await harness.press_done()
    await harness.press_done()

    assert harness.checks.committed == []
    assert harness.checks.deleted == []
    assert harness.aiogram.said("записывать нечего")
    assert await harness.current_state() == States.CHECK_CATEGORIES.state
    # Кнопка «Удалить» рядом: убрать чек целиком по-прежнему можно.
    assert DELETE_BUTTON in harness.aiogram.labels()


async def test_back_to_types_does_not_ask_the_model_again() -> None:
    """Возврат к типам ничего не пересчитывает и никуда не ходит.

    Типы у всех позиций уже есть, и звать модель заново значило бы платить за
    то, что и так известно.
    """
    harness = Harness(
        checks=[_check(1, ("конфеты", 4000))],
        ai=FakeAi(types={1: "сладости"}, categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.press_done()
    await harness.press(_BACK_BUTTON)

    assert await harness.current_state() == States.CHECK_TYPES.state
    assert harness.ai.type_calls == [["конфеты"]]
    assert harness.ai.category_calls == [["сладости"]]


async def test_round_trip_recomputes_only_the_changed_type() -> None:
    """Возврат к типам не затирает ручные правки категорий.

    Пересчитывается только позиция, чей тип изменился: остальным категория уже
    выведена из их нынешнего типа, и спрашивать о них модель заново значило бы
    отменить ручной выбор пользователя его же кнопкой «назад».
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990), ("конфеты", 4000))],
        cached={"молоко": "молочка"},
        ai=FakeAi(types={1: "сладости"}, categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.press_done()
    await harness.send("1 - прочее")  # руками: молоко в корзину

    await harness.press(_BACK_BUTTON)
    await harness.send("2 - шоколад")
    await harness.press_done()

    # Про «молочку» модель не спрашивали ни разу: тип закреплён за «Едой».
    assert harness.ai.category_calls == [["сладости"], ["шоколад"]]

    await harness.press_done()
    await harness.press_done()
    items = harness.checks.committed[0]["items"]
    assert [item.category_id for item in items] == [_BASKET.id, _FOOD.id]
    # Корзина типов не получает никогда — даже выбранная руками.
    assert [item.product_type for item in items] == [None, "шоколад"]


async def test_delete_survives_a_failed_category_edit() -> None:
    """Неизвестная категория в одной строке не отменяет удаление в другой.

    Правки применяются только после разбора всех строк: иначе отказ на
    последней оставлял бы первые применёнными и не сохранёнными.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990), ("пакет", 700))],
        cached={"молоко": "молочка", "пакет": "упаковка"},
        ai=FakeAi(categories={1: "Еда", 2: "Еда"}),
    )

    await harness.send("/check")
    await harness.press_done()
    await harness.send("!2\n1 - несуществующая")

    assert harness.aiogram.said("Есть такие:")

    await harness.press_done()
    await harness.press_done()
    # Удаление не применилось: сообщение отвергнуто целиком, обе позиции живы.
    assert [item.product_name for item in harness.checks.committed[0]["items"]] == [
        "молоко",
        "пакет",
    ]


@pytest.mark.parametrize("text", ["", "мусор"])
async def test_bad_edit_keeps_stage(text: str) -> None:
    """Неразобранная правка не меняет ни стадию, ни черновик."""
    harness = Harness(checks=[_check(1, ("молоко", 8990))], cached={"молоко": "молочка"})

    await harness.send("/check")
    await harness.send(text)

    assert await harness.current_state() == States.CHECK_TYPES.state
    assert harness.checks.committed == []


async def test_price_edit_changes_the_recorded_amount() -> None:
    """«1-75» ставит позиции цену, и в запись уходит она, а не цена из чека."""
    harness = Harness(
        checks=[_check(1, ("молоко", 8990), ("пакет", 700))],
        cached={"молоко": "молочка", "пакет": "упаковка"},
        ai=FakeAi(categories={1: "Еда", 2: "Еда"}),
    )

    await harness.send("/check")
    await harness.send("1-75")
    await harness.press_done()
    await harness.press_done()
    await harness.press_done()

    items = harness.checks.committed[0]["items"]
    assert [item.amount for item in items] == [Decimal("75"), Decimal("7.00")]


async def test_price_edit_works_on_the_categories_stage() -> None:
    """Цену можно поправить и на второй стадии, а не только на первой.

    Увидеть неверную сумму можно в любой момент разбора, и отправлять за этим
    в начало значило бы просить пройти его заново.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990))],
        cached={"молоко": "молочка"},
        ai=FakeAi(categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.press_done()
    await harness.send("1-60")
    await harness.press_done()
    await harness.press_done()

    assert [item.amount for item in harness.checks.committed[0]["items"]] == [Decimal("60")]


async def test_price_edit_shows_the_receipt_price_struck_through() -> None:
    """Правленая цена печатается вместе с зачёркнутой ценой из чека.

    Вторая правка подряд не объявляет «исходной» ту, которую ввёл сам
    пользователь: зачёркнутой остаётся цена из чека.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990))],
        cached={"молоко": "молочка"},
        ai=FakeAi(categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.send("1-75")
    assert harness.aiogram.said("<s>89,90 ₽</s> 75,00 ₽")

    await harness.send("1-60")
    assert harness.aiogram.said("<s>89,90 ₽</s> 60,00 ₽")


async def test_typing_the_receipt_price_back_removes_the_mark() -> None:
    """Набранная обратно цена из чека снимает пометку о правке.

    Отдельного синтаксиса «вернуть как было» нет, и набранное обратно число
    обязано значить именно это.
    """
    harness = Harness(
        checks=[_check(1, ("молоко", 8990))],
        cached={"молоко": "молочка"},
        ai=FakeAi(categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.send("1-75")
    await harness.send("1-89,90")

    assert harness.aiogram.said("<b>молочка</b> · 89,90 ₽")
    # Именно в последнем списке: зачёркнутая цена была в предыдущем.
    assert not any("<s>" in text for text in harness.aiogram.sent[-2:])


async def test_price_and_type_are_edited_in_one_message() -> None:
    """«1 - молочка» и «1-75» рядом — обе правки одной позиции применяются."""
    harness = Harness(
        checks=[_check(1, ("молоко", 8990))],
        ai=FakeAi(types={1: "прочее"}, categories={1: "Еда"}),
    )

    await harness.send("/check")
    await harness.send("1 - молочка\n1-75")
    await harness.press_done()
    await harness.press_done()
    await harness.press_done()

    item = harness.checks.committed[0]["items"][0]
    assert item.product_type == "молочка"
    assert item.amount == Decimal("75")


# --- Стадия дня ----------------------------------------------------------


def _at_day_stage(**kwargs: Any) -> Harness:
    """Харнесс с одним знакомым чеком; модель не нужна ни разу."""
    return Harness(
        checks=[_check(1, ("молоко", 8990))],
        cached={"молоко": "молочка"},
        ai=FakeAi(categories={1: "Еда"}),
        **kwargs,
    )


async def test_day_stage_opens_after_categories() -> None:
    """Второе «Готово» не записывает чек, а спрашивает день."""
    harness = _at_day_stage()

    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()

    assert await harness.current_state() == States.CHECK_DAY.state
    assert harness.checks.committed == []


async def test_day_stage_shows_the_inclusive_end_of_the_period() -> None:
    """Границы печатаются включительно: `end_date` исключительна.

    Напечатанная как есть, она рекламировала бы день, который api отвергнет, —
    самая правдоподобная ошибка этой стадии.
    """
    harness = _at_day_stage()
    periods = harness.periods

    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()

    last_day = periods.end_date - timedelta(days=1)
    assert harness.aiogram.said(LocaleFormat.day(last_day))
    assert not harness.aiogram.said(LocaleFormat.day(periods.end_date))


async def test_day_defaults_to_today() -> None:
    """Умолчание стадии — сегодня: чаще всего его и подтверждают."""
    harness = _at_day_stage()
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()

    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()
    await harness.press_done()

    assert harness.checks.committed[0]["added_at"] == today


async def test_typed_day_reaches_commit() -> None:
    """Присланное число уезжает в api датой, а не числом."""
    harness = _at_day_stage()
    expected = harness.periods.day_of(3)

    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()
    await harness.send("3")
    await harness.press_done()

    assert harness.checks.committed[0]["added_at"] == expected


async def test_day_outside_the_period_is_refused() -> None:
    """Число вне периода не записывает чек и не уводит со стадии."""
    harness = _at_day_stage()

    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()
    await harness.send("99")

    assert harness.checks.committed == []
    assert await harness.current_state() == States.CHECK_DAY.state
    # Клавиатура жива: иначе отказ оставлял бы чек без единой кнопки.
    assert harness.aiogram.rows()[0] == [_DONE_BUTTON]


async def test_category_edit_is_refused_on_the_day_stage() -> None:
    """Правка категорий на стадии дня отвергается и ничего не меняет.

    Стадия задаёт один вопрос: принять правку здесь значило бы позволить
    категории уехать после того, как чек показан готовым.
    """
    harness = _at_day_stage()

    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()
    await harness.send("1 - прочее")

    assert harness.checks.committed == []
    assert await harness.current_state() == States.CHECK_DAY.state

    await harness.press_done()
    assert harness.checks.committed[0]["items"][0].category_id == _FOOD.id


async def test_chosen_day_survives_a_trip_back_to_categories() -> None:
    """Возврат к категориям не сбрасывает выбранный день и не зовёт модель."""
    harness = _at_day_stage()
    expected = harness.periods.day_of(3)

    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()
    await harness.send("3")

    calls_before = len(harness.ai.category_calls)
    await harness.press(_BACK_TO_CATEGORIES_BUTTON)
    assert await harness.current_state() == States.CHECK_CATEGORIES.state
    assert len(harness.ai.category_calls) == calls_before

    await harness.press_done()
    await harness.press_done()
    assert harness.checks.committed[0]["added_at"] == expected


async def test_rolled_over_period_resets_the_day_and_keeps_the_check() -> None:
    """Отказ «день вне периода» переспрашивает, а не роняет разбор.

    Так выглядит смена периода посреди разбора: чек не записан, границы
    перечитываются, день сбрасывается на сегодня — иначе следующее «Готово»
    упёрлось бы в тот же отказ.
    """
    harness = _at_day_stage()
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    harness.checks.commit_error = ApiValidationError(
        422,
        code="business_rule",
        details={"reason": DAY_OUTSIDE_PERIOD_REASON},
    )

    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()
    await harness.send("3")

    asked_before = len(harness.periods.asked)
    await harness.press_done()

    assert harness.checks.committed == []
    assert await harness.current_state() == States.CHECK_DAY.state
    # Границы именно перечитаны, а не взяты из черновика.
    assert len(harness.periods.asked) > asked_before

    await harness.press_done()
    assert harness.checks.committed[0]["added_at"] == today


async def test_cancel_leaves_the_day_stage() -> None:
    """«Отмена» выпускает и с третьей стадии.

    Ветка отмены перечисляет свои состояния руками, и забытое в ней состояние
    превращает стадию в ловушку без выхода по кнопке.
    """
    harness = _at_day_stage()

    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()
    await harness.press(CANCEL_BUTTON_TEXT)

    assert await harness.current_state() is None
    assert harness.checks.committed == []
    assert harness.checks.deleted == []


async def test_declined_deletion_redraws_the_day_stage() -> None:
    """Отказ от удаления на стадии дня возвращает её же клавиатуру."""
    harness = _at_day_stage()

    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()
    await harness.press(DELETE_BUTTON)
    await harness.press(t("buttons.check_delete.decline"))

    assert await harness.current_state() == States.CHECK_DAY.state
    assert harness.aiogram.rows() == [
        [_DONE_BUTTON],
        [_BACK_TO_CATEGORIES_BUTTON],
        [SKIP_BUTTON, DELETE_BUTTON],
        [CANCEL_BUTTON_TEXT],
    ]


async def test_readiness_is_checked_before_the_day_is_asked() -> None:
    """Чек без единой позиции упирается в отказ на категориях, а не на дне.

    Проверка стоит на переходе намеренно: чинить её надо на категориях, и
    отказ со стадии дня уводил бы оттуда, куда пользователь только что пришёл.
    """
    harness = _at_day_stage()

    await harness.send("/check")
    await harness.send("!1")
    await harness.press_done()
    await harness.press_done()

    assert await harness.current_state() == States.CHECK_CATEGORIES.state
    assert harness.checks.committed == []
    assert harness.checks.deleted == []
