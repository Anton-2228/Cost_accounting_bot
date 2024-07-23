from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from Spreadsheet import Spreadsheet


class Command:
    def __init__(self, command_manager):
        self.spreadsheet = Spreadsheet()
        self.commandManager = command_manager

    async def execute(self, message: Message, state: FSMContext):
        pass
