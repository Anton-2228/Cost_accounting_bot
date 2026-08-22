"""Команда `/start`: приветствие и мастер создания учётной таблицы."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot import constants
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.enums import CommandName, FsmDataKeys
from telegram_bot.errors import TABLE_CREATING_MESSAGE
from telegram_bot.parsers import OnboardingParser, ParseError
from telegram_bot.parsers.onboarding_parser import SKIP_MARKERS
from telegram_bot.resources.messages import (
    ASK_EMAIL_MESSAGE,
    ASK_RESET_DAY_MESSAGE,
    ASK_TIMEZONE_MESSAGE,
    ASK_TITLE_MESSAGE,
    CREATING_TABLE_MESSAGE,
    WELCOME_MESSAGE,
)
from telegram_bot.states import States

#: Кнопка под приветствием. Префикс тот же, что ключ команды, — по нему нажатие
#: и находит обработчик.
CREATE_TABLE_BUTTON = ("Создать таблицу", f"{CommandName.START}:create")


class StartCommand(BaseCommand):
    """Вход в бота: приветствие, кнопка и мастер из четырёх шагов.

    Мастер начинается только по кнопке. Раньше `/start` первым же сообщением
    спрашивал название таблицы: человек, впервые открывший бота, получал вопрос
    вместо объяснения и не мог ни отказаться, ни понять, куда попал.

    Сам диалог разбирается внутри одной команды, а не разнесён по обработчикам:
    шаги связаны, и держать их рядом — единственный способ увидеть переход
    целиком. Ветвление идёт по текущему состоянию FSM.

    Промежуточные ответы живут в FSM-данных и больше нигде: они переживают
    перезапуск бота вместе с состоянием, и рассинхронизироваться им не с чем.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Ведёт пользователя по шагам мастера либо начинает всё заново.

        `restart` означает «пришла набранная команда `/start`», а не очередной
        ответ на вопрос шага. Различить их иначе нечем: оба входа обслуживает
        одна команда, и без флага набранный посреди мастера `/start` ушёл бы в
        разбор шага и получил бы «Странный ввод».

        Набранный `/start` чистит состояние **любой** ветки. Это второй выход
        из диалога, и нужен он затем, что первый — кнопка «Отмена» — живёт в
        сообщении: его можно пролистать, а у мастера создания таблицы кнопки
        нет вовсе, и без этой ветки он стал бы единственной ловушкой в боте.
        """
        if kwargs.get("restart"):
            await self.finish(chat_id=message.chat.id, state=state)
            await self._greet(message)
            return

        current = await self.aiogram.get_state(state)

        if current is None:
            await self._greet(message)
        elif current == States.CREATE_TABLE_TITLE.state:
            await self._on_title(message, state)
        elif current == States.CREATE_TABLE_RESET_DAY.state:
            await self._on_reset_day(message, state)
        elif current == States.CREATE_TABLE_TIMEZONE.state:
            await self._on_timezone(message, state)
        elif current == States.CREATE_TABLE_EMAIL.state:
            await self._on_email(message, state)

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Кнопка «Создать таблицу»: первый шаг мастера.

        Наличие таблицы проверяется здесь ещё раз, хотя приветствие с кнопкой
        показывается только без неё: кнопка живёт в переписке дольше экрана, и
        нажатая через неделю она провела бы владельца таблицы по всем четырём
        шагам, чтобы на последнем получить от api «таблица уже есть».
        """
        target = await self.callback_target(callback)
        if target is None:
            return
        chat_id, telegram_id = target

        if await self._show_entrance(chat_id=chat_id, telegram_id=telegram_id):
            return

        await self.aiogram.set_state(state, States.CREATE_TABLE_TITLE)
        await self.aiogram.send_message(chat_id, ASK_TITLE_MESSAGE)

    async def _greet(self, message: Message) -> None:
        """Вход в бота: приветствие, ожидание таблицы либо меню."""
        chat_id = message.chat.id
        if await self._show_entrance(chat_id=chat_id, telegram_id=self.user_id(message)):
            return

        await self.aiogram.send_message(
            chat_id,
            WELCOME_MESSAGE,
            keyboard=self.aiogram.inline_keyboard([CREATE_TABLE_BUTTON]),
        )

    async def _show_entrance(self, *, chat_id: int, telegram_id: int) -> bool:
        """Показывает экран владельцу таблицы. `False` — таблицы нет вовсе.

        Состояний три, а не два, и различить их может только эта команда:
        `spreadsheet_for` неготовую таблицу приравнивает к отсутствующей, а
        `find_spreadsheet` не различает готовность вовсе. Разница видна
        пользователю: «таблицы нет» — приглашение завести, «создаётся» —
        обещание, «готова» — меню.

        Меню до готовности не показывается: все его кнопки работают с
        документом, которого ещё нет, и нажатая упёрлась бы в отказ. Экран из
        пяти кнопок, где не работает ни одна, — это не меню.
        """
        spreadsheet = await self.find_spreadsheet(
            user_id=telegram_id,
            chat_id=chat_id,
            # Меню по `TABLE_READY` дорисовала бы дочитка, а следом его показал
            # бы и этот метод: два одинаковых экрана подряд.
            menu_on_ready=False,
        )
        if spreadsheet is None:
            return False
        if not spreadsheet.is_ready:
            await self.aiogram.send_message(chat_id, TABLE_CREATING_MESSAGE)
            return True
        await self.menu().show(chat_id=chat_id)
        return True

    async def _on_title(self, message: Message, state: FSMContext) -> None:
        """Название таблицы."""
        text = self.text_of(message)
        if text is None:
            await self.aiogram.answer_message(message, ASK_TITLE_MESSAGE)
            return
        try:
            title = OnboardingParser.title(text)
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        await self.aiogram.set_state_data(state, FsmDataKeys.TITLE, title)
        await self.aiogram.set_state(state, States.CREATE_TABLE_RESET_DAY)
        await self.aiogram.answer_message(message, ASK_RESET_DAY_MESSAGE)

    async def _on_reset_day(self, message: Message, state: FSMContext) -> None:
        """День перехода на новый учётный месяц."""
        text = self.text_of(message)
        if text is None:
            await self.aiogram.answer_message(message, ASK_RESET_DAY_MESSAGE)
            return
        try:
            reset_day = OnboardingParser.reset_day(text)
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        await self.aiogram.set_state_data(state, FsmDataKeys.RESET_DAY, reset_day)
        await self.aiogram.set_state(state, States.CREATE_TABLE_TIMEZONE)
        await self.aiogram.answer_message(
            message, ASK_TIMEZONE_MESSAGE.format(default=constants.DEFAULT_TIMEZONE)
        )

    async def _on_timezone(self, message: Message, state: FSMContext) -> None:
        """Часовой пояс: от него зависят и дата операции, и момент ролловера."""
        text = self.text_of(message)
        if text is None:
            await self.aiogram.answer_message(
                message, ASK_TIMEZONE_MESSAGE.format(default=constants.DEFAULT_TIMEZONE)
            )
            return

        raw = text.strip()
        if raw.lower() in SKIP_MARKERS:
            timezone = constants.DEFAULT_TIMEZONE
        else:
            try:
                timezone = OnboardingParser.timezone(raw)
            except ParseError as error:
                await self.aiogram.answer_message(message, error.message)
                return

        await self.aiogram.set_state_data(state, FsmDataKeys.TIMEZONE, timezone)
        await self.aiogram.set_state(state, States.CREATE_TABLE_EMAIL)
        await self.aiogram.answer_message(message, ASK_EMAIL_MESSAGE)

    async def _on_email(self, message: Message, state: FSMContext) -> None:
        """Последний шаг: почта (её можно пропустить) и создание таблицы."""
        text = self.text_of(message)
        if text is None:
            await self.aiogram.answer_message(message, ASK_EMAIL_MESSAGE)
            return
        try:
            email = OnboardingParser.email(text)
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        data = await state.get_data()
        title = str(data.get(FsmDataKeys.TITLE, ""))
        reset_day = int(data.get(FsmDataKeys.RESET_DAY, constants.MIN_RESET_DAY))
        timezone = str(data.get(FsmDataKeys.TIMEZONE, constants.DEFAULT_TIMEZONE))

        await self.aiogram.answer_message(message, CREATING_TABLE_MESSAGE)

        await self.api.spreadsheets.create(
            telegram_id=self.user_id(message),
            title=title,
            reset_day=reset_day,
            timezone=timezone,
            email=email,
        )

        # Состояние снимается только после успеха: упади создание, пользователь
        # останется на последнем шаге и сможет повторить, не набирая заново
        # название, день и пояс.
        await self.finish(chat_id=message.chat.id, state=state)

        # Мастер заканчивается обещанием, а не экраном. Документ создаёт
        # отдельный сервис по задаче из очереди, и до его появления не работает
        # ни одна кнопка меню: показать их сейчас значило бы выдать за
        # готовность то, что ею ещё не стало. Меню придёт само — вместе с
        # уведомлением `TABLE_READY`.
