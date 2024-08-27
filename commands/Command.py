from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from command_manager import CommandManager
from spreadsheet_wrapper import SpreadsheetWrapper


class Command:
    def __init__(self, command_manager, postgres_wrapper):
        self.spreadsheetWrapper: SpreadsheetWrapper = SpreadsheetWrapper()
        self.commandManager: CommandManager = command_manager
        self.postgres_wrapper = postgres_wrapper

    async def execute(
        self, message: Message, state: FSMContext, command: CommandObject
    ):
        pass
