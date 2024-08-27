from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from init import States


class DeleteTable(Command):
    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        user = self.postgres_wrapper.users_wrapper.get_user(message.from_user.id)
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
                user = self.postgres_wrapper.users_wrapper.get_user(message.from_user.id)
                spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(message.from_user.id)
                self.postgres_wrapper.users_wrapper.remove_user(user.id)
                self.postgres_wrapper.spreadsheets_wrapper.remove_spreadsheet(spreadsheet.id)
                await state.clear()
                await message.answer('Для создания новой таблицы напишите /start')
