"""Команда `/check`: разбор чека из очереди.

Диалог живёт в боте, а не в Mini App: здесь уже есть FSM, подбор по
псевдонимам и русские тексты, а Mini App пришлось бы заводить всё это заново.
Mini App остаётся тем, чем был, — входом.

Две стадии на один чек:

1. **типы** — товар из кэша получает тип без модели, остальные уходят в первый
   вызов; правки строками «1,3 - молочка»;
2. **категории** — тип определяет категорию детерминированно
   (`UNIQUE (spreadsheet_id, product_type)`), модель зовётся только для новых
   типов. «Готово» на этой стадии и записывает чек: `POST /checks/commit`.

Стадии проходимы в обе стороны: «К типам» возвращает на первую, ничего не
пересчитывая, а обратный переход трогает только позиции, чья категория не
выведена из нынешнего типа.

Лишнюю позицию убирает строка «!1,3» — на любой стадии, повторная возвращает.
Удаление не трогает ни тип, ни категорию и не удаляет чек: операции по такой
позиции просто не будет, а сам чек записывается целиком и помечается
разобранным. Иначе тот же QR отсканировался бы заново.

Валюта у чека своя и не спрашивается: её задаёт формат чека, и api проставляет
операциям ровно ту же. Счёт не спрашивается тоже — его в системе нет.

Что из старой реализации сознательно не повторяется:

* всё промежуточное — в FSM-данных, а не в `self.temp_data[user_id]`;
* форма ответа модели проверяется схемой, а не обходится словарём;
* `callback_data` несёт `check_id`, а обработчик фильтруется по состоянию: без
  этого кнопка от предыдущего чека оставалась живой и применялась к текущему;
* итоговый тип уходит в `commit` по **каждой** позиции, включая взятые из кэша
  — правка типа у знакомого товара больше не теряется.
"""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot import constants
from telegram_bot.ai import AiClient, AiError, LlmUsage
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.checks import CommitItem, NewProductType
from telegram_bot.api_client.errors import ApiConflictError, ApiError
from telegram_bot.api_client.models import (
    Category,
    CategoryKind,
    Check,
    LlmEntityKind,
    LlmOperation,
    Spreadsheet,
)
from telegram_bot.checks import ReceiptError, ReceiptExtractor
from telegram_bot.checks.draft import CheckDraft, DraftItem
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.cancel import BRANCH_CHECK, cancel_row
from telegram_bot.commands.manager import Manager
from telegram_bot.enums import CommandName, FsmDataKeys
from telegram_bot.errors import TYPE_TAKEN_REASON, ApiErrorPresenter
from telegram_bot.formatting import CheckFormatter
from telegram_bot.i18n import current_language, t
from telegram_bot.logging import get_logger
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.parsers import AssociationMatcher, CheckParser, ParsedCheckEdit, ParseError
from telegram_bot.states import States

logger = get_logger(__name__)

#: Префикс `callback_data`. Дальше — стадия и `check_id`: без него кнопка от
#: предыдущего чека применилась бы к текущему, ровно как в старой версии.
_DONE_PREFIX = "check_done"

#: Префикс кнопки «Вернуться к типам». Свой, а не ещё одна метка стадии у
#: «Готово»: стадия в `callback_data` говорит, *откуда* нажали, и «готово, чтобы
#: вернуться назад» читалось бы задом наперёд.
_BACK_PREFIX = "check_back"

#: Метки стадий в `callback_data`. Короткие и свои, а не строка состояния:
#: `States.CHECK_TYPES.state` — это «States:CHECK_TYPES», и двоеточие внутри
#: развалило бы разбор `callback_data`, который сам разделён двоеточиями.
_STAGE_TYPES = "types"
_STAGE_CATEGORIES = "categories"

#: Разметка списков сопоставления. Включается на месте вызова, а не глобально:
#: остальные сообщения несут данные пользователя, и HTML на всех превратил бы
#: любую угловую скобку в них в сломанное сообщение.
_HTML = "HTML"


