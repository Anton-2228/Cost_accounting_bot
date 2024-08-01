import datetime
import time

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from database.models import RecordsOrm, CategoriesOrm, CategoriesTypes, SpreadSheetsOrm
from database.queries.categories_queries import synchronizeCategories, get_category, get_categories_by_spreadsheet
from database.queries.records_queries import get_records_by_current_month, get_records_by_current_month_by_category
from database.queries.sources_queries import synchronizeSources, get_source
from database.queries.spreadsheets_queries import get_spreadsheet
from database.queries.users_queries import get_user
from init import daysUntilNextMonth, alf, States


class Synchronize(Command):
    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        success = True

        user = get_user(message.from_user.id)
        if user == None:
            await message.answer('Сначала создайте таблицу')
            return

        spreadsheet = get_spreadsheet(message.from_user.id)
        category_value = await self.sync_cat(message)
        source_value = await self.sync_sour(message)
        total_values = await self.sync_total(spreadsheet)

        if isinstance(category_value, str):
            await message.answer(category_value)
            success = False
            await state.set_state(States.CORRECT_TABLE)
        else:
            values = []
            values.append(category_value)
            values += total_values
            self.spreadsheet.cleanValues(spreadsheet.spreadsheet_id, 'Categories!A2:G100000')
            self.spreadsheet.cleanValues(spreadsheet.spreadsheet_id,
                                         f'{"Stat. " + str(spreadsheet.start_date)}!'
                                         f'A2:{alf[daysUntilNextMonth[spreadsheet.start_date.month]]}100000')

            self.spreadsheet.setValues(spreadsheet.spreadsheet_id, values)

            sheets = self.spreadsheet.getSheets(spreadsheet.spreadsheet_id)
            self.spreadsheet.spreadSheetSetStyler.setStyleTotalLists(spreadsheet.spreadsheet_id,
                                                                     sheets["Stat. " + str(spreadsheet.start_date)],
                                                                     daysUntilNextMonth[spreadsheet.start_date.month],
                                                                     total_values[0][-1],
                                                                     total_values[1][-1])

        if isinstance(source_value, str):
            await message.answer(source_value)
            success = False
            await state.set_state(States.CORRECT_TABLE)
        else:
            values = []
            values.append(source_value)
            self.spreadsheet.cleanValues(spreadsheet.spreadsheet_id, 'Bills!A2:F100000')
            self.spreadsheet.setValues(spreadsheet.spreadsheet_id, values)

        if success:
            await state.clear()
            await message.answer("Синхронизация успешна")

    async def sync_cat(self, message):
        resultSyncCat = synchronizeCategories(message, "Categories!A2:G100000", self.spreadsheet)
        if resultSyncCat is not None:
            if resultSyncCat['result'] == 'error':
                return resultSyncCat['message']
            categories = resultSyncCat['categories']
            return ["Categories", "ROWS", f'A2:G{len(categories) + 2}', categories]
        return 'Добавьте хотя бы одну категорию'

    async def sync_sour(self, message):
        resultSyncSour = synchronizeSources(message, "Bills!A2:F100000", self.spreadsheet)
        if resultSyncSour is not None:
            if resultSyncSour['result'] == 'error':
                return resultSyncSour['message']
            sources = resultSyncSour['sources']
            return ["Bills", "ROWS", f'A2:F{len(sources) + 2}', sources]
        return 'Добавьте хотя бы один источник'

    async def sync_records(self, spreadsheet):
        records: list[RecordsOrm] = get_records_by_current_month(spreadsheet.id, spreadsheet.start_date)
        value = []
        for i in records:
            category = get_category(i.category)
            source = get_source(i.source)
            value.append([i.id, str(i.added_at), i.amount, category.title, i.notes, source.title])

        return [str(spreadsheet.start_date), 'ROWS', f'A2:F{len(value) + 1}', value]

    async def sync_total(self, spreadsheet: SpreadSheetsOrm):
        dates = []
        date = spreadsheet.start_date
        for i in range(daysUntilNextMonth[spreadsheet.start_date.month]):
            dates.append(date)
            date += datetime.timedelta(days=1)

        categories: list[CategoriesOrm] = get_categories_by_spreadsheet(spreadsheet.id)
        income_categories = {i: [] for i in categories if i.type == CategoriesTypes.INCOME}
        cost_categories = {i: [] for i in categories if i.type == CategoriesTypes.COST}

        total_income = [0 for _ in range(daysUntilNextMonth[spreadsheet.start_date.month]+1)]
        for i in income_categories:
            records: list[RecordsOrm] = get_records_by_current_month_by_category(spreadsheet.id, spreadsheet.start_date, i.id)
            records = sorted(records, key=lambda x: x.added_at)
            income_categories[i].append(0)
            for x, z in enumerate(dates):
                su = sum([x.amount for x in records if x.added_at == z])
                income_categories[i].append(su)
                income_categories[i][0] += su
                total_income[x+1] += su
            total_income[0] += income_categories[i][0]

        total_cost = [0 for _ in range(daysUntilNextMonth[spreadsheet.start_date.month] + 1)]
        for i in cost_categories:
            records: list[RecordsOrm] = get_records_by_current_month_by_category(spreadsheet.id, spreadsheet.start_date, i.id)
            records = sorted(records, key=lambda x: x.added_at)
            cost_categories[i].append(0)
            for x, z in enumerate(dates):
                su = sum([x.amount for x in records if x.added_at == z])
                cost_categories[i].append(su)
                cost_categories[i][0] += su
                total_cost[x+1] += su
            total_cost[0] += cost_categories[i][0]

        values = []

        income_value = []
        row = ['Общие доходы'] + total_income
        income_value.append(row)
        for i in income_categories:
            row = [str(i.title)] + income_categories[i]
            income_value.append(row)
        values.append(["Stat. " + str(spreadsheet.start_date), 'ROWS',
                        f'A2:{alf[daysUntilNextMonth[spreadsheet.start_date.month]]}{len(income_value)+2}', income_value])

        cost_value = []
        row = ['Общие расходы'] + total_cost
        cost_value.append(row)
        for i in cost_categories:
            row = [str(i.title)] + cost_categories[i]
            cost_value.append(row)
        values.append(["Stat. " + str(spreadsheet.start_date), 'ROWS',
                       f'A{len(income_value) + 2 + 1}:{alf[daysUntilNextMonth[spreadsheet.start_date.month]]}{len(income_value) + len(cost_value) + 2 + 1}', cost_value])

        # self.spreadsheet.cleanValues(spreadsheet.spreadsheet_id,
        #                              f'{"Stat. " + str(spreadsheet.start_date)}!'
        #                              f'A2:{alf[daysUntilNextMonth[spreadsheet.start_date.month]]}100000')
        #
        # self.spreadsheet.setValues(spreadsheet.spreadsheet_id, values)

        return values
