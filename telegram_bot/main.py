"""Точка входа бота: polling рядом с notify-сервером."""

from __future__ import annotations

import asyncio
from typing import cast

import uvicorn
from aiogram import F
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message

from telegram_bot.commands.menu import MenuCommand
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
from telegram_bot.resources.messages import UNKNOWN_MESSAGE
from telegram_bot.states import States

logger = get_logger(__name__)

#: Состояния мастера создания таблицы: их обслуживает одна команда.
_CREATE_TABLE_STATES = (
    States.CREATE_TABLE_TITLE,
    States.CREATE_TABLE_RESET_DAY,
    States.CREATE_TABLE_TIMEZONE,
    States.CREATE_TABLE_EMAIL,
)

#: Состояния разбора чека: их обслуживает одна команда, а кнопки «Отложить» и
#: «Удалить» осмысленны только внутри них — вне разбора нечего откладывать и
#: нечего удалять.
_CHECK_STATES = (
    States.CHECK_TYPES,
    States.CHECK_CATEGORIES,
    States.CHECK_SOURCE,
)

#: Все состояния диалогов разом. Список нужен трижды — `/start` как выходу,
#: подсказке про идущий диалог и блокировке кнопок меню, — и собран один раз:
#: забытое в одном из трёх мест состояние стало бы ловушкой, из которой
#: выпускает не то, что должно.
_DIALOG_STATES = (
    *_CREATE_TABLE_STATES,
    *_CHECK_STATES,
    States.ADD_EMAIL,
    States.CONFIRM_UNLINK_TABLE,
    States.SETTINGS_ASK_TELEGRAM_ID,
)

#: Команды, которым не нужен ни диалог, ни аргументы разбора состояния.
_SIMPLE_COMMANDS = (
    CommandName.HELP,
    CommandName.MENU,
)

#: Команды с кнопочным входом. Префикс `callback_data` совпадает с ключом
#: команды, поэтому нажатие находит обработчик по одному правилу — тому же, по
#: которому команда находится по своему имени, — а не по второй таблице
#: соответствий, которую пришлось бы держать синхронной вручную.
#:
#: Кнопка «Готово» разбора чека сюда не входит: она законна внутри состояний
#: разбора и только там, поэтому регистрируется отдельно.
_BUTTON_COMMANDS = (
    CommandName.START,
    CommandName.TABLE,
    CommandName.TABLE_SYNC,
    CommandName.TABLE_EMAIL,
    CommandName.TABLE_UNLINK,
    CommandName.SETTINGS,
    CommandName.SETTINGS_LLM,
)

#: Их же префиксы. Отдельным кортежем, потому что `str.startswith` принимает
#: кортеж целиком, и фильтр на все кнопки сразу пишется одной строкой.
#:
#: Кнопки «Отмена» здесь нет намеренно: она законна **внутри** диалога, и
#: попади её префикс в этот список — блокировщик отвечал бы «сейчас идёт другой
#: диалог» на единственный выход из него.
_BUTTON_PREFIXES = tuple(f"{name}:" for name in _BUTTON_COMMANDS)

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
#:
#: Всё, что делается с таблицей, живёт кнопками экрана `/menu`, и командами эти
#: действия не набираются вовсе. Туда же ушли `/cancel`, `/check_skip` и
#: `/check_del`: выход из диалога и судьба разбираемого чека — кнопки того
#: блока, к которому относятся, а не слова, которые надо вспомнить посреди
#: кнопочного диалога.
#:
#: `/start` в списке нет: Telegram шлёт его сам кнопкой «Начать». Набрать его
#: при этом можно, и это второй выход из диалога — но предлагать его строкой
#: меню значило бы звать перезапускать бота как обычное действие.
#:
#: Список одинаков для всех: команда есть у каждого, разным бывает только
#: содержимое ответа. Раздавать разные списки по скоупам значило бы сообщать
#: клиенту роль, которую бот и так проверяет на каждом обращении, — и то же
#: касается готовности таблицы: до неё команды не исчезают, а отвечают, что
#: работать пока не с чем.
_MENU = [
    BotCommand(command=CommandName.MENU, description="Меню"),
    BotCommand(command=CommandName.ADD, description="Добавить операцию"),
    BotCommand(command=CommandName.DEL, description="Удалить операцию"),
    BotCommand(command=CommandName.ADD_TRANS, description="Перевод между счетами"),
    BotCommand(command=CommandName.DEL_TRANS, description="Удалить перевод"),
    BotCommand(command=CommandName.CHECK, description="Разобрать чек"),
    BotCommand(command=CommandName.HELP, description="Справка"),
]


