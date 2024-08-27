import copy

from sqlalchemy import select

from database.database import session_factory
from database.models import SourcesOrm, StatusTypes
from validation import validate_sources_row


class SourcesOrmWrapper:
    def get_source(self, id):
        with session_factory() as session:
            source: SourcesOrm = session.get(SourcesOrm, id)
            return source

    def set_status(self, id: int, status: StatusTypes):
        with session_factory() as session:
            source: SourcesOrm = session.get(SourcesOrm, id)
            source.status = status
            session.commit()

    def get_sources_by_spreadsheet(self, spreadsheet_id):
        with session_factory() as session:
            sources: SourcesOrm = session.scalars(
                select(SourcesOrm).where(
                    SourcesOrm.spreadsheet_id == spreadsheet_id,
                    SourcesOrm.status == StatusTypes.ACTIVE,
                )
            ).all()
            return sources

    def set_current_balance(self, id, current_balance):
        with session_factory() as session:
            source: SourcesOrm = session.get(SourcesOrm, id)
            source.current_balance = current_balance
            session.commit()

    def update_current_balance(self, id, shift):
        with session_factory() as session:
            source: SourcesOrm = session.get(SourcesOrm, id)
            source.current_balance = source.current_balance + shift
            session.commit()

    def synchronizeSources(self, spreadsheet, scope, spreadsheetWrapper):
        with session_factory() as session:
            # spreadsheet = get_spreadsheet(message.from_user.id)
            spreadsheets_sources = spreadsheetWrapper.getValues(
                spreadsheet.spreadsheet_id, scope
            )
            tmp_sql_sources = session.scalars(select(SourcesOrm)).all()
            sql_sources = {}
            for i in tmp_sql_sources:
                sql_sources[i.id] = i

            if "values" in spreadsheets_sources:
                for i in range(len(copy.deepcopy(spreadsheets_sources["values"]))):
                    row = spreadsheets_sources["values"][i]
                    if len(row) != 0:
                        spreadsheets_sources["values"][i].extend([""] * (6 - len(row)))
                result = {"result": "error"}
                message = validate_sources_row(spreadsheets_sources)
                if message is not None:
                    result["message"] = message
                    return result
                result["result"] = "success"

                add_sources = []
                sources = []
                for z, row in enumerate(spreadsheets_sources["values"]):
                    if len(row) == 0:
                        continue
                    if row[1] == "" and row[2] == "" and row[3] == "" and row[4] == "":
                        id = row[0]
                        self.set_status(id, StatusTypes.DELETED)
                        continue
                    if row[0] != "":
                        source = sql_sources[int(row[0])]
                        if row[1] == "1":
                            source.status = StatusTypes.ACTIVE
                        elif row[1] == "0":
                            source.status = StatusTypes.INACTIVE
                        source.title = row[2]
                        source.associations = [x.lower() for x in row[3].split()]
                        source.associations.append(row[2].lower())
                        source.associations = list(set(source.associations))
                        source.start_balance = float(row[4])
                        sources.append(
                            [
                                row[0],
                                row[1],
                                row[2],
                                " ".join(source.associations),
                                row[4],
                                source.current_balance,
                            ]
                        )
                    else:
                        if row[1] == "1":
                            status = StatusTypes.ACTIVE
                        elif row[1] == "0":
                            status = StatusTypes.INACTIVE
                        title = row[2]
                        associations = [x.lower() for x in row[3].split()]
                        associations.append(row[2].lower())
                        associations = list(set(associations))
                        start_balance = float(row[4])
                        source = SourcesOrm(
                            spreadsheet_id=spreadsheet.id,
                            status=status,
                            title=title,
                            associations=associations,
                            start_balance=start_balance,
                            current_balance=start_balance,
                        )
                        session.add(source)
                        session.flush()
                        add_sources.append(source)
                        sources.append(
                            [
                                str(source.id),
                                row[1],
                                row[2],
                                " ".join(source.associations),
                                row[4],
                                source.current_balance,
                            ]
                        )
                sources.sort(key=lambda x: int(x[0]))
                result["sources"] = sources
                session.commit()
                return result
