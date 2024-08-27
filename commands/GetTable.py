from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command


class GetTable(Command):
    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        user = self.postgres_wrapper.users_wrapper.get_user(message.from_user.id)
        if user == None:
            await message.answer('Сначала создайте таблицу')
            return

        spreadsheetid = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheetid(message.from_user.id)
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheetid}/edit#gid=0"
        await message.answer("ссылка на таблицу: " + url)
