"""Сборка графа объектов бота.

Импорт этого модуля создаёт `Bot`, `Dispatcher`, клиент api и реестр команд.
Побочный эффект сознательный и такой же, как в эталонном проекте: собирать
граф в одном месте проще, чем протаскивать зависимости через каждый
обработчик. Сетевых обращений на импорте при этом не происходит — только
конструирование.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.redis import RedisStorage

from telegram_bot.access import AccessGuard
from telegram_bot.ai import AiClient
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.commands import Manager, get_commands
from telegram_bot.config import settings
from telegram_bot.notifications import NotificationCatchUp

# Прокси — свойство одной только сессии Telegram. `None` означает «своя сессия
# без прокси», это и есть умолчание aiogram; отдельной ветки на запуск без
# прокси не нужно. Схема `socks5://` требует установленного `aiohttp-socks`
# (зависимость проекта): без него aiogram падает на конструкторе с RuntimeError,
# а не молча ходит напрямую.
SESSION = AiohttpSession(proxy=settings.telegram_proxy_url) if settings.telegram_proxy_url else None

BOT = Bot(
    token=settings.telegram_bot_token,
    session=SESSION,
    default=DefaultBotProperties(parse_mode=None),
)

# Состояние в Redis, а не в памяти: диалог создания таблицы не должен
# рассыпаться от перезапуска контейнера, а второго хранилища промежуточных
# данных в боте нет.
STORAGE = RedisStorage.from_url(settings.redis_url)
DISPATCHER = Dispatcher(storage=STORAGE)
ROUTER = Router()
DISPATCHER.include_router(ROUTER)

AIOGRAM_WRAPPER = AiogramWrapper(BOT, ROUTER, DISPATCHER)
API = ApiGateway(settings.api_base_url, timeout=settings.api_timeout_seconds)
CATCH_UP = NotificationCatchUp(API, AIOGRAM_WRAPPER)

# Клиент модели нужен одному сценарию — разбору чека. Собирается здесь же:
# сетевых обращений на импорте не происходит, только конструирование.
AI = AiClient(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    model=settings.openai_model,
    timeout=settings.ai_timeout_seconds,
    temperature=settings.ai_temperature,
)

ACCESS = AccessGuard(settings.allowed_telegram_ids)
MANAGER = Manager(ACCESS, AIOGRAM_WRAPPER)
MANAGER.register(get_commands(MANAGER, API, AIOGRAM_WRAPPER, CATCH_UP, AI))
