"""Тесты репозиториев пользователей и учётных таблиц."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.user_repository import UserRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_lookup_by_telegram_id_is_deterministic(session: AsyncSession) -> None:
    """Поиск по telegram_id даёт однозначный результат.

    Раньше `telegram_id` не был уникален, а запрос шёл без `ORDER BY`: какую из
    строк вернёт Postgres, определял порядок строк в куче, то есть результат
    менялся после каждого VACUUM.
    """
    user = await factories.create_user(session, telegram_id=555)
    spreadsheet = await factories.create_spreadsheet(session, user=user, title="Личное")
    await session.commit()

    assert await UserRepository(session).exists_by_telegram_id(555) is True
    found = await SpreadsheetRepository(session).get_by_telegram_id(555)
    assert found is not None
    assert found.id == spreadsheet.id


async def test_google_id_is_empty_until_document_created(session: AsyncSession) -> None:
    """Идентификатор документа появляется только после подтверждения от Google.

    Пустое поле — это рабочее состояние «документ ещё предстоит создать», а не
    ошибка: api в Google не ходит.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.google_spreadsheet_id is None

    assert spreadsheet.id is not None
    repository = SpreadsheetRepository(session)
    updated = await repository.set_google_spreadsheet_id(spreadsheet.id, "1AbC")
    # Обновлённая модель приходит из самого оператора: читать её следом нельзя,
    # в сессии остался бы объект с пустым идентификатором.
    assert updated is not None
    assert updated.google_spreadsheet_id == "1AbC"
    await session.commit()

    stored = await repository.get_by_id(spreadsheet.id)
    assert stored is not None
    assert stored.google_spreadsheet_id == "1AbC"
    assert (await repository.get_by_google_id("1AbC")).id == spreadsheet.id  # type: ignore[union-attr]


async def test_several_spreadsheets_can_await_creation(session: AsyncSession) -> None:
    """Несколько документов могут одновременно ждать создания.

    Поэтому уникальность `google_spreadsheet_id` обычная, без NULLS NOT
    DISTINCT: пустые значения должны считаться различными.
    """
    await factories.create_spreadsheet(session)
    await factories.create_spreadsheet(session)
    await session.commit()

    assert len(await SpreadsheetRepository(session).list_all()) == 2
