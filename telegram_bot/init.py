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
from aiogram.fsm.storage.redis import RedisStorage

from telegram_bot.access import AccessGuard
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.commands import Manager, get_commands
from telegram_bot.config import settings
from telegram_bot.notifications import NotificationCatchUp

BOT = Bot(
    token=settings.telegram_bot_token,
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

ACCESS = AccessGuard(settings.allowed_telegram_ids)
MANAGER = Manager(ACCESS, AIOGRAM_WRAPPER)
MANAGER.register(get_commands(MANAGER, API, AIOGRAM_WRAPPER, CATCH_UP))
