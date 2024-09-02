from sqlalchemy import select

from database import session_factory
from database.models import ChecksQueueOrm


class ChecksQueueWrapper:
    def create_check(self, spreadsheet_id: int, check_text: str) -> None:
        with session_factory() as session:
            check: ChecksQueueOrm = ChecksQueueOrm(spreadsheet_id=spreadsheet_id,
                                                   check_text=check_text)
            session.add(check)
            session.commit()

    def get_checks_by_spreadsheet(self, spreadsheet_id: int) -> list[ChecksQueueOrm]:
        with session_factory() as session:
            checks: list[ChecksQueueOrm] = session.scalars(select(ChecksQueueOrm)
                                                           .where(ChecksQueueOrm.spreadsheet_id == spreadsheet_id)
                                                           .order_by(ChecksQueueOrm.added_datetime)).all()
            return checks

    def remove_check(self, check_id: int):
        with session_factory() as session:
            check: ChecksQueueOrm = session.get(ChecksQueueOrm, check_id)
            session.delete(check)
            session.commit()
