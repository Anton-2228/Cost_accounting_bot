from typing import TypedDict, Literal

from database.models import StatusTypes, CategoriesTypes


class Category(TypedDict):
    status: StatusTypes
    type: CategoriesTypes
    name: str
    associations: list[str]


class SynchronizeCategoriesResponse(TypedDict):
    result: Literal["error", "success"]
    message: str
    category: Category