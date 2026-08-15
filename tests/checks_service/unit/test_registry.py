"""Тесты реестра форматов."""

from __future__ import annotations

import pytest

from checks_service.enums import CheckKind
from checks_service.exceptions import FormatNotSupportedError
from checks_service.formats.registry import FormatRegistry
from checks_service.formats.ru_fns.parser import RuFnsQrParser
from tests.checks_service.factories import RU_FNS_QR
from tests.checks_service.fakes import FakeFetcher


def _registry() -> FormatRegistry:
    """Реестр с единственным сегодня форматом."""
    return FormatRegistry(
        parsers=[RuFnsQrParser()],
        fetchers={CheckKind.RU_FNS: FakeFetcher()},
    )


def test_known_format_is_recognised() -> None:
    """Строка ФНС попадает к своему парсеру."""
    assert _registry().parse(RU_FNS_QR).kind is CheckKind.RU_FNS


def test_surrounding_whitespace_does_not_break_recognition() -> None:
    """Сканер может вернуть строку с переводом строки на конце."""
    assert _registry().parse(f"  {RU_FNS_QR}\n").kind is CheckKind.RU_FNS


def test_unknown_format_is_a_named_refusal() -> None:
    """Незнакомый формат — понятный отказ, а не разбор наугад."""
    with pytest.raises(FormatNotSupportedError):
        _registry().parse("https://suf.purs.gov.rs/v/?vl=A1ZQMDI4NTE5")


def test_fetcher_is_chosen_by_kind() -> None:
    """Каждому виду чека — свой способ расшифровки."""
    fetcher = FakeFetcher()
    registry = FormatRegistry(parsers=[RuFnsQrParser()], fetchers={CheckKind.RU_FNS: fetcher})
    assert registry.fetcher_for(CheckKind.RU_FNS) is fetcher


def test_parser_without_fetcher_is_a_build_error() -> None:
    """Уметь распознать формат и не уметь его расшифровать бессмысленно.

    Это ошибка сборки приложения, а не входных данных, поэтому она и не
    превращается в HTTP-ответ.
    """
    registry = FormatRegistry(parsers=[RuFnsQrParser()], fetchers={})
    with pytest.raises(RuntimeError):
        registry.fetcher_for(CheckKind.RU_FNS)
