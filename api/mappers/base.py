"""Базовый класс мапперов ORM ↔ domain.

Маппер — единственное место, знающее обе модели. `to_orm` намеренно не
выставляет `id`, `created_at` и `updated_at`: этими полями управляет БД.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable


class BaseMapper[ORM_T, DOMAIN_T](ABC):
    """Абстрактный маппер между ORM-моделью и доменной моделью."""

    @abstractmethod
    def to_domain(self, orm: ORM_T) -> DOMAIN_T:
        """Преобразует ORM-объект в доменную модель."""

    @abstractmethod
    def to_orm(self, domain: DOMAIN_T) -> ORM_T:
        """Создаёт новый ORM-объект из доменной модели (без id и таймстемпов)."""

    def to_domain_list(self, orms: Iterable[ORM_T]) -> list[DOMAIN_T]:
        """Преобразует коллекцию ORM-объектов в список доменных моделей."""
        return [self.to_domain(orm) for orm in orms]

    def to_orm_list(self, domains: Iterable[DOMAIN_T]) -> list[ORM_T]:
        """Преобразует коллекцию доменных моделей в список новых ORM-объектов."""
        return [self.to_orm(domain) for domain in domains]
