from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from commands.Command import Command
from database.models import CategoriesOrm, SourcesOrm, CategoriesTypes
from database.queries.categories_queries import get_categories_by_spreadsheet
from database.queries.records_queries import create_record, get_records_by_current_month
from database.queries.sources_queries import get_sources_by_spreadsheet, set_current_balance, get_source, \
    update_current_balance
from database.queries.spreadsheets_queries import get_spreadsheet
from database.queries.users_queries import get_user
from init import States
from validation import validate_records_row


class AddRecord(Command):
    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        user = get_user(message.from_user.id)
        if user == None:
            await message.answer('Сначала создайте таблицу')
            return

        args = command.args.split()
        amount = float(args[0])
        cat = args[1].lower()
        sour = args[2].lower()
        notes = ' '.join(args[3:])

        add_resuld = await self.add_record(message.from_user.id, command.args)

        await message.answer(add_resuld['message'])


    async def add_record(self, id, row):
        response = {}
        args = row.split()

        amount = float(args[0])
        cat = args[1].lower()
        sour = args[2].lower()
        notes = ' '.join(args[3:])

        spreadsheet = get_spreadsheet(id)

        categories: list[CategoriesOrm] = get_categories_by_spreadsheet(spreadsheet.id)
        sources: list[SourcesOrm] = get_sources_by_spreadsheet(spreadsheet.id)

        res = validate_records_row(row, categories, sources)
        if res is not None:
            # await message.answer(res)
            response["message"] = res
            response["status"] = "error"
            return response

        for i in categories:
            if cat in i.associations:
                category = i

        for i in sources:
            if sour in i.associations:
                source = i

        if category.type == CategoriesTypes.INCOME:
            typeCat = 'доход'
            update_current_balance(source.id, amount)
        elif category.type == CategoriesTypes.COST:
            typeCat = 'расход'
            update_current_balance(source.id, -amount)

        source = get_source(source.id)

        if category.type == CategoriesTypes.INCOME:
            record = create_record(spreadsheet.id, amount, category.id, source.id, notes)
        elif category.type == CategoriesTypes.COST:
            record = create_record(spreadsheet.id, -amount, category.id, source.id, notes)

        values = []

        value = [[record.id, str(record.added_at), amount, category.title, notes, source.title]]
        records = get_records_by_current_month(spreadsheet.id, spreadsheet.start_date)
        count = len(records) + 1
        values.append([str(spreadsheet.start_date), "ROWS", f"A{count}:F{count}", value])

        source_value = await self.commandManager.getCommands()['sync'].sync_sour(spreadsheet)
        total_values = await self.commandManager.getCommands()['sync'].sync_total(spreadsheet)
        values.append(source_value)
        values += total_values

        self.spreadsheet.setValues(spreadsheet.spreadsheet_id, values)

        res = f"Сумма {args[0]}\n{typeCat} --> {category.title}\nиз {source.title}\nc пометкой: {notes}\nid:{record.id}"
        response["message"] = res
        response["status"] = "success"

        return response


        # await message.answer(f"Сумма {args[0]}\n{typeCat} --> {category.title}\nиз {source.title}\nc пометкой: {notes}\nid:{record.id}")

        # await self.commandManager.getCommands()['sync'].execute(message, state, command)
