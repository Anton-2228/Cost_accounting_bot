from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from commands.utils.Synchronize_utils import (sync_records_from_db_to_table,
                                              sync_sour_from_table_to_db,
                                              sync_total_from_db_to_table)
from database import RecordsOrm
from validation import validate_delete_command_args


class DeleteRecord(Command):
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
        delete_id = command.args
        records: list[RecordsOrm] = (
            self.postgres_wrapper.records_wrapper.get_records_by_current_month(
                spreadsheet.id, spreadsheet.start_date
            )
        )
        delete_record = None
        if delete_id == None:
            delete_record: RecordsOrm = records[-1]
        else:
            err_message = validate_delete_command_args(command.args)
            if err_message != None:
                await message.answer(err_message)
            delete_id = int(command.args)
            for i in records:
                if i.id == delete_id:
                    delete_record: RecordsOrm = i
        if delete_record == None:
            await message.answer("Операции с таким id нет.")
            return

        self.postgres_wrapper.records_wrapper.remove_record(delete_record.id)

        self.postgres_wrapper.sources_wrapper.update_current_balance(
            delete_record.source, -delete_record.amount
        )

        values = []
        value_record = sync_records_from_db_to_table(
            spreadsheet, self.postgres_wrapper
        )
        source_value = sync_sour_from_table_to_db(
            spreadsheet, self.spreadsheetWrapper, self.postgres_wrapper
        )
        total_values = sync_total_from_db_to_table(
            spreadsheet, self.postgres_wrapper
        )
        values.append(value_record)
        values.append(source_value)
        values += total_values

        self.spreadsheetWrapper.cleanValues(
            spreadsheet.spreadsheet_id, f"{str(spreadsheet.start_date)}!A2:F100000"
        )
        self.spreadsheetWrapper.setValues(spreadsheet.spreadsheet_id, values)
        await message.answer("Запить удалена")
