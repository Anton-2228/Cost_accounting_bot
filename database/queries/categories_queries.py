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
        categories: CategoriesOrm = session.scalars(select(CategoriesOrm)
                                                   .where(CategoriesOrm.spreadsheet_id == spreadsheet_id,
                                                          CategoriesOrm.status == StatusTypes.ACTIVE)).all()
        return categories


def synchronizeCategories(message, scope, spreadsheetWrapper):
    with session_factory() as session:
        spreadsheet = get_spreadsheet(message.from_user.id)
        spreadsheets_categories = spreadsheetWrapper.getValues(spreadsheet.spreadsheet_id, scope)
        tmp_sql_categories = session.scalars(select(CategoriesOrm)).all()
        sql_categories = {}
        for i in tmp_sql_categories:
            sql_categories[i.id] = i

        if "values" in spreadsheets_categories:
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
                if len(row) == 1:
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
                    categories.append([row[0], row[1], row[2], row[3], row[4], ' '.join(category.associations)])
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
                    category = CategoriesOrm(spreadsheet_id=spreadsheet.id,
                                             status=status,
                                             type=type,
                                             title=title,
                                             associations=associations)
                    session.add(category)
                    session.flush()
                    add_categories.append(category)
                    categories.append([category.id, row[1], row[2], row[3], row[4], ' '.join(associations)])
            result['categories'] = categories
            session.commit()
            return result
