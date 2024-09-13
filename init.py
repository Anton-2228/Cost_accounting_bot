import os

import googleapiclient.discovery
import httplib2
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials

dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

from check_wrapper import TelethonBot
from database.queries.postgres_wrapper import PostgresWrapper

credentials = ServiceAccountCredentials.from_json_keyfile_name(
    os.getenv("credentials_google_api_service_account"),
    [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ],
)
httpAuth = credentials.authorize(httplib2.Http())

storage = MemoryStorage()

bot = Bot(
    token=os.getenv("API_TOKEN"),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=storage)
router = Router()

postgres_wrapper = PostgresWrapper()

telethon_bot = TelethonBot(bot, postgres_wrapper)


class States(StatesGroup):
    CHOICE_TABLE_NAME = State()
    SET_EMAIL = State()
    CORRECT_TABLE = State()
    COMFIRM_DELETE = State()
    COMFIRM_CHANGE_DATE_RESET = State()
    ADD_EMAIL = State()
    CONFIRM_TYPES_CHECK = State()
    CONFIRM_CATEGORIES_CHECK = State()
    FINISH_CHECK = State()


COMMANDS = [
    BotCommand(command="check", description="Начать добавление новых чеков в базу"),
    BotCommand(command="add", description="Добавление новой записи в таблицу"),
    BotCommand(command="del", description="Удаление указанной записи(либо последней)"),
    BotCommand(command="transfer", description="Перевод денег со счета на счет"),
    BotCommand(command="cancel", description="Отмена обработки чеков"),
    BotCommand(command="skip", description="Пропуск текущего чека"),
    BotCommand(command="remove", description="Удаление текущего чека"),
    BotCommand(command="table", description="Получить ссылку на таблицу"),
    BotCommand(command="sync", description="Синхронизация таблицы и бота"),
    BotCommand(command="help", description="Вывести подсказку по боту"),
    BotCommand(command="start", description="Создание новой таблицы"),
    BotCommand(command="addemail", description="Привязать новой почты"),
    BotCommand(command="deletetable", description="Удаление таблицы"),
]

# async def get_user_state(user_id: int):
#     storage_key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
#     context = FSMContext(storage=dp.storage, key=storage_key)
#     state = await context.get_state()
#     return state


def createSheetService():
    sheetService = googleapiclient.discovery.build("sheets", "v4", http=httpAuth)
    return sheetService


def createDriveService():
    driveService = googleapiclient.discovery.build("drive", "v3", http=httpAuth)
    return driveService
