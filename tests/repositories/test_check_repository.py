"""Тесты репозитория сохранённых чеков."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.check import Check
from api.enums import CheckKind
from api.repositories.check_repository import CheckRepository
from api.repositories.record_repository import RecordRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")

_FETCHED_AT = datetime(2026, 7, 25, 15, 7, tzinfo=UTC)
_PROCESSED_AT = datetime(2026, 7, 26, 9, 0, tzinfo=UTC)
_LATER = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)


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


async def test_unprocessed_queue_keeps_order_and_loses_marked(session: AsyncSession) -> None:
    """Очередь разбора — только неотмеченные, от самого старого.

    Порядок существен: чек, пролежавший неделю, должен быть разобран раньше
    сегодняшнего, иначе очередь превращается в стек и старое в ней тонет.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    repository = CheckRepository(session)
    saved = [await repository.add(_check(spreadsheet.id, key)) for key in ("а", "б", "в")]
    await session.commit()
    assert saved[1].id is not None

    marked = await repository.mark_processed(saved[1].id, at=_PROCESSED_AT)
    await session.commit()
    assert marked is not None and marked.processed_at == _PROCESSED_AT

    queue = await repository.list_by_spreadsheet(spreadsheet.id, unprocessed=True)
    assert [check.external_key for check in queue] == ["а", "в"]
    assert len(await repository.list_by_spreadsheet(spreadsheet.id)) == 3


async def test_mark_processed_is_not_repeatable(session: AsyncSession) -> None:
    """Повторная отметка ничего не меняет и говорит об этом.

    Условие `processed_at IS NULL` — не перестраховка: без него второй разбор
    переписал бы метку времени и отчитался об успехе там, где записывать чек
    уже было нельзя.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    repository = CheckRepository(session)
    saved = await repository.add(_check(spreadsheet.id, "ключ"))
    await session.commit()
    assert saved.id is not None

    assert await repository.mark_processed(saved.id, at=_PROCESSED_AT) is not None
    assert await repository.mark_processed(saved.id, at=_LATER) is None

    stored = await repository.get_for_spreadsheet(saved.id, spreadsheet.id)
    assert stored is not None and stored.processed_at == _PROCESSED_AT


async def test_check_of_another_document_is_invisible(session: AsyncSession) -> None:
    """Чек чужого документа не находится по id."""
    mine = await factories.create_spreadsheet(session)
    other = await factories.create_spreadsheet(session)
    await session.commit()
    assert mine.id is not None and other.id is not None

    repository = CheckRepository(session)
    alien = await repository.add(_check(other.id, "чужой"))
    await session.commit()
    assert alien.id is not None

    assert await repository.get_for_spreadsheet(alien.id, other.id) is not None
    assert await repository.get_for_spreadsheet(alien.id, mine.id) is None


async def test_period_archive_holds_only_checks_of_that_month(session: AsyncSession) -> None:
    """В архив месяца попадают чеки, чьи операции лежат в этом периоде.

    Своего периода у чека нет: он приезжает из Mini App задолго до разбора, а
    месяц ему назначают операции. Неразобранный чек операций не имеет и в
    архиве не появляется вовсе.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    month = await factories.create_period(session, spreadsheet, day=date(2026, 7, 20))
    next_month = await factories.create_period(session, spreadsheet, day=date(2026, 8, 20))
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and month.id is not None

    repository = CheckRepository(session)
    parsed = await repository.add(_check(spreadsheet.id, "разобран"))
    other_month = await repository.add(_check(spreadsheet.id, "из другого месяца"))
    await repository.add(_check(spreadsheet.id, "в очереди"))
    await session.commit()

    await factories.create_record(
        session, spreadsheet, month, category, source,
        amount=Decimal("-89.90"), check_id=parsed.id,
    )
    await factories.create_record(
        session, spreadsheet, next_month, category, source,
        amount=Decimal("-10.00"), check_id=other_month.id,
    )
    await session.commit()

    archive = await repository.list_processed_for_period(spreadsheet.id, month.id)
    assert [item.id for item in archive] == [parsed.id]


