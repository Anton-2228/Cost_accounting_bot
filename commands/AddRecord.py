from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from commands.utils.AddRecord_utils import parse_records_row, add_record, create_add_message
from database.models import CategoriesOrm, SourcesOrm
from database.queries.categories_queries import get_categories_by_spreadsheet
from database.queries.sources_queries import get_sources_by_spreadsheet
from database.queries.spreadsheets_queries import get_spreadsheet
from database.queries.users_queries import get_user


class AddRecord(Command):
    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        user = get_user(message.from_user.id)
        if user == None:
            await message.answer('Сначала создайте таблицу')
            return

        row_line = command.args
        user_id = message.from_user.id
        spreadsheet = get_spreadsheet(user_id)
        categories: list[CategoriesOrm] = get_categories_by_spreadsheet(spreadsheet.id)
        sources: list[SourcesOrm] = get_sources_by_spreadsheet(spreadsheet.id)

        response = parse_records_row(row_line, categories, sources)
        if response["status"] == 'error':
            await message.answer(response["message"])
        data = response["value"]

        add_result = await add_record(data=response["value"],
                                      spreadsheet=spreadsheet,
                                      commandManager=self.commandManager,
                                      spreadsheetWrapper=self.spreadsheetWrapper)
        data["id"] = add_result

        add_message = create_add_message(data)

        await message.answer(add_message)