class CheckCommand(BaseCommand):
    """Очередь неразобранных чеков и диалог разбора текущего."""

    def __init__(
        self,
        manager: Manager,
        api: ApiGateway,
        aiogram_wrapper: AiogramWrapper,
        catch_up: NotificationCatchUp,
        ai: AiClient,
    ) -> None:
        super().__init__(manager, api, aiogram_wrapper, catch_up)
        self.ai = ai

    # --- Точки входа -----------------------------------------------------

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Начинает разбор либо обрабатывает очередной шаг диалога."""
        current = await self.aiogram.get_state(state)
        chat_id = message.chat.id

        if current == States.CHECK_TYPES.state:
            await self._edit_types(message, state)
            return
        if current == States.CHECK_CATEGORIES.state:
            await self._edit_categories(message, state)
            return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return
        await self._open_queue(chat_id, state, spreadsheet=spreadsheet)

    async def _open_queue(
        self,
        chat_id: int,
        state: FSMContext,
        *,
        user_id: int | None = None,
        spreadsheet: Spreadsheet | None = None,
    ) -> None:
        """Начинает сессию разбора: с команды `/check` или с кнопки меню.

        Один метод на оба входа: команда приносит сообщение, кнопка — только
        номер пользователя, а дальше сессия у них общая до последнего чека.
        """
        if spreadsheet is None:
            if user_id is None:
                return
            spreadsheet = await self.spreadsheet_for(user_id=user_id, chat_id=chat_id)
            if spreadsheet is None:
                return

        # Сессия начинается начисто: пропущенные в прошлый раз чеки снова
        # попадают в очередь — иначе «пропустить» означало бы «удалить».
        await self.finish(chat_id=chat_id, state=state)
        await self.show_next(chat_id=chat_id, state=state, spreadsheet=spreadsheet)

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Кнопки ветки: вход из меню и переходы между стадиями."""
        await self.aiogram.answer_callback(callback)
        if callback.message is None or callback.from_user is None:
            return
        chat_id = callback.message.chat.id

        # Кнопка меню «Обработать чеки» — до всего остального: очередь ещё не
        # начата, черновика нет, и спрашивать о нём здесь нечего. Разбирается
        # по префиксу, а не по состоянию: кнопка живёт вне состояний вовсе.
        if (callback.data or "").startswith(f"{CommandName.CHECK}:"):
            await self._open_queue(chat_id, state, user_id=callback.from_user.id)
            return

        draft = await self._draft(state)
        if draft is None:
            await self.finish(chat_id=chat_id, state=state)
            await self.aiogram.send_message(chat_id, t("text.check_lost"))
            return

        if not self.is_current(callback.data, draft):
            await self.aiogram.send_message(chat_id, t("text.check_stale_button"))
            return

        spreadsheet = await self.spreadsheet_for(user_id=callback.from_user.id, chat_id=chat_id)
        if spreadsheet is None:
            return

        # Возврат разбирается до стадии: он ведёт в одно и то же место откуда
        # угодно, и спрашивать о текущей стадии тут нечего.
        if (callback.data or "").startswith(f"{_BACK_PREFIX}:"):
            await self._back_to_types(chat_id, state, draft, spreadsheet)
            return

        current = await self.aiogram.get_state(state)
        if current == States.CHECK_TYPES.state:
            await self._to_categories(chat_id, state, draft, spreadsheet)
        elif current == States.CHECK_CATEGORIES.state:
            await self._commit(chat_id, state, draft, spreadsheet)

    # --- Очередь ---------------------------------------------------------

    async def show_next(
        self,
        *,
        chat_id: int,
        state: FSMContext,
        spreadsheet: Spreadsheet,
    ) -> None:
        """Показывает старейший неразобранный чек, не попавший в пропущенные.

        Публичный метод: им же пользуются `/check_skip` и `/check_del`, которым
        после своей работы надо показать следующий чек.
        """
        skipped = await self._skipped(state)
        saved = await self._saved_count(state)

        checks = await self.api.checks.list_unprocessed(spreadsheet.id)
        pending = [check for check in checks if check.id not in skipped]
        if not pending:
            text = (
                t("text.check_queue_empty")
                if not saved and not skipped
                else CheckFormatter.finished(saved=saved, skipped=len(skipped))
            )
            # Ветка кончилась: гасим клавиатуру последнего блока вместе со
            # снятием состояния, иначе «Отмена» и «Удалить» остались бы живыми
            # там, где отменять и удалять уже нечего.
            await self.finish(chat_id=chat_id, state=state)
            await self.aiogram.send_message(chat_id, text)
            # И сразу меню: разбор кончается там же, откуда начался кнопкой, и
            # оставлять пользователя с итогом без единого действия незачем.
            await self.menu().show(chat_id=chat_id)
            return

        await self._start_check(
            pending[0],
            chat_id=chat_id,
            state=state,
            spreadsheet=spreadsheet,
            left=len(pending) - 1,
        )

    async def _start_check(
        self,
        check: Check,
        *,
        chat_id: int,
        state: FSMContext,
        spreadsheet: Spreadsheet,
        left: int,
    ) -> None:
        """Готовит первую стадию: шапка, кэш, подсказки модели."""
        try:
            receipt = ReceiptExtractor.extract(check)
        except ReceiptError as error:
            # Чек остаётся в очереди: его надо либо убрать, либо отложить, и
            # обе кнопки живут только внутри состояния разбора. Текст отказа —
            # от разбора, а не общий: он называет причину («это возврат»,
            # «сумма не сошлась»), и подменять его общей формулировкой значило
            # бы отнять единственное объяснение.
            broken = CheckDraft(check_id=check.id)
            await self._save_draft(state, broken)
            await self.aiogram.set_state(state, States.CHECK_TYPES)
            await self.ask(
                chat_id=chat_id,
                state=state,
                text=error.message,
                rows=self.stage_rows(broken, stage=None),
            )
            return

        draft = CheckDraft(
            check_id=check.id,
            retail_place=receipt.retail_place,
            purchased_at=(
                receipt.purchased_at.isoformat(timespec="minutes") if receipt.purchased_at else ""
            ),
            total=receipt.total,
            currency=receipt.currency,
            items=[DraftItem(name=item.name, amount=item.amount) for item in receipt.items],
        )

        cached = {
            record.product_name: record.product_type.strip().lower()
            for record in await self.api.checks.cashed_records(spreadsheet.id)
        }
        for item in draft.items:
            item.cached_type = cached.get(item.name)
            item.product_type = item.cached_type

        categories = await self.api.catalog.categories(spreadsheet.id)
        suggested = await self._suggest_types(
            draft,
            categories,
            chat_id=chat_id,
            state=state,
            spreadsheet_id=spreadsheet.id,
        )
        if not suggested:
            return

        await self._save_draft(state, draft)
        await self.aiogram.set_state(state, States.CHECK_TYPES)
        await self.ask(
            chat_id=chat_id,
            state=state,
            text=CheckFormatter.header(draft, left=left),
        )
        await self._show_types(chat_id, state, draft, categories)

    async def _suggest_types(
        self,
        draft: CheckDraft,
        categories: list[Category],
        *,
        chat_id: int,
        state: FSMContext,
        spreadsheet_id: int,
    ) -> bool:
        """Спрашивает модель о товарах, которых нет в кэше.

        `False` означает «дальше идти нельзя»: модель недоступна, диалог
        свёрнут, чек остался неразобранным и вернётся следующей сессией.
        """
        unknown = draft.untyped()
        if not unknown:
            return True

        known_types = sorted(_product_types(categories))
        try:
            answer, usage = await self.ai.suggest_types(
                [draft.items[number - 1].name for number in unknown],
                known_types,
                language=current_language(),
            )
        except AiError as error:
            logger.warning("Модель не подсказала типы: %s", error)
            await self.finish(chat_id=chat_id, state=state)
            await self.aiogram.send_message(chat_id, t("text.check_ai_unavailable"))
            return False

        await self._report_usage(
            usage,
            spreadsheet_id=spreadsheet_id,
            operation=LlmOperation.SUGGEST_PRODUCT_TYPES,
            check_id=draft.check_id,
        )

        for position, number in enumerate(unknown, 1):
            suggested = answer.get(position)
            if suggested:
                draft.items[number - 1].product_type = suggested[
                    : constants.PRODUCT_TYPE_MAX_LENGTH
                ]
        return True

    async def _report_usage(
        self,
        usage: LlmUsage | None,
        *,
        spreadsheet_id: int,
        operation: LlmOperation,
        check_id: int,
    ) -> None:
        """Записывает, во что обошёлся вызов модели.

        Ошибка учёта глушится логом: деньги уже потрачены, а разбор чека —
        то, ради чего пользователь здесь, и ронять его из-за не записанной
        строки статистики нельзя.

        Пустой замер означает, что провайдер не прислал `usage`: учитывать
        нечего.
        """
        if usage is None:
            logger.warning("Провайдер не прислал usage для операции %s", operation)
            return
        try:
            await self.api.llm_usages.record(
                spreadsheet_id,
                usage=usage,
                operation=operation,
                entity_kind=LlmEntityKind.CHECK,
                entity_id=check_id,
            )
        except ApiError as error:
            logger.warning("Замер обращения к модели не записан: %s", error)

    # --- Стадия 1: типы --------------------------------------------------

    async def _show_types(
        self,
        chat_id: int,
        state: FSMContext,
        draft: CheckDraft,
        categories: list[Category],
    ) -> None:
        """Печатает список «товар → тип» и клавиатуру стадии.

        Справочник нужен не для подбора, а для показа: тип, которого нет ни у
        одной категории, выделяется — он будет заведён при записи чека.

        Блок из двух сообщений, клавиатура — у нижнего: список бывает длинным,
        и кнопки, приклеенные к его началу, уехали бы за край экрана.
        """
        await self.ask(
            chat_id=chat_id,
            state=state,
            text=CheckFormatter.types(draft, _product_types(categories)),
            parse_mode=_HTML,
        )
        await self.ask(
            chat_id=chat_id,
            state=state,
            text=t("text.check_ask_types"),
            rows=self.stage_rows(draft, stage=_STAGE_TYPES),
        )

    async def _show_broken(self, chat_id: int, state: FSMContext, draft: CheckDraft) -> None:
        """Повторяет отказ разбора вместе с кнопками судьбы чека.

        Отдельно от `_show_types`: у неразобранного чека нет ни списка позиций,
        ни стадии, к которой вела бы кнопка «Готово», — только выбор, отложить
        его или удалить.
        """
        await self.ask(
            chat_id=chat_id,
            state=state,
            text=t("text.check_broken"),
            rows=self.stage_rows(draft, stage=None),
        )

    async def _edit_types(self, message: Message, state: FSMContext) -> None:
        """Применяет правки типов и печатает список заново."""
        chat_id = message.chat.id
        draft = await self._require_draft(message, state)
        if draft is None:
            return
        if not draft.items:
            await self._show_broken(chat_id, state, draft)
            return

        text = self.text_of(message)
        try:
            edits = CheckParser.parse(
                text,
                count=len(draft.items),
                max_value_length=constants.PRODUCT_TYPE_MAX_LENGTH,
            )
        except ParseError as error:
            await self.ask(
                chat_id=chat_id,
                state=state,
                text=error.message,
                rows=self.stage_rows(draft, stage=_STAGE_TYPES),
            )
            return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        for edit in edits:
            if edit.delete:
                _toggle_deleted(draft, edit.numbers)
                continue
            for number in edit.numbers:
                item = draft.item(number)
                if item is not None:
                    item.product_type = edit.value.strip().lower()

        await self._save_draft(state, draft)
        await self._show_types(
            chat_id,
            state,
            draft,
            await self.api.catalog.categories(spreadsheet.id),
        )

    # --- Стадия 2: категории ---------------------------------------------

    async def _to_categories(
        self,
        chat_id: int,
        state: FSMContext,
        draft: CheckDraft,
        spreadsheet: Spreadsheet,
    ) -> None:
        """Раскладывает позиции по категориям и переходит ко второй стадии.

        Раскладываются не все позиции, а только те, чья категория ещё не
        выведена из нынешнего типа. Сюда приходят дважды — второй раз после
        «Вернуться к типам», — и пересчёт целиком затирал бы ручные правки
        категорий и слал бы модели весь чек заново ради одного изменённого
        типа.

        Удалённые позиции раскладываются наравне со всеми: вернуть позицию
        можно в любой момент, и она обязана вернуться с категорией.
        """
        if not draft.items:
            await self._show_broken(chat_id, state, draft)
            return

        categories = await self.api.catalog.categories(spreadsheet.id)
        by_type = {
            product_type: category
            for category in categories
            for product_type in category.product_types
        }
        stale = [
            item
            for item in draft.items
            if item.category_id is None or item.category_for_type != item.product_type
        ]
        unknown_types = [
            product_type
            for product_type in dict.fromkeys(item.product_type for item in stale)
            if product_type and product_type not in by_type
        ]

        default = _default_expense(categories)
        suggested: dict[str, str] = {}
        if unknown_types:
            try:
                answer, usage = await self.ai.suggest_categories(
                    unknown_types,
                    [category.title for category in categories],
                    default_category=default.title if default is not None else None,
                )
            except AiError as error:
                logger.warning("Модель не подсказала категории: %s", error)
                await self.finish(chat_id=chat_id, state=state)
                await self.aiogram.send_message(chat_id, t("text.check_ai_unavailable"))
                return

            await self._report_usage(
                usage,
                spreadsheet_id=spreadsheet.id,
                operation=LlmOperation.SUGGEST_CATEGORIES,
                check_id=draft.check_id,
            )

            for position, product_type in enumerate(unknown_types, 1):
                title = answer.get(position)
                if title:
                    suggested[product_type] = title

        for item in stale:
            resolved = self._category_for(item, by_type, suggested, categories)
            category = resolved or default
            item.category_id = category.id if category is not None else None
            item.category_title = category.title if category is not None else None
            # Подтверждена только категория, выведенная из закреплённого типа.
            # Подсказанную моделью и корзину пользователь должен увидеть в
            # нижнем блоке списка и проверить глазами.
            item.category_confirmed = (
                resolved is not None and item.product_type in by_type
            )
            item.category_for_type = item.product_type

        await self._save_draft(state, draft)
        await self.aiogram.set_state(state, States.CHECK_CATEGORIES)
        await self._show_categories(chat_id, state, draft)

    async def _back_to_types(
        self,
        chat_id: int,
        state: FSMContext,
        draft: CheckDraft,
        spreadsheet: Spreadsheet,
    ) -> None:
        """Возвращает на стадию типов, ничего не пересчитывая.

        Черновик не трогается вовсе: и типы, и уже разложенные категории —
        работа пользователя, и возврат «посмотреть и поправить одну строку» не
        повод её отменять. Что делать с изменившимся типом, решит `_to_categories`
        на обратном пути.

        Модель не зовётся: типы у всех позиций уже есть — либо из кэша, либо из
        первого вызова, либо из правки.
        """
        if not draft.items:
            await self._show_broken(chat_id, state, draft)
            return
        await self.aiogram.set_state(state, States.CHECK_TYPES)
        await self._show_types(
            chat_id,
            state,
            draft,
            await self.api.catalog.categories(spreadsheet.id),
        )

    @staticmethod
    def _category_for(
        item: DraftItem,
        by_type: dict[str, Category],
        suggested: dict[str, str],
        categories: list[Category],
    ) -> Category | None:
        """Категория позиции: по закреплённому типу, затем по подсказке модели.

        Закреплённый тип сильнее подсказки и не перепроверяется моделью вовсе:
        `UNIQUE (spreadsheet_id, product_type)` делает это соответствие
        однозначным, и спрашивать о нём значило бы позволить модели его менять.
        """
        if not item.product_type:
            return None
        known = by_type.get(item.product_type)
        if known is not None:
            return known
        title = suggested.get(item.product_type)
        return _by_title(categories, title) if title else None

    async def _show_categories(
        self,
        chat_id: int,
        state: FSMContext,
        draft: CheckDraft,
    ) -> None:
        """Печатает список «товар → категория» и клавиатуру стадии."""
        await self.ask(
            chat_id=chat_id,
            state=state,
            text=CheckFormatter.categories(draft),
            parse_mode=_HTML,
        )
        await self.ask(
            chat_id=chat_id,
            state=state,
            text=t("text.check_ask_categories"),
            rows=self.stage_rows(draft, stage=_STAGE_CATEGORIES),
        )

    async def _edit_categories(self, message: Message, state: FSMContext) -> None:
        """Применяет правки категорий: значение ищется по псевдониму."""
        chat_id = message.chat.id
        draft = await self._require_draft(message, state)
        if draft is None:
            return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return
        categories = await self.api.catalog.categories(spreadsheet.id)

        try:
            edits = CheckParser.parse(self.text_of(message), count=len(draft.items))
        except ParseError as error:
            await self.ask(
                chat_id=chat_id,
                state=state,
                text=error.message,
                rows=self.stage_rows(draft, stage=_STAGE_CATEGORIES),
            )
            return

        # Сперва разбираются все правки и только потом применяются. Иначе
        # неизвестный псевдоним в последней строке оставлял бы применёнными
        # первые — и не сохранёнными: `_save_draft` стоит за `return`. С
        # появлением «!N» это значило бы «удаление молча не сработало».
        resolved: list[tuple[ParsedCheckEdit, Category | None]] = []
        for edit in edits:
            if edit.delete:
                resolved.append((edit, None))
                continue
            category = AssociationMatcher.category(edit.value, categories)
            if category is None:
                hint = AssociationMatcher.hint([item.title for item in categories])
                await self.ask(
                    chat_id=chat_id,
                    state=state,
                    text=t("parse.category_not_found", value=edit.value, hint=hint),
                    rows=self.stage_rows(draft, stage=_STAGE_CATEGORIES),
                )
                return
            resolved.append((edit, category))

        for edit, category in resolved:
            if category is None:
                _toggle_deleted(draft, edit.numbers)
                continue
            for number in edit.numbers:
                item = draft.item(number)
                if item is not None:
                    item.category_id = category.id
                    item.category_title = category.title
                    item.category_confirmed = True
                    # Ручной выбор привязывается к нынешнему типу: без этого
                    # поход «Вернуться к типам» и обратно пересчитал бы его
                    # заново и затёр.
                    item.category_for_type = item.product_type

        await self._save_draft(state, draft)
        await self._show_categories(chat_id, state, draft)

    # --- Запись чека -----------------------------------------------------

    async def _commit(
        self,
        chat_id: int,
        state: FSMContext,
        draft: CheckDraft,
        spreadsheet: Spreadsheet,
    ) -> None:
        """Записывает разобранный чек и переходит к следующему.

        Отдельной стадии подтверждения нет: «Готово» на категориях и есть
        подтверждение. Прежде здесь спрашивался счёт, и запись была побочным
        следствием ответа на этот вопрос; со счётом ушёл и вопрос, а проверка
        «у всех позиций есть категория» осталась — она про сам чек, а не про
        то, о чём спрашивали.

        Валюта не спрашивается и здесь: её знает формат чека, и api проставляет
        операциям ровно ту же — см. `telegram_bot.checks.models`.
        """
        # Чек, из которого убрали всё, не записывается и не удаляется: записать
        # нечего, а удалить — значило бы освободить ключ среди живых строк и
        # разрешить тому же QR отсканироваться заново. Чек остаётся в очереди,
        # и кнопка «Удалить» рядом — на случай, если убрать его и правда хотели.
        if not draft.alive():
            await self.ask(
                chat_id=chat_id,
                state=state,
                text=t("text.check_all_deleted"),
                rows=self.stage_rows(draft, stage=_STAGE_CATEGORIES),
            )
            return

        # Категория удалённой позиции не проверяется: операции по ней не будет,
        # и требовать её значило бы просить разложить то, что не записывается.
        if any(item.category_id is None for item in draft.alive()):
            await self.ask(
                chat_id=chat_id,
                state=state,
                text=t("text.check_no_category"),
                rows=self.stage_rows(draft, stage=_STAGE_CATEGORIES),
            )
            return

        categories = await self.api.catalog.categories(spreadsheet.id)
        default = _default_expense(categories)
        default_id = default.id if default is not None else None

        try:
            records = await self.api.checks.commit(
                spreadsheet.id,
                check_id=draft.check_id,
                items=self._commit_items(draft, default_id),
                new_product_types=self._new_product_types(draft, categories, default_id),
            )
        except ApiConflictError as error:
            if error.reason != TYPE_TAKEN_REASON:
                raise
            # Чек не записан. Возвращаем на стадию типов: чинить надо именно
            # тип, из-за которого отказали.
            await self.aiogram.set_state(state, States.CHECK_TYPES)
            await self.ask(
                chat_id=chat_id,
                state=state,
                text=ApiErrorPresenter.present(error),
            )
            await self._show_types(chat_id, state, draft, categories)
            return

        await self.aiogram.send_message(
            chat_id,
            CheckFormatter.saved(draft, count=len(records)),
        )
        await self._bump_saved(state)
        await self.show_next(chat_id=chat_id, state=state, spreadsheet=spreadsheet)

    @staticmethod
    def _commit_items(draft: CheckDraft, default_id: int | None) -> list[CommitItem]:
        """Позиции для записи.

        Позиция, осевшая в категории-корзине, едет **без типа**: корзина типов
        не получает никогда, и запоминать по ней «молоко → нечто» значило бы
        притянуть туда же следующие чеки.

        Удалённых позиций здесь нет вовсе: `alive()` — единственное место, где
        они отсекаются от записи. Кэш «товар → тип» api наполняет из этого же
        списка, так что удалённая позиция заодно ничему и не учит.

        Вызывается только после проверки «у всех позиций есть категория»,
        поэтому `category_id` здесь уже не пуст.
        """
        return [
            CommitItem(
                product_name=item.name,
                product_type=None if item.category_id == default_id else item.product_type,
                category_id=item.category_id,
                amount=item.amount,
            )
            for item in draft.alive()
            if item.category_id is not None
        ]

    @staticmethod
    def _new_product_types(
        draft: CheckDraft,
        categories: list[Category],
        default_id: int | None,
    ) -> list[NewProductType]:
        """Типы, которых у категории ещё нет, без повторов.

        Удалённая позиция типов не заводит: чек её не записывает, и закреплять
        за категорией тип ради строки, которой не будет, значило бы притянуть
        по нему следующие чеки.
        """
        owned = {
            (category.id, product_type)
            for category in categories
            for product_type in category.product_types
        }
        new: dict[tuple[int, str], NewProductType] = {}
        for item in draft.alive():
            if not item.product_type or item.category_id is None:
                continue
            key = (item.category_id, item.product_type)
            if item.category_id == default_id or key in owned:
                continue
            new[key] = NewProductType(
                category_id=item.category_id,
                product_type=item.product_type,
            )
        return list(new.values())

    # --- FSM -------------------------------------------------------------

    async def _draft(self, state: FSMContext) -> CheckDraft | None:
        """Черновик разбора из FSM-данных."""
        return CheckDraft.load(
            await self.aiogram.get_state_data(state, FsmDataKeys.CHECK_DRAFT)
        )

    async def _require_draft(self, message: Message, state: FSMContext) -> CheckDraft | None:
        """Черновик или `None` с уже отправленной подсказкой и снятым состоянием."""
        draft = await self._draft(state)
        if draft is None:
            await self.finish(chat_id=message.chat.id, state=state)
            await self.aiogram.answer_message(message, t("text.check_lost"))
        return draft

    async def _save_draft(self, state: FSMContext, draft: CheckDraft) -> None:
        """Кладёт черновик в FSM-данные."""
        await self.aiogram.set_state_data(state, FsmDataKeys.CHECK_DRAFT, draft.dump())

    async def _skipped(self, state: FSMContext) -> list[int]:
        """Чеки, пропущенные в этой сессии."""
        raw = await self.aiogram.get_state_data(state, FsmDataKeys.SKIPPED_CHECK_IDS, [])
        return [int(value) for value in raw] if isinstance(raw, list) else []

    async def add_skipped(self, state: FSMContext, check_id: int) -> None:
        """Запоминает пропущенный чек: он не должен вернуться в этой сессии."""
        skipped = await self._skipped(state)
        if check_id not in skipped:
            skipped.append(check_id)
        await self.aiogram.set_state_data(state, FsmDataKeys.SKIPPED_CHECK_IDS, skipped)

    async def _saved_count(self, state: FSMContext) -> int:
        """Сколько чеков записано в этой сессии."""
        raw = await self.aiogram.get_state_data(state, FsmDataKeys.SAVED_COUNT, 0)
        return int(raw) if isinstance(raw, int) else 0

    async def _bump_saved(self, state: FSMContext) -> None:
        """Увеличивает счётчик записанных чеков."""
        await self.aiogram.set_state_data(
            state,
            FsmDataKeys.SAVED_COUNT,
            await self._saved_count(state) + 1,
        )

    async def current_draft(self, state: FSMContext) -> CheckDraft | None:
        """Черновик текущего чека для кнопок «Отложить» и «Удалить»."""
        return await self._draft(state)

    async def show_stage(
        self,
        *,
        chat_id: int,
        state: FSMContext,
        draft: CheckDraft,
        spreadsheet: Spreadsheet,
    ) -> None:
        """Перерисовывает блок текущей стадии.

        Нужно отказу от удаления: подтверждение съело клавиатуру стадии, и
        ответ «нет» обязан вернуть пользователя ровно туда, откуда он ушёл, —
        иначе отказ от удаления оставлял бы чек без единой живой кнопки.
        """
        current = await self.aiogram.get_state(state)
        if current == States.CHECK_TYPES.state:
            if not draft.items:
                await self._show_broken(chat_id, state, draft)
                return
            categories = await self.api.catalog.categories(spreadsheet.id)
            await self._show_types(chat_id, state, draft, categories)
        elif current == States.CHECK_CATEGORIES.state:
            await self._show_categories(chat_id, state, draft)

    # --- Кнопки ----------------------------------------------------------

    @staticmethod
    def stage_rows(draft: CheckDraft, *, stage: str | None) -> list[tuple[tuple[str, str], ...]]:
        """Клавиатура блока: переход, судьба чека и выход.

        `stage` — метка стадии для кнопки «Готово»; `None` означает, что
        переходить некуда: у неразобранного чека следующего шага нет вовсе.

        «Отложить» и «Удалить» стоят рядом одним рядом и есть на каждом блоке
        ветки: заметить «этот чек лишний» можно на любой стадии, а не только на
        первой, и уводить за таким решением обратно в начало значило бы просить
        пройти разбор ещё раз, чтобы от него отказаться.

        `check_id` едет в каждой `callback_data`: кнопка живёт в переписке
        дольше своего чека, и без номера нажатая на прошлом блоке «Удалить»
        снесла бы чек, который разбирают сейчас.

        Кнопки судьбы чека собираются здесь, рядом с клавиатурой, хотя
        обслуживают их отдельные команды: те импортируют `check.py` ради очереди
        и черновика, и обратный импорт замкнул бы круг. Команд `/check_skip` и
        `/check_del` больше нет: они были осмысленны ровно внутри разбора, а
        набирать их приходилось посреди кнопочного диалога.
        """
        rows: list[tuple[tuple[str, str], ...]] = []
        if stage is not None:
            rows.append(((t("buttons.check.done"), f"{_DONE_PREFIX}:{stage}:{draft.check_id}"),))
            # «К типам» — только со второй стадии: с первой возвращаться некуда,
            # а у неразобранного чека нет и самих стадий. Своим рядом, а не
            # рядом с «Готово»: это движение в обратную сторону, и стоять
            # вплотную к кнопке, которая ведёт вперёд, ему незачем.
            if stage == _STAGE_CATEGORIES:
                rows.append(
                    ((t("buttons.check.back_to_types"), f"{_BACK_PREFIX}:{draft.check_id}"),)
                )
        rows.append(
            (
                (t("buttons.check.skip"), f"{CommandName.CHECK_SKIP}:{draft.check_id}"),
                (t("buttons.check.delete"), f"{CommandName.CHECK_DEL}:{draft.check_id}"),
            )
        )
        rows.append(cancel_row(BRANCH_CHECK))
        return rows

    @staticmethod
    def is_current(data: str | None, draft: CheckDraft) -> bool:
        """Относится ли нажатая кнопка к разбираемому сейчас чеку.

        Номер чека стоит последним во всех `callback_data` ветки, сколько бы
        частей в них ни было: у «Готово» это `check_done:стадия:id`, у
        подтверждения удаления — `check_del:yes:id`. Сверка по последней части
        поэтому одна на все кнопки и не забывается при добавлении новой.
        """
        parts = (data or "").split(":")
        return len(parts) >= 2 and parts[-1] == str(draft.check_id)


