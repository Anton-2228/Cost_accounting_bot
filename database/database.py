from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from database.config import settings

engine = create_engine(
    url=settings.DB_URL_psycopg,
    echo=False,
    pool_size=5,
    max_overflow=10
)

session_factory = sessionmaker(engine)

class Base(DeclarativeBase):
    pass