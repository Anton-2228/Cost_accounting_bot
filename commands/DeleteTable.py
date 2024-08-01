from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from database.queries.spreadsheets_queries import get_spreadsheet, remove_spreadsheet
from database.queries.users_queries import get_user, remove_user
from init import States


class DeleteTable(Command):
    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        user = get_user(message.from_user.id)
        if user == None:
            await message.answer('Сначала создайте таблицу')
            return

        cur_state = await state.get_state()
        if cur_state == None:
            await state.set_state(States.COMFIRM_DELETE)
            await message.answer(
                "Напишите 'ПОДТВЕРЖДАЮ УДАЛЕНИЕ' для удаления таблицы.\nСама таблица существовать продолжит, однако привязать её к боту будет уже невозможно")
        elif cur_state == States.COMFIRM_DELETE:
            text = message.text
            if text != "ПОДТВЕРЖДАЮ УДАЛЕНИЕ":
                await message.answer('Удаление таблицы отменено')
            else:
                user = get_user(message.from_user.id)
                spreadsheet = get_spreadsheet(message.from_user.id)
                remove_user(user.id)
                remove_spreadsheet(spreadsheet.id)
                await state.clear()
                await message.answer('Для создания новой таблицы напишите /start')
