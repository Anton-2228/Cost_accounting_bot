import datetime

from sqlalchemy import select

from database.database import session_factory
from database.models import SpreadSheetsOrm, UsersOrm


class SpreadsheetsOrmWrapper:
    def create(self, gmail: list[str], spreadsheet_id: str, start_date: datetime.date):
        with session_factory() as session:
            spreadsheet = SpreadSheetsOrm(
                spreadsheet_id=spreadsheet_id, gmail=gmail, start_date=start_date
            )
            session.add_all([spreadsheet])
            session.commit()
            spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, spreadsheet.id)
        return spreadsheet.id

    def remove_spreadsheet(self, id: int):
        with session_factory() as session:
            spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, id)
            session.delete(spreadsheet)
            session.commit()

    def add_gmail(self, user_telegram_id: int, gmail: str):
        with session_factory() as session:
            user: UsersOrm = session.scalar(
                select(UsersOrm).where(UsersOrm.telegram_id == user_telegram_id)
            )
            spreadsheet: SpreadSheetsOrm = session.get(
                SpreadSheetsOrm, user.spreadsheet_id
            )
            spreadsheet.gmail.append(gmail)
            session.commit()

    def get_spreadsheetid(self, user_telegram_id: int):
        with session_factory() as session:
            user: UsersOrm = session.scalar(
                select(UsersOrm).where(UsersOrm.telegram_id == user_telegram_id)
            )
            spreadsheet: SpreadSheetsOrm = session.get(
                SpreadSheetsOrm, user.spreadsheet_id
            )
            return spreadsheet.spreadsheet_id

    def get_spreadsheet(self, user_telegram_id: int):
        with session_factory() as session:
            user: UsersOrm = session.scalar(
                select(UsersOrm).where(UsersOrm.telegram_id == user_telegram_id)
            )
            spreadsheet: SpreadSheetsOrm = session.get(
                SpreadSheetsOrm, user.spreadsheet_id
            )
            return spreadsheet

    def get_spreadsheet_by_id(self, id):
        with session_factory() as session:
            spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, id)
            return spreadsheet

    def get_all_spreadsheets(self):
        with session_factory() as session:
            spreadsheets: list[SpreadSheetsOrm] = session.scalars(
                select(SpreadSheetsOrm)
            ).all()
            return spreadsheets

    def update_start_date(self, id, start_date: datetime.date):
        with session_factory() as session:
            spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, id)
            spreadsheet.start_date = start_date
            session.commit()

    # def get_start_date(self, user_telegram_id: int):
    #     with session_factory() as session:
    #         user: UsersOrm = session.scalar(select(UsersOrm).where(UsersOrm.telegram_id == user_telegram_id))
    #         spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, user.spreadsheet_id)
    #         return spreadsheet.start_date
