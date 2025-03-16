from os import getenv

from database.database import Base, engine


class Database:
    pass


def create_tables():
    if getenv("DEBUG") == "True":
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
