from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from spreadsheet import Spreadsheet
from spreadsheet_set_styles import SpreadSheetSetStyler


class Command:
    def __init__(self, command_manager):
        self.spreadsheet = Spreadsheet()
        self.commandManager = command_manager

    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        pass
