"""Тесты диалога разбора чека.

Ни сети, ни Redis, ни Telegram: api и модель подменены фейками, состояние — в
`MemoryStorage`. Предмет проверки — то, ради чего диалог и переписан:

* очередь не зацикливается, а пропущенный чек возвращается следующей сессией;
* правка типа у **уже знакомого** товара доезжает до `commit` (в старой версии
  она молча терялась);
* отказ модели не роняет диалог и не оставляет пользователя в состоянии.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message
from aiogram.types import User as TelegramUser

from telegram_bot.access import AccessGuard
from telegram_bot.ai import AiClient, AiUnavailableError, LlmUsage
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.checks import CommitItem, NewProductType
from telegram_bot.api_client.errors import ApiUnavailableError
from telegram_bot.api_client.models import (
    CashedRecord,
    Category,
    Check,
    LlmEntityKind,
    LlmOperation,
    Record,
    Source,
)
from telegram_bot.commands.check import CheckCommand
from telegram_bot.commands.check_delete import CheckDeleteCommand
from telegram_bot.commands.check_skip import CheckSkipCommand
from telegram_bot.commands.manager import Manager
from telegram_bot.enums import CommandName
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.states import States
from tests.telegram_bot.conftest import make_category, make_source

_USER_ID = 7
_CHAT_ID = 7
_TOKEN = "123456:AAHtesttesttesttesttesttesttesttest"

_FOOD = make_category(category_id=1, title="Еда", associations=["еда", "продукты"])
_FOOD.product_types.append("молочка")
_BASKET = make_category(category_id=2, title="НеопределенныеТраты", associations=["прочее"])
_CARD = make_source(source_id=1, title="Карта", associations=["карта"])


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

    def done_callback_data(self) -> str:
        """`callback_data` последней кнопки «Готово»."""
        return self.keyboards[-1].inline_keyboard[0][0].callback_data or ""


class FakeSpreadsheets:
    """Клиент документов: один пользователь, один документ."""

    async def by_telegram_id(self, telegram_id: int) -> Any:
        from telegram_bot.api_client.models import Spreadsheet

        return Spreadsheet(
            id=10,
            google_spreadsheet_id="google-1",
            title="Тест",
            reset_day=15,
            timezone="Europe/Moscow",
        )


class FakeCatalog:
    """Справочники документа."""

    def __init__(self, categories: list[Category], sources: list[Source]) -> None:
        self._categories = categories
        self._sources = sources

    async def categories(self, spreadsheet_id: int, *, only_active: bool = True) -> list[Category]:
        return list(self._categories)

    async def sources(self, spreadsheet_id: int, *, only_active: bool = True) -> list[Source]:
        return list(self._sources)


class FakeChecks:
    """Очередь чеков, кэш типов и запись."""

    def __init__(self, checks: list[Check], cached: dict[str, str]) -> None:
        self.checks = checks
        self.cached = cached
        self.committed: list[dict[str, Any]] = []
        self.deleted: list[int] = []

    async def list_unprocessed(self, spreadsheet_id: int) -> list[Check]:
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
        source_id: int,
        items: Any,
        new_product_types: Any = (),
    ) -> list[Record]:
        self.committed.append(
            {
                "check_id": check_id,
                "source_id": source_id,
                "items": list(items),
                "new_product_types": list(new_product_types),
            }
        )
        self.checks = [check for check in self.checks if check.id != check_id]
        return [
            Record(
                id=index,
                period_id=1,
                category_id=item.category_id,
                source_id=source_id,
                amount=-item.amount,
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
            raise ApiUnavailableError("api недоступен")
        self.recorded.append(
            {
                "spreadsheet_id": spreadsheet_id,
                "operation": operation,
                "entity_kind": entity_kind,
                "entity_id": entity_id,
                "usage": usage,
            }
        )


class FakeApi:
    """Шлюз api целиком."""

    def __init__(
        self,
        checks: FakeChecks,
        catalog: FakeCatalog,
        llm_usages: FakeLlmUsages | None = None,
    ) -> None:
        self.spreadsheets = FakeSpreadsheets()
        self.catalog = catalog
        self.checks = checks
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
        self.usage = usage if usage is not None else make_usage()
        self.type_calls: list[list[str]] = []
        self.category_calls: list[list[str]] = []

    async def suggest_types(
        self,
        products: Any,
        known_types: Any,
    ) -> tuple[dict[int, str], LlmUsage | None]:
        if self.broken:
            raise AiUnavailableError("нет связи")
        self.type_calls.append(list(products))
        return dict(self.types), self.usage

    async def suggest_categories(
        self,
        product_types: Any,
        categories: Any,
    ) -> tuple[dict[int, str], LlmUsage | None]:
        if self.broken:
            raise AiUnavailableError("нет связи")
        self.category_calls.append(list(product_types))
        return dict(self.categories), self.usage


class FakeCatchUp:
    """Дочитка уведомлений: в этих тестах ей нечего доставлять."""

    async def deliver(self, spreadsheet_id: int, chat_id: int) -> None:
        return None


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
    ) -> None:
        self.aiogram = FakeAiogram()
        self.checks = FakeChecks(checks, cached or {})
        self.catalog = FakeCatalog(categories or [_FOOD, _BASKET], [_CARD])
        self.ai = ai or FakeAi()
        self.llm_usages = llm_usages or FakeLlmUsages()
        api = cast("ApiGateway", FakeApi(self.checks, self.catalog, self.llm_usages))
        catch_up = cast("NotificationCatchUp", FakeCatchUp())

        self.manager = Manager(AccessGuard(frozenset({_USER_ID})), self.aiogram)
        command = CheckCommand(
            self.manager,
            api,
            self.aiogram,
            catch_up,
            cast("AiClient", self.ai),
        )
        self.manager.register(
            {
                CommandName.CHECK: command,
                CommandName.CHECK_SKIP: CheckSkipCommand(
                    self.manager, api, self.aiogram, catch_up, command
                ),
                CommandName.CHECK_DEL: CheckDeleteCommand(
                    self.manager, api, self.aiogram, catch_up, command
                ),
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
        await self.manager.launch_callback(
            CommandName.CHECK,
            _callback(self.aiogram.done_callback_data()),
            self.state,
        )

    async def current_state(self) -> str | None:
        """Текущее FSM-состояние."""
        return await self.state.get_state()


async def _walk_to_commit(harness: Harness, source: str = "карта") -> None:
    """Проходит все три стадии без правок."""
    await harness.send("/check")
    await harness.press_done()
    await harness.press_done()
    await harness.send(source)


async def test_whole_check_reaches_commit() -> None:
    """Чек проходит три стадии и уезжает в api одним запросом.

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
    assert harness.ai.category_calls == [["сладости"]]

    committed = harness.checks.committed
    assert len(committed) == 1
    assert committed[0]["check_id"] == 1
    assert committed[0]["source_id"] == _CARD.id
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
    await harness.send("карта")

    items = harness.checks.committed[0]["items"]
    assert [item.product_type for item in items] == ["сыры"]
    assert harness.checks.committed[0]["new_product_types"] == [
        NewProductType(category_id=_FOOD.id, product_type="сыры")
    ]
    assert harness.aiogram.said("Запомнил: молоко → сыры")


