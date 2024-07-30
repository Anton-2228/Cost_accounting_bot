from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from database.models import RecordsOrm
from database.queries.categories_queries import get_category
from database.queries.records_queries import get_records_by_current_month, remove_record
from database.queries.sources_queries import update_current_balance, get_source
from database.queries.spreadsheets_queries import get_spreadsheet
from validation import validate_delete_command_args


class DeleteRecord(Command):
    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        spreadsheet = get_spreadsheet(message.from_user.id)
        delete_id = command.args
        print(delete_id)
        records: list[RecordsOrm] = get_records_by_current_month(spreadsheet.id, spreadsheet.start_date)
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

        remove_record(delete_record.id)

        update_current_balance(delete_record.source, -delete_record.amount)

        values = []
        value_record = await self.commandManager.getCommands()['sync'].sync_records(spreadsheet)
        source_value = await self.commandManager.getCommands()['sync'].sync_sour(message)
        values.append(value_record)
        values.append(source_value)

        self.spreadsheet.cleanValues(spreadsheet.spreadsheet_id, f'{str(spreadsheet.start_date)}!A2:F100000')
        self.spreadsheet.setValues(spreadsheet.spreadsheet_id, values)
        await message.answer("Запить удалена")