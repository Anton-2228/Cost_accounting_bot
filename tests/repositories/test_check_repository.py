"""Тесты репозитория сохранённых чеков."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.check import Check
from api.enums import CheckKind
from api.repositories.check_repository import CheckRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")

_FETCHED_AT = datetime(2026, 7, 25, 15, 7, tzinfo=UTC)


def _check(spreadsheet_id: int, external_key: str) -> Check:
    """Собирает чек с минимальным правдоподобным сырьём."""
    return Check(
        spreadsheet_id=spreadsheet_id,
        kind=CheckKind.RU_FNS,
        qr_raw=f"t=20260725T1507&s=1214.95&fn=7384440901402798&i=145&fp={external_key}&n=1",
        external_key=external_key,
        raw_payload={"code": 1, "data": {"json": {"items": [{"name": "молоко", "sum": 8990}]}}},
        fetched_at=_FETCHED_AT,
    )


async def test_raw_payload_survives_roundtrip(session: AsyncSession) -> None:
    """Ответ внешнего сервиса возвращается из БД тем же, чем уехал.

    Хранить чек целиком имеет смысл только в этом случае: разбор придёт позже и
    возьмёт из `raw_payload` поля, о которых сейчас неизвестно, что они
    понадобятся.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    repository = CheckRepository(session)
    saved = await repository.add(_check(spreadsheet.id, "7384440901402798:145:698610272"))
    await session.commit()

    assert saved.id is not None
    assert saved.raw_payload["data"]["json"]["items"][0]["sum"] == 8990
    assert saved.fetched_at == _FETCHED_AT


async def test_external_key_lookup_is_scoped_to_spreadsheet(session: AsyncSession) -> None:
    """Один и тот же чек у двух пользователей — две разные строки.

    Ключ дедупликации не глобальный: люди ходят в магазин вдвоём, и чек,
    добавленный одним, не должен становиться «уже добавленным» для другого.
    """
    mine = await factories.create_spreadsheet(session)
    other = await factories.create_spreadsheet(session)
    await session.commit()
    assert mine.id is not None and other.id is not None

    key = "7384440901402798:145:698610272"
    repository = CheckRepository(session)
    await repository.add(_check(other.id, key))
    await session.commit()

    assert await repository.get_by_external_key(other.id, CheckKind.RU_FNS, key) is not None
    assert await repository.get_by_external_key(mine.id, CheckKind.RU_FNS, key) is None

    await repository.add(_check(mine.id, key))
    await session.commit()
    assert await repository.get_by_external_key(mine.id, CheckKind.RU_FNS, key) is not None


async def test_checks_are_ordered_by_arrival(session: AsyncSession) -> None:
    """Чеки возвращаются в порядке поступления."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    repository = CheckRepository(session)
    for key in ("первый", "второй", "третий"):
        await repository.add(_check(spreadsheet.id, key))
    await session.commit()

    checks = await repository.list_by_spreadsheet(spreadsheet.id)
    assert [check.external_key for check in checks] == ["первый", "второй", "третий"]
