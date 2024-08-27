from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from datafiles import HELP_MESSAGE


class GetHelp(Command):
    def __init__(self, command_manager, postgres_wrapper):
        super().__init__(command_manager, postgres_wrapper)
        self.help = HELP_MESSAGE

    async def execute(
        self, message: Message, state: FSMContext, command: CommandObject
    ):
        await message.answer(self.help)
