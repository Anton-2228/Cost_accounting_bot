"""Тесты входа в бота и экрана меню.

Ни сети, ни Redis, ни Telegram: api подменён фейком, состояние — в
`MemoryStorage`. Предмет проверки — то, ради чего экраны и заводятся:

* мастер создания таблицы начинается только по кнопке, а не первым же
  сообщением бота;
* владелец таблицы попадает сразу в меню — и командой, и старой кнопкой
  «Создать таблицу», пролежавшей в переписке;
* каждая кнопка меню доходит до своей команды, включая те две, что открывают
  диалог;
* ни одна кнопка не осталась без обработчика.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message
from aiogram.types import User as TelegramUser

from telegram_bot.access import AccessGuard
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.errors import ApiNotFoundError
from telegram_bot.api_client.models import Spreadsheet
from telegram_bot.commands.manager import Manager
from telegram_bot.commands.menu import MENU_BUTTONS, MenuCommand
from telegram_bot.commands.settings import SettingsCommand
from telegram_bot.commands.start import CREATE_TABLE_BUTTON, StartCommand
from telegram_bot.commands.table import TableCommand
from telegram_bot.commands.table_email import TableEmailCommand
from telegram_bot.commands.table_sync import TableSyncCommand
from telegram_bot.commands.table_unlink import CONFIRM_WORD, TableUnlinkCommand
from telegram_bot.enums import CommandName
from telegram_bot.errors import NO_TABLE_MESSAGE
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.resources.messages import MENU_MESSAGE, WELCOME_MESSAGE
from telegram_bot.states import States

_USER_ID = 11
_ADMIN_ID = 12
_TOKEN = "123456:AAHtesttesttesttesttesttesttesttest"


def _spreadsheet(*, google_id: str = "google-1") -> Spreadsheet:
    """Таблица пользователя; пустой `google_id` — документ ещё создаётся."""
    return Spreadsheet(
        id=1,
        google_spreadsheet_id=google_id,
        title="Бюджет",
        reset_day=1,
        timezone="Europe/Moscow",
        deleted_at=None,
    )


def _message(text: str, *, user_id: int = _USER_ID) -> Message:
    """Сообщение от пользователя."""
    return Message(
        message_id=1,
        date=datetime(2026, 8, 20, tzinfo=UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=TelegramUser(id=user_id, is_bot=False, first_name="Тест"),
        text=text,
    )


def _callback(data: str, *, user_id: int = _USER_ID, with_message: bool = True) -> CallbackQuery:
    """Нажатие кнопки.

    `with_message=False` — сообщение старше суток: Telegram не прикладывает его
    к нажатию, и отвечать боту некуда.
    """
    return CallbackQuery(
        id="1",
        from_user=TelegramUser(id=user_id, is_bot=False, first_name="Тест"),
        chat_instance="instance",
        data=data,
        message=_message("Меню", user_id=user_id) if with_message else None,
    )


class FakeAiogram(AiogramWrapper):
    """Обёртка aiogram без единого обращения к Telegram.

    Наследование, а не утиный фейк: команды типизированы `AiogramWrapper`, и
    подмена обязана оставаться ею же, иначе проверка типов ничего не проверяет.
    """

    def __init__(self) -> None:
        super().__init__(Bot(token=_TOKEN), Router(), Dispatcher())
        self.sent: list[str] = []
        self.keyboards: list[InlineKeyboardMarkup | None] = []
        self.answered_callbacks = 0

    async def answer_message(self, message: Message, text: str) -> Message:
        self.sent.append(text)
        self.keyboards.append(None)
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
        self.keyboards.append(keyboard)
        return _message(text, user_id=chat_id)

    async def answer_callback(self, callback: CallbackQuery, text: str | None = None) -> None:
        self.answered_callbacks += 1
        if text is not None:
            self.sent.append(text)

    def said(self, fragment: str) -> bool:
        """Было ли сказано что-то, содержащее фрагмент."""
        return any(fragment in text for text in self.sent)

    def buttons(self) -> list[tuple[str, str]]:
        """Кнопки последней показанной клавиатуры, сверху вниз."""
        for keyboard in reversed(self.keyboards):
            if keyboard is not None:
                return [
                    (button.text, button.callback_data or "")
                    for row in keyboard.inline_keyboard
                    for button in row
                ]
        return []

    def rows(self) -> list[int]:
        """Число кнопок в каждом ряду последней клавиатуры."""
        for keyboard in reversed(self.keyboards):
            if keyboard is not None:
                return [len(row) for row in keyboard.inline_keyboard]
        return []


class FakeSpreadsheets:
    """Клиент документов: одна таблица на пользователя либо ни одной."""

    def __init__(self, spreadsheet: Spreadsheet | None) -> None:
        self._spreadsheet = spreadsheet
        self.created: list[dict[str, Any]] = []
        self.synced: list[int] = []
        self.emails: list[tuple[int, str]] = []
        self.deleted: list[int] = []

    async def by_telegram_id(self, telegram_id: int) -> Spreadsheet:
        if self._spreadsheet is None:
            raise ApiNotFoundError(404, code="not_found", details={"resource": "spreadsheet"})
        return self._spreadsheet

    async def create(self, **kwargs: Any) -> Spreadsheet:
        self.created.append(kwargs)
        self._spreadsheet = _spreadsheet(google_id="")
        return self._spreadsheet

    async def request_sync(self, spreadsheet_id: int) -> None:
        self.synced.append(spreadsheet_id)

    async def add_email(self, spreadsheet_id: int, email: str) -> None:
        self.emails.append((spreadsheet_id, email))

    async def delete(self, spreadsheet_id: int) -> None:
        self.deleted.append(spreadsheet_id)


class FakeApi:
    """Шлюз api из единственного клиента, который нужен этим экранам."""

    def __init__(self, spreadsheets: FakeSpreadsheets) -> None:
        self.spreadsheets = spreadsheets


class FakeCatchUp:
    """Дочитка уведомлений: доставлять нечего."""

    async def deliver(self, spreadsheet_id: int, chat_id: int) -> None:
        return None


class Harness:
    """Собранный бот: менеджер, все кнопочные команды и фейки под рукой."""

    def __init__(self, *, spreadsheet: Spreadsheet | None = None) -> None:
        self.aiogram = FakeAiogram()
        self.spreadsheets = FakeSpreadsheets(spreadsheet)
        api = cast("ApiGateway", FakeApi(self.spreadsheets))
        catch_up = cast("NotificationCatchUp", FakeCatchUp())
        access = AccessGuard(frozenset({_USER_ID, _ADMIN_ID}), frozenset({_ADMIN_ID}))

        self.manager = Manager(access, self.aiogram)
        arguments = (self.manager, api, self.aiogram, catch_up)
        menu = MenuCommand(*arguments)
        self.manager.register(
            {
                CommandName.START: StartCommand(*arguments, menu),
                CommandName.MENU: menu,
                CommandName.TABLE: TableCommand(*arguments),
                CommandName.TABLE_SYNC: TableSyncCommand(*arguments),
                CommandName.TABLE_EMAIL: TableEmailCommand(*arguments),
                CommandName.TABLE_UNLINK: TableUnlinkCommand(*arguments),
                CommandName.SETTINGS: SettingsCommand(*arguments, access),
            }
        )
        self._state = FSMContext(
            storage=MemoryStorage(),
            key=StorageKey(bot_id=1, chat_id=_USER_ID, user_id=_USER_ID),
        )

    @property
    def state(self) -> FSMContext:
        """Состояние диалога пользователя."""
        return self._state

    async def command(self, name: str, text: str, *, user_id: int = _USER_ID) -> None:
        """Набирает команду."""
        await self.manager.launch(name, _message(text, user_id=user_id), self._state)

    async def press(self, data: str, *, user_id: int = _USER_ID, with_message: bool = True) -> None:
        """Нажимает кнопку: команда находится по префиксу `callback_data`."""
        name = data.split(":", maxsplit=1)[0]
        await self.manager.launch_callback(
            name, _callback(data, user_id=user_id, with_message=with_message), self._state
        )


class TestEntrance:
    """Вход в бота: приветствие, кнопка и мастер."""

    async def test_new_user_gets_welcome_with_single_button(self) -> None:
        """Новичок видит приветствие и одну кнопку, а не вопрос про название.

        Ровно то, ради чего экран заведён: раньше `/start` первым же сообщением
        спрашивал название таблицы, и отказаться было нельзя.
        """
        harness = Harness()
        await harness.command(CommandName.START, "/start")

        assert harness.aiogram.said(WELCOME_MESSAGE)
        assert harness.aiogram.buttons() == [CREATE_TABLE_BUTTON]
        assert await harness.state.get_state() is None

    async def test_owner_gets_menu_instead_of_welcome(self) -> None:
        """У кого таблица есть, тот попадает сразу в меню."""
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.command(CommandName.START, "/start")

        assert harness.aiogram.said(MENU_MESSAGE)
        assert not harness.aiogram.said(WELCOME_MESSAGE)

    async def test_button_starts_the_wizard(self) -> None:
        """Кнопка задаёт первый вопрос и ставит состояние мастера."""
        harness = Harness()
        await harness.press(CREATE_TABLE_BUTTON[1])

        assert await harness.state.get_state() == States.CREATE_TABLE_TITLE.state
        assert harness.aiogram.said("Как её назвать")
        assert harness.aiogram.answered_callbacks == 1

    async def test_stale_button_shows_menu(self) -> None:
        """Кнопка, нажатая владельцем таблицы, ведёт в меню, а не в мастер.

        Кнопка живёт в переписке дольше экрана: без проверки владелец прошёл бы
        все четыре шага, чтобы на последнем получить от api «таблица уже есть».
        """
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(CREATE_TABLE_BUTTON[1])

        assert harness.aiogram.said(MENU_MESSAGE)
        assert await harness.state.get_state() is None

    async def test_button_without_message_does_nothing(self) -> None:
        """Нажатие сообщения старше суток не ставит состояние.

        Отвечать некуда, а состояние без вопроса оставило бы пользователя перед
        молчащим ботом, который ждёт название таблицы.
        """
        harness = Harness()
        await harness.press(CREATE_TABLE_BUTTON[1], with_message=False)

        assert await harness.state.get_state() is None
        assert harness.aiogram.sent == []

    async def test_wizard_ends_with_menu(self) -> None:
        """Мастер заканчивается меню: ни ссылки, ни справки.

        Ссылки у свежей таблицы всё равно нет — документ создаёт отдельный
        сервис, и адрес приедет уведомлением.
        """
        harness = Harness()
        await harness.press(CREATE_TABLE_BUTTON[1])
        for answer in ("Бюджет", "1", "-", "-"):
            await harness.command(CommandName.START, answer)

        assert harness.spreadsheets.created
        assert harness.aiogram.sent[-1] == MENU_MESSAGE
        assert await harness.state.get_state() is None


class TestMenuScreen:
    """Сам экран меню."""

    async def test_all_buttons_in_one_column(self) -> None:
        """Пять кнопок в заданном порядке, по одной в ряд."""
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.command(CommandName.MENU, "/menu")

        assert harness.aiogram.buttons() == list(MENU_BUTTONS)
        assert harness.aiogram.rows() == [1, 1, 1, 1, 1]

    async def test_without_table_menu_is_refused(self) -> None:
        """Без таблицы меню бессмысленно: все его кнопки работают с документом."""
        harness = Harness()
        await harness.command(CommandName.MENU, "/menu")

        assert harness.aiogram.said(NO_TABLE_MESSAGE)
        assert harness.aiogram.buttons() == []


class TestMenuButtons:
    """Каждая кнопка доходит до своей команды."""

    async def test_table_button_answers_link(self) -> None:
        """«Получить таблицу» — адрес документа."""
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(MENU_BUTTONS[0][1])

        assert harness.aiogram.said("docs.google.com/spreadsheets/d/google-1")

    async def test_sync_button_requests_sync(self) -> None:
        """«Синхронизировать таблицу» ставит задачу api."""
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(MENU_BUTTONS[1][1])

        assert harness.spreadsheets.synced == [1]

    async def test_email_button_opens_dialog(self) -> None:
        """«Дать доступ к таблице» спрашивает почту и ждёт ответа."""
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(MENU_BUTTONS[2][1])

        assert await harness.state.get_state() == States.ADD_EMAIL.state

        await harness.command(CommandName.TABLE_EMAIL, "user@example.com")

        assert harness.spreadsheets.emails == [(1, "user@example.com")]
        assert await harness.state.get_state() is None

    async def test_unlink_button_asks_confirmation(self) -> None:
        """«Отвязать таблицу от бота» отвязывает только после слова-подтверждения."""
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(MENU_BUTTONS[3][1])

        assert await harness.state.get_state() == States.CONFIRM_UNLINK_TABLE.state
        assert harness.spreadsheets.deleted == []

        await harness.command(CommandName.TABLE_UNLINK, CONFIRM_WORD)

        assert harness.spreadsheets.deleted == [1]

    async def test_settings_button_opens_screen(self) -> None:
        """«Настройки» открывает экран настроек — у обычного пользователя заглушку."""
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(MENU_BUTTONS[4][1])

        assert harness.aiogram.said("Настройки")

    @pytest.mark.parametrize("button", [*MENU_BUTTONS, CREATE_TABLE_BUTTON])
    async def test_every_button_answers_the_callback(self, button: tuple[str, str]) -> None:
        """Любое нажатие гасит «часики».

        Без ответа на callback кнопка у пользователя крутится до таймаута
        Telegram, и забыть об этом можно ровно в одной ветке из шести.
        """
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(button[1])

        assert harness.aiogram.answered_callbacks == 1


class TestRouting:
    """Связь кнопок с регистрацией обработчиков."""

    def test_every_button_has_a_handler(self) -> None:
        """У каждой кнопки есть зарегистрированный префикс.

        Кнопка без обработчика не падает и ничего не пишет в журнал — она
        просто крутится у пользователя, поэтому соответствие проверяется тестом,
        а не наблюдением.
        """
        from telegram_bot.main import _BUTTON_PREFIXES

        for _, data in (*MENU_BUTTONS, CREATE_TABLE_BUTTON):
            assert data.startswith(_BUTTON_PREFIXES)

    async def test_button_during_dialog_gets_a_hint(self, monkeypatch: Any) -> None:
        """Нажатие посреди диалога объясняется, а не проглатывается молча."""
        from telegram_bot import main
        from telegram_bot.resources.messages import DIALOG_IN_PROGRESS_MESSAGE

        aiogram = FakeAiogram()
        monkeypatch.setattr(main, "AIOGRAM_WRAPPER", aiogram)

        state = FSMContext(
            storage=MemoryStorage(),
            key=StorageKey(bot_id=1, chat_id=_USER_ID, user_id=_USER_ID),
        )
        await main._on_button_during_dialog(_callback(MENU_BUTTONS[0][1]), state)

        assert aiogram.said(DIALOG_IN_PROGRESS_MESSAGE)
        assert aiogram.answered_callbacks == 1
