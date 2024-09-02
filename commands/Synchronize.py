import datetime
import time

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from commands.utils.Synchronize_utils import (sync_cat_from_table_to_db,
                                              sync_sour_from_table_to_db,
                                              sync_total_from_db_to_table)
from datafiles import ALF, DAYSUNTILNEXTMONTH
from init import States


class Synchronize(Command):
    async def execute(
        self, message: Message, state: FSMContext, command: CommandObject
    ):
        success = True

        user = self.postgres_wrapper.users_wrapper.get_user(message.from_user.id)
        if user == None:
            await message.answer("Сначала создайте таблицу")
            return

        spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(
            message.from_user.id
        )
        category_value = await sync_cat_from_table_to_db(
            spreadsheet, self.spreadsheetWrapper, self.postgres_wrapper
        )
        source_value = await sync_sour_from_table_to_db(
            spreadsheet, self.spreadsheetWrapper, self.postgres_wrapper
        )
        total_values = await sync_total_from_db_to_table(
            spreadsheet, self.postgres_wrapper
        )

        if isinstance(category_value, str):
            await message.answer(category_value)
            success = False
            await state.set_state(States.CORRECT_TABLE)
        else:
            values = []
            values.append(category_value)
            values += total_values
            self.spreadsheetWrapper.cleanValues(
                spreadsheet.spreadsheet_id, "Categories!A2:G100000"
            )
            self.spreadsheetWrapper.cleanValues(
                spreadsheet.spreadsheet_id,
                f'{"Stat. " + str(spreadsheet.start_date)}!'
                f"A2:{ALF[str(DAYSUNTILNEXTMONTH[str(spreadsheet.start_date.month)])]}100000",
            )

            self.spreadsheetWrapper.setValues(spreadsheet.spreadsheet_id, values)

            sheets = self.spreadsheetWrapper.getSheets(spreadsheet.spreadsheet_id)
            self.spreadsheetWrapper.spreadSheetSetStyler.setStyleTotalLists(
                spreadsheet.spreadsheet_id,
                sheets["Stat. " + str(spreadsheet.start_date)],
                DAYSUNTILNEXTMONTH[str(spreadsheet.start_date.month)],
                total_values[0][-1],
                total_values[1][-1],
            )

        if isinstance(source_value, str):
            await message.answer(source_value)
            success = False
            await state.set_state(States.CORRECT_TABLE)
        else:
            values = []
            values.append(source_value)
            self.spreadsheetWrapper.cleanValues(
                spreadsheet.spreadsheet_id, "Bills!A2:F100000"
            )
            self.spreadsheetWrapper.setValues(spreadsheet.spreadsheet_id, values)

        if success:
            await state.clear()
            await message.answer("Синхронизация успешна")
