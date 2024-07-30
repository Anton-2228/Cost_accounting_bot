import os

import asyncio
from aiogram.filters import Command, StateFilter, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from CommandManager import CommandManager
from commands import get_commands
from database.core import create_tables
from init import createBot, createDispatcher, createRouter, States

bot = createBot(os.getenv('API_TOKEN'))
dp = createDispatcher()
router = createRouter()
commandManager = CommandManager()
commandManager.addCommands(get_commands(commandManager))

# data = GlobalVariables.data
# globTimer = GlobalVariables.globTimer
# counter = GlobalVariables.counter

@router.message(Command('start'))
@router.message(States.COMFIRM_CHANGE_DATE_RESET)
@router.message(States.CHOICE_TABLE_NAME)
@router.message(States.SET_EMAIL)
async def startFunc(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand('start', message, state, command)

@router.message(Command('addemail'))
@router.message(States.ADD_EMAIL)
async def addEmail(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand('addEmail', message, state, command)

@router.message(Command('help'))
async def help(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand('help', message, state, command)

@router.message(Command('sync'))
@router.message(States.CORRECT_TABLE, Command('sync'))
async def synchronize(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand('sync', message, state, command)

@router.message(Command('transfer'))
async def transfer(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand('transfer', message, state, command)

@router.message(States.CORRECT_TABLE)
async def errorRecord(message: Message, state: FSMContext, command: CommandObject = None):
    await message.answer("Исправьте таблицу и синхронизируйте её")

@router.message(Command('table'))
async def getTable(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand('table', message, state, command)

@router.message(Command('del'))
async def deleteLastRecord(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand('del', message, state, command)

@router.message(Command('deletetable'))
@router.message(States.COMFIRM_DELETE)
async def deleteTable(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand('deleteTable', message, state, command)

@router.message(StateFilter(None))
async def newRecord(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand('addRecord', message, state, command)

async def start_polling():
    dp.include_routers(router)
    await dp.start_polling(bot)

async def start():
    await asyncio.gather(start_polling())
    # await asyncio.gather(start_polling(), timer())

if __name__ == "__main__":
    create_tables()
    asyncio.run(start())
