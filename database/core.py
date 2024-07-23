from database.database import engine, Base

class Database:
    pass

def create_tables():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
