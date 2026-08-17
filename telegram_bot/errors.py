"""Перевод ошибок api в русский текст для пользователя.

Одно место на весь бот. Api отдаёт машинный `code` и уточнение в `details`
(`resource` для 404, `reason` для 409) — по ним и подбирается формулировка.

Исключение — 422: там `message` уже по-русски и собран из данных документа
(«Период с 2026-07-01 закрыт»), выразить его кодом нечем, и он печатается как
есть. То же самое делают уведомления фоновой работы.
"""

from __future__ import annotations

from telegram_bot.api_client.errors import (
    ApiConflictError,
    ApiError,
    ApiNotFoundError,
    ApiUnavailableError,
    ApiValidationError,
)

#: Ответ на 404 по тому, чего именно не нашли.
_NOT_FOUND: dict[str, str] = {
    "spreadsheet": "Сначала создайте таблицу: /start",
    "user": "Сначала создайте таблицу: /start",
    "category": "Такой категории нет, либо она выключена",
    "source": "Такого счёта нет, либо он выключен",
    "record": "Операции с таким id нет",
    "transfer": "Перевода с таким id нет",
    "period": "За этот период ещё ничего не записано",
    "access": "Такой доступ не выдавался",
    "check": "Этого чека уже нет в очереди",
    "notification": "Этого сообщения уже нет",
}

#: Ответ на 409 по машинному признаку конфликта.
_CONFLICT: dict[str, str] = {
    "spreadsheet_exists": "У вас уже есть таблица. Посмотреть: /table",
    "spreadsheet_not_ready": (
        "Таблица ещё создаётся — пришлю ссылку, как только будет готова"
    ),
    "access_exists": "Этой почте доступ уже открыт",
    "google_id_already_set": "К этой таблице уже привязан документ",
    "check_already_saved": "Этот чек уже добавлен",
    "check_already_processed": "Этот чек уже разобран — его операции в реестре",
}

#: Признак конфликта, текст которого собирается из данных документа: назвать
#: чужую категорию необходимо, иначе отказ выглядит беспричинным — пользователь
#: не знает, куда «молочка» уже отнесена, и повторяет ту же правку.
TYPE_TAKEN_REASON = "product_type_taken"

UNAVAILABLE_MESSAGE = "Сервис данных недоступен, попробуйте позже"
UNEXPECTED_MESSAGE = "Что-то пошло не так. Попробуйте ещё раз"
NO_TABLE_MESSAGE = _NOT_FOUND["spreadsheet"]


class ApiErrorPresenter:
    """Подбирает текст ответа по типу ошибки api."""

    @classmethod
    def present(cls, error: ApiError) -> str:
        """Русский текст для пользователя."""
        if isinstance(error, ApiUnavailableError):
            return UNAVAILABLE_MESSAGE
        if isinstance(error, ApiNotFoundError):
            return _NOT_FOUND.get(error.resource, "Не нашёл того, о чём вы просите")
        if isinstance(error, ApiConflictError):
            if error.reason == TYPE_TAKEN_REASON:
                return cls._type_taken(error)
            return _CONFLICT.get(error.reason, "Так сейчас нельзя")
        if isinstance(error, ApiValidationError):
            # Текст приходит готовым и объясняет причину точнее, чем любая
            # формулировка по коду: он собран из данных самого документа.
            return error.message or "Так нельзя"
        return UNEXPECTED_MESSAGE

    @staticmethod
    def _type_taken(error: ApiConflictError) -> str:
        """Текст отказа «тип уже закреплён за другой категорией».

        Собирается из `details`, потому что оба слова в нём — данные документа:
        какой именно тип и за какой категорией он числится. Категории в ответе
        может не быть — так бывает, когда конфликт поймала гонка с импортом
        листа, и назвать её тогда нечем.
        """
        product_type = str(error.details.get("product_type", ""))
        category = str(error.details.get("category", ""))
        subject = f"Тип «{product_type}»" if product_type else "Этот тип"
        if category:
            return (
                f"{subject} уже закреплён за категорией «{category}».\n"
                "Выберите её же или другой тип"
            )
        return f"{subject} уже закреплён за другой категорией. Выберите другой тип"
