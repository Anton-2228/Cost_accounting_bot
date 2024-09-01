from aiogram import F
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from ai_wrapper import AiWrapper
from check_wrapper import get_check_data, get_important_check_data
from commands.Command import Command
from commands.utils.AddCheck_utils import (add_types, create_first_input,
                                           create_output_for_categories,
                                           create_output_for_types,
                                           create_second_input,
                                           get_category_by_product_type,
                                           get_product_types,
                                           get_values_to_add_record,
                                           parse_categories_input,
                                           parse_types_input, send_first_stage_message_with_button,
                                           send_second_stage_message_with_button)
from commands.utils.AddRecord_utils import add_record
from commands.utils.Synchronize_utils import (sync_cat_from_db_to_table,
                                              sync_records_from_db_to_table)
from database import CashedRecordsOrm, CategoriesOrm, SourcesOrm
from datafiles import (FINISH_STAGE_ADD_CHECK_MESSAGE,
                       FIRST_STAGE_ADD_CHECK_MESSAGE,
                       SECOND_STAGE_ADD_CHECK_MESSAGE)
from init import States
from validation import validate_check_enter


class AddCheck(Command):
    def __init__(self, command_manager, postgres_wrapper):
        super().__init__(command_manager, postgres_wrapper)
        self.ai_wrapper = AiWrapper()
        self.temp_data = {}
        command_manager.router.callback_query.register(self.confirm_select_types, F.data == "confirm_select_types")
        command_manager.router.callback_query.register(self.confirm_select_categories, F.data == "confirm_select_categories")

    async def execute(
        self, message: Message, state: FSMContext, command: CommandObject
    ):
        user = self.postgres_wrapper.users_wrapper.get_user(message.chat.id)
        if user == None:
            await message.answer("Сначала создайте таблицу")
            return

        if message.text == "/cancel":
            await message.answer("Отмена успешна")
            await state.clear()
            return

        cur_state = await state.get_state()
        if cur_state == None:
            await self.zero_stage(message, state)
        elif cur_state == States.CONFIRM_TYPES_CHECK:
            await self.first_stage(message, state)
        elif cur_state == States.CONFIRM_CATEGORIES_CHECK:
            await self.second_stage(message, state)
        elif cur_state == States.FINISH_CHECK:
            await self.third_stage(message, state)

    async def zero_stage(self, message: Message, state: FSMContext):
        user_id = message.chat.id
        check_text = message.text
        self.temp_data[user_id] = {}

        all_check_data = await get_check_data(
            ai_wrapper=self.ai_wrapper, check_text=check_text
        )
        self.temp_data[user_id]["all_check_data"] = all_check_data

        check_data = get_important_check_data(all_check_data)
        self.temp_data[user_id]["check_data"] = check_data

        await self.preparing_first_stage(message, state)
        await self.set_type_finish_state(message, state)

    async def first_stage(self, message: Message, state: FSMContext):
        await self.process_delete_confirm_select_types_button(message, state)

        user_id = message.chat.id
        spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(
            user_id
        )
        categories: list[CategoriesOrm] = (
            self.postgres_wrapper.categories_wrapper.get_active_categories_by_spreadsheet(
                spreadsheet.id
            )
        )
        row = message.text
        check_data = self.temp_data[user_id]["check_data"]

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

        output = create_output_for_types(check_data)
        await message.answer(output)
        await send_first_stage_message_with_button(FIRST_STAGE_ADD_CHECK_MESSAGE, message, state)

    async def second_stage(self, message: Message, state: FSMContext):
        await self.process_delete_confirm_select_categories_button(message, state)

        user_id = message.chat.id
        spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(
            message.chat.id
        )
        row = message.text
        categories: list[CategoriesOrm] = (
            self.postgres_wrapper.categories_wrapper.get_active_categories_by_spreadsheet(
                spreadsheet.id
            )
        )
        check_data = self.temp_data[user_id]["check_data"]

        response = parse_categories_input(
            check_data=check_data, categories=categories, row=row
        )
        if response["status"] == "error":
            await message.answer(response["message"])
            return

        for id in response["value"]:
            check_data[id]["unconfirmed_category"] = response["value"][id]

        output = create_output_for_categories(check_data)
        await message.answer(output)
        await send_second_stage_message_with_button(SECOND_STAGE_ADD_CHECK_MESSAGE, message, state)

    async def third_stage(self, message: Message, state: FSMContext):
        user_id = message.chat.id
        spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(
            user_id
        )
        record_source = message.text.lower()
        categories: list[CategoriesOrm] = (
            self.postgres_wrapper.categories_wrapper.get_active_categories_by_spreadsheet(
                spreadsheet.id
            )
        )
        sources: list[SourcesOrm] = (
            self.postgres_wrapper.sources_wrapper.get_sources_by_spreadsheet(
                spreadsheet.id
            )
        )
        check_data = self.temp_data[user_id]["check_data"]
        check_json = self.temp_data[user_id]["all_check_data"]

        err_message = validate_check_enter(record_source, sources)
        if err_message != None:
            await message.answer(err_message)
            return

        for id in check_data:
            check_data[id]["source"] = record_source

        await add_types(check_data, self.postgres_wrapper)

        for id in check_data:
            record = check_data[id]
            if record["confirmed_type"] is not None:
                check_data[id]["type"] = check_data[id]["confirmed_type"]
            if record["new_type"] is not None:
                check_data[id]["type"] = check_data[id]["new_type"]
                check_data[id]["category"] = check_data[id]["unconfirmed_category"]
        records = await get_values_to_add_record(
            check_data=check_data,
            categories=categories,
            check_json=check_json,
            sources=sources,
        )
        cashed_records: list[CashedRecordsOrm] = (
            self.postgres_wrapper.cashed_records_wrapper.get_cashed_records(
                spreadsheet.id
            )
        )
        cashed_names = [x.product_name for x in cashed_records]
        for record in records:
            if record["name"] not in cashed_names:
                new_cashed_record: CashedRecordsOrm = self.postgres_wrapper.cashed_records_wrapper.add_cashed_record(
                    spreadsheet_id=spreadsheet.id,
                    name=record["name"],
                    type=record["type"],
                )
                cashed_names.append(new_cashed_record.product_name)
            await add_record(
                record,
                spreadsheet,
                self.commandManager,
                self.spreadsheetWrapper,
                self.postgres_wrapper,
            )

        values = []
        category_value = await sync_cat_from_db_to_table(
            spreadsheet, self.postgres_wrapper
        )
        # records_value = await sync_records_from_db_to_table(spreadsheet, self.postgres_wrapper)
        values.append(category_value)
        # values.append(records_value)
        self.spreadsheetWrapper.setValues(spreadsheet.spreadsheet_id, values)

        await message.answer("Траты успешно добавлены")
        await state.clear()

    async def preparing_first_stage(self, message: Message, state: FSMContext):
        user_id = message.chat.id
        spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(
            user_id
        )
        categories: list[CategoriesOrm] = (
            self.postgres_wrapper.categories_wrapper.get_active_categories_by_spreadsheet(
                spreadsheet.id
            )
        )
        records: list[CashedRecordsOrm] = (
            self.postgres_wrapper.cashed_records_wrapper.get_cashed_records(
                spreadsheet_id=spreadsheet.id
            )
        )
        check_data = self.temp_data[user_id]["check_data"]

        cashed_records = {}
        for record in records:
            cashed_records[record.product_name] = record.type

        input = create_first_input(
            check_data=check_data, categories=categories, cashed_records=cashed_records
        )
        if input["check"] != {}:
            answer = await self.ai_wrapper.first_invoke_check(input)

            for id in check_data:
                if id in answer:
                    if answer[id]["type"] is not None:
                        answer[id]["type"] = answer[id]["type"].lower()
                    if answer[id]["new_type"] is not None:
                        answer[id]["new_type"] = answer[id]["new_type"].lower()
                    check_data[id] = answer[id]
                else:
                    check_data[id]["type"] = cashed_records[check_data[id]["name"]]
                    check_data[id]["new_type"] = None

        for id in check_data:
            record = check_data[str(id)]
            record["confirmed_type"] = None
            if record["name"] in cashed_records:
                record["confirmed_type"] = cashed_records[record["name"]]
                record["type"] = None
                record["new_type"] = None

        output = create_output_for_types(check_data)
        await message.answer(output)

    async def preparing_second_stage(self, message: Message):
        user_id = message.chat.id
        spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(
            user_id
        )
        check_data = self.temp_data[user_id]["check_data"]
        categories: list[CategoriesOrm] = (
            self.postgres_wrapper.categories_wrapper.get_active_categories_by_spreadsheet(
                spreadsheet.id
            )
        )

        input = create_second_input(check_data, categories)
        answer = await self.ai_wrapper.second_invoke_check(input)
        for id in check_data:
            record = check_data[id]
            if id in answer:
                record["category"] = None
                record["unconfirmed_category"] = answer[id]["category"]
            else:
                if record["confirmed_type"] is None:
                    check_data[id]["category"] = get_category_by_product_type(
                        type=record["type"], categories=categories
                    )
                else:
                    check_data[id]["category"] = get_category_by_product_type(
                        type=record["confirmed_type"], categories=categories
                    )

        output = create_output_for_categories(check_data)
        await message.answer(output)

    async def set_type_finish_state(self, message: Message, state: FSMContext):
        check_data = self.temp_data[message.chat.id]["check_data"]
        for id in check_data:
            if check_data[id]["confirmed_type"] is None:
                await send_first_stage_message_with_button(FIRST_STAGE_ADD_CHECK_MESSAGE, message, state)
                await state.set_state(States.CONFIRM_TYPES_CHECK)
                return
        await state.set_state(States.CONFIRM_CATEGORIES_CHECK)
        await self.preparing_second_stage(message)
        await self.set_category_finish_state(message, state)

    async def set_category_finish_state(self, message: Message, state: FSMContext):
        check_data = self.temp_data[message.chat.id]["check_data"]
        for id in check_data:
            if check_data[id]["category"] is None:
                await send_second_stage_message_with_button(SECOND_STAGE_ADD_CHECK_MESSAGE, message, state)
                await state.set_state(States.CONFIRM_CATEGORIES_CHECK)
                return
        await message.answer(FINISH_STAGE_ADD_CHECK_MESSAGE)
        await state.set_state(States.FINISH_CHECK)

    async def confirm_select_types(self, callback: CallbackQuery, state: FSMContext):
        await callback.answer()
        await self.commandManager.bot.edit_message_reply_markup(
            chat_id=callback.from_user.id, message_id=callback.message.message_id, reply_markup=None
        )
        await state.update_data(confirm_select_types_messages=None)
        await self.preparing_second_stage(callback.message)
        await self.set_category_finish_state(callback.message, state)

    async def process_delete_confirm_select_types_button(self, message: Message, state: FSMContext) -> None:
        confirm_select_types_messages = (await state.get_data())["confirm_select_types_messages"]
        if confirm_select_types_messages:
            await self.commandManager.bot.edit_message_reply_markup(
                chat_id=message.chat.id, message_id=confirm_select_types_messages, reply_markup=None
            )
            await state.update_data(confirm_select_types_messages=None)

    async def confirm_select_categories(self, callback: CallbackQuery, state: FSMContext):
        await callback.answer()
        await self.commandManager.bot.edit_message_reply_markup(
            chat_id=callback.from_user.id, message_id=callback.message.message_id, reply_markup=None
        )
        await state.update_data(confirm_select_categories_messages=None)
        await callback.message.answer(FINISH_STAGE_ADD_CHECK_MESSAGE)
        await state.set_state(States.FINISH_CHECK)

    async def process_delete_confirm_select_categories_button(self, message: Message, state: FSMContext) -> None:
        confirm_select_categories_messages = (await state.get_data())["confirm_select_categories_messages"]
        if confirm_select_categories_messages:
            await self.commandManager.bot.edit_message_reply_markup(
                chat_id=message.chat.id, message_id=confirm_select_categories_messages, reply_markup=None
            )
            await state.update_data(confirm_select_categories_messages=None)
