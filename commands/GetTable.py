from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from database.queries.spreadsheets_queries import get_spreadsheetid


class GetTable(Command):
    async def execute(self, message: Message, state: FSMContext):
        spreadsheetid = get_spreadsheetid(message.from_user.id)
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheetid}/edit#gid=0"
        await message.answer("ссылка на таблицу: " + url)
