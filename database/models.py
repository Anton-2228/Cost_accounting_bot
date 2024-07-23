import datetime
from enum import Enum
from typing import List

from sqlalchemy import MetaData, Column, Table, Integer, String, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, ARRAY

from database.database import Base

class CategoriesTypes(Enum):
    COST = "cost"
    INCOME = "income"

class UsersOrm(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int]
    spreadsheet_id: Mapped[str] = mapped_column(ForeignKey("spreadsheets.id", ondelete="SET NULL"), nullable=True)

class SpreadSheetsOrm(Base):
    __tablename__ = "spreadsheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    spreadsheet_id: Mapped[str] = mapped_column(nullable=True)
    gmail: Mapped[list[str]] = mapped_column(ARRAY(String))
    # Начало текущего месяца
    # start_date: Mapped[datetime.date] = mapped_column(server_default=text("TIMEZONE('utc', now())::date"))
    start_date: Mapped[datetime.date] = mapped_column(nullable=True)

class CategoriesOrm(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    spreadsheet_id: Mapped[int] = mapped_column(ForeignKey("spreadsheets.id", ondelete="CASCADE"))
    active: Mapped[bool]
    type: Mapped[CategoriesTypes] = mapped_column(PgEnum(CategoriesTypes, name="categories_types", create_type=True))
    title: Mapped[str]
    associations: Mapped[str] # подумать про list


class SourcesOrm(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    spreadsheet_id: Mapped[int] = mapped_column(ForeignKey("spreadsheets.id", ondelete="CASCADE"))
    active: Mapped[bool]
    title: Mapped[str]
    associations: Mapped[str] # подумать про list
    start_balance: Mapped[int]
    current_balance: Mapped[int]

class RecordsOrm(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(primary_key=True)
    added_at: Mapped[datetime.datetime] = mapped_column(server_default=text("TIMEZONE('utc', now())"))
    amount: Mapped[int]
    category: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    notes: Mapped[str]
    source: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))

# metadata = MetaData()

# workers_table = Table(
#     "workers",
#     metadata,
#     Column("id", Integer, primary_key=True),
#     Column("username", String)
# )