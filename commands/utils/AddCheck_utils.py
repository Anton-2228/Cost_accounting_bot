from database.models import CategoriesOrm, CategoriesTypes


def create_first_input(check_data: dict, categories: list[CategoriesOrm]) -> dict:
    input = {}

    input["types"] = get_product_types(categories)
    input["check"] = check_data

    return input

def create_second_input(check_data: dict, categories: list[CategoriesOrm]) -> dict:
    input = {}

    model_records = {}
    for id in check_data:
        record = check_data[str(id)]
        if record['type'] is None:
            model_records[str(id)] = {}
            model_records[str(id)]['name'] = record['name']
            model_records[str(id)]['type'] = record['new_type']
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
            ids = [int(i.strip()) for i in ids.split(',')]
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

def parse_categories_input(check_data: dict, categories: list[CategoriesOrm], row: str) -> dict:
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
            ids = [int(i.strip()) for i in ids.split(',')]
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

def get_category_title_by_association(association: str, categories: list[CategoriesOrm]):
    for i in categories:
        if association in i.associations:
            return i.title

def create_output_for_types(check_data: dict) -> str:
    output = ""
    for id in check_data:
        product = check_data[str(id)]
        output += f'{id}) {product['name']}\n'
        if product['type'] is not None:
            output += f'    <b>{product['type']}</b>\n'
        else:
            output += f'    <b>{product['new_type'].upper()}</b>\n'
    return output

def create_output_for_categories(check_data: dict):
    output = ""
    for id in check_data:
        record = check_data[str(id)]
        if record["category"] is not None:
            output += (f'{record["name"]}\n'
                       f'   <b>{record['category']}</b>\n')
    output += '\n'
    for id in check_data:
        record = check_data[str(id)]
        if record["category"] is None:
            output += f'{id}) {record['name']}\n'
            if record['category'] is not None:
                output += f'   <b>{record['category']}</b>\n'
            else:
                output += f'    <b>{record['unconfirmed_category']}</b>\n'
    return output

async def add_types():
    pass

async def add_record():
    pass
