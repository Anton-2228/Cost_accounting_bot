"""Тесты выбора языка: раскладка, `/start`, настройки и границы.

Выбор языка — единственный экран, который бот показывает раньше, чем знает язык
человека, и единственный, после которого меняется язык всего остального.
Поэтому проверяется и сама клавиатура, и то, что после выбора бот продолжает
на новом языке и ровно там, откуда пришли.
"""

from __future__ import annotations

from typing import cast

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from telegram_bot.access import ACCESS_DENIED_MESSAGE, AccessGuard
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.errors import ApiNotFoundError, ApiUnavailableError
from telegram_bot.commands import language_picker
from telegram_bot.commands.language import LanguageCommand
from telegram_bot.commands.language_picker import ORIGINS, PickerAction
from telegram_bot.commands.manager import Manager
from telegram_bot.commands.menu import MenuCommand
from telegram_bot.commands.settings import LLM_COSTS_DATA, SettingsCommand
from telegram_bot.commands.start import StartCommand
from telegram_bot.enums import CommandName
from telegram_bot.i18n import NATIVE_LABELS, PICKER_ORDER, Language, t_in
from telegram_bot.i18n import language as i18n_language
from telegram_bot.languages import LanguageStore, UserLanguages
from telegram_bot.notifications import NotificationCatchUp
from tests.telegram_bot.conftest import FakeLanguages
from tests.telegram_bot.test_menu_command import (
    _ADMIN_ID,
    _USER_ID,
    FakeAiogram,
    FakeApi,
    FakeCatchUp,
    FakeSpreadsheets,
    _callback,
    _message,
    _spreadsheet,
)

_EN, _RU, _HI, _ES, _FR = PICKER_ORDER


def _labels(rows: list[language_picker.Row]) -> list[list[str]]:
    """Надписи клавиатуры по рядам."""
    return [[text for text, _ in row] for row in rows]


class TestPicker:
    """Раскладка клавиатуры: чистая логика, без бота."""

    def test_first_page(self) -> None:
        """Четыре языка по одному в ряд, ✓ у текущего, навигация отдельно."""
        rows = language_picker.rows(origin="settings", page=1, current=_EN, languages=PICKER_ORDER)

        assert _labels(rows) == [
            [f"✓ {NATIVE_LABELS[_EN]}"],
            [NATIVE_LABELS[_RU]],
            [NATIVE_LABELS[_HI]],
            [NATIVE_LABELS[_ES]],
            ["·", "1/2", "▶"],
        ]
        assert rows[-1][2][1] == "language:page:settings:2"
        assert rows[1][0][1] == "language:set:settings:ru"

    def test_last_page(self) -> None:
        """На последней странице стрелка назад, а вместо «вперёд» — заглушка."""
        rows = language_picker.rows(origin="start", page=2, current=_FR, languages=PICKER_ORDER)

        assert _labels(rows) == [[f"✓ {NATIVE_LABELS[_FR]}"], ["◀", "2/2", "·"]]
        assert rows[-1][0][1] == "language:page:start:1"

    def test_page_out_of_range_is_clamped(self) -> None:
        """Устаревшая кнопка страницы, которой больше нет, ведёт на последнюю."""
        clamped = language_picker.rows(origin="start", page=9, current=_EN, languages=PICKER_ORDER)
        last = language_picker.rows(origin="start", page=2, current=_EN, languages=PICKER_ORDER)
        assert clamped == last

    def test_single_page_has_no_navigation(self) -> None:
        """Одна страница — ряд навигации был бы из одних заглушек."""
        rows = language_picker.rows(origin="start", page=1, current=_RU, languages=(_EN, _RU))
        assert _labels(rows) == [[NATIVE_LABELS[_EN]], [f"✓ {NATIVE_LABELS[_RU]}"]]

    def test_every_callback_fits_telegram_limit(self) -> None:
        """`callback_data` длиннее 64 байт Telegram отвергает целиком."""
        for origin in ORIGINS:
            for page in (1, 2):
                rows = language_picker.rows(
                    origin=origin, page=page, current=_EN, languages=PICKER_ORDER
                )
                assert all(len(data.encode()) <= 64 for row in rows for _, data in row)

    def test_opens_on_the_page_of_current_language(self) -> None:
        """Французу не нужно листать к своему языку каждый раз."""
        assert language_picker.page_of(_FR, PICKER_ORDER) == 2
        assert language_picker.page_of(_EN, PICKER_ORDER) == 1

    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            ("language:open", PickerAction("open")),
            ("language:noop", PickerAction("noop")),
            ("language:set:start:ru", PickerAction("set", origin="start", value="ru")),
            ("language:page:settings:2", PickerAction("page", origin="settings", value="2")),
            ("language:set:elsewhere:ru", None),
            ("language:page:settings", None),
            ("settings:open", None),
            (None, None),
        ],
    )
    def test_parse(self, data: str | None, expected: PickerAction | None) -> None:
        """Незнакомая форма — не ошибка, а повод промолчать."""
        assert language_picker.parse(data) == expected


