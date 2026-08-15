"""Тесты нормализации псевдонимов и типов товаров."""

from __future__ import annotations

from api.core.text import normalize_terms


def test_lowercases_and_strips() -> None:
    """Регистр и пробелы по краям не создают разных значений."""
    assert normalize_terms(["  Продукты ", "ЕДА"]) == ["еда", "продукты"]


def test_removes_duplicates_ignoring_case() -> None:
    """Дубли, отличающиеся регистром, схлопываются."""
    assert normalize_terms(["еда", "Еда", "ЕДА"]) == ["еда"]


def test_drops_empty_values() -> None:
    """Пустые и пробельные значения выбрасываются."""
    assert normalize_terms(["", "   ", "еда"]) == ["еда"]


def test_result_is_sorted() -> None:
    """Порядок детерминирован.

    Прежний код дедуплицировал набор через `set()`, а хеш строк в Python
    рандомизирован при каждом запуске процесса — лист `Categories`
    перетасовывался при каждой синхронизации.
    """
    assert normalize_terms(["янтарь", "апельсин", "берёза"]) == ["апельсин", "берёза", "янтарь"]


def test_empty_input_gives_empty_result() -> None:
    """Пустой набор остаётся пустым."""
    assert normalize_terms([]) == []
