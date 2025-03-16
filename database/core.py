from os import getenv

from database.database import Base, engine


class Database:
    pass


def create_tables():
    if getenv("DROP_DB") == "True":
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
