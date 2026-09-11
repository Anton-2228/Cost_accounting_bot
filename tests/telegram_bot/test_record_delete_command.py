"""Тесты `/del`: операция удаляется только после набранного id.

Ни сети, ни Redis, ни Telegram: api подменён фейком, состояние — в
`MemoryStorage`. Предмет проверки — то, ради чего подтверждение заведено:

* до ответа ничего не удаляется, а в вопросе видно, что именно удалится;
* удаляется показанная операция, а не последняя на момент ответа;
* любой другой ответ отменяет удаление и снимает состояние;
* ошибка api на удалении не оставляет пользователя в ожидании id.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import pytest
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message
from aiogram.types import User as TelegramUser

from telegram_bot.access import AccessGuard
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.errors import ApiError, ApiNotFoundError
from telegram_bot.api_client.models import Category, CategoryKind, Currency, Record
from telegram_bot.commands.cancel import BRANCH_DELETE, CancelCommand
from telegram_bot.commands.manager import Manager
from telegram_bot.commands.menu import MenuCommand
from telegram_bot.commands.record_delete import RecordDeleteCommand
from telegram_bot.enums import CommandName, FsmDataKeys
from telegram_bot.formatting import RecordFormatter
from telegram_bot.formatting.money_formatter import MoneyFormatter
from telegram_bot.i18n import t
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.states import States
from tests.telegram_bot.conftest import FakeLanguages, make_category
from tests.telegram_bot.test_menu_command import (
    FakeAiogram,
    FakeCatchUp,
    FakeSpreadsheets,
    _callback,
    _spreadsheet,
)

#: Тот же пользователь, что у `_callback` из тестов меню.
_USER_ID = 11

_CATEGORIES = [
    make_category(category_id=1, title="Продукты"),
    make_category(category_id=2, title="Зарплата", kind=CategoryKind.INCOME),
]


def _record(
    record_id: int, *, amount: str = "-250", category_id: int = 1, notes: str = ""
) -> Record:
    """Операция текущего периода; расход — с минусом, как её хранит api."""
    return Record(
        id=record_id,
        period_id=1,
        category_id=category_id,
        amount=Decimal(amount),
        currency=Currency.RUB,
        added_at=date(2026, 9, 1),
        notes=notes,
    )


_EARLIER = _record(41, amount="1000", category_id=2)
_LAST = _record(42, notes="кофе с собой")

CANCELLED = t("text.record_delete_cancelled")


def _typed(text: str | None) -> Message:
    """Сообщение пользователя; `None` — не текст (стикер, фото)."""
    return Message(
        message_id=1,
        date=datetime(2026, 9, 1, tzinfo=UTC),
        chat=Chat(id=_USER_ID, type="private"),
        from_user=TelegramUser(id=_USER_ID, is_bot=False, first_name="Тест"),
        text=text,
    )


class FakeRecords:
    """Операции текущего периода и журнал удалений."""

    def __init__(self, records: list[Record]) -> None:
        self.records = list(records)
        self.deleted: list[int] = []
        #: Ошибка, которой api ответит на удаление.
        self.error: ApiError | None = None

    async def current(self, spreadsheet_id: int) -> list[Record]:
        return list(self.records)

    async def delete(self, spreadsheet_id: int, record_id: int) -> Record:
        if self.error is not None:
            raise self.error
        record = next(item for item in self.records if item.id == record_id)
        self.records.remove(record)
        self.deleted.append(record_id)
        return record


class FakeCatalog:
    """Справочник категорий."""

    async def categories(self, spreadsheet_id: int, *, only_active: bool = True) -> list[Category]:
        return list(_CATEGORIES)


class FakeApi:
    """Шлюз api из клиентов, которые нужны `/del`."""

    def __init__(self, records: FakeRecords) -> None:
        self.spreadsheets = FakeSpreadsheets(_spreadsheet())
        self.records = records
        self.catalog = FakeCatalog()


class Harness:
    """`/del`, «Отмена» и меню, к которому отмена возвращает."""

    def __init__(self, records: list[Record]) -> None:
        self.aiogram = FakeAiogram()
        self.records = FakeRecords(records)
        api = cast("ApiGateway", FakeApi(self.records))
        catch_up = cast("NotificationCatchUp", FakeCatchUp())
        access = AccessGuard(frozenset({_USER_ID}), frozenset())
        self.manager = Manager(access, self.aiogram, FakeLanguages())
        arguments = (self.manager, api, self.aiogram, catch_up)
        self.manager.register(
            {
                CommandName.DEL: RecordDeleteCommand(*arguments),
                CommandName.CANCEL: CancelCommand(*arguments),
                CommandName.MENU: MenuCommand(*arguments),
            }
        )
        self.state = FSMContext(
            storage=MemoryStorage(),
            key=StorageKey(bot_id=1, chat_id=_USER_ID, user_id=_USER_ID),
        )

    async def delete(self, args: str | None = None) -> None:
        """Набирает `/del` с аргументом или без."""
        text = "/del" if args is None else f"/del {args}"
        command = CommandObject(prefix="/", command=CommandName.DEL, args=args)
        await self.manager.launch(CommandName.DEL, _typed(text), self.state, command=command)

    async def reply(self, text: str | None) -> None:
        """Отвечает на вопрос — как шаг приходит из `main.py`, без `command`."""
        await self.manager.launch(CommandName.DEL, _typed(text), self.state)

    async def current_state(self) -> str | None:
        return await self.state.get_state()


def _harness() -> Harness:
    return Harness([_EARLIER, _LAST])


class TestQuestion:
    """`/del` спрашивает, а не удаляет."""

    async def test_bare_del_shows_last_record(self) -> None:
        """Без id показывается последняя операция — целиком и с её id."""
        harness = _harness()
        await harness.delete()

        assert await harness.current_state() == States.CONFIRM_DELETE_RECORD.state
        assert harness.aiogram.said(RecordFormatter.card(_LAST, categories=_CATEGORIES))
        assert harness.records.deleted == []

    async def test_del_with_id_shows_that_record(self) -> None:
        """С id показывается и запоминается именно она."""
        harness = _harness()
        await harness.delete("41")

        assert harness.aiogram.said(RecordFormatter.card(_EARLIER, categories=_CATEGORIES))
        assert (await harness.state.get_data())[FsmDataKeys.DELETE_RECORD_ID] == 41
        assert harness.records.deleted == []

    async def test_question_has_cancel_button(self) -> None:
        """Выход из вопроса — кнопкой, как у каждого диалога."""
        harness = _harness()
        await harness.delete()

        assert harness.aiogram.buttons() == [
            (t("buttons.cancel"), f"{CommandName.CANCEL}:{BRANCH_DELETE}")
        ]

    async def test_empty_period(self) -> None:
        """Удалять нечего — вопроса нет, состояния тоже."""
        harness = Harness([])
        await harness.delete()

        assert harness.aiogram.said(t("record_delete.empty"))
        assert await harness.current_state() is None

    async def test_id_outside_current_period(self) -> None:
        """Чужой или старый id — отказ сразу, без вопроса."""
        harness = _harness()
        await harness.delete("7")

        assert harness.aiogram.said(t("record_delete.not_in_period", id=7))
        assert await harness.current_state() is None

    async def test_bad_id(self) -> None:
        """Не число — подсказка, как нужно."""
        harness = _harness()
        await harness.delete("abc")

        assert harness.aiogram.said(t("record_delete.bad_id", raw="abc"))
        assert await harness.current_state() is None


class TestAnswer:
    """Ответ на вопрос."""

    @pytest.mark.parametrize("answer", ["42", " 42 "])
    async def test_shown_id_deletes_the_record(self, answer: str) -> None:
        """Набранный id удаляет операцию, снимает состояние и гасит кнопку."""
        harness = _harness()
        await harness.delete()
        await harness.reply(answer)

        assert harness.records.deleted == [42]
        assert await harness.current_state() is None
        assert harness.aiogram.said(RecordFormatter.deleted(_LAST, categories=_CATEGORIES))
        assert harness.aiogram.cleared

    async def test_record_added_after_question_is_kept(self) -> None:
        """Появившаяся после вопроса операция не получает чужое подтверждение."""
        harness = _harness()
        await harness.delete()
        harness.records.records.append(_record(43))
        await harness.reply("42")

        assert harness.records.deleted == [42]

    @pytest.mark.parametrize("answer", ["41", "43", "да", None])
    async def test_other_answer_cancels(self, answer: str | None) -> None:
        """Другой id — даже настоящий, — слово или стикер отменяют удаление."""
        harness = _harness()
        await harness.delete()
        await harness.reply(answer)

        assert harness.records.deleted == []
        assert await harness.current_state() is None
        assert harness.aiogram.said(CANCELLED)

    async def test_api_error_does_not_leave_the_question_open(self) -> None:
        """Операцию уже удалили в другом месте: ошибка видна, ожидания id нет."""
        harness = _harness()
        harness.records.error = ApiNotFoundError(
            404, code="not_found", details={"resource": "record"}
        )
        await harness.delete()
        await harness.reply("42")

        assert harness.aiogram.said(t("errors.not_found.record"))
        assert await harness.current_state() is None


class TestExit:
    """Выход из вопроса."""

    async def test_cancel_button(self) -> None:
        """«Отмена» выпускает, ничего не удалив."""
        harness = _harness()
        await harness.delete()
        await harness.manager.launch_callback(
            CommandName.CANCEL, _callback(f"{CommandName.CANCEL}:{BRANCH_DELETE}"), harness.state
        )

        assert harness.records.deleted == []
        assert await harness.current_state() is None
        assert harness.aiogram.said(t("text.cancelled"))

    async def test_command_during_question_points_to_cancel(self) -> None:
        """Набранная посреди вопроса команда получает подсказку с выходом этой ветки."""
        harness = _harness()
        await harness.delete()
        await harness.manager.launch(CommandName.CANCEL, _typed("/add евро 5 еда"), harness.state)

        assert harness.aiogram.buttons() == [
            (t("buttons.cancel"), f"{CommandName.CANCEL}:{BRANCH_DELETE}")
        ]
        assert await harness.current_state() == States.CONFIRM_DELETE_RECORD.state


class TestCard:
    """Карточка операции в вопросе."""

    def test_expense_card_has_everything(self) -> None:
        """Вид и сумма, категория, пометка, дата и id."""
        card = RecordFormatter.card(_LAST, categories=_CATEGORIES)
        amount = MoneyFormatter.format(_LAST.amount, _LAST.currency)

        assert card.splitlines() == [
            t("format.record.expense", amount=amount),
            t("format.record.category", title="Продукты"),
            t("format.record.notes", notes="кофе с собой"),
            t("format.record.date", date="01.09.2026"),
            t("format.record.id", id=42),
        ]

    def test_income_without_notes(self) -> None:
        """Доход узнаётся по знаку суммы; пустой пометки в карточке нет."""
        card = RecordFormatter.card(_EARLIER, categories=_CATEGORIES)
        amount = MoneyFormatter.format(_EARLIER.amount, _EARLIER.currency)

        assert card.splitlines()[0] == t("format.record.income", amount=amount)
        assert not any(
            line.startswith(t("format.record.notes", notes="")) for line in card.splitlines()
        )