class _BrokenLanguages:
    """Источник языка, который падает: граница ошибок обязана это пережить."""

    async def resolve(self, telegram_id: int) -> Language:
        raise RuntimeError("язык недоступен")

    async def change(self, telegram_id: int, language: Language) -> Language:
        raise RuntimeError("язык недоступен")


class Harness:
    """Вход, меню, настройки и выбор языка на фейках."""

    def __init__(
        self,
        *,
        spreadsheet: object = None,
        language: Language = _EN,
        languages: LanguageStore | None = None,
    ) -> None:
        self.aiogram = FakeAiogram()
        self.languages = FakeLanguages(language)
        store = languages if languages is not None else self.languages
        api = cast("ApiGateway", FakeApi(FakeSpreadsheets(spreadsheet)))  # type: ignore[arg-type]
        catch_up = cast("NotificationCatchUp", FakeCatchUp())
        access = AccessGuard(frozenset({_USER_ID, _ADMIN_ID}), frozenset({_ADMIN_ID}))

        self.manager = Manager(access, self.aiogram, store)
        arguments = (self.manager, api, self.aiogram, catch_up)
        self.manager.register(
            {
                CommandName.START: StartCommand(*arguments),
                CommandName.MENU: MenuCommand(*arguments),
                CommandName.SETTINGS: SettingsCommand(*arguments, access),
                CommandName.LANGUAGE: LanguageCommand(*arguments, store),
            }
        )
        self.state = FSMContext(
            storage=MemoryStorage(),
            key=StorageKey(bot_id=1, chat_id=_USER_ID, user_id=_USER_ID),
        )

    async def restart(self, *, user_id: int = _USER_ID) -> None:
        """Набирает `/start`."""
        await self.manager.launch(
            CommandName.START, _message("/start", user_id=user_id), self.state, restart=True
        )

    async def press(self, data: str, *, user_id: int = _USER_ID) -> None:
        """Нажимает кнопку: команда находится по префиксу `callback_data`."""
        name = data.split(":", maxsplit=1)[0]
        await self.manager.launch_callback(name, _callback(data, user_id=user_id), self.state)


class TestStart:
    """`/start` начинается с выбора языка — каждый раз."""

    async def test_start_asks_language_first(self) -> None:
        """Подпись над выбором английская, приветствия до выбора нет."""
        harness = Harness(language=_RU)
        await harness.restart()

        assert harness.aiogram.sent == [t_in(_EN, "language.choose_start")]
        assert f"✓ {NATIVE_LABELS[_RU]}" in [text for text, _ in harness.aiogram.buttons()]

    async def test_choice_greets_in_the_new_language(self) -> None:
        """После выбора — подтверждение и приветствие уже на выбранном языке."""
        harness = Harness(language=_EN)
        await harness.restart()
        await harness.press("language:set:start:ru")

        assert harness.languages.changed == {_USER_ID: _RU}
        assert harness.aiogram.edits[-1] == (1, t_in(_RU, "language.changed"), None)
        assert harness.aiogram.sent[-1] == t_in(_RU, "text.welcome")

    async def test_owner_gets_menu_after_choice(self) -> None:
        """Владелец таблицы после выбора попадает в меню, а не в приветствие."""
        harness = Harness(spreadsheet=_spreadsheet(), language=_RU)
        await harness.restart()
        await harness.press("language:set:start:en")

        assert harness.aiogram.sent[-1] == t_in(_EN, "text.menu")

    async def test_start_asks_every_time(self) -> None:
        """Выбранный язык не отменяет выбора на следующем `/start`."""
        harness = Harness()
        await harness.restart()
        await harness.press("language:set:start:ru")
        await harness.restart()

        assert harness.aiogram.sent[-1] == t_in(_EN, "language.choose_start")


class TestSettings:
    """Кнопка «Язык» в настройках и возврат к ним."""

    async def test_everyone_gets_the_language_button(self) -> None:
        """Язык меняет каждый, а не только админ."""
        harness = Harness()
        await harness.press("settings:open")

        assert harness.aiogram.buttons() == [
            (t_in(_EN, "buttons.settings.language"), language_picker.open_data())
        ]

    async def test_admin_gets_both_buttons(self) -> None:
        """У админа под языком — траты на модель."""
        harness = Harness()
        await harness.press("settings:open", user_id=_ADMIN_ID)

        assert [data for _, data in harness.aiogram.buttons()] == [
            language_picker.open_data(),
            LLM_COSTS_DATA,
        ]

    async def test_button_sends_a_new_message(self) -> None:
        """Выбор приходит новым сообщением на языке пользователя."""
        harness = Harness(language=_RU)
        await harness.press("language:open")

        assert harness.aiogram.sent == [t_in(_RU, "language.choose")]
        assert harness.aiogram.edits == []

    async def test_page_edits_the_same_message(self) -> None:
        """Листание меняет клавиатуру того же сообщения, не присылая нового."""
        harness = Harness()
        await harness.press("language:open")
        sent = len(harness.aiogram.sent)

        await harness.press("language:page:settings:2")

        assert len(harness.aiogram.sent) == sent
        message_id, text, keyboard = harness.aiogram.edits[-1]
        assert (message_id, text) == (1, None)
        assert keyboard is not None

    async def test_choice_returns_to_settings_in_the_new_language(self) -> None:
        """После выбора — экран настроек, уже на новом языке."""
        harness = Harness(language=_RU)
        await harness.press("language:open")
        await harness.press("language:set:settings:en")

        assert harness.languages.changed == {_USER_ID: _EN}
        assert harness.aiogram.said(t_in(_EN, "language.changed"))
        assert harness.aiogram.sent[-1] == t_in(_EN, "text.settings_user")

    @pytest.mark.parametrize(
        "data",
        ["language:set:settings:de", "language:set:elsewhere:ru", "language:noop"],
    )
    async def test_junk_changes_nothing(self, data: str) -> None:
        """Незнакомый язык, чужая форма и инертная кнопка — только «часики» гаснут."""
        harness = Harness()
        await harness.press(data)

        assert harness.languages.changed == {}
        assert harness.aiogram.sent == []
        assert harness.aiogram.answered_callbacks == 1


