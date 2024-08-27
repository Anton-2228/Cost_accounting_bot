import datetime

from sqlalchemy import select

from database import session_factory, CategoriesOrm
from database import CashedRecordsOrm

class CashedRecordsOrmWrapper:
    def add_cashed_record(self, spreadsheet_id, name=None, type=None):
        with session_factory() as session:
            record = CashedRecordsOrm(spreadsheet_id=spreadsheet_id,
                                      product_name=name,
                                      type=type)
            session.add_all([record])
            session.commit()
            record: CashedRecordsOrm = session.get(CashedRecordsOrm, record.id)
            return record

    def get_cashed_records(self, spreadsheet_id):
        with session_factory() as session:
            records: list[CashedRecordsOrm] = session.scalars(select(CashedRecordsOrm)
                                                        .where(CashedRecordsOrm.spreadsheet_id == spreadsheet_id)).all()
            return records

    def remove_cashed_record(self, id: int):
        with session_factory() as session:
            record: CashedRecordsOrm = session.get(CashedRecordsOrm, id)
            session.delete(record)
            session.commit()


    # def remove_cashed_records_by_type(self, type: str):
    #     with session_factory() as session:
    #         records = session.query(CashedRecordsOrm).filter(CashedRecordsOrm.type == type).all()
    #         for record in records:
    #             session.delete(record)
    #         session.commit()

    # def delete_cashed_names_by_deleted_category(self, category_id):
    #     with session_factory() as session:
    #         category: CategoriesOrm = session.get(CategoriesOrm, category_id)
    #         deleted_types = category.product_types
    #         records: list[CashedRecordsOrm] = session.scalars(select(CashedRecordsOrm).filter(CashedRecordsOrm.type.in_(deleted_types))).all()
    #         for record in records:
    #             session.delete(record)
    #         session.commit()
