"""Транспорт к основному api: единственный владелец `httpx.AsyncClient`.

Повторяет :mod:`google_sheets_service.main_api.http`. Доменные клиенты получают
его в конструктор и не знают ни про конверты ответов, ни про коды статусов.
"""

from __future__ import annotations

from typing import Any

import httpx

from checks_service.exceptions import ApiError


class ApiHttpClient:
    """Тонкий транспорт поверх httpx: разворачивает конверты, переводит ошибки.

    Api отвечает `{"data": ...}` на одиночный ресурс и `{"items": [...]}` на
    список — клиент возвращает уже содержимое, а не конверт. Любой неожиданный
    статус превращается в :class:`ApiError` с телом ответа: там лежит `code`, по
    которому вызывающий отличает «чек уже добавлен» от прочих конфликтов.
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
        response = await self._request("GET", path, params=params)
        if response.status_code == httpx.codes.NOT_FOUND and allow_404:
            return None
        self._raise_for_status(response, expected=httpx.codes.OK)
        data = response.json()["data"]
        return dict(data) if data is not None else None

    async def post_data(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: int = httpx.codes.OK,
    ) -> dict[str, Any]:
        """POST, возвращающий одиночный ресурс."""
        response = await self._request("POST", path, json=body)
        self._raise_for_status(response, expected=expected)
        return dict(response.json()["data"])

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Выполняет запрос, превращая сетевой сбой в :class:`ApiError`.

        Без этого недоступное api вылетало бы наружу `httpx.ConnectError` мимо
        обработчиков и становилось пятисоткой без единого внятного слова.
        """
        try:
            return await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise ApiError(httpx.codes.BAD_GATEWAY, str(error)) from error

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
