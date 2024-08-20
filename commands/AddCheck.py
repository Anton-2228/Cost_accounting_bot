import json

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from langchain_core.messages import AIMessage

from ai_wrapper import AiWrapper
from commands.Command import Command
from database.models import CategoriesOrm, SourcesOrm, CategoriesTypes
from database.queries.categories_queries import get_categories_by_spreadsheet
from database.queries.sources_queries import get_sources_by_spreadsheet
from database.queries.spreadsheets_queries import get_spreadsheet
from init import States
from validation import validate_check_enter


class AddCheck(Command):
    def __init__(self, command_manager):
        super().__init__(command_manager)
        self.ai_wrapper = AiWrapper()
        self.temp_data = {}

    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        cur_state = await state.get_state()
        spreadsheet = get_spreadsheet(message.from_user.id)
        if cur_state == None:
            self.temp_data[message.from_user.id] = {}
            self.temp_data[message.from_user.id]["check"] = message.text
            await self.preparing_first_stage(message, spreadsheet)
            await message.answer("Правильно ли модель распределила типы по товарам?\n\nЕсли нет, то напишите через запятую номера товаров, тире, тип, который хотите дать этим товарам. С новой строки можете писать сколько угодно таких правок.\n\nЕсли да, то напишите 'Да'")
            await state.set_state(States.CONFIRM_TYPES_CHECK)

        elif cur_state == States.CONFIRM_TYPES_CHECK:
            if message.text.lower() == "да":
                records = self.temp_data[message.from_user.id]["records"]
                for id in records:
                    if records[id][2] == "":
                        records[id][2] = records[id][3]
                await state.set_state(States.CONFIRM_CATEGORIES_CHECK)
            elif message.text == "/cancel":
                await message.answer("Отмена успешна")
                await state.clear()
            else:
                row = message.text
                records = self.temp_data[message.from_user.id]["records"]
                for line in row.split("\n"):
                    ids, type = line.split("-")
                    ids = ids.strip()
                    type = type.strip().lower()
                    ids = [int(i.strip()) for i in ids.split(',')]
                    for id in ids:
                        if id in records:
                            records[id][2] = type
                        else:
                            await message.answer("Указан несуществующий id")

                output = await self.create_output_for_types(spreadsheet.id, message.from_user.id)
                await message.answer(output)
                await message.answer("Правильно ли модель распределила типы по товарам?\n\nЕсли нет, то напишите через запятую номера товаров, тире, тип, который хотите дать этим товарам. С новой строки можете писать сколько угодно таких правок.\n\nЕсли да, то напишите 'Да'")

        elif cur_state == States.CONFIRM_CATEGORIES_CHECK:
            if message.text.lower() == "да":
                await state.set_state(States.FINISH_CHECK)
            elif message.text == "/cancel":
                await message.answer("Отмена успешна")
                await state.clear()
            else:
                pass
                # record_source = message.text.split()[0].lower()
                # notes = ' '.join(message.text.split()[1:])
                # sources: list[SourcesOrm] = get_sources_by_spreadsheet(spreadsheet.id)
                # err_message = validate_check_enter(record_source, sources)
                # if err_message != None:
                #     await message.answer(err_message)
                #     return
                # # for i in sources:
                # #     if record_source in i.associations:
                # #         source = i
                #
                # print(self.temp_data[message.from_user.id]["records"])
                # for record_category in self.temp_data[message.from_user.id]["records"]:
                #     for row_record in self.temp_data[message.from_user.id]["records"][record_category]:
                #         # row_record = self.temp_data[message.from_user.id]["records"][record_category]
                #         print(row_record)
                #         print(record_source)
                #         record = f"{row_record[0]} {record_category} {record_source} {row_record[1]}"
                #         if notes != "":
                #             record += f"; {notes}"
                #         await self.commandManager.getCommands()['addRecord'].add_record(message.from_user.id, record)
                #
                # await message.answer("Траты успешно добавлены")
                # await state.clear()

    async def create_first_input(self, message: Message, spreadsheet):
        input = {}

        types_input = await self.types_input(spreadsheet)
        input["types"] = types_input
        input["check"] = self.temp_data[message.from_user.id]["check"]

        return input

    async def types_input(self, spreadsheet):
        categories: list[CategoriesOrm] = get_categories_by_spreadsheet(spreadsheet.id)
        types = []
        for category in categories:
            if category.type == CategoriesTypes.COST:
                types += category.product_types
        return ', '.join(types)

    async def create_second_input(self, message: Message, spreadsheet):
        input = {}

        category_input = await self.category_input(spreadsheet)
        input["categories"] = category_input
        input["check"] = self.temp_data[message.from_user.id]["check"]

        return input

    async def category_input(self, spreadsheet):
        categories: list[CategoriesOrm] = get_categories_by_spreadsheet(spreadsheet.id)

        input = ""
        for category in categories:
            input += (f"Название: {category.title}\n"
                      f"Ассоциации: {category.associations}\n"
                      f"Описание: {category.description}\n\n")

        return input

    async def create_output_for_types(self, spreadsheet_id, user_id):
        categories = get_categories_by_spreadsheet(spreadsheet_id)
        types = []
        for category in categories:
            if category.type == CategoriesTypes.COST:
                types += category.product_types

        output = ""
        for id in self.temp_data[user_id]["records"]:
            product = self.temp_data[user_id]["records"][id]
            output += f'{id}) {product[0]}\n'
            if product[2] != "":
                if product[2] in types:
                    output += f'    <b>{product[2]}</b>\n'
                else:
                    output += f'    <b>{product[2].upper()}</b>\n'
            else:
                output += f'    <b>{product[3].upper()}</b>\n'
        return output