def _register_handlers() -> None:
    """Регистрирует обработчики.

    Порядок существенный: aiogram отдаёт сообщение первому подошедшему.

    1. `/start` — раньше всего и во всех состояниях. Это второй выход из
       диалога, и у мастера создания таблицы — единственный: попади он ниже
       подсказки, мастер стал бы ловушкой, а внутри самого мастера ушёл бы в
       разбор шага и получил «Странный ввод», как `/table` в старой версии.
    2. Любая другая команда, набранная посреди диалога, получает подсказку с
       кнопкой выхода, а не молчание и не разбор её текста как ответа.
    3. Шаги диалогов.
    4. Кнопки: сначала «Отмена» — она законна внутри любого диалога и обязана
       обойти блокировку; затем кнопки разбора чека — внутри его состояний и
       только там; затем блокировка кнопок меню посреди диалога; и только
       потом сами кнопки меню — вне состояний.
    5. Обычные команды — только вне состояний.
    6. Всё остальное.
    """
    router = ROUTER

    router.message.register(_on_start, Command(CommandName.START))

    router.message.register(
        _on_command_during_dialog,
        StateFilter(*_DIALOG_STATES),
        F.text.startswith("/"),
    )

    router.message.register(_on_create_table_step, StateFilter(*_CREATE_TABLE_STATES))
    router.message.register(_on_add_email_step, StateFilter(States.ADD_EMAIL))
    router.message.register(_on_unlink_table_step, StateFilter(States.CONFIRM_UNLINK_TABLE))
    router.message.register(_on_check_step, StateFilter(*_CHECK_STATES))
    router.message.register(
        _on_settings_llm_step, StateFilter(States.SETTINGS_ASK_TELEGRAM_ID)
    )

    # «Отмена» — раньше блокировки кнопок: она и есть выход из идущего диалога,
    # и ответить на неё «сейчас идёт другой диалог» значило бы запереть
    # пользователя единственной кнопкой, которая должна была его выпустить.
    # Фильтра по состоянию у неё нет намеренно: нажатая вне диалога кнопка
    # объясняется («от другого диалога»), а не проваливается в «Не понимаю».
    router.callback_query.register(
        _on_cancel, F.data.startswith(f"{CommandName.CANCEL}:")
    )

    # Кнопки разбора живут только внутри его состояний: без фильтра кнопка от
    # предыдущего чека оставалась бы живой и применялась к текущему. Номер чека
    # в `callback_data` — вторая половина той же защиты, от блока к блоку.
    router.callback_query.register(
        _on_check_done,
        StateFilter(*_CHECK_STATES),
        F.data.startswith("check_done:"),
    )
    router.callback_query.register(
        _on_check_skip,
        StateFilter(*_CHECK_STATES),
        F.data.startswith(f"{CommandName.CHECK_SKIP}:"),
    )
    router.callback_query.register(
        _on_check_delete,
        StateFilter(*_CHECK_STATES),
        F.data.startswith(f"{CommandName.CHECK_DEL}:"),
    )

    # Кнопка меню, нажатая посреди диалога, получает ту же подсказку, что и
    # набранная команда. Молча проглатывать нельзя: меню остаётся висеть в
    # переписке, нажать его во время разбора чека — обычное дело, а состояние в
    # FSM одно на пользователя, и вопрос про почту затёр бы недоразобранный чек.
    router.callback_query.register(
        _on_button_during_dialog,
        StateFilter(*_DIALOG_STATES),
        # `str.startswith` принимает кортеж — отдельного фильтра на каждый
        # префикс не нужно.
        F.data.func(lambda data: data.startswith(_BUTTON_PREFIXES)),
    )

    # Сами кнопки — вне состояний, по той же причине, что и блокировка выше.
    # `settings:` и `settings_llm:` не путаются: префиксы сравниваются целиком,
    # вместе с двоеточием.
    for name in _BUTTON_COMMANDS:
        router.callback_query.register(
            _make_button_handler(name), StateFilter(None), F.data.startswith(f"{name}:")
        )

    router.message.register(_on_check, Command(CommandName.CHECK), StateFilter(None))

    for name in _SIMPLE_COMMANDS:
        router.message.register(_make_simple_handler(name), Command(name), StateFilter(None))
    for name in _ARGUMENT_COMMANDS:
        router.message.register(_make_argument_handler(name), Command(name), StateFilter(None))

    router.message.register(_on_unknown)


