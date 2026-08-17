"""Модели ответа модели.

Ответ **валидируется схемой**, а не обходится словарём. Это не педантизм: в
старой версии форму ответа никто не проверял, и первый же чек с незнакомым
товаром ронял разбор `ValueError`-ом мимо обработчика ошибок — в тишину.

Схема нарочно плоская: список пар «номер позиции → значение». Прежний протокол
требовал от модели заполнить ровно одно из двух полей (`type` или `new_type`) и
оставить второе пустым; какое из них новое, бот и так знает по своему списку
типов, а от модели это требовало соблюдать правило, которое ей незачем знать.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TypeSuggestion(BaseModel):
    """Тип товара, предложенный модели для одной позиции."""

    model_config = ConfigDict(extra="ignore")

    id: int
    type: str = Field(min_length=1)


class TypeSuggestions(BaseModel):
    """Ответ модели на вопрос «какой тип у этих товаров»."""

    model_config = ConfigDict(extra="ignore")

    items: list[TypeSuggestion] = []


class CategorySuggestion(BaseModel):
    """Категория, предложенная модели для одного типа товара."""

    model_config = ConfigDict(extra="ignore")

    id: int
    category: str = Field(min_length=1)


class CategorySuggestions(BaseModel):
    """Ответ модели на вопрос «в какую категорию относятся эти типы»."""

    model_config = ConfigDict(extra="ignore")

    items: list[CategorySuggestion] = []
