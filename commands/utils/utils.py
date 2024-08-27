from aiogram.types import Message

from database.models import CategoriesOrm, SourcesOrm
from database import PostgresWrapper


def category_by_association(row_category: str, categories:list[CategoriesOrm]) -> CategoriesOrm:
    row_category = row_category.lower()
    category = None
    for cur_category in categories:
        if row_category in cur_category.associations:
            category = cur_category
    return category

def source_by_association(row_source: str, sources:list[SourcesOrm]) -> SourcesOrm:
    row_source.lower()
    source = None
    for cur_source in sources:
        if row_source in cur_source.associations:
            source = cur_source
    return source

async def check_user_exist(message: Message, postgres_wrapper: PostgresWrapper):
    user = postgres_wrapper.users_wrapper.get_user(message.from_user.id)
    if user == None:
        await message.answer('Сначала создайте таблицу')
        return "error"
    return "success"

async def check_spreadsheet_exist(message: Message, postgres_wrapper: PostgresWrapper):
    spreadsheet = postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(message.from_user.id)
    if spreadsheet != None:
        await message.answer('Таблица уже создана')
        return "error"
    return "success"
