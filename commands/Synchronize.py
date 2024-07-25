from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from database.queries.categories_queries import synchronizeCategories
from database.queries.sources_queries import synchronizeSources
from database.queries.spreadsheets_queries import get_spreadsheet


class Synchronize(Command):
    async def execute(self, message: Message, state: FSMContext):
        values = []

        resultSyncCat = synchronizeCategories(message, "Categories!A2:G100000", self.spreadsheet)
        print(resultSyncCat)
        if resultSyncCat is not None:
            if resultSyncCat['result'] == 'error':
                await message.answer(resultSyncCat['message'])
                return
            categories = resultSyncCat['categories']
            values.append(["Categories", "ROWS", f'A2:G{len(categories) + 2}', categories])

        resultSyncSour = synchronizeSources(message, "Bills!A2:F100000", self.spreadsheet)
        print(resultSyncSour)
        if resultSyncSour is not None:
            if resultSyncSour['result'] == 'error':
                await message.answer(resultSyncSour['message'])
                return
            sources = resultSyncSour['sources']
            values.append(["Bills", "ROWS", f'A2:F{len(sources) + 2}', sources])

        spreadsheetid = get_spreadsheet(message.from_user.id).spreadsheet_id

        self.spreadsheet.cleanValues(spreadsheetid, 'Categories!A2:G100000')
        self.spreadsheet.cleanValues(spreadsheetid, 'Bills!A2:F100000')
        self.spreadsheet.setValues(spreadsheetid, values)

