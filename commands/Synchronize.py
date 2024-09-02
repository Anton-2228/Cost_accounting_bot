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
                f"A2:{ALF[DAYSUNTILNEXTMONTH[spreadsheet.start_date.month]]}100000",
            )

            self.spreadsheetWrapper.setValues(spreadsheet.spreadsheet_id, values)

            sheets = self.spreadsheetWrapper.getSheets(spreadsheet.spreadsheet_id)
            self.spreadsheetWrapper.spreadSheetSetStyler.setStyleTotalLists(
                spreadsheet.spreadsheet_id,
                sheets["Stat. " + str(spreadsheet.start_date)],
                DAYSUNTILNEXTMONTH[spreadsheet.start_date.month],
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

    # async def sync_cat_from_table_to_db(self, spreadsheet):
    #     resultSyncCat = synchronizeCategories(spreadsheet, "Categories!A2:G100000", self.spreadsheetWrapper)
    #     if resultSyncCat is not None:
    #         if resultSyncCat['result'] == 'error':
    #             return resultSyncCat['message']
    #         categories = resultSyncCat['categories']
    #         return ["Categories", "ROWS", f'A2:G{len(categories) + 2}', categories]
    #     return 'Добавьте хотя бы одну категорию'
    #
    # async def sync_sour_from_table_to_db(self, spreadsheet):
    #     resultSyncSour = synchronizeSources(spreadsheet, "Bills!A2:F100000", self.spreadsheetWrapper)
    #     if resultSyncSour is not None:
    #         if resultSyncSour['result'] == 'error':
    #             return resultSyncSour['message']
    #         sources = resultSyncSour['sources']
    #         return ["Bills", "ROWS", f'A2:F{len(sources) + 2}', sources]
    #     return 'Добавьте хотя бы один источник'

    # async def sync_records_from_db_to_table(self, spreadsheet):
    #     records: list[RecordsOrm] = get_records_by_current_month(spreadsheet.id, spreadsheet.start_date)
    #     value = []
    #     for i in records:
    #         category = get_category(i.category)
    #         source = get_source(i.source)
    #         value.append([i.id, str(i.added_at), i.amount, category.title, i.notes, source.title, i.product_name, i.check_json,])
    #
    #     return [str(spreadsheet.start_date), 'ROWS', f'A2:H{len(value) + 1}', value]
    #
    # async def sync_total_from_db_to_table(self, spreadsheet: SpreadSheetsOrm):
    #     dates = []
    #     date = spreadsheet.start_date
    #     for i in range(daysUntilNextMonth[spreadsheet.start_date.month]):
    #         dates.append(date)
    #         date += datetime.timedelta(days=1)
    #
    #     categories: list[CategoriesOrm] = get_categories_by_spreadsheet(spreadsheet.id)
    #     income_categories = {i: [] for i in categories if i.type == CategoriesTypes.INCOME}
    #     cost_categories = {i: [] for i in categories if i.type == CategoriesTypes.COST}
    #
    #     total_income = [0 for _ in range(daysUntilNextMonth[spreadsheet.start_date.month]+1)]
    #     for i in income_categories:
    #         records: list[RecordsOrm] = get_records_by_current_month_by_category(spreadsheet.id, spreadsheet.start_date, i.id)
    #         records = sorted(records, key=lambda x: x.added_at)
    #         income_categories[i].append(0)
    #         for x, z in enumerate(dates):
    #             su = int(sum([x.amount for x in records if x.added_at == z]))
    #             income_categories[i].append(su)
    #             income_categories[i][0] += su
    #             total_income[x+1] += su
    #         income_categories[i][0] = int(income_categories[i][0])
    #         total_income[0] += income_categories[i][0]
    #         # income_categories[i][0] = int(income_categories[i][0])
    #     # total_income[0] = int(total_income[0])
    #
    #     total_cost = [0 for _ in range(daysUntilNextMonth[spreadsheet.start_date.month] + 1)]
    #     for i in cost_categories:
    #         records: list[RecordsOrm] = get_records_by_current_month_by_category(spreadsheet.id, spreadsheet.start_date, i.id)
    #         records = sorted(records, key=lambda x: x.added_at)
    #         cost_categories[i].append(0)
    #         for x, z in enumerate(dates):
    #             su = int(sum([x.amount for x in records if x.added_at == z]))
    #             cost_categories[i].append(su)
    #             cost_categories[i][0] += su
    #             total_cost[x+1] += su
    #         total_cost[0] += cost_categories[i][0]
    #         # cost_categories[i][0] = int(cost_categories[i][0])
    #     # total_cost[0] = int(total_cost[0])
    #
    #     values = []
    #
    #     income_value = []
    #     row = ['Общие доходы'] + total_income
    #     income_value.append(row)
    #     for i in income_categories:
    #         row = [str(i.title)] + income_categories[i]
    #         income_value.append(row)
    #     values.append(["Stat. " + str(spreadsheet.start_date), 'ROWS',
    #                     f'A2:{alf[daysUntilNextMonth[spreadsheet.start_date.month]]}{len(income_value)+2}', income_value])
    #
    #     cost_value = []
    #     row = ['Общие расходы'] + total_cost
    #     cost_value.append(row)
    #     for i in cost_categories:
    #         row = [str(i.title)] + cost_categories[i]
    #         cost_value.append(row)
    #     values.append(["Stat. " + str(spreadsheet.start_date), 'ROWS',
    #                    f'A{len(income_value) + 2 + 1}:{alf[daysUntilNextMonth[spreadsheet.start_date.month]]}{len(income_value) + len(cost_value) + 2 + 1}', cost_value])
    #
    #     # self.spreadsheet.cleanValues(spreadsheet.spreadsheet_id,
    #     #                              f'{"Stat. " + str(spreadsheet.start_date)}!'
    #     #                              f'A2:{alf[daysUntilNextMonth[spreadsheet.start_date.month]]}100000')
    #     #
    #     # self.spreadsheet.setValues(spreadsheet.spreadsheet_id, values)
    #
    #     return values
