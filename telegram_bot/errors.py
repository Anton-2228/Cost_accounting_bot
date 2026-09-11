"""Перевод ошибок api в текст для пользователя.

Одно место на весь бот. Api отдаёт машинный `code` и уточнение в `details`
(`resource` для 404, `reason` для 409 и 422) — по ним и подбирается ключ
каталога. Поле `message` пользователю не показывается никогда: оно на одном
языке для всех и написано для журнала, а не для человека.
"""

from __future__ import annotations

from datetime import date

from telegram_bot.api_client.errors import (
    ApiConflictError,
    ApiError,
    ApiNotFoundError,
    ApiUnavailableError,
    ApiValidationError,
)
from telegram_bot.i18n import LocaleFormat, t

#: Ресурсы 404, у которых есть своя формулировка: `errors.not_found.<ресурс>`.
#: Остальные получают общую — `errors.not_found.default`.
NOT_FOUND_RESOURCES = frozenset(
    {"spreadsheet", "user", "category", "record", "period", "access", "check", "notification"}
)

#: Признак 409 → ключ текста. Словарём, а не шаблоном ключа: состояние «таблица
#: ещё создаётся» печатает и `BaseCommand`, не дожидаясь отказа api, и двух
#: формулировок одного состояния быть не должно.
CONFLICT_KEYS: dict[str, str] = {
    # Команды `/table` не существует: ссылку выдаёт кнопка экрана `/menu`.
    "spreadsheet_exists": "errors.conflict.spreadsheet_exists",
    "spreadsheet_not_ready": "errors.table_creating",
    "access_exists": "errors.conflict.access_exists",
    "google_id_already_set": "errors.conflict.google_id_already_set",
    "check_already_saved": "errors.conflict.check_already_saved",
    "check_already_processed": "errors.conflict.check_already_processed",
}

#: Признаки 422 со своей формулировкой: `errors.validation.<признак>`.
#: Остальные — и нарушение схемы запроса (`validation_error`), у которого
#: признака нет вовсе, — получают общую, `errors.validation.generic`.
VALIDATION_REASONS = frozenset(
    {"period_closed", "amount_not_positive", "filters_incompatible", "period_target_mismatch"}
)

#: Признак конфликта, текст которого собирается из данных документа: назвать
#: чужую категорию необходимо, иначе отказ выглядит беспричинным — пользователь
#: не знает, куда «молочка» уже отнесена, и повторяет ту же правку.
TYPE_TAKEN_REASON = "product_type_taken"


class ApiErrorPresenter:
    """Подбирает текст ответа по типу ошибки api."""

    @classmethod
    def present(cls, error: ApiError) -> str:
        """Текст для пользователя на языке обращения."""
        if isinstance(error, ApiUnavailableError):
            return t("errors.unavailable")
        if isinstance(error, ApiNotFoundError):
            if error.resource in NOT_FOUND_RESOURCES:
                return t(f"errors.not_found.{error.resource}")
            return t("errors.not_found.default")
        if isinstance(error, ApiConflictError):
            if error.reason == TYPE_TAKEN_REASON:
                return cls._type_taken(error)
            return t(CONFLICT_KEYS.get(error.reason, "errors.conflict.default"))
        if isinstance(error, ApiValidationError):
            return cls._validation(error)
        return t("errors.unexpected")

    @staticmethod
    def _validation(error: ApiValidationError) -> str:
        """Текст отказа 422 по признаку правила.

        Дата закрытого периода приходит в ISO и печатается по правилам языка:
        «с 2026-07-01» по-русски выглядело бы как выписка из базы, а не ответ.
        Испорченная дата не роняет ответ — отказ всё равно будет понятен и без
        неё, общей формулировкой.
        """
        reason = error.reason
        if reason not in VALIDATION_REASONS:
            return t("errors.validation.generic")
        if reason == "period_closed":
            try:
                start = date.fromisoformat(str(error.details.get("start_date", "")))
            except ValueError:
                return t("errors.validation.generic")
            return t("errors.validation.period_closed", start_date=LocaleFormat.day(start))
        return t(f"errors.validation.{reason}")

    @staticmethod
    def _type_taken(error: ApiConflictError) -> str:
        """Текст отказа «тип уже закреплён за другой категорией».

        Собирается из `details`, потому что оба слова в нём — данные документа:
        какой именно тип и за какой категорией он числится. Категории в ответе
        может не быть — так бывает, когда конфликт поймала гонка с импортом
        листа, и назвать её тогда нечем.

        Четыре целых формулировки, а не подлежащее, приставленное к сказуемому:
        в других языках «этот тип» и «тип «X»» по-разному согласуются с
        остальной фразой, и склейка из кусков развалилась бы при переводе.
        """
        product_type = str(error.details.get("product_type", ""))
        category = str(error.details.get("category", ""))
        if product_type and category:
            return t(
                "errors.type_taken.named_with_category",
                product_type=product_type,
                category=category,
            )
        if product_type:
            return t("errors.type_taken.named", product_type=product_type)
        if category:
            return t("errors.type_taken.unnamed_with_category", category=category)
        return t("errors.type_taken.unnamed")