def _toggle_deleted(draft: CheckDraft, numbers: tuple[int, ...]) -> None:
    """Переключает «удалена» у перечисленных позиций.

    Переключатель, а не флаг: «!1» дважды — это «убрал» и «передумал», и
    отдельного синтаксиса для возврата нет намеренно. Тип и категория позиции
    при этом не трогаются — вернуться она обязана готовой.

    Один на обе стадии: заметить лишнюю позицию можно на любой из них, и
    удаление, работающее только на первой, отправляло бы за этим в начало.
    """
    for number in numbers:
        item = draft.item(number)
        if item is not None:
            item.deleted = not item.deleted


def _product_types(categories: list[Category]) -> set[str]:
    """Все типы товаров, закреплённые за категориями документа."""
    return {product_type for item in categories for product_type in item.product_types}


def _default_expense(categories: list[Category]) -> Category | None:
    """Корзина расходов: категория по умолчанию вида «расход».

    По флагу, а не по названию: название на языке пользователя и может быть
    переименовано в листе. Корзины может не оказаться вовсе — у таблицы, где её
    переименовали до появления флага, — и тогда позиция, которой не нашлось
    категории, так и останется без неё до правки пользователем.
    """
    return next(
        (item for item in categories if item.is_default and item.kind is CategoryKind.EXPENSE),
        None,
    )


def _by_title(categories: list[Category], title: str | None) -> Category | None:
    """Категория по названию без учёта регистра."""
    if not title:
        return None
    needle = title.strip().lower()
    return next((item for item in categories if item.title.strip().lower() == needle), None)
