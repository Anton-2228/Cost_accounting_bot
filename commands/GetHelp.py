from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command


class GetHelp(Command):
    def __init__(self, command_manager):
        super().__init__(command_manager)
        with open('datafiles/help.txt', 'r', encoding='utf-8') as file:
            self.help = file.read()

    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        await message.answer(self.help)
