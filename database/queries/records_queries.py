import datetime

from sqlalchemy import select

from database.database import session_factory
from database.models import RecordsOrm
from init import daysUntilNextMonth


def create_record(spreadsheet_id, amount, category_id, source_id, notes, name=None, check_json=None):
    with session_factory() as session:
        record = RecordsOrm(spreadsheet_id=spreadsheet_id,
                            amount=amount,
                            category=category_id,
                            source=source_id,
                            notes=notes)
        session.add_all([record])
        session.commit()
        record: RecordsOrm = session.get(RecordsOrm, record.id)
        return record

def get_records_by_current_month(spreadsheet_id, start_date: datetime.date):
    end_date = start_date + datetime.timedelta(days=daysUntilNextMonth[start_date.month])
    with session_factory() as session:
        records: RecordsOrm = session.scalars(select(RecordsOrm)
                                                    .where(RecordsOrm.spreadsheet_id == spreadsheet_id,
                                                           RecordsOrm.added_at.between(start_date, end_date))
                                              .order_by(RecordsOrm.id)).all()
        return records

def get_records_by_current_month_by_category(spreadsheet_id, start_date: datetime.date, category_id):
    end_date = start_date + datetime.timedelta(days=daysUntilNextMonth[start_date.month])
    with session_factory() as session:
        records: list[RecordsOrm] = session.scalars(select(RecordsOrm)
                                                    .where(RecordsOrm.spreadsheet_id == spreadsheet_id,
                                                           RecordsOrm.category == category_id,
                                                           RecordsOrm.added_at.between(start_date, end_date))
                                              .order_by(RecordsOrm.id)).all()
        return records


def remove_record(id: int):
    with session_factory() as session:
        record: RecordsOrm = session.get(RecordsOrm, id)
        session.delete(record)
        session.commit()

# def get_records_by_spreadsheet(spreadsheet_id):
#     with session_factory() as session:
#         records: RecordsOrm = session.scalars(select(RecordsOrm)
#                                               .where(RecordsOrm.spreadsheet_id == spreadsheet_id).order_by(RecordsOrm.id)).all()
#         return records