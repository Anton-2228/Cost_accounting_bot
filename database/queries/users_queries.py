from sqlalchemy import select

from database.database import session_factory
from database.models import UsersOrm


class UsersOrmWrapper:
    def create_user(self, telegram_id: int, spreadsheet_id: str = None):
        with session_factory() as session:
            user = UsersOrm(telegram_id=telegram_id, spreadsheet_id=spreadsheet_id)
            session.add(user)
            # session.add_all([user])
            session.commit()

    def get_user(self, user_telegram_id: int):
        with session_factory() as session:
            user: UsersOrm = session.scalar(
                select(UsersOrm).where(UsersOrm.telegram_id == user_telegram_id)
            )
            return user

    def remove_user(self, id: int):
        with session_factory() as session:
            user: UsersOrm = session.get(UsersOrm, id)
            session.delete(user)
            session.commit()

    def set_spreadsheetid(self, spreadsheet_id):
        with session_factory() as session:
            user: UsersOrm = session.get(UsersOrm, id)
            user.spreadsheet_id = spreadsheet_id
            session.commit()
