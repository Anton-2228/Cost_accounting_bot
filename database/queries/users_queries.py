from database.database import session_factory
from database.models import UsersOrm


def create_user(telegram_id: int, spreadsheet_id: str = None):
    with session_factory() as session:
        user = UsersOrm(telegram_id=telegram_id, spreadsheet_id=spreadsheet_id)
        session.add(user)
        # session.add_all([user])
        session.commit()
