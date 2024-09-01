import json

from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from commands.utils.utils import category_by_association, source_by_association
from database import (CategoriesOrm, CategoriesTypes, PostgresWrapper,
                      RecordsOrm, SourcesOrm)


def create_first_input(
    check_data: dict, categories: list[CategoriesOrm], cashed_records: dict
) -> dict:
    input = {}

    model_records = {}
    for id in check_data:
        record = check_data[str(id)]
        if record["name"] not in cashed_records:
            model_records[id] = record

    input["types"] = get_product_types(categories)
    input["check"] = model_records

    return input


def create_second_input(check_data: dict, categories: list[CategoriesOrm]) -> dict:
    input = {}

    model_records = {}
    for id in check_data:
        record = check_data[str(id)]
        if record["type"] is None and record["confirmed_type"] is None:
            model_records[str(id)] = {}
            model_records[str(id)]["name"] = record["name"]
            model_records[str(id)]["type"] = record["new_type"]
    input["check"] = model_records
    input["categories"] = get_category_titles(categories)

    return input


def get_product_types(categories: list[CategoriesOrm]) -> list[str]:
    types = []
    for category in categories:
        if category.type == CategoriesTypes.COST:
            types += category.product_types
    return types


def get_category_titles(categories: list[CategoriesOrm]) -> list[str]:
    input = []
    for category in categories:
        input.append(category.title)
    return input


def get_category_by_product_type(type: str, categories: list[CategoriesOrm]) -> str:
    for category in categories:
        if type in category.product_types:
            return category.title


def parse_types_input(check_data: dict, row: str) -> dict:
    response = {"status": "error"}
    value = {}
    try:
        for line in row.split("\n"):
            ids, category_row = line.split("-")
            ids = ids.strip()
            category_row = category_row.strip().lower()
            ids = [int(i.strip()) for i in ids.split(",")]
            for id in ids:
                if str(id) in check_data:
                    value[str(id)] = category_row
                else:
                    response["message"] = "Указан несуществующий id"
                    return response
    except:
        response["message"] = "Странный ввод"
        return response
    response["status"] = "success"
    response["value"] = value
    return response


def parse_categories_input(
    check_data: dict, categories: list[CategoriesOrm], row: str
) -> dict:
    response = {"status": "error"}
    value = {}
    try:
        for line in row.split("\n"):
            ids, category_row = line.split("-")
            ids = ids.strip()
            category_row = category_row.strip().lower()
            category_title = get_category_title_by_association(category_row, categories)
            if category_title is None:
                response["message"] = "Указана несуществующая категория"
                return response
            ids = [int(i.strip()) for i in ids.split(",")]
            for id in ids:
                if str(id) in check_data:
                    value[str(id)] = category_title
                else:
                    response["message"] = "Указан несуществующий id"
                    return response
    except:
        response["message"] = "Странный ввод"
        return response
    response["status"] = "success"
    response["value"] = value
    return response


def get_category_title_by_association(
    association: str, categories: list[CategoriesOrm]
):
    for i in categories:
        if association in i.associations:
            return i.title


def create_output_for_types(check_data: dict) -> str:
    output = ""
    for id in check_data:
        product = check_data[str(id)]
        if product["confirmed_type"] is not None:
            output += f"{product['name']}\n" f"    <b>{product['confirmed_type']}</b>\n"
    output += "\n"
    for id in check_data:
        product = check_data[str(id)]
        if product["confirmed_type"] is None:
            output += f"{id}) {product['name']}\n"
            if product["type"] is not None:
                output += f"    <b>{product['type']}</b>\n"
            else:
                output += f"    <b>{product['new_type'].upper()}</b>\n"
    return output


def create_output_for_categories(check_data: dict):
    output = ""
    for id in check_data:
        record = check_data[str(id)]
        if record["category"] is not None:
            output += f"{record['name']}\n" f"   <b>{record['category']}</b>\n"
    output += "\n"
    for id in check_data:
        record = check_data[str(id)]
        if record["category"] is None:
            output += f"{id}) {record['name']}\n"
            if record["category"] is not None:
                output += f"   <b>{record['category']}</b>\n"
            else:
                output += f"    <b>{record['unconfirmed_category']}</b>\n"
    return output


async def add_types(check_data: dict, postgres_wrapper: PostgresWrapper):
    for id in check_data:
        record = check_data[id]
        if (
            record["new_type"] is not None
            and record["unconfirmed_category"] != "НеопределенныеТраты"
        ):
            postgres_wrapper.categories_wrapper.add_product_type_by_category_title(
                record["unconfirmed_category"], record["new_type"]
            )


async def get_values_to_add_record(
    check_data: dict,
    check_json: dict,
    categories: list[CategoriesOrm],
    sources: list[SourcesOrm],
):
    values = []
    for id in check_data:
        record = check_data[id]
        value = {}
        value["amount"] = float(record["sum"])
        value["category"] = category_by_association(record["category"], categories)
        value["source"] = source_by_association(record["source"], sources)
        # value["notes"] = record["type"]
        value["notes"] = ""
        value["name"] = record["name"]
        value["check_json"] = json.dumps(check_json)
        value["type"] = record["type"]
        values.append(value)
    return values

async def send_first_stage_message_with_button(text_message: str, message: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="ок", callback_data="confirm_select_types"))
    sent_message = await message.answer(text_message, reply_markup=builder.as_markup())
    await state.update_data(confirm_select_types_messages=sent_message.message_id)

async def send_second_stage_message_with_button(text_message: str, message: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="ок", callback_data="confirm_select_categories"))
    sent_message = await message.answer(text_message, reply_markup=builder.as_markup())
    await state.update_data(confirm_select_categories_messages=sent_message.message_id)
