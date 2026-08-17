"""Тесты разбора ответа модели.

Сети здесь нет: проверяется только то, как из текста ответа достаётся объект
JSON и как он ложится на схему. Именно эта пара и разваливалась в старой
версии — форму ответа никто не проверял, и `ValueError` уходил мимо
обработчика.
"""

from __future__ import annotations

import pytest

from telegram_bot.ai import AiResponseError, CategorySuggestions, TypeSuggestions
from telegram_bot.ai.client import _validate

_PLAIN = '{"items": [{"id": 1, "type": "молочка"}]}'


def test_plain_json_is_accepted() -> None:
    """Ответ ровно по договорённости разбирается как есть."""
    answer = _validate(_PLAIN, TypeSuggestions)
    assert [(item.id, item.type) for item in answer.items] == [(1, "молочка")]


@pytest.mark.parametrize(
    "raw",
    [
        f"```json\n{_PLAIN}\n```",
        f"```\n{_PLAIN}\n```",
        f"  ```json\n{_PLAIN}\n```  ",
        f"Вот результат:\n{_PLAIN}",
    ],
)
def test_json_in_wrapping_is_found(raw: str) -> None:
    """JSON достаётся из markdown-забора и из пояснения вокруг.

    `response_format: json_object` — пожелание, а не гарантия: Claude через
    OpenRouter отвечает валидным JSON, но заворачивает его в ```` ```json ````.
    Ровно на этом `/check` отвечал «Подсказки недоступны» на каждый чек.
    """
    answer = _validate(raw, TypeSuggestions)
    assert [item.type for item in answer.items] == ["молочка"]


def test_categories_answer_uses_its_own_schema() -> None:
    """Ответ второй стадии разбирается своей схемой, а не общей."""
    raw = '```json\n{"items": [{"id": 2, "category": "Еда"}]}\n```'
    answer = _validate(raw, CategorySuggestions)
    assert [(item.id, item.category) for item in answer.items] == [(2, "Еда")]


@pytest.mark.parametrize("raw", ["", "совсем не json", "```json\nтоже не json\n```", "{"])
def test_garbage_is_named_error(raw: str) -> None:
    """Неразбираемый ответ становится ошибкой с именем, а не `ValueError`."""
    with pytest.raises(AiResponseError):
        _validate(raw, TypeSuggestions)


def test_wrong_shape_is_named_error() -> None:
    """Валидный JSON не той формы тоже отвергается схемой.

    Послабление касается только того, где в тексте начинается JSON. Разбирать
    ответ «на глазок» по-прежнему нельзя: старый код обходил его словарём и
    падал на первом же чеке с незнакомым товаром.
    """
    with pytest.raises(AiResponseError):
        _validate('{"items": [{"id": "не число", "type": "молочка"}]}', TypeSuggestions)