async def test_period_archive_survives_deletion_of_one_record(session: AsyncSession) -> None:
    """Чек остаётся в архиве, пока жив сам, — удалённые операции не в счёт.

    Пользователь, удаливший одну строку реестра, не отзывал чек. Считай выборка
    только живые операции — правка одной позиции молча выносила бы чек из
    архива, ради которого лист и существует. Исчезает чек по собственной метке
    удаления, а её ставит уход **последней** его операции.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and period.id is not None

    repository = CheckRepository(session)
    check = await repository.add(_check(spreadsheet.id, "ключ"))
    await session.commit()

    first = await factories.create_record(
        session, spreadsheet, period, category, source,
        amount=Decimal("-89.90"), check_id=check.id,
    )
    await factories.create_record(
        session, spreadsheet, period, category, source,
        amount=Decimal("-10.00"), check_id=check.id,
    )
    await session.commit()
    assert first.id is not None

    await RecordRepository(session).soft_delete(first.id, at=_LATER)
    await session.commit()

    archive = await repository.list_processed_for_period(spreadsheet.id, period.id)
    assert [item.id for item in archive] == [check.id]


async def test_deleted_check_disappears_from_archive_and_list(session: AsyncSession) -> None:
    """Мягко удалённый чек пропадает и из архива месяца, и из списка документа.

    Операции при этом остаются на месте — удалёнными, со ссылкой на чек. Именно
    поэтому чек нельзя стирать физически: ссылке было бы не на что смотреть.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and period.id is not None

    repository = CheckRepository(session)
    check = await repository.add(_check(spreadsheet.id, "ключ"))
    await session.commit()
    assert check.id is not None

    record = await factories.create_record(
        session, spreadsheet, period, category, source,
        amount=Decimal("-89.90"), check_id=check.id,
    )
    await session.commit()
    assert record.id is not None

    records = RecordRepository(session)
    await records.soft_delete(record.id, at=_LATER)
    await repository.soft_delete(check.id, at=_LATER)
    await session.commit()

    assert await repository.list_processed_for_period(spreadsheet.id, period.id) == []
    assert await repository.list_by_spreadsheet(spreadsheet.id) == []
    assert await repository.get_for_spreadsheet(check.id, spreadsheet.id) is None

    orphan = await records.get_for_spreadsheet(record.id, spreadsheet.id, include_deleted=True)
    assert orphan is not None and orphan.check_id == check.id


async def test_check_deletion_is_soft(session: AsyncSession) -> None:
    """Удаление чека мягкое: строка остаётся, повтор ничего не меняет.

    Сырьё — единственный след покупки, и стирать его вместе с меткой удаления
    незачем; повторный вызов возвращает `False`, потому что второе удаление уже
    ничего не удаляет.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    repository = CheckRepository(session)
    saved = await repository.add(_check(spreadsheet.id, "ключ"))
    await session.commit()
    assert saved.id is not None

    assert await repository.soft_delete(saved.id, at=_LATER) is True
    await session.commit()

    assert await repository.list_by_spreadsheet(spreadsheet.id) == []
    assert await repository.soft_delete(saved.id, at=_PROCESSED_AT) is False

    stored = await repository.get_by_id(saved.id, include_deleted=True)
    assert stored is not None
    assert stored.deleted_at == _LATER
    assert stored.raw_payload["data"]["json"]["items"][0]["sum"] == 8990


async def test_same_paper_is_scannable_again_after_deletion(session: AsyncSession) -> None:
    """Ключ занимает только живой чек: удалённый не мешает новому.

    Уникальность частичная (`WHERE deleted_at IS NULL`). Пока чек жив, второй с
    тем же ключом невыразим; после удаления та же бумажка принимается как новый
    чек — иначе мягкое удаление означало бы «чек исчез, и вернуть его нечем».
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    repository = CheckRepository(session)
    first = await repository.add(_check(spreadsheet.id, "ключ"))
    await session.commit()
    assert first.id is not None

    with pytest.raises(IntegrityError):
        # `add` делает flush, поэтому нарушение всплывает здесь, а не на commit.
        await repository.add(_check(spreadsheet.id, "ключ"))
    await session.rollback()

    assert await repository.soft_delete(first.id, at=_LATER) is True
    await session.commit()

    second = await repository.add(_check(spreadsheet.id, "ключ"))
    await session.commit()

    assert second.id is not None and second.id != first.id
    assert [item.id for item in await repository.list_by_spreadsheet(spreadsheet.id)] == [
        second.id
    ]
