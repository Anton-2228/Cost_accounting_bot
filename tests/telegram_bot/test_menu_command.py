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
from telegram_bot.api_client.models import NotificationKind, Spreadsheet
from telegram_bot.commands.cancel import (
    BRANCH_CHECK,
    BRANCH_EMAIL,
    CANCEL_BUTTON_TEXT,
    CancelCommand,
)
from telegram_bot.commands.manager import Manager
from telegram_bot.commands.menu import MENU_BUTTONS, MenuCommand
from telegram_bot.commands.settings import SettingsCommand
from telegram_bot.commands.start import CREATE_TABLE_BUTTON, StartCommand
from telegram_bot.commands.table import TableCommand
from telegram_bot.commands.table_email import TableEmailCommand
from telegram_bot.commands.table_sync import TableSyncCommand
from telegram_bot.commands.table_unlink import CONFIRM_WORD, TableUnlinkCommand
from telegram_bot.enums import CommandName
from telegram_bot.errors import NO_TABLE_MESSAGE, TABLE_CREATING_MESSAGE
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.resources.messages import (
    CANCEL_STALE_MESSAGE,
    CREATING_TABLE_MESSAGE,
    DIALOG_IN_PROGRESS_NO_EXIT_MESSAGE,
    MENU_MESSAGE,
    WELCOME_MESSAGE,
)
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
        #: Сообщения, у которых сняли клавиатуру.
        self.cleared: list[int] = []

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

    async def clear_keyboard(self, chat_id: int, message_id: int) -> None:
        """Гасит клавиатуру: помнит, у какого сообщения её сняли."""
        self.cleared.append(message_id)

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

    #: Что дочитка отдаёт вызывающему. По умолчанию — ничего: почти каждому
    #: тесту доставлять нечего, а `TABLE_READY` подставляют те, кто проверяет
    #: меню после готовности таблицы.
    delivered: tuple[NotificationKind, ...] = ()

    async def deliver(self, spreadsheet_id: int, chat_id: int) -> list[NotificationKind]:
        return list(self.delivered)


