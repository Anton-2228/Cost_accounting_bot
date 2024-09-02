from database import session_factory
from database.models import ChecksQueueOrm


class ChecksQueueWrapper:
    def create_check(self, spreadsheet_id: int, check_text: str):
        with session_factory() as session:
            check: ChecksQueueOrm = ChecksQueueOrm(spreadsheet_id=spreadsheet_id,
                                                   check_text=check_text)
            session.add(check)
            session.commit()