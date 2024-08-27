import asyncio
import datetime

from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from command_manager import CommandManager
from commands import get_commands
from commands.utils.Synchronize_utils import sync_total_from_db_to_table
from database import PostgresWrapper, create_tables
from init import (COMMANDS, States, bot, daysUntilNextMonth, dp, router,
                  telethon_bot)

# bot = createBot(os.getenv('API_TOKEN'))
# telethon_bot = TelethonBot()
# dp = createDispatcher()
# router = createRouter() = createRouter()
postgres_wrapper = PostgresWrapper()
commandManager = CommandManager()
commandManager.addCommands(get_commands(commandManager, postgres_wrapper))

# data = GlobalVariables.data
# globTimer = GlobalVariables.globTimer
# counter = GlobalVariables.counter


@router.message(Command("start"), StateFilter(None))
@router.message(States.COMFIRM_CHANGE_DATE_RESET)
@router.message(States.CHOICE_TABLE_NAME)
@router.message(States.SET_EMAIL)
async def startFunc(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand("start", message, state, command)


@router.message(Command("addemail"), StateFilter(None))
@router.message(States.ADD_EMAIL)
async def addEmail(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand("addEmail", message, state, command)


@router.message(Command("help"), StateFilter(None))
async def help(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand("help", message, state, command)


@router.message(Command("sync"), StateFilter(None))
@router.message(States.CORRECT_TABLE, Command("sync"))
async def synchronize(
    message: Message, state: FSMContext, command: CommandObject = None
):
    response = await commandManager.launchCommand("sync", message, state, command)


@router.message(Command("transfer"), StateFilter(None))
async def transfer(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand("transfer", message, state, command)


@router.message(States.CORRECT_TABLE)
async def errorRecord(
    message: Message, state: FSMContext, command: CommandObject = None
):
    await message.answer("Исправьте таблицу и синхронизируйте её")


@router.message(Command("table"), StateFilter(None))
async def getTable(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand("table", message, state, command)


@router.message(Command("del"), StateFilter(None))
async def deleteLastRecord(
    message: Message, state: FSMContext, command: CommandObject = None
):
    response = await commandManager.launchCommand("del", message, state, command)


@router.message(Command("deletetable"), StateFilter(None))
@router.message(States.COMFIRM_DELETE)
async def deleteTable(
    message: Message, state: FSMContext, command: CommandObject = None
):
    response = await commandManager.launchCommand(
        "deleteTable", message, state, command
    )


@router.message(Command("add"), StateFilter(None))
async def newRecord(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand("addRecord", message, state, command)


@router.message(StateFilter(None))
@router.message(States.CONFIRM_TYPES_CHECK)
@router.message(States.CONFIRM_CATEGORIES_CHECK)
@router.message(States.FINISH_CHECK)
async def newCheck(message: Message, state: FSMContext, command: CommandObject = None):
    response = await commandManager.launchCommand("addCheck", message, state, command)


async def start_polling():
    await bot.set_my_commands(commands=COMMANDS)
    dp.include_routers(router)
    await dp.start_polling(bot)


async def timer():
    while True:
        spreadsheets = postgres_wrapper.spreadsheets_wrapper.get_all_spreadsheets()
        for i in spreadsheets:
            end_date = i.start_date + datetime.timedelta(
                days=daysUntilNextMonth[i.start_date.month]
            )
            # tz = datetime.timezone(datetime.timedelta(hours=2, minutes=50))
            # today = datetime.datetime.now(tz=tz).date()
            today = datetime.date.today()
            if today == end_date:
                spreadsheetWrapper = commandManager.getCommands()[
                    "help"
                ].spreadsheetWrapper
                postgres_wrapper.spreadsheets_wrapper.update_start_date(i.id, end_date)
                spreadsheet = postgres_wrapper.sources_wrapper.get_spreadsheet_by_id(
                    i.id
                )
                response = spreadsheetWrapper.addNewOperationsSheet(
                    spreadsheet.spreadsheet_id, end_date
                )
                response = spreadsheetWrapper.addNewStatisticsSheet(
                    spreadsheet.spreadsheet_id,
                    end_date,
                    daysUntilNextMonth[end_date.month],
                )
                total_values = sync_total_from_db_to_table(
                    spreadsheet, postgres_wrapper
                )
                values = []
                values += total_values

                spreadsheetWrapper.setValues(spreadsheet.spreadsheet_id, values)

                sheets = spreadsheetWrapper.getSheets(spreadsheet.spreadsheet_id)
                spreadsheetWrapper.spreadSheetSetStyler.setStyleTotalLists(
                    spreadsheet.spreadsheet_id,
                    sheets["Stat. " + str(spreadsheet.start_date)],
                    daysUntilNextMonth[spreadsheet.start_date.month],
                    total_values[0][-1],
                    total_values[1][-1],
                )

        await asyncio.sleep(60)


async def start():
    # await asyncio.gather(telethon_bot.start())
    # async with telethon_bot:
    # await telethon_bot.client.get_me()
    # await telethon_bot.start()
    # telethon_bot.client.loop.run_until_complete(telethon_bot.start())
    await asyncio.gather(start_polling(), timer(), telethon_bot.start())


if __name__ == "__main__":
    create_tables()
    asyncio.run(start())
