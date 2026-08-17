"""Клиент модели: единственное место, где бот касается OpenAI.

Построен по образцу :mod:`telegram_bot.api_client.http`: вся работа с внешним
сервисом внутри, наружу — доменные модели и типизированные ошибки. Ни `openai`,
ни текстов промптов за пределами этого пакета нет.

Три вещи, которых не было в старой обёртке и без которых ветка чеков не
работала:

* **явный таймаут** — прежний клиент полагался на умолчание библиотеки, а
  зависший вызов останавливал разбор насовсем;
* **валидация ответа схемой** — форма ответа проверяется, а не предполагается;
* **типизированные ошибки** — отказ модели становится сообщением пользователю,
  а не исключением мимо обработчика.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from openai import APIError, AsyncOpenAI, OpenAIError
from pydantic import ValidationError

from telegram_bot import constants
from telegram_bot.ai.errors import AiResponseError, AiUnavailableError
from telegram_bot.ai.models import CategorySuggestions, TypeSuggestions
from telegram_bot.logging import get_logger
from telegram_bot.resources.prompts import (
    CATEGORIES_SYSTEM_PROMPT,
    CATEGORIES_USER_PROMPT,
    TYPES_SYSTEM_PROMPT,
    TYPES_USER_PROMPT,
)

logger = get_logger(__name__)

#: Ограда markdown-блока: часть моделей заворачивает в неё JSON, несмотря на
#: `response_format`.
_FENCE = "```"


class AiClient:
    """Подсказывает типы товаров и категории для типов.

    Оба вызова устроены одинаково: боту нужен ответ по нумерованному списку, и
    номер в ответе — это позиция во входном списке. Модель не знает ни про
    идентификаторы категорий, ни про кэш: сопоставлением занимается бот, у
    которого есть справочники.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        model: str,
        timeout: float,
        temperature: float,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._model = model
        self._temperature = temperature

    async def aclose(self) -> None:
        """Закрывает соединение с провайдером."""
        await self._client.close()

    async def suggest_types(
        self,
        products: Sequence[str],
        known_types: Sequence[str],
    ) -> dict[int, str]:
        """Тип для каждого товара: номер позиции → тип.

        Номера — позиции во входном списке, начиная с единицы. Позиции, о
        которых модель промолчала, в ответе просто отсутствуют: разбор покажет
        их пустыми и даст поправить руками, а не откажется целиком.
        """
        raw = await self._invoke(
            TYPES_SYSTEM_PROMPT,
            TYPES_USER_PROMPT.format(
                products=_numbered(products),
                types=_listed(known_types),
            ),
        )
        answer = _validate(raw, TypeSuggestions)
        return {item.id: item.type.strip().lower() for item in answer.items if item.id > 0}

    async def suggest_categories(
        self,
        product_types: Sequence[str],
        categories: Sequence[str],
    ) -> dict[int, str]:
        """Категория для каждого типа товара: номер типа → название категории.

        Спрашивается именно про типы, а не про позиции: категорию определяет
        тип, и два одинаковых типа в одном чеке не должны разъехаться по разным
        категориям из-за того, что модель ответила о них по отдельности.
        """
        raw = await self._invoke(
            CATEGORIES_SYSTEM_PROMPT.format(
                default_category=constants.DEFAULT_EXPENSE_CATEGORY
            ),
            CATEGORIES_USER_PROMPT.format(
                product_types=_numbered(product_types),
                categories=_listed(categories),
            ),
        )
        answer = _validate(raw, CategorySuggestions)
        return {item.id: item.category.strip() for item in answer.items if item.id > 0}

    async def _invoke(self, system_prompt: str, user_prompt: str) -> str:
        """Один вызов модели; возвращает содержимое ответа как текст."""
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                n=1,
                response_format={"type": "json_object"},
                max_tokens=constants.AI_MAX_TOKENS,
            )
        except APIError as error:
            logger.warning("Модель ответила ошибкой: %s", error)
            raise AiUnavailableError(str(error)) from error
        except OpenAIError as error:
            # Сюда попадают таймаут и обрыв соединения: для пользователя они
            # неотличимы от «сервис недоступен» и лечатся одинаково — повтором.
            logger.warning("Модель недоступна: %s", error)
            raise AiUnavailableError(str(error)) from error

        choices = response.choices
        content = choices[0].message.content if choices else None
        if not content:
            raise AiResponseError("Модель вернула пустой ответ")
        return content


def _validate[T: (TypeSuggestions, CategorySuggestions)](raw: str, schema: type[T]) -> T:
    """Разбирает ответ модели по схеме.

    Обе неудачи — не JSON и JSON не той формы — становятся `AiResponseError`.
    Разница между ними для пользователя нулевая, а разбирать ответ «на глазок»
    и было той ошибкой, из-за которой ветка чеков не работала совсем.
    """
    try:
        return schema.model_validate(_json_payload(raw))
    except ValidationError as error:
        raise AiResponseError("Ответ модели не той формы") from error


def _json_payload(raw: str) -> Any:
    """Достаёт объект JSON из ответа модели.

    `response_format={"type": "json_object"}` — пожелание, а не гарантия.
    Часть провайдеров исполняет его буквально, часть передаёт как подсказку в
    промпт: Claude через OpenRouter отвечает валидным JSON, но заворачивает его
    в markdown-забор ```` ```json … ``` ````, и `json.loads` падает на первом же
    символе. Модель при этом ни в чём не виновата и менять её незачем.

    Поэтому три попытки по возрастанию грубости: как есть, без забора, и
    вырезав самый внешний объект. Схема проверяется после всех трёх — «на
    глазок» ответ по-прежнему не разбирается, послабление касается только того,
    где в тексте начинается JSON.
    """
    text = raw.strip()
    for candidate in (text, _without_fence(text), _outermost_object(text)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    raise AiResponseError("Ответ модели не является JSON")


def _without_fence(text: str) -> str:
    """Содержимое markdown-забора или пустая строка, если забора нет."""
    if not text.startswith(_FENCE):
        return ""
    body = text[len(_FENCE) :]
    # Первая строка забора может нести язык: ```json.
    newline = body.find("\n")
    if newline != -1:
        body = body[newline + 1 :]
    closing = body.rfind(_FENCE)
    return (body[:closing] if closing != -1 else body).strip()


def _outermost_object(text: str) -> str:
    """Кусок от первой `{` до последней `}` или пустая строка.

    Последняя попытка — на случай пояснения вокруг JSON («Вот результат: …»).
    Если внутри окажется что-то кроме одного объекта, `json.loads` честно
    откажется, и ответ станет `AiResponseError`.
    """
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else ""


def _numbered(values: Sequence[str]) -> str:
    """Нумерованный список для промпта: номер и есть идентификатор в ответе."""
    return "\n".join(f"{index}. {value}" for index, value in enumerate(values, start=1))


def _listed(values: Sequence[str]) -> str:
    """Простой перечень значений по строке на каждое."""
    return "\n".join(values)
