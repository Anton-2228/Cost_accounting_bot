import datetime

from sqlalchemy import select

from database.database import session_factory
from database.models import SpreadSheetsOrm, UsersOrm


def create(gmail: str, spreadsheet_id: str = None):
    with session_factory() as session:
        spreadsheet = SpreadSheetsOrm(spreadsheet_id=spreadsheet_id, gmail=gmail)
        session.add_all([spreadsheet])
        # Пиздец
        id = session.scalar(select(SpreadSheetsOrm.id).where(SpreadSheetsOrm.spreadsheet_id == spreadsheet_id))
        session.commit()
    return id

def add_gmail(user_telegram_id: int, gmail: str):
    with session_factory() as session:
        user: UsersOrm = session.scalar(select(UsersOrm)
                                                .where(UsersOrm.telegram_id == user_telegram_id))
        spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, user.spreadsheet_id)
        spreadsheet.gmail.append(gmail)
        session.commit()

# def add_spreadsheetid(user_telegram_id: int, spreadsheet_id: str):
#     with session_factory() as session:
#         user: UsersOrm = session.scalar(select(UsersOrm)
#                                         .where(UsersOrm.telegram_id == user_telegram_id))
#         spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, user.spreadsheet_id)
#         spreadsheet.spreadsheet_id = spreadsheet_id
#         session.commit()

# def get_gmail(user_telegram_id: int):
#     with session_factory() as session:
#         user: UsersOrm = session.scalar(select(UsersOrm).where(UsersOrm.telegram_id == user_telegram_id))
#         spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, user.spreadsheet_id)
#         return spreadsheet.gmail

def get_spreadsheetid(user_telegram_id: int):
    with session_factory() as session:
        user: UsersOrm = session.scalar(select(UsersOrm).where(UsersOrm.telegram_id == user_telegram_id))
        spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, user.spreadsheet_id)
        return spreadsheet.spreadsheet_id

def get_start_date(user_telegram_id: int):
    with session_factory() as session:
        user: UsersOrm = session.scalar(select(UsersOrm).where(UsersOrm.telegram_id == user_telegram_id))
        spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, user.spreadsheet_id)
        return spreadsheet.start_date

# def update_date(user_telegram_id: int, new_date: datetime.date):
#     with session_factory() as session:
#         user: UsersOrm = session.scalar(select(UsersOrm).where(UsersOrm.telegram_id == user_telegram_id))
#         spreadsheet: SpreadSheetsOrm = session.get(SpreadSheetsOrm, user.spreadsheet_id)
#         spreadsheet.start_date = new_date
#         session.commit()