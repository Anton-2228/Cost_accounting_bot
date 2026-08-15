"""Импорт: правки пользователя в листе едут в базу и тут же возвращаются в лист."""

from __future__ import annotations

from google_sheets_service import constants
from google_sheets_service.exceptions import SyncError
from google_sheets_service.google.sheets_client import GoogleSheetsClient
from google_sheets_service.logging import get_logger
from google_sheets_service.main_api import ApiGateway
from google_sheets_service.main_api.dto import ImportResult
from google_sheets_service.sheets.a1 import column_letter, qualify
from google_sheets_service.sheets.layout import SheetLayout
from google_sheets_service.sheets.layouts import BILLS_LAYOUT, CATEGORIES_LAYOUT
from google_sheets_service.sheets.values import to_cell_rows
from google_sheets_service.sync.redraw import SheetRedrawer
from google_sheets_service.sync.structure import DocumentState

logger = get_logger(__name__)


class SheetImporter:
    """Читает лист справочника и отдаёт его строки в api.

    После успешного применения лист **сразу** перерисовывается — в той же
    задаче, не дожидаясь отдельной. Иначе между записью в базу и перерисовкой
    остаётся окно, в котором у новых строк листа ещё пустые идентификаторы:
    второй `/sync`, попавший в это окно, прочитал бы их как «создать» и завёл
    дубликаты категорий. Задача перерисовки, которую api ставит сам, при этом
    остаётся — она просто сделает ту же работу второй раз, а это безопасно и
    дёшево.
    """

    def __init__(
        self,
        *,
        api: ApiGateway,
        sheets: GoogleSheetsClient,
        redrawer: SheetRedrawer,
    ) -> None:
        self._api = api
        self._sheets = sheets
        self._redrawer = redrawer

    async def import_sheet(self, state: DocumentState, target: str) -> ImportResult:
        """Вчитывает лист справочника в базу и перерисовывает его."""
        layout = self._layout(target)
        mapping = state.mapping(target, None)
        range_a1 = qualify(
            mapping.title,
            f"A{constants.FIRST_DATA_ROW}:{_last_column(layout)}",
        )

        raw = await self._sheets.get_values(state.google_id, range_a1)
        rows = to_cell_rows(raw, width=layout.column_count)

        result = await self._apply(state.spreadsheet.id, target, rows)
        if result.error is not None:
            # Разбор не удался: в базу не записано ничего, а русский текст
            # ошибки api уже положил в уведомления. Перерисовывать нечего —
            # лист и так соответствует базе.
            logger.info(
                "Импорт %s документа %s отклонён: %s",
                target,
                state.spreadsheet.id,
                result.error,
            )
            return result

        await self._redrawer.redraw(state, target, None)
        logger.info(
            "Импорт %s документа %s: +%s ~%s -%s",
            target,
            state.spreadsheet.id,
            result.created,
            result.updated,
            result.deleted,
        )
        return result

    async def _apply(
        self,
        spreadsheet_id: int,
        target: str,
        rows: list[list[str]],
    ) -> ImportResult:
        """Отдаёт строки в соответствующий эндпоинт импорта."""
        if target == "CATEGORIES":
            return await self._api.imports.import_categories(spreadsheet_id, rows)
        if target == "BILLS":
            return await self._api.imports.import_bills(spreadsheet_id, rows)
        raise SyncError(f"Лист {target} не читается обратно")

    @staticmethod
    def _layout(target: str) -> SheetLayout:
        """Описание читаемого листа."""
        if target == "CATEGORIES":
            return CATEGORIES_LAYOUT
        if target == "BILLS":
            return BILLS_LAYOUT
        raise SyncError(f"Лист {target} не читается обратно")


def _last_column(layout: SheetLayout) -> str:
    """Буква последней колонки листа.

    Диапазон чтения ограничен колонками листа, но не строками: сколько их
    заполнил пользователь, заранее неизвестно, а Google всё равно вернёт только
    непустые.
    """
    return column_letter(layout.column_count)
