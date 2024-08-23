from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from spreadsheet_wrapper.spreadsheetwrapper import SpreadsheetWrapper


class Command:
    def __init__(self, command_manager):
        self.spreadsheetWrapper = SpreadsheetWrapper()
        self.commandManager = command_manager

    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        pass
