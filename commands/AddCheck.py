from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ai_wrapper.ai_wrapper import AiWrapper
from check_wrapper.utils import get_check_data, get_important_check_data
from commands.Command import Command
from commands.utils.AddCheck_utils import create_first_input, create_output_for_types, parse_types_input, \
    get_product_types, create_second_input, get_category_by_product_type, create_output_for_categories, \
    parse_categories_input, add_types, get_values_to_add_record
from commands.utils.AddRecord_utils import add_record
from commands.utils.Synchronize_utils import sync_cat_from_table_to_db, sync_records_from_db_to_table, \
    sync_cat_from_db_to_table
from database.models import CategoriesOrm, SourcesOrm
from database.queries.categories_queries import get_active_categories_by_spreadsheet
from database.queries.sources_queries import get_sources_by_spreadsheet
from database.queries.spreadsheets_queries import get_spreadsheet
from database.queries.users_queries import get_user
from datafiles import FIRST_STAGE_ADD_CHECK_MESSAGE, SECOND_STAGE_ADD_CHECK_MESSAGE, FINISH_STAGE_ADD_CHECK_MESSAGE
from init import States
from validation import validate_check_enter


class AddCheck(Command):
    def __init__(self, command_manager):
        super().__init__(command_manager)
        self.ai_wrapper = AiWrapper()
        self.temp_data = {}

    async def execute(self, message: Message, state: FSMContext, command: CommandObject):
        user = get_user(message.from_user.id)
        if user == None:
            await message.answer('Сначала создайте таблицу')
            return

        if message.text == "/cancel":
            await message.answer("Отмена успешна")
            await state.clear()
            return

        cur_state = await state.get_state()
        if cur_state == None:
            await self.zero_stage(message, state)
        elif cur_state == States.CONFIRM_TYPES_CHECK:
            if message.text.lower() == "да":
                await self.preparing_second_stage(message)
                await self.set_category_finish_state(message, state)
            else:
                await self.first_stage(message)
        elif cur_state == States.CONFIRM_CATEGORIES_CHECK:
                if message.text.lower() == "да":
                    await message.answer(FINISH_STAGE_ADD_CHECK_MESSAGE)
                    await state.set_state(States.FINISH_CHECK)
                else:
                    await self.second_stage(message)
        elif cur_state == States.FINISH_CHECK:
            await self.third_stage(message, state)


    async def zero_stage(self, message: Message, state: FSMContext):
        user_id = message.from_user.id
        check_text = message.text
        self.temp_data[user_id] = {}

        all_check_data = await get_check_data(ai_wrapper=self.ai_wrapper, check_text=check_text)
        self.temp_data[user_id]['all_check_data'] = all_check_data

        check_data = get_important_check_data(all_check_data)
        self.temp_data[user_id]['check_data'] = check_data

        await self.preparing_first_stage(message)
        await message.answer(FIRST_STAGE_ADD_CHECK_MESSAGE)
        await state.set_state(States.CONFIRM_TYPES_CHECK)

    async def first_stage(self, message: Message):
        user_id = message.from_user.id
        spreadsheet = get_spreadsheet(user_id)
        categories: list[CategoriesOrm] = get_active_categories_by_spreadsheet(spreadsheet.id)
        row = message.text
        check_data = self.temp_data[user_id]['check_data']

        response = parse_types_input(check_data, row)
        if response["status"] == "error":
            await message.answer(response["message"])
            return

        types = get_product_types(categories=categories)
        for id in response["value"]:
            if response["value"][id] in types:
                check_data[str(id)]["type"] = response["value"][str(id)]
                check_data[str(id)]["new_type"] = None
            else:
                check_data[str(id)]["type"] = None
                check_data[str(id)]["new_type"] = response["value"][str(id)]

        print(check_data)

        output = create_output_for_types(check_data)
        await message.answer(output)
        await message.answer(FIRST_STAGE_ADD_CHECK_MESSAGE)

    async def second_stage(self, message: Message):
        user_id = message.from_user.id
        spreadsheet = get_spreadsheet(message.from_user.id)
        row = message.text
        categories: list[CategoriesOrm] = get_active_categories_by_spreadsheet(spreadsheet.id)
        check_data = self.temp_data[user_id]['check_data']

        response = parse_categories_input(check_data=check_data, categories=categories, row=row)
        if response["status"] == "error":
            await message.answer(response["message"])
            return

        for id in response["value"]:
            check_data[id]['unconfirmed_category'] = response["value"][id]

        print(check_data)

        output = create_output_for_categories(check_data)
        await message.answer(output)
        await message.answer(SECOND_STAGE_ADD_CHECK_MESSAGE)

    async def third_stage(self, message: Message, state: FSMContext):
        user_id = message.from_user.id
        spreadsheet = get_spreadsheet(user_id)
        record_source = message.text.lower()
        categories: list[CategoriesOrm] = get_active_categories_by_spreadsheet(spreadsheet.id)
        sources: list[SourcesOrm] = get_sources_by_spreadsheet(spreadsheet.id)
        check_data = self.temp_data[user_id]["check_data"]
        check_json = self.temp_data[user_id]['all_check_data']

        err_message = validate_check_enter(record_source, sources)
        if err_message != None:
            await message.answer(err_message)
            return

        for id in check_data:
            check_data[id]['source'] = record_source

        await add_types(check_data)

        print(check_data)

        for id in check_data:
            record = check_data[id]
            if record["new_type"] is not None:
                check_data[id]['type'] = check_data[id]['new_type']
                check_data[id]['category'] = check_data[id]['unconfirmed_category']
        records = await get_values_to_add_record(check_data=check_data,
                                                 categories=categories,
                                                 check_json=check_json,
                                                 sources=sources)
        for record in records:
            print(record)
            await add_record(record, spreadsheet, self.commandManager, self.spreadsheetWrapper)

        values = []
        category_value = await sync_cat_from_db_to_table(spreadsheet)
        records_value = await sync_records_from_db_to_table(spreadsheet)
        values.append(category_value)
        values.append(records_value)
        self.spreadsheetWrapper.setValues(spreadsheet.spreadsheet_id, values)

        await message.answer("Траты успешно добавлены")
        await state.clear()

    async def preparing_first_stage(self, message: Message):
        user_id = message.from_user.id
        spreadsheet = get_spreadsheet(user_id)
        categories: list[CategoriesOrm] = get_active_categories_by_spreadsheet(spreadsheet.id)
        check_data = self.temp_data[user_id]['check_data']

        input = create_first_input(check_data=check_data, categories=categories)
        answer = await self.ai_wrapper.first_invoke_check(input)
        print(answer)
        for id in answer:
            if answer[id]["type"] is not None:
                answer[id]["type"] = answer[id]["type"].lower()
            if answer[id]["new_type"] is not None:
                answer[id]["new_type"] = answer[id]["new_type"].lower()
        self.temp_data[user_id]['check_data'] = answer
        check_data = self.temp_data[user_id]['check_data']

        output = create_output_for_types(check_data)
        await message.answer(output)

    async def preparing_second_stage(self, message: Message):
        user_id = message.from_user.id
        spreadsheet = get_spreadsheet(user_id)
        check_data = self.temp_data[user_id]["check_data"]
        categories: list[CategoriesOrm] = get_active_categories_by_spreadsheet(spreadsheet.id)

        input = create_second_input(check_data, categories)
        answer = await self.ai_wrapper.second_invoke_check(input)
        print(answer)
        for id in check_data:
            if id in answer:
                check_data[id]['category'] = None
                check_data[id]['unconfirmed_category'] = answer[id]['category']
            else:
                check_data[id]['category'] = get_category_by_product_type(type=check_data[id]['type'],
                                                                          categories=categories)

        output = create_output_for_categories(check_data)
        await message.answer(output)

    async def set_category_finish_state(self, message: Message, state: FSMContext):
        check_data = self.temp_data[message.from_user.id]['check_data']
        for id in check_data:
            if check_data[id]['category'] is None:
                await message.answer(SECOND_STAGE_ADD_CHECK_MESSAGE)
                await state.set_state(States.CONFIRM_CATEGORIES_CHECK)
                return
        await message.answer(FINISH_STAGE_ADD_CHECK_MESSAGE)
        await state.set_state(States.FINISH_CHECK)
