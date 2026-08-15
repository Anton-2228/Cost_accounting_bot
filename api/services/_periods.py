"""Общие правила работы с учётным периодом.

Вынесено из сервисов, потому что правило одно и то же для операций, переводов и
чеков: сегодняшняя дата берётся по часовому поясу документа, период под неё
создаётся при необходимости, а закрытый период не меняется.
"""

from __future__ import annotations

from datetime import date

from api.core.period import period_bounds, today_in_timezone
from api.domain.period import Period
from api.domain.spreadsheet import Spreadsheet
from api.enums import PeriodStatus
from api.exceptions.base import BusinessRuleError, NotFoundError
from api.repositories.period_repository import PeriodRepository


def today_for(spreadsheet: Spreadsheet) -> date:
    """Сегодняшняя дата в часовом поясе документа."""
    return today_in_timezone(spreadsheet.timezone)


async def ensure_current_period(
    periods: PeriodRepository,
    spreadsheet: Spreadsheet,
    today: date,
) -> Period:
    """Возвращает период под сегодняшнюю дату, создавая его при необходимости.

    Период создаётся здесь, а не только фоновым ролловером, намеренно. Ролловер
    может не успеть или не работать вовсе (api лежал), а операции запрещены в
    закрытый период — без ленивого создания первая же операция после простоя
    упиралась бы в 422 и пользователь не мог бы сделать ничего.
    """
    assert spreadsheet.id is not None
    start_date, end_date = period_bounds(today, spreadsheet.reset_day)
    period = await periods.ensure(spreadsheet.id, start_date, end_date)
    assert_open(period)
    return period


async def resolve_period(
    periods: PeriodRepository,
    spreadsheet: Spreadsheet,
    period_id: int | None,
) -> Period | None:
    """Период, о котором спрашивают: указанный явно или текущий.

    Пустой `period_id` — «текущий месяц»: так один эндпоинт обслуживает и бота
    («покажи мои операции»), и `google_sheets_service` («перерисуй лист периода
    7»). `None` в ответе означает, что текущего периода ещё нет; чужой или
    несуществующий период — 404, а не молчаливый пустой список.
    """
    assert spreadsheet.id is not None
    if period_id is None:
        return await periods.get_containing(spreadsheet.id, today_for(spreadsheet))

    period = await periods.get_for_spreadsheet(period_id, spreadsheet.id)
    if period is None:
        raise NotFoundError("period")
    return period


def assert_open(period: Period) -> None:
    """Запрещает менять закрытый период.

    Закрытие означает «месяц сдан»: и добавление, и удаление задним числом
    поменяли бы уже показанные пользователю итоги.
    """
    if period.status is PeriodStatus.CLOSED:
        raise BusinessRuleError(
            f"Период с {period.start_date} закрыт",
            details={"period_id": period.id},
        )
