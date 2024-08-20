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
                await self.preparing_second_stage(message, spreadsheet)
                await message.answer("")
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

    async def preparing_first_stage(self, message: Message, spreadsheet):
        input = await self.create_first_input(message, spreadsheet)

        answer = self.ai_wrapper.first_invoke_check(input)
        # print(answer)

        records = {}
        for x, i in enumerate(answer):
            record = i
            record[2] = record[2].lower()
            record[3] = record[3].lower()
            records[x + 1] = record

        self.temp_data[message.from_user.id]["records"] = records

        output = await self.create_output_for_types(spreadsheet.id, message.from_user.id)
        await message.answer(output)

    async def preparing_second_stage(self, message: Message, spreadsheet):
        records = self.temp_data[message.from_user.id]["records"]
        categories: list[CategoriesOrm] = get_categories_by_spreadsheet(spreadsheet.id)
        product_types = await self.get_product_types(categories)
        model_records = {}
        for id in records:
            record = records[id]
            if record[2] not in product_types:
                model_records[id] = record
            else:
                for category in categories:
                    if record[2] in category.product_types:
                        records[id].append(category.title)
        input = await self.create_second_input(categories, model_records)
        answer = self.ai_wrapper.second_invoke_check(input)
        for i in answer:
            records[i[0]].append(i[1])
        model_record_ids = [x[0] for x in answer]

        output = await self.create_output_for_categories(message.from_user.id, categories, model_record_ids)
        await message.answer(output)


    async def create_first_input(self, message: Message, spreadsheet):
        input = {}

        categories: list[CategoriesOrm] = get_categories_by_spreadsheet(spreadsheet.id)

        product_types = await self.get_product_types(categories)

        input["types"] = ', '.join(product_types)
        input["check"] = self.temp_data[message.from_user.id]["check"]

        return input

    async def get_product_types(self, categories):
        types = []
        for category in categories:
            if category.type == CategoriesTypes.COST:
                types += category.product_types
        return types

    async def create_second_input(self, categories, model_records):
        input = {}

        input["categories"] = await self.get_category_titles(categories)
        input["products"] = await self.product_input(model_records)

        return input

    async def get_category_titles(self, categories):
        input = []
        for category in categories:
            input.append(category.title)
        return input

    async def product_input(self, model_records):
        input = []
        for id in model_records:
            record = model_records[id]
            input.append({"id": id,
                          "title": record[0],
                          "type": record[2]})
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

    async def create_output_for_categories(self, user_id, categories, model_record_ids):
        category_titles = await self.get_category_titles(categories)
        records = self.temp_data[user_id]["records"]
        output = ""
        for id in records:
            record = records[id]
            if id not in model_record_ids:
                output += (f'{record[0]}\n'
                           f'   <b>{record[4]}</b>\n')
        output += '\n'
        for id in model_record_ids:
            record = records[id]
            output += f'{id}) {record[0]}\n'
            if record[4] in category_titles:
                output += f'    <b>{record[4]}</b>\n'
            else:
                output += f'    <b>{record[4].upper()}</b>\n'
        return output