class Harness:
    """Собранный бот: менеджер, все кнопочные команды и фейки под рукой."""

    def __init__(self, *, spreadsheet: Spreadsheet | None = None) -> None:
        self.aiogram = FakeAiogram()
        self.spreadsheets = FakeSpreadsheets(spreadsheet)
        self.catch_up = FakeCatchUp()
        api = cast("ApiGateway", FakeApi(self.spreadsheets))
        catch_up = cast("NotificationCatchUp", self.catch_up)
        access = AccessGuard(frozenset({_USER_ID, _ADMIN_ID}), frozenset({_ADMIN_ID}))

        self.manager = Manager(access, self.aiogram)
        arguments = (self.manager, api, self.aiogram, catch_up)
        self.manager.register(
            {
                CommandName.START: StartCommand(*arguments),
                CommandName.MENU: MenuCommand(*arguments),
                CommandName.CANCEL: CancelCommand(*arguments),
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

    async def restart(self, *, user_id: int = _USER_ID) -> None:
        """Набирает `/start` — вход в бота и выход из любого диалога."""
        await self.manager.launch(
            CommandName.START, _message("/start", user_id=user_id), self._state, restart=True
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

    async def test_wizard_ends_with_a_promise_not_a_menu(self) -> None:
        """Мастер заканчивается обещанием: ни ссылки, ни меню.

        Документ создаёт отдельный сервис, и до его появления не работает ни
        одна кнопка экрана. Показать их сейчас значило бы выдать за готовность
        то, что ею ещё не стало, — и первое же нажатие упёрлось бы в отказ.
        """
        harness = Harness()
        await harness.press(CREATE_TABLE_BUTTON[1])
        for answer in ("Бюджет", "1", "-", "-"):
            await harness.command(CommandName.START, answer)

        assert harness.spreadsheets.created
        assert harness.aiogram.sent[-1] == CREATING_TABLE_MESSAGE
        assert not harness.aiogram.said(MENU_MESSAGE)
        assert await harness.state.get_state() is None

    async def test_owner_of_unready_table_waits(self) -> None:
        """Пока документа нет, `/start` обещает, а не показывает меню."""
        harness = Harness(spreadsheet=_spreadsheet(google_id=""))
        await harness.command(CommandName.START, "/start")

        assert harness.aiogram.said(TABLE_CREATING_MESSAGE)
        assert not harness.aiogram.said(MENU_MESSAGE)
        assert not harness.aiogram.said(WELCOME_MESSAGE)

    async def test_stale_button_on_unready_table_waits(self) -> None:
        """И кнопка «Создать таблицу» — тоже: второй таблицы не заводится."""
        harness = Harness(spreadsheet=_spreadsheet(google_id=""))
        await harness.press(CREATE_TABLE_BUTTON[1])

        assert harness.aiogram.said(TABLE_CREATING_MESSAGE)
        assert await harness.state.get_state() is None

    async def test_menu_arrives_when_the_table_gets_ready(self) -> None:
        """`TABLE_READY`, приехавшее дочиткой, дорисовывает меню.

        Второй путь доставки: push мог не пройти, пока бот лежал. Без этого
        пользователь, чьё уведомление приехало дочиткой, остался бы без экрана
        и не знал бы, что его чего-то лишили.
        """
        harness = Harness(spreadsheet=_spreadsheet())
        harness.catch_up.delivered = (NotificationKind.TABLE_READY,)

        await harness.command(CommandName.MENU, "/menu")

        assert harness.aiogram.sent.count(MENU_MESSAGE) == 2

    async def test_start_draws_the_menu_once(self) -> None:
        """`/start` не показывает меню дважды, когда дочитка привезла готовность.

        Он и сам рисует экран по готовности: без отдельного правила пользователь
        получил бы два одинаковых меню подряд.
        """
        harness = Harness(spreadsheet=_spreadsheet())
        harness.catch_up.delivered = (NotificationKind.TABLE_READY,)

        await harness.command(CommandName.START, "/start")

        assert harness.aiogram.sent.count(MENU_MESSAGE) == 1


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

    async def test_unready_table_menu_is_refused(self) -> None:
        """Неготовая таблица для меню — то же, что её отсутствие.

        Api за готовностью сюда не ходит вовсе: `/menu` только ищет документ.
        Без проверки на стороне бота экран нарисовался бы весь, и каждая его
        кнопка упёрлась бы в отказ по отдельности.
        """
        harness = Harness(spreadsheet=_spreadsheet(google_id=""))
        await harness.command(CommandName.MENU, "/menu")

        assert harness.aiogram.said(TABLE_CREATING_MESSAGE)
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

    def test_cancel_is_not_blocked_as_a_menu_button(self) -> None:
        """Префикса «Отмены» нет среди блокируемых кнопок меню.

        Попади он туда — блокировщик отвечал бы «сейчас идёт другой диалог» на
        единственную кнопку, которая должна была из этого диалога выпустить.
        """
        from telegram_bot.main import _BUTTON_PREFIXES

        assert not f"{CommandName.CANCEL}:".startswith(_BUTTON_PREFIXES)

    async def test_button_during_dialog_gets_a_hint(self) -> None:
        """Нажатие посреди диалога объясняется и несёт выход из ветки."""
        from telegram_bot.resources.messages import DIALOG_IN_PROGRESS_MESSAGE

        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(MENU_BUTTONS[2][1])  # «Дать доступ к таблице»
        await harness.manager.launch_callback(
            CommandName.CANCEL, _callback(MENU_BUTTONS[0][1]), harness.state
        )

        assert harness.aiogram.said(DIALOG_IN_PROGRESS_MESSAGE)
        assert CANCEL_BUTTON_TEXT in [text for text, _ in harness.aiogram.buttons()]
        # Диалог цел: подсказка объясняет, а не отменяет за пользователя.
        assert await harness.state.get_state() == States.ADD_EMAIL.state


class TestCancelButton:
    """Кнопка «Отмена» вместо прежней команды `/cancel`."""

    async def test_cancel_closes_the_dialog_and_shows_menu(self) -> None:
        """Отмена снимает состояние и возвращает туда, откуда диалог начали."""
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(MENU_BUTTONS[2][1])

        await harness.press(f"{CommandName.CANCEL}:{BRANCH_EMAIL}")

        assert await harness.state.get_state() is None
        assert harness.aiogram.sent[-1] == MENU_MESSAGE
        assert harness.spreadsheets.emails == []

    async def test_button_of_another_branch_keeps_the_dialog(self) -> None:
        """Кнопка чужой ветки ничего не отменяет.

        Она живёт в переписке дольше своего диалога: без сверки нажатая через
        неделю «Отмена» от почты снесла бы недоразобранный чек.
        """
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(MENU_BUTTONS[2][1])

        await harness.press(f"{CommandName.CANCEL}:{BRANCH_CHECK}")

        assert await harness.state.get_state() == States.ADD_EMAIL.state
        assert harness.aiogram.said(CANCEL_STALE_MESSAGE)

    async def test_cancel_outside_any_dialog_is_explained(self) -> None:
        """Нажатая вне диалога кнопка объясняется, а не молчит."""
        harness = Harness(spreadsheet=_spreadsheet())

        await harness.press(f"{CommandName.CANCEL}:{BRANCH_EMAIL}")

        assert harness.aiogram.said(CANCEL_STALE_MESSAGE)
        assert not harness.aiogram.said(MENU_MESSAGE)


class TestStartAsExit:
    """Набранный `/start` — второй выход из диалога."""

    async def test_start_clears_any_dialog(self) -> None:
        """Из ветки с кнопкой он тоже выпускает: кнопку можно и не найти."""
        harness = Harness(spreadsheet=_spreadsheet())
        await harness.press(MENU_BUTTONS[2][1])

        await harness.restart()

        assert await harness.state.get_state() is None
        assert harness.aiogram.said(MENU_MESSAGE)

    async def test_start_is_the_only_way_out_of_the_wizard(self) -> None:
        """Мастер кнопки не несёт, и выпускает из него только `/start`."""
        harness = Harness()
        await harness.press(CREATE_TABLE_BUTTON[1])
        await harness.command(CommandName.START, "Бюджет")

        assert await harness.state.get_state() == States.CREATE_TABLE_RESET_DAY.state

        await harness.restart()

        assert await harness.state.get_state() is None
        assert harness.aiogram.said(WELCOME_MESSAGE)
        assert harness.spreadsheets.created == []

    async def test_hint_inside_the_wizard_names_start(self) -> None:
        """Подсказка в мастере зовёт `/start`, а не несуществующую кнопку."""
        harness = Harness()
        await harness.press(CREATE_TABLE_BUTTON[1])

        await harness.command(CommandName.CANCEL, "/menu")

        assert harness.aiogram.said(DIALOG_IN_PROGRESS_NO_EXIT_MESSAGE)
        assert CANCEL_BUTTON_TEXT not in [text for text, _ in harness.aiogram.buttons()]
        assert await harness.state.get_state() == States.CREATE_TABLE_TITLE.state
