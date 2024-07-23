import re

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from database.queries.spreadsheets_queries import add_gmail, get_spreadsheetid
from init import States


class AddEmail(Command):
    async def execute(self, message: Message, state: FSMContext):
        cur_state = await state.get_state()
        if cur_state == None:
            await state.set_state(States.ADD_EMAIL)
            await message.answer("Пришлите почту на домене @gmail")

        elif cur_state == States.ADD_EMAIL:
            if re.fullmatch(r'\w+@gmail.com', message.text) == None:
                await message.answer("Мне почта не нравится, давай другую")
            else:
                gmail = message.text
                add_gmail(message.from_user.id, gmail)
                spreadsheetid = get_spreadsheetid(message.from_user.id)
                self.spreadsheet.issueRights(spreadsheetid, "user", "writer", gmail)
                await state.clear()
                await message.answer("Права добавлены")