async def _on_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Отмена»: выход из диалога."""
    await MANAGER.launch_callback(CommandName.CANCEL, callback, state)


async def _on_command_during_dialog(message: Message, state: FSMContext) -> None:
    """Объясняет, что сейчас идёт другой диалог, и показывает выход.

    Через `Manager`, а не прямой отправкой текста: подсказка обязана назвать
    выход именно из этой ветки, а знает о выходах одна команда — та, что их и
    обслуживает. Заодно на подсказку распространяется общая граница ошибок.
    """
    await MANAGER.launch(CommandName.CANCEL, message, state)


async def _on_create_table_step(message: Message, state: FSMContext) -> None:
    """Очередной шаг мастера создания таблицы."""
    await MANAGER.launch(CommandName.START, message, state)


async def _on_add_email_step(message: Message, state: FSMContext) -> None:
    """Ответ с почтой для выдачи доступа."""
    await MANAGER.launch(CommandName.TABLE_EMAIL, message, state)


async def _on_unlink_table_step(message: Message, state: FSMContext) -> None:
    """Подтверждение отвязки таблицы."""
    await MANAGER.launch(CommandName.TABLE_UNLINK, message, state)


async def _on_check_step(message: Message, state: FSMContext) -> None:
    """Очередной шаг разбора чека: правки или счёт."""
    await MANAGER.launch(CommandName.CHECK, message, state)


async def _on_check_skip(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Отложить»: текущий чек уходит в конец очереди сессии."""
    await MANAGER.launch_callback(CommandName.CHECK_SKIP, callback, state)


async def _on_check_delete(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Удалить»: подтверждение и удаление текущего чека."""
    await MANAGER.launch_callback(CommandName.CHECK_DEL, callback, state)


async def _on_settings_llm_step(message: Message, state: FSMContext) -> None:
    """Введённый telegram id, чьи траты показать."""
    await MANAGER.launch(CommandName.SETTINGS_LLM, message, state)


async def _on_check_done(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Готово» на стадии разбора чека."""
    await MANAGER.launch_callback(CommandName.CHECK, callback, state)


async def _on_start(message: Message, state: FSMContext) -> None:
    """Вход в бота, он же — выход из любого диалога.

    `restart` отличает набранную команду от очередного ответа на вопрос
    мастера: обе приходят в одну команду, и без флага `/start`, набранный на
    шаге «часовой пояс», разобрался бы как название пояса.
    """
    await MANAGER.launch(CommandName.START, message, state, restart=True)


async def _on_check(message: Message, state: FSMContext) -> None:
    """Начало разбора чеков."""
    await MANAGER.launch(CommandName.CHECK, message, state)


async def _on_button_during_dialog(callback: CallbackQuery, state: FSMContext) -> None:
    """Объясняет, что кнопка меню сейчас не сработает.

    Уходит в ту же команду, что и набранная посреди диалога: подсказка одна, и
    выход в ней тоже один. «Часики» гасит она же — `callback_target`.
    """
    await MANAGER.launch_callback(CommandName.CANCEL, callback, state)


def _make_button_handler(name: str):  # type: ignore[no-untyped-def]
    """Обработчик нажатия кнопки команды `name`."""

    async def handler(callback: CallbackQuery, state: FSMContext) -> None:
        await MANAGER.launch_callback(name, callback, state)

    return handler


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
    logger.info(
        "Бот запущен, разрешённых пользователей: %s, из них админов: %s",
        len(settings.permitted_telegram_ids),
        len(settings.admin_telegram_ids),
    )

    # Меню берётся из реестра команд, а не собирается заново: экран один, и
    # второй его сборки, живущей отдельно, быть не должно.
    notify_server_app = NotifyServer(
        AIOGRAM_WRAPPER,
        cast("MenuCommand", MANAGER.get(CommandName.MENU)),
    ).build_app()

    notify_config = uvicorn.Config(
        notify_server_app,
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
