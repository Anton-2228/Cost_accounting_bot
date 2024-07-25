from sqlalchemy import select

from database.database import session_factory
from database.models import StatusTypes, SourcesOrm
from database.queries.spreadsheets_queries import get_spreadsheet
from validation import validate_sources_row


def set_status(id: int, status: StatusTypes):
    with session_factory() as session:
        category: SourcesOrm = session.get(SourcesOrm, id)
        category.status = status
        session.commit()

def synchronizeSources(message, scope, spreadsheetWrapper):
    with session_factory() as session:
        spreadsheet = get_spreadsheet(message.from_user.id)
        spreadsheets_sources = spreadsheetWrapper.getValues(spreadsheet.spreadsheet_id, scope)
        tmp_sql_sources = session.scalars(select(SourcesOrm)).all()
        sql_sources = {}
        for i in tmp_sql_sources:
            print(i)
            print(i.id)
            sql_sources[i.id] = i

        if "values" in spreadsheets_sources:
            print(spreadsheets_sources)
            result = {'result': 'error'}
            message = validate_sources_row(spreadsheets_sources)
            if message is not None:
                result['message'] = message
                return result
            result['result'] = 'success'

            add_sources = []
            sources = []
            for z, row in enumerate(spreadsheets_sources["values"]):
                if len(row) == 0:
                    continue
                if row[1] == '' and row[2] == '' and row[3] == '' and row[4] == '':
                    id = row[0]
                    set_status(id, StatusTypes.DELETED)
                    continue
                if row[0] != '':
                    source = sql_sources[int(row[0])]
                    if row[1] == '1':
                        source.status = StatusTypes.ACTIVE
                    elif row[1] == '0':
                        source.status = StatusTypes.INACTIVE
                    source.title = row[2]
                    source.associations = row[3].split()
                    source.start_balance = float(row[4])
                    sources.append([row[0], row[1], row[2], row[3], row[4], row[5]])
                else:
                    if row[1] == '1':
                        status = StatusTypes.ACTIVE
                    elif row[1] == '0':
                        status = StatusTypes.INACTIVE
                    title = row[2]
                    associations = row[3].split()
                    start_balance = float(row[4])
                    source = SourcesOrm(spreadsheet_id=spreadsheet.id,
                                        status=status,
                                        title=title,
                                        associations=associations,
                                        start_balance=start_balance,
                                        current_balance=start_balance)
                    session.add(source)
                    session.flush()
                    add_sources.append(source)
                    sources.append([source.id, row[1], row[2], row[3], row[4], source.current_balance])
            result['sources'] = sources
            session.commit()
            return result
