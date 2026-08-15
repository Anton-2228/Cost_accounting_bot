"""Тесты подбора категории и счёта по псевдониму."""

from __future__ import annotations

from telegram_bot.api_client.models import Category, Source
from telegram_bot.parsers import AssociationMatcher
from tests.telegram_bot.conftest import make_category, make_source


def test_matches_by_alias(categories: list[Category]) -> None:
    """Слово из списка псевдонимов находит категорию."""
    found = AssociationMatcher.category("еда", categories)
    assert found is not None
    assert found.title == "Продукты"


def test_match_is_case_insensitive(categories: list[Category]) -> None:
    """Регистр ввода не важен: псевдонимы в базе всегда в нижнем."""
    assert AssociationMatcher.category("ЕДА", categories) is not None
    assert AssociationMatcher.category("  Еда ", categories) is not None


def test_unknown_alias_gives_none(categories: list[Category]) -> None:
    """Неизвестное слово — `None`, а не первая попавшаяся категория."""
    assert AssociationMatcher.category("бензин", categories) is None


def test_first_match_wins() -> None:
    """Возвращается первое совпадение, и перебор на этом прекращается.

    Дублей в базе быть не может — `(spreadsheet_id, alias)` уникален. Тест
    фиксирует поведение на случай, если данные всё же придут кривыми: старая
    версия продолжала скан и молча выбирала последний дубль, то есть писала
    операцию в другую категорию, ничего не сообщая.
    """
    duplicates = [
        make_category(category_id=1, title="Первая", associations=["общий"]),
        make_category(category_id=2, title="Вторая", associations=["общий"]),
    ]
    found = AssociationMatcher.category("общий", duplicates)
    assert found is not None
    assert found.id == 1


def test_namespaces_are_separate(categories: list[Category], sources: list[Source]) -> None:
    """Псевдоним счёта не находится среди категорий и наоборот."""
    assert AssociationMatcher.category("карта", categories) is None
    assert AssociationMatcher.source("еда", sources) is None


def test_source_matches_by_alias(sources: list[Source]) -> None:
    """Счёт находится по сокращению."""
    found = AssociationMatcher.source("нал", sources)
    assert found is not None
    assert found.title == "Наличные"


def test_hint_lists_titles() -> None:
    """Подсказка перечисляет названия через запятую."""
    assert AssociationMatcher.hint(["Еда", "Кафе"]) == "Еда, Кафе"


def test_hint_is_truncated() -> None:
    """Длинный справочник обрезается: иначе подсказка не влезет в сообщение."""
    hint = AssociationMatcher.hint([f"Категория {number}" for number in range(40)])
    assert hint.endswith("и другие")
    assert hint.count(",") < 40


def test_hint_of_empty_list() -> None:
    """Пустой справочник даёт пустую подсказку, а не «и другие»."""
    assert AssociationMatcher.hint([]) == ""


def test_source_and_category_helpers_ignore_surrounding_spaces(sources: list[Source]) -> None:
    """Пробелы вокруг слова не мешают подбору счёта."""
    assert AssociationMatcher.source(" карта ", sources) is not None
    assert make_source(title="Копилка").associations == ["копилка"]
