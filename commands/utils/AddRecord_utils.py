from command_manager import CommandManager
from commands.utils.Synchronize_utils import sync_sour_from_table_to_db, sync_total_from_db_to_table
from commands.utils.utils import category_by_association, source_by_association
from database import CategoriesOrm, SourcesOrm, CategoriesTypes, SpreadSheetsOrm
from database import PostgresWrapper
from datafiles import ADD_RECORD_MESSAGE
from spreadsheet_wrapper import SpreadsheetWrapper


def parse_records_row(row, categories:list[CategoriesOrm], sources:list[SourcesOrm] = None) -> dict:
    response = {}
    response["status"] = 'error'
    value = {}

    args = row.split()
    if len(args) < 3:
        response["message"] = "Какой-то странный ввод"
        return response

    row_amount = args[0]
    row_category = args[1].lower()
    row_source = args[2].lower()
    row_notes = ' '.join(args[3:])

    try:
        amount = float(row_amount)
        value["amount"] = amount
    except:
        response["message"] = "Сумма должна быть числом"
        return response

    category = category_by_association(row_category, categories)
    if category is None:
        response["message"] = "Такой категории нет, либо она выключена"
        return response
    value["category"] = category

    source = source_by_association(row_source, sources)
    if source is None:
        response["message"] = "Такого источника нет, либо он выключен"
        return response
    value["source"] = source

    value["notes"] = row_notes
    value["name"] = None
    value["check_json"] = None
    value["type"] = None

    response["status"] = 'success'
    response["value"] = value

    return response

async def add_record(data: dict, spreadsheet: SpreadSheetsOrm, commandManager: CommandManager, spreadsheetWrapper: SpreadsheetWrapper, postgres_wrapper: PostgresWrapper) -> int:
    amount: float = data['amount']
    category: CategoriesOrm = data['category']
    source: SourcesOrm = data['source']
    notes: str = data['notes']
    name: str = data['name']
    check_json: str = data['check_json']
    type: str = data["type"]

    if category.type == CategoriesTypes.INCOME:
        postgres_wrapper.sources_wrapper.update_current_balance(source.id, amount)
        record = postgres_wrapper.records_wrapper.create_record(spreadsheet_id=spreadsheet.id,
                                                                amount=amount,
                                                                category_id=category.id,
                                                                source_id=source.id,
                                                                notes=notes,
                                                                name=name,
                                                                check_json=check_json,
                                                                type=type)
        value = [[record.id, str(record.added_at), amount, record.product_name, category.title, record.type, notes,
                  source.title, record.check_json]]


    elif category.type == CategoriesTypes.COST:
        postgres_wrapper.sources_wrapper.update_current_balance(source.id, -amount)
        record = postgres_wrapper.records_wrapper.create_record(spreadsheet_id=spreadsheet.id,
                                                                amount=-amount,
                                                                category_id=category.id,
                                                                source_id=source.id,
                                                                notes=notes,
                                                                name=name,
                                                                check_json=check_json,
                                                                type=type)
        value = [[record.id, str(record.added_at), -amount, record.product_name, category.title, record.type, notes,
                  source.title, record.check_json]]

    values = []

    # value = [[record.id, str(record.added_at), amount, record.product_name, record.type, category.title, notes, source.title, record.check_json]]
    records = postgres_wrapper.records_wrapper.get_records_by_current_month(spreadsheet.id, spreadsheet.start_date)
    count = len(records) + 1
    # values.append([str(spreadsheet.start_date), "ROWS", f"A{count}:F{count}", value])
    values.append([str(spreadsheet.start_date), "ROWS", f"A{count}:I{count}", value])

    source_value = await sync_sour_from_table_to_db(spreadsheet, spreadsheetWrapper, postgres_wrapper)
    total_values = await sync_total_from_db_to_table(spreadsheet, postgres_wrapper)
    values.append(source_value)
    values += total_values

    spreadsheetWrapper.setValues(spreadsheet.spreadsheet_id, values)

    return record.id

def create_add_message(data: dict) -> str:
    amount = data['amount']
    category: CategoriesOrm = data['category']
    source: SourcesOrm = data['source']
    notes = data['notes']
    id = data['id']

    if category.type == CategoriesTypes.INCOME:
        typeCat = 'доход'
    elif category.type == CategoriesTypes.COST:
        typeCat = 'расход'

    return ADD_RECORD_MESSAGE.format(amount=amount,
                                     typeCat=typeCat,
                                     category=category.title,
                                     source=source.title,
                                     notes=notes,
                                     id=id)
