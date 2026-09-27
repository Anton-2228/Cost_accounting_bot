"""Отложенные чеки: список для Mini App, повторы и отчёты фона."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants, messages
from api.core.logging import get_logger
from api.domain.check_summary import CheckNotice, CheckSummary
from api.domain.pending_check import PendingCheck
from api.enums import CheckKind, NotificationKind
from api.exceptions.base import ConflictError, NotFoundError
from api.repositories.check_repository import CheckRepository
from api.repositories.pending_check_repository import PendingCheckRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.base import BaseSpreadsheetService
from api.services.check_service import ALREADY_SAVED_REASON, check_currency

logger = get_logger(__name__)

#: Причина конфликта: чек прямо сейчас запрашивает кто-то другой — фон или
#: второй экран. Повторять одновременно незачем, ответ придёт и так.
BUSY_REASON = "pending_check_busy"


class PendingCheckService(BaseSpreadsheetService):
    """Чеки, которые внешний сервис пока не отдал.

    Сам внешний сервис api не зовёт — это делает `checks_service`, который
    знает форматы. Здесь только учёт: что отложено, кто сейчас спрашивает и
    когда спросить снова. Сохраняется дошедший чек обычным
    `CheckService.save`, который и убирает строку отсюда.

    Готовность Google-таблицы не проверяется, как и при сохранении чека:
    сканирующему незачем знать, дорисован ли документ.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        checks: CheckRepository,
        pending_checks: PendingCheckRepository,
        notifications: UserNotificationRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._checks = checks
        self._pending_checks = pending_checks
        self._notifications = notifications

    async def list_pending(self, spreadsheet_id: int) -> list[PendingCheck]:
        """Отложенные чеки документа в порядке сканирования, истёкшие тоже."""
        await self._get(spreadsheet_id)
        return await self._pending_checks.list_by_spreadsheet(spreadsheet_id)

    async def add(
        self,
        spreadsheet_id: int,
        *,
        kind: CheckKind,
        qr_raw: str,
        external_key: str,
        error: str,
    ) -> PendingCheck:
        """Откладывает чек; повторный скан того же чека вернёт ту же строку.

        Уже сохранённый чек не откладывается — 409, как и при сохранении:
        иначе фон неделю спрашивал бы о чеке, который давно в таблице.
        """
        await self._get(spreadsheet_id)
        if await self._checks.get_by_external_key(spreadsheet_id, kind, external_key):
            raise ConflictError("Чек уже добавлен", details={"reason": ALREADY_SAVED_REASON})

        pending = await self._pending_checks.add_or_get(
            spreadsheet_id,
            kind=kind,
            qr_raw=qr_raw,
            external_key=external_key,
            error=error,
        )
        await self._commit()
        logger.info("Чек %s (%s) отложен в документе %s", pending.id, kind, spreadsheet_id)
        return pending

    async def delete(self, spreadsheet_id: int, pending_id: int) -> None:
        """Убирает отложенный чек: фон о нём больше не спрашивает."""
        await self._get(spreadsheet_id)
        pending = await self._pending_checks.get_for_spreadsheet(pending_id, spreadsheet_id)
        if pending is None:
            raise NotFoundError("pending_check")
        await self._pending_checks.delete(pending_id)
        await self._commit()
        logger.info("Отложенный чек %s удалён из документа %s", pending_id, spreadsheet_id)

    async def claim(self, spreadsheet_id: int, pending_id: int) -> PendingCheck:
        """Забирает чек для ручного повтора.

        Занятый чек — 409 `pending_check_busy`: его прямо сейчас спрашивает
        фон или второй экран, и второй одновременный запрос ничего не ускорит.
        """
        await self._get(spreadsheet_id)
        if await self._pending_checks.get_for_spreadsheet(pending_id, spreadsheet_id) is None:
            raise NotFoundError("pending_check")
        claimed = await self._pending_checks.claim_one(pending_id, spreadsheet_id)
        if claimed is None:
            raise ConflictError(
                "Чек уже запрашивается",
                details={"reason": BUSY_REASON},
            )
        await self._commit()
        return claimed

    async def claim_due(
        self,
        limit: int = constants.PENDING_CHECK_CLAIM_LIMIT,
    ) -> list[PendingCheck]:
        """Забирает пачку чеков, которым пора повторить запрос (для фона).

        Коммит немедленный: `claim_due` держит строки под `FOR UPDATE`, а
        поход во внешний сервис длится секунды.
        """
        claimed = await self._pending_checks.claim_due(limit)
        await self._commit()
        return claimed

    async def fail(
        self,
        pending_id: int,
        error: str,
        *,
        manual: bool,
        notice: CheckNotice | None,
    ) -> PendingCheck | None:
        """Принимает отчёт о неудачной попытке и назначает следующую.

        Если на этой неудаче фоновое окно истекло, пользователю уходит
        уведомление: фон сдался, дальше решать ему. `notice` — сводка из
        QR-строки для этого уведомления; без неё уведомления нет — назвать чек
        нечем, и пользователь увидит его в Mini App.

        Строки уже нет (чек сохранили или удалили, пока шла попытка) —
        отчёт принимается молча и возвращается `None`: для отчитавшегося это
        нормальный ход дел, а не ошибка.
        """
        before = await self._pending_checks.get_by_id(pending_id)
        if before is None:
            return None
        pending = await self._pending_checks.record_failure(pending_id, error, manual=manual)
        if pending is None:
            return None

        just_expired = before.expired_at is None and pending.expired_at is not None
        if just_expired:
            logger.info("Отложенный чек %s истёк после %s попыток", pending_id, pending.attempts)
        if just_expired and notice is not None:
            spreadsheet = await self._get(pending.spreadsheet_id)
            summary = CheckSummary.of(
                notice,
                currency=check_currency(pending.kind),
                timezone=spreadsheet.timezone,
            )
            await self._notifications.notify(
                pending.spreadsheet_id,
                NotificationKind.PENDING_CHECK,
                messages.check_expired(summary),
            )
        await self._commit()
        return pending
