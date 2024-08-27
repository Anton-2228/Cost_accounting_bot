from database.queries.cashed_records_queries import CashedRecordsOrmWrapper
from database.queries.categories_queries import CategoriesOrmWrapper
from database.queries.records_queries import RecordsOrmWrapper
from database.queries.sources_queries import SourcesOrmWrapper
from database.queries.spreadsheets_queries import SpreadsheetsOrmWrapper
from database.queries.users_queries import UsersOrmWrapper


class PostgresWrapper:
    def __init__(self):
        self.categories_wrapper = CategoriesOrmWrapper()
        self.sources_wrapper = SourcesOrmWrapper()
        self.records_wrapper = RecordsOrmWrapper()
        self.spreadsheets_wrapper = SpreadsheetsOrmWrapper()
        self.users_wrapper = UsersOrmWrapper()
        self.cashed_records_wrapper = CashedRecordsOrmWrapper()