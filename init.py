import json
import os

import httplib2
import googleapiclient.discovery
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials

from aiogram import Bot, Dispatcher, Router
# from aiogram.contrib.fsm_storage.memory import MemoryStorage
# from aiogram.contrib.middlewares.logging import LoggingMiddleware

from command_manager import CommandManager
from telethon_bot import TelethonBot

# from Timer import Timer

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

credentials = ServiceAccountCredentials.from_json_keyfile_name(os.getenv('credentials_google_api_service_account'),
                                                                   ['https://www.googleapis.com/auth/spreadsheets',
                                                                    'https://www.googleapis.com/auth/drive'])
httpAuth = credentials.authorize(httplib2.Http())

storage = MemoryStorage()

bot = Bot(token=os.getenv('API_TOKEN'),
          default=DefaultBotProperties(
              parse_mode=ParseMode.HTML
          ))

dp = Dispatcher(storage=storage)

router = Router()

telethon_bot = TelethonBot()

class States(StatesGroup):
    # mode = HelperMode.snake_case

    CHOICE_TABLE_NAME = State()
    SET_EMAIL = State()
    CORRECT_TABLE = State()
    COMFIRM_DELETE = State()
    COMFIRM_CHANGE_DATE_RESET = State()
    ADD_EMAIL = State()
    CONFIRM_TYPES_CHECK = State()
    CONFIRM_CATEGORIES_CHECK = State()
    FINISH_CHECK = State()

async def get_user_state(user_id: int):
    storage_key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    context = FSMContext(storage=dp.storage, key=storage_key)
    state = await context.get_state()
    return state

# def createBot(token):
#     # bot = Bot(token=Settings.API_TOKEN)
#     bot = Bot(token=token)
#     return bot

# def createDispatcher():
#     dp = Dispatcher(storage=storage)
#     return dp

# def createRouter():
#     router = Router()
#     return router

def createSheetService():
    sheetService = googleapiclient.discovery.build('sheets', 'v4', http=httpAuth)
    return sheetService

def createDriveService():
    driveService = googleapiclient.discovery.build('drive', 'v3', http=httpAuth)
    return driveService

def getTemplateTitle():
    with open('datafiles/templateTitle.json', 'r') as file:
        titles = json.load(file)
    return titles

def getTemplateOperations():
    with open('datafiles/templateOperations.json', 'r') as file:
        templateOperatios = json.load(file)
    return templateOperatios

def getTemplateStatistics():
    with open('datafiles/templateStatistics.json', 'r') as file:
        templateStatistics = json.load(file)
    return templateStatistics

def getFirstPrompt():
    with open('datafiles/prompts/first.txt', 'r') as file:
        prompt = file.read()
    return prompt

def getSecondPrompt():
    with open('datafiles/prompts/second.txt', 'r') as file:
        prompt = file.read()
    return prompt

# def createTimer():
#     return Timer()

daysUntilNextMonth = {1: 31,
                      2: 28,
                      3: 31,
                      4: 30,
                      5: 31,
                      6: 30,
                      7: 31,
                      8: 31,
                      9: 30,
                      10: 31,
                      11: 30,
                      12: 31}

alf = {0:'C',
       1:'D',
       2:'E',
       3:'F',
       4:'G',
       5:'H',
       6:'I',
       7:'J',
       8:'K',
       9:'L',
       10:'M',
       11:'N',
       12:'O',
       13:'P',
       14:'Q',
       15:'R',
       16:'S',
       17:'T',
       18:'U',
       19:'V',
       20:'W',
       21:'X',
       22:'Y',
       23:'Z',
       24:'AA',
       25:'AB',
       26:'AC',
       27:'AD',
       28:'AE',
       29:'AF',
       30:'AG',
       31:'AH'}
