"""Тесты переводов между счетами."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import SheetTarget
from api.exceptions.base import BusinessRuleError, NotFoundError
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.repositories.source_repository import SourceRepository
from api.services.transfer_service import TransferService
from tests import factories


async def test_transfer_moves_money_between_two_accounts(
    session: AsyncSession,
    transfer_service: TransferService,
) -> None:
    """Обе стороны перевода — одна строка, а не два движения баланса.

    Прежняя версия двигала два баланса по отдельности: половину перевода можно
    было потерять, и следа от него не оставалось.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    wallet = await factories.create_source(session, spreadsheet, start_balance=Decimal("500.00"))
    card = await factories.create_source(session, spreadsheet, start_balance=Decimal("100.00"))
    await session.commit()
    assert spreadsheet.id is not None and wallet.id is not None and card.id is not None

    transfer = await transfer_service.create(
        spreadsheet.id,
        from_source_id=wallet.id,
        to_source_id=card.id,
        amount=Decimal("200.00"),
    )
    assert transfer.amount == Decimal("200.00")

    sources = SourceRepository(session)
    balances = {item.source_id: item.balance for item in await sources.balances(spreadsheet.id)}
    assert balances[wallet.id] == Decimal("300.00")
    assert balances[card.id] == Decimal("300.00")


async def test_transfer_does_not_touch_statistics(
    session: AsyncSession,
    transfer_service: TransferService,
) -> None:
    """Статистика не устаревает от перевода: деньги не появились и не исчезли.

    А вот реестр операций и балансы — устаревают: перевод должен быть виден,
    иначе ошибочный перевод нельзя ни найти, ни отменить.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    wallet = await factories.create_source(session, spreadsheet)
    card = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and wallet.id is not None and card.id is not None

    await transfer_service.create(
        spreadsheet.id,
        from_source_id=wallet.id,
        to_source_id=card.id,
        amount=Decimal("10.00"),
    )

    targets = {
        task.target
        for task in await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    }
    assert targets == {SheetTarget.OPERATIONS, SheetTarget.BILLS}


async def test_transfer_to_itself_is_rejected(
    session: AsyncSession,
    transfer_service: TransferService,
) -> None:
    """Перевод на тот же счёт — 422: он ничего не делает, но выглядит как операция."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    wallet = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and wallet.id is not None

    with pytest.raises(BusinessRuleError):
        await transfer_service.create(
            spreadsheet.id,
            from_source_id=wallet.id,
            to_source_id=wallet.id,
            amount=Decimal("10.00"),
        )


async def test_transfer_with_alien_source_is_not_found(
    session: AsyncSession,
    transfer_service: TransferService,
) -> None:
    """Счёт чужого документа — 404."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    wallet = await factories.create_source(session, spreadsheet)
    stranger = await factories.create_spreadsheet(session, ready=True)
    alien = await factories.create_source(session, stranger)
    await session.commit()
    assert spreadsheet.id is not None and wallet.id is not None and alien.id is not None

    with pytest.raises(NotFoundError):
        await transfer_service.create(
            spreadsheet.id,
            from_source_id=wallet.id,
            to_source_id=alien.id,
            amount=Decimal("10.00"),
        )


async def test_delete_last_transfer_restores_balances(
    session: AsyncSession,
    transfer_service: TransferService,
) -> None:
    """Удаление перевода возвращает балансы: они не хранятся, а считаются."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    wallet = await factories.create_source(session, spreadsheet, start_balance=Decimal("500.00"))
    card = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and wallet.id is not None and card.id is not None

    transfer = await transfer_service.create(
        spreadsheet.id,
        from_source_id=wallet.id,
        to_source_id=card.id,
        amount=Decimal("120.00"),
    )
    deleted = await transfer_service.delete(spreadsheet.id)
    assert deleted.id == transfer.id

    balances = {
        item.source_id: item.balance
        for item in await SourceRepository(session).balances(spreadsheet.id)
    }
    assert balances[wallet.id] == Decimal("500.00")
    assert balances[card.id] == Decimal("0.00")
    assert await transfer_service.list_by_period(spreadsheet.id) == []
