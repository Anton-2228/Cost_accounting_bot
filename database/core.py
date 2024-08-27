from database.database import Base, engine


class Database:
    pass


def create_tables():
    # Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
