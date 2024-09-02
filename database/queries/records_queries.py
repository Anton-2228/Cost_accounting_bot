import datetime

from sqlalchemy import select

from database.database import session_factory
from database.models import RecordsOrm, CashedRecordsOrm
from datafiles import DAYSUNTILNEXTMONTH


class RecordsOrmWrapper:
    def create_record(
        self,
        spreadsheet_id,
        amount,
        category_id,
        source_id,
        notes,
        name=None,
        check_json=None,
        type=None,
    ):
        with session_factory() as session:
            record = RecordsOrm(
                spreadsheet_id=spreadsheet_id,
                amount=amount,
                category=category_id,
                source=source_id,
                notes=notes,
                product_name=name,
                check_json=check_json,
                type=type,
            )
            session.add_all([record])
            session.commit()
            record: RecordsOrm = session.get(RecordsOrm, record.id)
            return record

    def get_records_by_current_month(self, spreadsheet_id, start_date: datetime.date):
        end_date = start_date + datetime.timedelta(
            days=DAYSUNTILNEXTMONTH[str(start_date.month)]
        )
        with session_factory() as session:
            records: RecordsOrm = session.scalars(
                select(RecordsOrm)
                .where(
                    RecordsOrm.spreadsheet_id == spreadsheet_id,
                    RecordsOrm.added_at.between(start_date, end_date),
                )
                .order_by(RecordsOrm.id)
            ).all()
            return records

    def get_records_by_current_month_by_category(
        self, spreadsheet_id, start_date: datetime.date, category_id
    ):
        end_date = start_date + datetime.timedelta(
            days=DAYSUNTILNEXTMONTH[str(start_date.month)]
        )
        with session_factory() as session:
            records: list[RecordsOrm] = session.scalars(
                select(RecordsOrm)
                .where(
                    RecordsOrm.spreadsheet_id == spreadsheet_id,
                    RecordsOrm.category == category_id,
                    RecordsOrm.added_at.between(start_date, end_date),
                )
                .order_by(RecordsOrm.id)
            ).all()
            return records

    def remove_record(self, id: int):
        with session_factory() as session:
            record: RecordsOrm = session.get(RecordsOrm, id)
            self.delete_cashed_name_by_deleted_record(record.product_name, session)
            session.delete(record)
            session.commit()

    def delete_cashed_name_by_deleted_record(self, record_product_name, session):
        record: CashedRecordsOrm = session.scalar(
            select(CashedRecordsOrm).filter(CashedRecordsOrm.product_name == record_product_name)
        )
        if record is not None:
            session.delete(record)
        session.commit()

    # def get_records_by_spreadsheet(spreadsheet_id):
    #     with session_factory() as session:
    #         records: RecordsOrm = session.scalars(select(RecordsOrm)
    #                                               .where(RecordsOrm.spreadsheet_id == spreadsheet_id).order_by(RecordsOrm.id)).all()
    #         return records
