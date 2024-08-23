from aiogram.types import Message

from database.queries.spreadsheets_queries import get_spreadsheet
from database.queries.users_queries import get_user


async def check_user_exist(message: Message):
    user = get_user(message.from_user.id)
    if user == None:
        await message.answer('Сначала создайте таблицу')
        return "error"
    return "success"

async def check_spreadsheet_exist(message: Message):
    spreadsheet = get_spreadsheet(message.from_user.id)
    if spreadsheet != None:
        await message.answer('Таблица уже создана')
        return "error"
    return "success"
