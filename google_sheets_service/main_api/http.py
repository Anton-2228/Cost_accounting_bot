"""Транспорт к основному api: единственный владелец `httpx.AsyncClient`.

Доменные клиенты получают его в конструктор и не знают ни про конверты ответов,
ни про коды статусов. Соединение одно на все домены.
"""

from __future__ import annotations

from typing import Any

import httpx

from google_sheets_service.exceptions import ApiError


class ApiHttpClient:
    """Тонкий транспорт поверх httpx: разворачивает конверты, переводит ошибки.

    Api отвечает `{"data": ...}` на одиночный ресурс и `{"items": [...]}` на
    список — клиент возвращает уже содержимое, а не конверт. Любой неожиданный
    статус превращается в :class:`ApiError` с телом ответа: там лежит `code`, по
    которому вызывающий отличает «нет такого документа» от «Google-таблица ещё
    не создана».
    """

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.aclose()

    async def get_data(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> dict[str, Any] | None:
        """GET одиночного ресурса; `None` на 404, если это разрешено."""
        response = await self._client.get(path, params=params)
        if response.status_code == httpx.codes.NOT_FOUND and allow_404:
            return None
        self._raise_for_status(response, expected=httpx.codes.OK)
        data = response.json()["data"]
        return dict(data) if data is not None else None

    async def get_items(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET списка.

        Пагинации здесь нет намеренно: каждая выборка api ограничена одним
        документом и одним учётным месяцем и вырасти не может.
        """
        response = await self._client.get(path, params=params)
        self._raise_for_status(response, expected=httpx.codes.OK)
        return list(response.json()["items"])

    async def post_data(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: int = httpx.codes.OK,
    ) -> dict[str, Any]:
        """POST, возвращающий одиночный ресурс."""
        response = await self._client.post(path, json=body)
        self._raise_for_status(response, expected=expected)
        return dict(response.json()["data"])

    async def post_items(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: int = httpx.codes.OK,
    ) -> list[dict[str, Any]]:
        """POST, возвращающий список."""
        response = await self._client.post(path, json=body)
        self._raise_for_status(response, expected=expected)
        return list(response.json()["items"])

    async def post_empty(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: int = httpx.codes.NO_CONTENT,
    ) -> None:
        """POST без содержательного ответа."""
        response = await self._client.post(path, json=body)
        self._raise_for_status(response, expected=expected)

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, expected: int) -> None:
        """Превращает неожиданный статус в :class:`ApiError`."""
        if response.status_code == expected:
            return
        raise ApiError(response.status_code, _safe_json(response))


def _safe_json(response: httpx.Response) -> Any:
    """Тело ответа как JSON, а если это не JSON — как текст."""
    try:
        return response.json()
    except ValueError:
        return response.text
