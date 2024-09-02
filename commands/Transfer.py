from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from commands.utils.Synchronize_utils import sync_sour_from_table_to_db
from database import SourcesOrm
from validation import validate_transfer_command_args


class Transfer(Command):
    async def execute(
        self, message: Message, state: FSMContext, command: CommandObject
    ):
        user = self.postgres_wrapper.users_wrapper.get_user(message.from_user.id)
        if user == None:
            await message.answer("Сначала создайте таблицу")
            return

        spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(
            message.from_user.id
        )
        sources: list[SourcesOrm] = (
            self.postgres_wrapper.sources_wrapper.get_sources_by_spreadsheet(
                spreadsheet.id
            )
        )
        err_message = validate_transfer_command_args(command.args, sources)
        if err_message != None:
            await message.answer(err_message)
            return

        args = command.args.split()
        amount = int(args[0])
        from_source = args[1].lower()
        to_source = args[2].lower()

        for i in sources:
            if from_source in i.associations:
                from_source = i

        for i in sources:
            if to_source in i.associations:
                to_source = i

        self.postgres_wrapper.sources_wrapper.update_current_balance(
            from_source.id, -amount
        )
        self.postgres_wrapper.sources_wrapper.update_current_balance(
            to_source.id, amount
        )

        values = []
        source_value = sync_sour_from_table_to_db(
            spreadsheet, self.spreadsheetWrapper, self.postgres_wrapper
        )
        values.append(source_value)
        self.spreadsheetWrapper.setValues(spreadsheet.spreadsheet_id, values)

        await message.answer("Перевод успешен")
