"""Тесты выбора пути чтения QR с фото."""

from __future__ import annotations

import pytest

from checks_service.enums import CheckKind
from checks_service.exceptions import QrNotFoundError
from checks_service.formats.registry import FormatRegistry
from checks_service.formats.ru_fns.parser import RuFnsQrParser
from checks_service.main_api.spreadsheets import Spreadsheet
from checks_service.services.photo_qr import PhotoQrService
from tests.checks_service.factories import make_qr_photo
from tests.checks_service.fakes import FakeApiGateway, FakeFetcher


async def test_disabled_fallback_answers_qr_not_found_without_the_api() -> None:
    """Выключенный фолбек — как до его появления: ни таблицы, ни модели."""
    api = FakeApiGateway()
    api.spreadsheets.spreadsheet = Spreadsheet(id=7, title="Мои расходы")
    registry = FormatRegistry(parsers=[RuFnsQrParser()], fetchers={CheckKind.RU_FNS: FakeFetcher()})
    service = PhotoQrService(registry=registry, api=api, qr_vision=None)  # type: ignore[arg-type]

    with pytest.raises(QrNotFoundError):
        await service.decode(make_qr_photo(), telegram_id=1)

    assert api.spreadsheets.calls == []
