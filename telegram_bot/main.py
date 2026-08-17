"""Точка входа бота: polling рядом с notify-сервером."""

from __future__ import annotations

import asyncio

import uvicorn
from aiogram import F
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message

from telegram_bot.config import settings
from telegram_bot.enums import CommandName
from telegram_bot.init import (
    AI,
    AIOGRAM_WRAPPER,
    API,
    BOT,
    DISPATCHER,
    MANAGER,
    ROUTER,
    STORAGE,
)
from telegram_bot.logging import get_logger, setup_logging
from telegram_bot.notify_server import NotifyServer
from telegram_bot.resources.messages import DIALOG_IN_PROGRESS_MESSAGE, UNKNOWN_MESSAGE
from telegram_bot.states import States

logger = get_logger(__name__)

#: Состояния мастера создания таблицы: их обслуживает одна команда.
_CREATE_TABLE_STATES = (
    States.CREATE_TABLE_TITLE,
    States.CREATE_TABLE_RESET_DAY,
    States.CREATE_TABLE_TIMEZONE,
    States.CREATE_TABLE_EMAIL,
)

#: Состояния разбора чека: их обслуживает одна команда, а `/check_skip` и
#: `/check_del` осмысленны только внутри них — вне разбора нечего пропускать и
#: нечего удалять.
_CHECK_STATES = (
    States.CHECK_TYPES,
    States.CHECK_CATEGORIES,
    States.CHECK_SOURCE,
)

#: Команды, которым не нужен ни диалог, ни аргументы разбора состояния.
_SIMPLE_COMMANDS = (
    CommandName.HELP,
    CommandName.TABLE,
    CommandName.TABLE_SYNC,
)

#: Команды, разбирающие аргументы строки.
_ARGUMENT_COMMANDS = (
    CommandName.ADD,
    CommandName.DEL,
    CommandName.ADD_TRANS,
    CommandName.DEL_TRANS,
)

#: Меню команд Telegram. Здесь только то, что действительно зарегистрировано:
#: старая версия объявляла в меню `/cancel`, `/skip` и `/remove`, которых как
#: команд не существовало, и они отвечали «Не понимаю о чем речь».
_MENU = [
    BotCommand(command=CommandName.START, description="Завести таблицу"),
    BotCommand(command=CommandName.ADD, description="Добавить операцию"),
    BotCommand(command=CommandName.DEL, description="Удалить операцию"),
    BotCommand(command=CommandName.ADD_TRANS, description="Перевод между счетами"),
    BotCommand(command=CommandName.DEL_TRANS, description="Удалить перевод"),
    BotCommand(command=CommandName.TABLE, description="Ссылка на таблицу"),
    BotCommand(command=CommandName.TABLE_SYNC, description="Вчитать правки из таблицы"),
    BotCommand(command=CommandName.TABLE_EMAIL, description="Открыть доступ почте"),
    BotCommand(command=CommandName.TABLE_DELETE, description="Отвязать таблицу"),
    BotCommand(command=CommandName.CHECK, description="Разобрать чек"),
    BotCommand(command=CommandName.CHECK_SKIP, description="Отложить чек"),
    BotCommand(command=CommandName.CHECK_DEL, description="Удалить чек"),
    BotCommand(command=CommandName.CANCEL, description="Прервать диалог"),
    BotCommand(command=CommandName.HELP, description="Справка"),
]


def _register_handlers() -> None:
    """Регистрирует обработчики.

    Порядок существенный: aiogram отдаёт сообщение первому подошедшему.

    1. `/cancel` — раньше всего и во всех состояниях, иначе диалог мог бы его
       перехватить и разобрать как свой ответ.
    2. Команды разбора чека — внутри его состояний и только там.
    3. Любая другая команда, набранная посреди диалога, получает подсказку, а
       не молчание и не разбор её текста как ответа на вопрос. В старой версии
       `/table` внутри диалога уходил в разбор шага и получал «Странный ввод».
    4. Шаги диалогов.
    5. Обычные команды — только вне состояний.
    6. Всё остальное.
    """
    router = ROUTER

    router.message.register(_on_cancel, Command(CommandName.CANCEL))

    router.message.register(
        _on_check_skip, Command(CommandName.CHECK_SKIP), StateFilter(*_CHECK_STATES)
    )
    router.message.register(
        _on_check_delete, Command(CommandName.CHECK_DEL), StateFilter(*_CHECK_STATES)
    )

    router.message.register(
        _on_command_during_dialog,
        StateFilter(
            *_CREATE_TABLE_STATES,
            *_CHECK_STATES,
            States.ADD_EMAIL,
            States.CONFIRM_DELETE_TABLE,
        ),
        F.text.startswith("/"),
    )

    router.message.register(_on_create_table_step, StateFilter(*_CREATE_TABLE_STATES))
    router.message.register(_on_add_email_step, StateFilter(States.ADD_EMAIL))
    router.message.register(_on_delete_table_step, StateFilter(States.CONFIRM_DELETE_TABLE))
    router.message.register(_on_check_step, StateFilter(*_CHECK_STATES))

    # Кнопка «Готово» живёт только внутри разбора: без фильтра по состоянию
    # кнопка от предыдущего чека оставалась бы живой и применялась к текущему.
    router.callback_query.register(
        _on_check_done,
        StateFilter(*_CHECK_STATES),
        F.data.startswith("check_done:"),
    )

    router.message.register(_on_start, Command(CommandName.START), StateFilter(None))
    router.message.register(_on_check, Command(CommandName.CHECK), StateFilter(None))
    router.message.register(_on_table_email, Command(CommandName.TABLE_EMAIL), StateFilter(None))
    router.message.register(
        _on_table_delete, Command(CommandName.TABLE_DELETE), StateFilter(None)
    )

    for name in _SIMPLE_COMMANDS:
        router.message.register(_make_simple_handler(name), Command(name), StateFilter(None))
    for name in _ARGUMENT_COMMANDS:
        router.message.register(_make_argument_handler(name), Command(name), StateFilter(None))

    router.message.register(_on_unknown)