async def test_skipped_check_returns_in_next_session() -> None:
    """Пропуск ничего не сохраняет: чек вернётся при следующем `/check`.

    Список пропущенных живёт в FSM ровно поэтому — без него «следующим»
    бесконечно оказывался бы тот же самый чек.
    """
    harness = Harness(checks=[_check(1, ("молоко", 8990))], cached={"молоко": "молочка"})

    await harness.send("/check")
    await harness.send("/check_skip", CommandName.CHECK_SKIP)

    assert harness.checks.deleted == []
    assert harness.checks.committed == []
    assert harness.aiogram.said("Пропущено: 1")
    assert await harness.current_state() is None

    harness.aiogram.sent.clear()
    await harness.send("/check")
    assert harness.aiogram.said("молоко")


async def test_deleted_check_leaves_the_queue() -> None:
    """`/check_del` убирает чек и показывает следующий."""
    harness = Harness(
        checks=[_check(1, ("молоко", 8990)), _check(2, ("хлеб", 4000))],
        cached={"молоко": "молочка", "хлеб": "выпечка"},
    )

    await harness.send("/check")
    await harness.send("/check_del", CommandName.CHECK_DEL)

    assert harness.checks.deleted == [1]
    assert harness.aiogram.said("хлеб")


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
    stale = harness.aiogram.done_callback_data()
    await harness.send("/check_skip", CommandName.CHECK_SKIP)

    harness.aiogram.sent.clear()
    await harness.manager.launch_callback(CommandName.CHECK, _callback(stale), harness.state)

    assert harness.aiogram.said("от другого чека")
    assert await harness.current_state() == States.CHECK_TYPES.state


async def test_broken_receipt_keeps_delete_reachable() -> None:
    """Нечитаемый чек не выкидывает из разбора: его можно убрать.

    Иначе `/check_del` был бы недоступен — он зарегистрирован только внутри
    состояний разбора, — и чек застрял бы в очереди навсегда.
    """
    broken = Check(
        id=1,
        qr_raw="t=20260725T1507&s=1.00&fn=1&i=1&fp=1",
        raw_payload={"code": 1, "data": {}},
        fetched_at=datetime(2026, 7, 25, 15, 8, tzinfo=UTC),
    )
    harness = Harness(checks=[broken])

    await harness.send("/check")
    assert harness.aiogram.said("/check_del")
    assert await harness.current_state() == States.CHECK_TYPES.state

    await harness.send("/check_del", CommandName.CHECK_DEL)
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


@pytest.mark.parametrize("text", ["", "мусор"])
async def test_bad_edit_keeps_stage(text: str) -> None:
    """Неразобранная правка не меняет ни стадию, ни черновик."""
    harness = Harness(checks=[_check(1, ("молоко", 8990))], cached={"молоко": "молочка"})

    await harness.send("/check")
    await harness.send(text)

    assert await harness.current_state() == States.CHECK_TYPES.state
    assert harness.checks.committed == []
