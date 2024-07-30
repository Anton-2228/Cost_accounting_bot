import time

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from database.models import RecordsOrm
from database.queries.categories_queries import synchronizeCategories, get_category
from database.queries.records_queries import get_records_by_current_month
from database.queries.sources_queries import synchronizeSources, get_source
from database.queries.spreadsheets_queries import get_spreadsheet


class Synchronize(Command):
    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        category_value = await self.sync_cat(message)
        source_value = await self.sync_sour(message)

        values = []
        values.append(category_value)
        values.append(source_value)

        spreadsheetid = get_spreadsheet(message.from_user.id).spreadsheet_id

        self.spreadsheet.cleanValues(spreadsheetid, 'Categories!A2:G100000')
        self.spreadsheet.cleanValues(spreadsheetid, 'Bills!A2:F100000')
        self.spreadsheet.setValues(spreadsheetid, values)

        await message.answer("Синхронизация успешна")

    async def sync_cat(self, message):
        resultSyncCat = synchronizeCategories(message, "Categories!A2:G100000", self.spreadsheet)
        if resultSyncCat is not None:
            if resultSyncCat['result'] == 'error':
                await message.answer(resultSyncCat['message'])
                return
            categories = resultSyncCat['categories']
            return ["Categories", "ROWS", f'A2:G{len(categories) + 2}', categories]

    async def sync_sour(self, message):
        resultSyncSour = synchronizeSources(message, "Bills!A2:F100000", self.spreadsheet)
        if resultSyncSour is not None:
            if resultSyncSour['result'] == 'error':
                await message.answer(resultSyncSour['message'])
                return
            sources = resultSyncSour['sources']
            return ["Bills", "ROWS", f'A2:F{len(sources) + 2}', sources]

    async def sync_records(self, spreadsheet):
        records: list[RecordsOrm] = get_records_by_current_month(spreadsheet.id, spreadsheet.start_date)
        value = []
        for i in records:
            category = get_category(i.category)
            source = get_source(i.source)
            value.append([i.id, str(i.added_at), i.amount, category.title, i.notes, source.title])

        return [str(spreadsheet.start_date), 'ROWS', f'A2:F{len(value) + 1}', value]