async def _on_cancel(message: Message, state: FSMContext) -> None:
    """Прерывает любой диалог."""
    await MANAGER.launch(CommandName.CANCEL, message, state)


async def _on_command_during_dialog(message: Message, state: FSMContext) -> None:
    """Объясняет, что сейчас идёт другой диалог."""
    await AIOGRAM_WRAPPER.answer_message(message, DIALOG_IN_PROGRESS_MESSAGE)


async def _on_create_table_step(message: Message, state: FSMContext) -> None:
    """Очередной шаг мастера создания таблицы."""
    await MANAGER.launch(CommandName.START, message, state)


async def _on_add_email_step(message: Message, state: FSMContext) -> None:
    """Ответ с почтой для выдачи доступа."""
    await MANAGER.launch(CommandName.TABLE_EMAIL, message, state)


async def _on_delete_table_step(message: Message, state: FSMContext) -> None:
    """Подтверждение отвязки таблицы."""
    await MANAGER.launch(CommandName.TABLE_DELETE, message, state)


async def _on_check_step(message: Message, state: FSMContext) -> None:
    """Очередной шаг разбора чека: правки или счёт."""
    await MANAGER.launch(CommandName.CHECK, message, state)


async def _on_check_skip(message: Message, state: FSMContext) -> None:
    """Отложить текущий чек."""
    await MANAGER.launch(CommandName.CHECK_SKIP, message, state)


async def _on_check_delete(message: Message, state: FSMContext) -> None:
    """Удалить текущий чек."""
    await MANAGER.launch(CommandName.CHECK_DEL, message, state)


async def _on_check_done(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Готово» на стадии разбора чека."""
    await MANAGER.launch_callback(CommandName.CHECK, callback, state)


async def _on_start(message: Message, state: FSMContext) -> None:
    """Начало мастера создания таблицы."""
    await MANAGER.launch(CommandName.START, message, state)


async def _on_check(message: Message, state: FSMContext) -> None:
    """Начало разбора чеков."""
    await MANAGER.launch(CommandName.CHECK, message, state)


async def _on_table_email(message: Message, state: FSMContext) -> None:
    """Начало выдачи доступа почте."""
    await MANAGER.launch(CommandName.TABLE_EMAIL, message, state)


async def _on_table_delete(message: Message, state: FSMContext) -> None:
    """Начало отвязки таблицы."""
    await MANAGER.launch(CommandName.TABLE_DELETE, message, state)


def _make_simple_handler(name: str):  # type: ignore[no-untyped-def]
    """Обработчик команды без аргументов."""

    async def handler(message: Message, state: FSMContext) -> None:
        await MANAGER.launch(name, message, state)

    return handler


def _make_argument_handler(name: str):  # type: ignore[no-untyped-def]
    """Обработчик команды с аргументами строки."""

    async def handler(message: Message, state: FSMContext, command: CommandObject) -> None:
        await MANAGER.launch(name, message, state, command=command)

    return handler


async def _on_unknown(message: Message, state: FSMContext) -> None:
    """Ответ на всё, что не подошло ни одному обработчику."""
    await AIOGRAM_WRAPPER.answer_message(message, UNKNOWN_MESSAGE)


async def main() -> None:
    """Запускает polling и notify-сервер в одной группе задач."""
    setup_logging()
    _register_handlers()
    await BOT.set_my_commands(_MENU)
    logger.info("Бот запущен, разрешённых пользователей: %s", len(settings.allowed_telegram_ids))

    notify_config = uvicorn.Config(
        NotifyServer(AIOGRAM_WRAPPER).build_app(),
        host="0.0.0.0",  # noqa: S104 — порт доступен только внутри docker-сети
        port=settings.notify_port,
        log_config=None,
    )
    notify_server = uvicorn.Server(notify_config)

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(DISPATCHER.start_polling(BOT), name="aiogram-polling")
            group.create_task(notify_server.serve(), name="notify-http")
    finally:
        await API.aclose()
        await AI.aclose()
        await STORAGE.close()
        await BOT.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