class TestRouting:
    """Кнопки выбора живут вне диалогов, как и остальные кнопки экранов."""

    def test_language_buttons_are_routed_and_blocked_during_dialogs(self) -> None:
        """Префикс в списке кнопок: обработчик есть, а посреди диалога — подсказка."""
        from telegram_bot.main import _BUTTON_PREFIXES

        assert language_picker.open_data().startswith(_BUTTON_PREFIXES)


class TestManager:
    """Язык выбирается на входе, один раз."""

    async def test_stranger_is_refused_in_english_without_asking_api(self) -> None:
        """Язык знает только api, а постороннего к нему не пускают."""
        harness = Harness(language=_RU)
        await harness.restart(user_id=999)

        assert harness.aiogram.sent == [ACCESS_DENIED_MESSAGE]
        assert harness.languages.resolved == []

    async def test_command_runs_in_users_language(self) -> None:
        """Всё, что печатает команда, — на языке пользователя."""
        harness = Harness(language=_RU)
        await harness.press("settings:open")

        assert harness.aiogram.sent == [t_in(_RU, "text.settings_user")]

    async def test_broken_language_source_is_survived(self) -> None:
        """Сбой источника языка — язык по умолчанию, а не молчание."""
        harness = Harness(languages=_BrokenLanguages())
        await harness.press("settings:open")

        assert harness.aiogram.sent == [
            t_in(i18n_language.DEFAULT_LANGUAGE, "text.settings_user")
        ]


class _FakeUsers:
    """Клиент пользователей api по сценарию."""

    def __init__(self, outcome: Language | Exception | None) -> None:
        self._outcome = outcome
        self.asked = 0
        self.saved: list[Language] = []

    async def language(self, telegram_id: int) -> Language | None:
        self.asked += 1
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome

    async def set_language(self, telegram_id: int, language: Language) -> Language:
        self.saved.append(language)
        return language


class _FakeUsersApi:
    """Шлюз из одного клиента пользователей."""

    def __init__(self, users: _FakeUsers) -> None:
        self.users = users


def _store(users: _FakeUsers) -> UserLanguages:
    """Кэш языков поверх фейкового api."""
    return UserLanguages(cast("ApiGateway", _FakeUsersApi(users)))


class TestUserLanguages:
    """Кэш языков: когда спрашивать api и что запоминать."""

    async def test_second_resolve_costs_no_request(self) -> None:
        """Язык меняется раз в жизни — спрашивать его на каждое сообщение незачем."""
        users = _FakeUsers(_FR)
        store = _store(users)

        assert await store.resolve(1) is _FR
        assert await store.resolve(1) is _FR
        assert users.asked == 1

    async def test_unknown_user_speaks_default_and_is_cached(self) -> None:
        """Новичок, не выбравший язык, не стоит запроса на каждое сообщение."""
        users = _FakeUsers(ApiNotFoundError(404, code="not_found", details={"resource": "user"}))
        store = _store(users)

        assert await store.resolve(1) is i18n_language.DEFAULT_LANGUAGE
        await store.resolve(1)
        assert users.asked == 1

    async def test_api_failure_is_not_cached(self) -> None:
        """Сбой временный: запомнить его — говорить не на том языке до перезапуска."""
        users = _FakeUsers(ApiUnavailableError(0))
        store = _store(users)

        assert await store.resolve(1) is i18n_language.DEFAULT_LANGUAGE
        await store.resolve(1)
        assert users.asked == 2

    async def test_change_updates_the_cache(self) -> None:
        """Выбранный язык действует сразу, без нового запроса."""
        users = _FakeUsers(_RU)
        store = _store(users)
        await store.resolve(1)

        await store.change(1, _ES)

        assert users.saved == [_ES]
        assert await store.resolve(1) is _ES
        assert users.asked == 1
