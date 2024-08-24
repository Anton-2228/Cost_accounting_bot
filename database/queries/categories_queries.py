import copy

from sqlalchemy import select

from database.database import session_factory
from database.models import StatusTypes, CategoriesOrm, CategoriesTypes
from database.queries.spreadsheets_queries import get_spreadsheet
from validation import validate_category_row

def get_category(id):
    with session_factory() as session:
        category: CategoriesOrm = session.get(CategoriesOrm, id)
        return category

def remove_category(id: int):
    with session_factory() as session:
        category: CategoriesOrm = session.get(CategoriesOrm, id)
        session.delete(category)
        session.commit()

def set_status(id: int, status: StatusTypes):
    with session_factory() as session:
        category: CategoriesOrm = session.get(CategoriesOrm, id)
        category.status = status
        session.commit()

def get_categories_by_spreadsheet(spreadsheet_id):
    with session_factory() as session:
        categories: list[CategoriesOrm] = session.scalars(select(CategoriesOrm)
                                                   .where(CategoriesOrm.spreadsheet_id == spreadsheet_id,
                                                          CategoriesOrm.status == StatusTypes.ACTIVE)).all()
        return categories

def add_product_type_by_category_title(category_title: str, type: str):
    with session_factory() as session:
        category: CategoriesOrm = session.scalar(select(CategoriesOrm).where(CategoriesOrm.title == category_title))
        category.product_types.append(type)
        session.commit()

def synchronizeCategories(spreadsheet, scope, spreadsheetWrapper):
    with session_factory() as session:
        # spreadsheet = get_spreadsheet(message.from_user.id)
        spreadsheets_categories = spreadsheetWrapper.getValues(spreadsheet.spreadsheet_id, scope)
        tmp_sql_categories = session.scalars(select(CategoriesOrm)).all()
        sql_categories = {}
        for i in tmp_sql_categories:
            sql_categories[i.id] = i

        if "values" in spreadsheets_categories:
            for i in range(len(copy.deepcopy(spreadsheets_categories["values"]))):
                row = spreadsheets_categories["values"][i]
                if len(row) != 0:
                    spreadsheets_categories["values"][i].extend([''] * (7 - len(row)))
            result = {'result': 'error'}
            message = validate_category_row(spreadsheets_categories)
            if message is not None:
                result['message'] = message
                return result
            result['result'] = 'success'

            add_categories = []
            categories = []
            for z, row in enumerate(spreadsheets_categories["values"]):
                if len(row) == 0:
                    continue
                if row[1] == '' and row[2] == '' and row[3] == '' and row[4] == '' and row[5] == '' and row[6] == '':
                    id = row[0]
                    set_status(id, StatusTypes.DELETED)
                    continue
                if row[0] != '':
                    category = sql_categories[int(row[0])]
                    if row[1] == '1':
                        category.status = StatusTypes.ACTIVE
                    elif row[1] == '0':
                        category.status = StatusTypes.INACTIVE
                    if row[2] == '1':
                        category.type = CategoriesTypes.INCOME
                    elif row[3] == '1':
                        category.type = CategoriesTypes.COST
                    category.title = row[4]
                    category.associations = [x.lower() for x in row[5].split()]
                    category.associations.append(row[4].lower())
                    category.associations = list(set(category.associations))
                    category.product_types = list(set([x.lower() for x in row[6].split(', ')]))
                    categories.append([row[0], row[1], row[2], row[3], row[4], ' '.join(category.associations), ', '.join(category.product_types)])
                else:
                    if row[1] == '1':
                        status = StatusTypes.ACTIVE
                    elif row[1] == '0':
                        status = StatusTypes.INACTIVE
                    if row[2] == '1':
                        type = CategoriesTypes.INCOME
                    elif row[3] == '1':
                        type = CategoriesTypes.COST
                    title = row[4]
                    associations = [x.lower() for x in row[5].split()]
                    associations.append(row[4].lower())
                    associations = list(set(associations))
                    product_types = list(set([x.lower() for x in row[6].split(', ')]))
                    category = CategoriesOrm(spreadsheet_id=spreadsheet.id,
                                             status=status,
                                             type=type,
                                             title=title,
                                             associations=associations,
                                             product_types=product_types)
                    session.add(category)
                    session.flush()
                    add_categories.append(category)
                    categories.append([category.id, row[1], row[2], row[3], row[4], ' '.join(associations), ', '.join(product_types)])
            categories.sort(key=lambda x: (x[3], x[4]))
            result['categories'] = categories
            session.commit()
            return result
