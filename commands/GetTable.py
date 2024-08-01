from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from database.queries.spreadsheets_queries import get_spreadsheetid
from database.queries.users_queries import get_user


class GetTable(Command):
    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        user = get_user(message.from_user.id)
        if user == None:
            await message.answer('Сначала создайте таблицу')
            return

        spreadsheetid = get_spreadsheetid(message.from_user.id)
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheetid}/edit#gid=0"
        await message.answer("ссылка на таблицу: " + url)
