"""Тесты `/settings`: роли на экране и отчёт о тратах на модель.

Ни сети, ни Redis, ни Telegram: api подменён фейком, состояние — в
`MemoryStorage`. Предмет проверки — то, ради чего команда и заводится:

* админская ветка закрыта и командой, и кнопкой;
* траты раскладываются по периодам **в часовом поясе таблицы**, а не по UTC;
* вызов без известной цены не превращается в бесплатный;
* сумма строк отчёта сходится с итогом.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

from aiogram import Bot, Dispatcher, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message
from aiogram.types import User as TelegramUser

from telegram_bot.access import ACCESS_DENIED_MESSAGE, AccessGuard
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.errors import ApiNotFoundError
from telegram_bot.api_client.models import (
    LlmOperation,
    LlmUsage,
    NotificationKind,
    Period,
    PeriodStatus,
    Spreadsheet,
)
from telegram_bot.commands.manager import Manager
from telegram_bot.commands.settings import LLM_COSTS_BUTTON, SettingsCommand
from telegram_bot.commands.settings_llm import SettingsLlmCostsCommand
from telegram_bot.enums import CommandName
from telegram_bot.formatting import LlmUsageFormatter, SpreadsheetUsage
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.states import States

_ADMIN_ID = 7
_USER_ID = 8
_TARGET_ID = 555
_TOKEN = "123456:AAHtesttesttesttesttesttesttesttest"

#: Пояс с ненулевым смещением обязателен: на UTC различие между «датой в поясе
#: таблицы» и «датой метки времени» не проявилось бы вовсе, и тест проходил бы
#: при любой из двух логик.
_MOSCOW = "Europe/Moscow"


def _spreadsheet(
    spreadsheet_id: int = 1,
    *,
    title: str = "Бюджет",
    timezone: str = _MOSCOW,
    deleted: bool = False,
) -> Spreadsheet:
    """Таблица пользователя; `deleted` делает её отвязанной."""
    return Spreadsheet(
        id=spreadsheet_id,
        google_spreadsheet_id="google-1",
        title=title,
        reset_day=15,
        timezone=timezone,
        deleted_at=datetime(2026, 8, 1, tzinfo=UTC) if deleted else None,
    )


def _period(period_id: int = 1) -> Period:
    """Период 15.07–14.08 включительно (`end_date` исключительна)."""
    return Period(
        id=period_id,
        start_date=date(2026, 7, 15),
        end_date=date(2026, 8, 15),
        status=PeriodStatus.OPEN,
    )


def _usage(
    usage_id: int,
    moment: datetime,
    *,
    cost: str | None = "0.0100",
    tokens: int = 1000,
) -> LlmUsage:
    """Замер обращения к модели; `cost=None` — цена неизвестна."""
    return LlmUsage(
        id=usage_id,
        operation=LlmOperation.SUGGEST_PRODUCT_TYPES,
        model="anthropic/claude-sonnet-4.5",
        prompt_tokens=tokens - 100,
        completion_tokens=100,
        total_tokens=tokens,
        cost=None if cost is None else Decimal(cost),
        created_at=moment,
    )


def _message(text: str, *, user_id: int = _ADMIN_ID) -> Message:
    """Сообщение от пользователя."""
    return Message(
        message_id=1,
        date=datetime(2026, 8, 20, tzinfo=UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=TelegramUser(id=user_id, is_bot=False, first_name="Тест"),
        text=text,
    )


def _callback(data: str, *, user_id: int = _ADMIN_ID) -> CallbackQuery:
    """Нажатие кнопки экрана настроек."""
    return CallbackQuery(
        id="1",
        from_user=TelegramUser(id=user_id, is_bot=False, first_name="Тест"),
        chat_instance="instance",
        data=data,
        message=_message("Настройки", user_id=user_id),
    )


class FakeAiogram(AiogramWrapper):
    """Обёртка aiogram без единого обращения к Telegram.

    Наследование, а не утиный фейк: команды типизированы `AiogramWrapper`, и
    подмена обязана оставаться ею же, иначе проверка типов ничего не проверяет.
    """

    def __init__(self) -> None:
        super().__init__(Bot(token=_TOKEN), Router(), Dispatcher())
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
        return _message(text, user_id=chat_id)

    async def clear_keyboard(self, chat_id: int, message_id: int) -> None:
        """Гасит клавиатуру: помнит, у какого сообщения её сняли."""
        self.cleared.append(message_id)

    async def answer_callback(self, callback: CallbackQuery, text: str | None = None) -> None:
        if text is not None:
            self.sent.append(text)

    def said(self, fragment: str) -> bool:
        """Было ли сказано что-то, содержащее фрагмент."""
        return any(fragment in text for text in self.sent)

    def last_callback_data(self) -> str:
        """`callback_data` последней показанной кнопки."""
        if not self.keyboards:
            return ""
        return self.keyboards[-1].inline_keyboard[0][0].callback_data or ""


class FakeSpreadsheets:
    """Клиент документов: история пользователей по telegram_id."""

    def __init__(self, spreadsheets: dict[int, list[Spreadsheet]]) -> None:
        self._spreadsheets = spreadsheets
        self.asked: list[int] = []

    async def list_by_telegram_id(self, telegram_id: int) -> list[Spreadsheet]:
        self.asked.append(telegram_id)
        if telegram_id not in self._spreadsheets:
            raise ApiNotFoundError(404, code="not_found", details={"resource": "user"})
        return self._spreadsheets[telegram_id]


class FakePeriods:
    """Клиент периодов."""

    def __init__(self, periods: dict[int, list[Period]]) -> None:
        self._periods = periods

    async def list_for_spreadsheet(self, spreadsheet_id: int) -> list[Period]:
        return self._periods.get(spreadsheet_id, [])


class FakeLlmUsages:
    """Клиент замеров."""

    def __init__(self, usages: dict[int, list[LlmUsage]]) -> None:
        self._usages = usages

    async def list_for_spreadsheet(self, spreadsheet_id: int) -> list[LlmUsage]:
        return self._usages.get(spreadsheet_id, [])


class FakeApi:
    """Шлюз api из трёх клиентов, которыми пользуется отчёт."""

    def __init__(
        self,
        spreadsheets: FakeSpreadsheets,
        periods: FakePeriods,
        llm_usages: FakeLlmUsages,
    ) -> None:
        self.spreadsheets = spreadsheets
        self.periods = periods
        self.llm_usages = llm_usages


class FakeCatchUp:
    """Дочитка уведомлений: отчёту доставлять нечего."""

    #: Что дочитка отдаёт вызывающему. По умолчанию — ничего: почти каждому
    #: тесту доставлять нечего, а `TABLE_READY` подставляют те, кто проверяет
    #: меню после готовности таблицы.
    delivered: tuple[NotificationKind, ...] = ()

    async def deliver(self, spreadsheet_id: int, chat_id: int) -> list[NotificationKind]:
        return list(self.delivered)


class Harness:
    """Собранные настройки: менеджер, обе команды и фейки под рукой."""

    def __init__(
        self,
        *,
        spreadsheets: dict[int, list[Spreadsheet]] | None = None,
        periods: dict[int, list[Period]] | None = None,
        usages: dict[int, list[LlmUsage]] | None = None,
    ) -> None:
        self.aiogram = FakeAiogram()
        self.spreadsheets = FakeSpreadsheets(spreadsheets or {})
        api = cast(
            "ApiGateway",
            FakeApi(self.spreadsheets, FakePeriods(periods or {}), FakeLlmUsages(usages or {})),
        )
        catch_up = cast("NotificationCatchUp", FakeCatchUp())
        access = AccessGuard(frozenset({_USER_ID}), frozenset({_ADMIN_ID}))

        self.manager = Manager(access, self.aiogram)
        settings = SettingsCommand(self.manager, api, self.aiogram, catch_up, access)
        self.manager.register(
            {
                CommandName.SETTINGS: settings,
                CommandName.SETTINGS_LLM: SettingsLlmCostsCommand(
                    self.manager, api, self.aiogram, catch_up, settings
                ),
            }
        )
        self._states: dict[int, FSMContext] = {}

    def state(self, user_id: int = _ADMIN_ID) -> FSMContext:
        """Состояние диалога конкретного пользователя."""
        if user_id not in self._states:
            self._states[user_id] = FSMContext(
                storage=MemoryStorage(),
                key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id),
            )
        return self._states[user_id]

    async def open_settings(self, user_id: int = _ADMIN_ID) -> None:
        """Набирает `/settings`."""
        await self.manager.launch(
            CommandName.SETTINGS, _message("/settings", user_id=user_id), self.state(user_id)
        )

    async def press_costs(self, user_id: int = _ADMIN_ID) -> None:
        """Нажимает кнопку «Траты на LLM»."""
        await self.manager.launch_callback(
            CommandName.SETTINGS_LLM,
            _callback(LLM_COSTS_BUTTON[1], user_id=user_id),
            self.state(user_id),
        )

    async def answer(self, text: str, user_id: int = _ADMIN_ID) -> None:
        """Отвечает на вопрос про telegram id."""
        await self.manager.launch(
            CommandName.SETTINGS_LLM, _message(text, user_id=user_id), self.state(user_id)
        )


class TestScreen:
    """Экран настроек у разных ролей."""

    async def test_admin_gets_button(self) -> None:
        """У админа на экране кнопка трат."""
        harness = Harness()
        await harness.open_settings()

        assert harness.aiogram.last_callback_data() == LLM_COSTS_BUTTON[1]

    async def test_ordinary_user_gets_stub(self) -> None:
        """Обычный пользователь видит заглушку и ни одной кнопки.

        Отказом отвечать нечему: `/settings` доступна всем, разным у ролей будет
        содержимое экрана.
        """
        harness = Harness()
        await harness.open_settings(_USER_ID)

        assert harness.aiogram.said("нечего менять")
        assert harness.aiogram.keyboards == []


class TestRoleGuard:
    """Админская ветка закрыта на обоих входах."""

    async def test_dialog_step_is_denied(self) -> None:
        """Шаг ввода id не выполняется обычным пользователем.

        Роль проверяет `Manager` по атрибуту команды, поэтому состояние,
        оставшееся от прежней роли, ветку не открывает: до api дело не доходит.
        """
        harness = Harness(spreadsheets={_TARGET_ID: []})
        await harness.answer(str(_TARGET_ID), _USER_ID)

        assert harness.aiogram.said(ACCESS_DENIED_MESSAGE)
        assert harness.spreadsheets.asked == []

    async def test_button_is_denied(self) -> None:
        """Нажатие кнопки обычным пользователем ничего не открывает.

        Кнопка живёт в переписке дольше команды, и её `callback_data` видна
        клиенту: защита только на стороне команды оставила бы ветку доступной
        нажатием.
        """
        harness = Harness()
        await harness.press_costs(_USER_ID)

        assert harness.aiogram.said(ACCESS_DENIED_MESSAGE)
        assert await harness.state(_USER_ID).get_state() is None


class TestDialog:
    """Диалог ввода telegram id."""

    async def test_button_asks_for_id(self) -> None:
        """Кнопка ставит состояние и задаёт вопрос."""
        harness = Harness()
        await harness.press_costs()

        assert harness.aiogram.said("telegram id")
        assert await harness.state().get_state() == States.SETTINGS_ASK_TELEGRAM_ID.state

    async def test_bad_input_keeps_the_dialog(self) -> None:
        """Опечатка не выкидывает из диалога.

        Админ ошибся в числе, а не передумал: сброс состояния заставлял бы
        начинать с `/settings` из-за одной опечатки.
        """
        harness = Harness()
        await harness.press_costs()
        await harness.answer("не число")

        assert harness.aiogram.said("целое положительное число")
        assert await harness.state().get_state() == States.SETTINGS_ASK_TELEGRAM_ID.state

    async def test_negative_id_is_rejected(self) -> None:
        """Минус означает чат, а не человека: в api за таким не ходят."""
        harness = Harness()
        await harness.press_costs()
        await harness.answer("-100500")

        assert harness.aiogram.said("целое положительное число")
        assert harness.spreadsheets.asked == []

    async def test_unknown_user_is_named(self) -> None:
        """Неизвестный id отличается от «ничего не тратил».

        Спутать их значило бы молча принять опечатку в идентификаторе за ответ.
        """
        harness = Harness(spreadsheets={_TARGET_ID: []})
        await harness.press_costs()
        await harness.answer("999")

        assert harness.aiogram.said("не найден")
        assert await harness.state().get_state() == States.SETTINGS_ASK_TELEGRAM_ID.state

    async def test_report_returns_to_settings(self) -> None:
        """После отчёта диалог закрывается и экран показывается снова."""
        harness = Harness(
            spreadsheets={_TARGET_ID: [_spreadsheet()]},
            periods={1: [_period()]},
            usages={1: [_usage(1, datetime(2026, 7, 20, tzinfo=UTC))]},
        )
        await harness.press_costs()
        await harness.answer(str(_TARGET_ID))

        assert harness.aiogram.said("0,0100 $")
        assert await harness.state().get_state() is None
        assert harness.aiogram.last_callback_data() == LLM_COSTS_BUTTON[1]


class TestReport:
    """Сборка отчёта."""

    def test_usage_belongs_to_the_period_of_the_table_timezone(self) -> None:
        """Границу периода определяет пояс таблицы, а не UTC.

        21:30 UTC 14 июля — это уже 15 июля в Москве, то есть первый день
        периода. По UTC вызов попал бы «вне периодов», и цифра месяца оказалась
        бы занижена — ровно та ошибка, что уже случалась с датой операции.
        """
        report = LlmUsageFormatter.report(
            _TARGET_ID,
            [
                SpreadsheetUsage(
                    spreadsheet=_spreadsheet(),
                    periods=[_period()],
                    usages=[_usage(1, datetime(2026, 7, 14, 21, 30, tzinfo=UTC))],
                )
            ],
        )

        assert "15.07.2026 — 14.08.2026" in report[1]
        assert "вне периодов" not in report[1]

    def test_usage_before_the_first_period_is_kept_apart(self) -> None:
        """Вызов вне периодов попадает в свою строку, а не в чужой месяц.

        20:30 UTC 14 июля — это 23:30 того же дня в Москве, до начала периода.
        """
        report = LlmUsageFormatter.report(
            _TARGET_ID,
            [
                SpreadsheetUsage(
                    spreadsheet=_spreadsheet(),
                    periods=[_period()],
                    usages=[_usage(1, datetime(2026, 7, 14, 20, 30, tzinfo=UTC))],
                )
            ],
        )

        assert "вне периодов" in report[1]

    def test_unknown_cost_is_not_free(self) -> None:
        """Пустая цена считается отдельно, а не нулём.

        Иначе сумма занижалась бы ровно на неизвестное, и отличить «не прислали
        цену» от «вызов был бесплатным» было бы нечем.
        """
        report = LlmUsageFormatter.report(
            _TARGET_ID,
            [
                SpreadsheetUsage(
                    spreadsheet=_spreadsheet(),
                    periods=[_period()],
                    usages=[
                        _usage(1, datetime(2026, 7, 20, tzinfo=UTC), cost="0.0100"),
                        _usage(2, datetime(2026, 7, 20, tzinfo=UTC), cost=None),
                    ],
                )
            ],
        )

        assert "Без известной цены: 1" in report[0]
        assert "0,0100 $" in report[0]
        assert "2 вызовов" in report[0]

    def test_tiny_sum_is_not_shown_as_zero(self) -> None:
        """Сумма меньше шага показа печатается как «менее», а не «0,0000».

        Разбор одного чека стоит доли цента, и ноль рядом с состоявшимся
        вызовом читался бы как сбой учёта.
        """
        report = LlmUsageFormatter.report(
            _TARGET_ID,
            [
                SpreadsheetUsage(
                    spreadsheet=_spreadsheet(),
                    periods=[_period()],
                    usages=[_usage(1, datetime(2026, 7, 20, tzinfo=UTC), cost="0.00001")],
                )
            ],
        )

        assert "менее 0,0001 $" in report[0]

    def test_parts_add_up_to_the_total(self) -> None:
        """Итог равен сумме таблиц, включая отвязанную и бесперодную."""
        report = LlmUsageFormatter.report(
            _TARGET_ID,
            [
                SpreadsheetUsage(
                    spreadsheet=_spreadsheet(1, title="Бюджет"),
                    periods=[_period()],
                    usages=[_usage(1, datetime(2026, 7, 20, tzinfo=UTC), cost="0.2000")],
                ),
                SpreadsheetUsage(
                    spreadsheet=_spreadsheet(2, title="Старая", deleted=True),
                    periods=[],
                    usages=[_usage(2, datetime(2026, 6, 1, tzinfo=UTC), cost="0.1000")],
                ),
            ],
        )

        assert "Итого: 0,3000 $" in report[0]
        assert "из них отвязанных: 1" in report[0]
        assert "(отвязана)" in report[2]
        # У второй таблицы периодов нет вовсе, и её трата не должна пропасть.
        assert "вне периодов: 0,1000 $" in report[2]

    def test_message_per_spreadsheet(self) -> None:
        """Сообщений столько же, сколько таблиц, плюс шапка.

        «Таблицы × периоды» растут с историей, и одно сообщение упёрлось бы в
        лимит Telegram в 4096 символов.
        """
        report = LlmUsageFormatter.report(
            _TARGET_ID,
            [SpreadsheetUsage(_spreadsheet(number), [_period()], []) for number in (1, 2, 3)],
        )

        assert len(report) == 4

    def test_user_without_spreadsheets(self) -> None:
        """Пользователь без таблиц получает одно понятное сообщение."""
        report = LlmUsageFormatter.report(_TARGET_ID, [])

        assert len(report) == 1
        assert "нет ни одной таблицы" in report[0]

    def test_broken_timezone_does_not_lose_the_report(self) -> None:
        """Неизвестный пояс не отменяет отчёт целиком.

        Имя пояса приезжает из своей же базы, и несовпадение с tzdata в
        контейнере — свойство сборки, а не данных: терять из-за него весь отчёт
        не за что.
        """
        report = LlmUsageFormatter.report(
            _TARGET_ID,
            [
                SpreadsheetUsage(
                    spreadsheet=_spreadsheet(timezone="Мордор/Барад-дур"),
                    periods=[_period()],
                    usages=[_usage(1, datetime(2026, 7, 20, tzinfo=UTC))],
                )
            ],
        )

        assert "0,0100 $" in report[0]
