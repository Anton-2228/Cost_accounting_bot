from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from commands.utils.AddRecord_utils import (add_record, create_add_message,
                                            parse_records_row)
from database import CategoriesOrm, SourcesOrm


class AddRecord(Command):
    async def execute(
        self, message: Message, state: FSMContext, command: CommandObject
    ):
        user = self.postgres_wrapper.users_wrapper.get_user(message.from_user.id)
        if user == None:
            await message.answer("Сначала создайте таблицу")
            return

        row_line = command.args
        user_id = message.from_user.id
        spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(
            user_id
        )
        categories: list[CategoriesOrm] = (
            self.postgres_wrapper.categories_wrapper.get_active_categories_by_spreadsheet(
                spreadsheet.id
            )
        )
        sources: list[SourcesOrm] = (
            self.postgres_wrapper.sources_wrapper.get_sources_by_spreadsheet(
                spreadsheet.id
            )
        )

        response = parse_records_row(row_line, categories, sources)
        if response["status"] == "error":
            await message.answer(response["message"])
        data = response["value"]

        add_result = await add_record(
            data=response["value"],
            spreadsheet=spreadsheet,
            commandManager=self.commandManager,
            spreadsheetWrapper=self.spreadsheetWrapper,
            postgres_wrapper=self.postgres_wrapper,
        )
        data["id"] = add_result

        add_message = create_add_message(data)

        await message.answer(add_message)
