"""Транспорт к api: единственный владелец `httpx.AsyncClient`.

Доменные клиенты получают его в конструктор и не знают ни про конверты ответов,
ни про коды статусов.
"""

from __future__ import annotations

from typing import Any

import httpx

from telegram_bot.api_client.errors import (
    ApiConflictError,
    ApiError,
    ApiNotFoundError,
    ApiUnavailableError,
    ApiValidationError,
)

_ERROR_BY_STATUS: dict[int, type[ApiError]] = {
    httpx.codes.NOT_FOUND: ApiNotFoundError,
    httpx.codes.CONFLICT: ApiConflictError,
    httpx.codes.UNPROCESSABLE_ENTITY: ApiValidationError,
}


class ApiHttpClient:
    """Тонкий транспорт поверх httpx: разворачивает конверты, переводит ошибки.

    Api отвечает `{"data": ...}` на одиночный ресурс и `{"items": [...]}` на
    список — наружу отдаётся содержимое, а не конверт.

    Таймаут задаётся на месте вызова: создание документа и просьба вчитать
    листы занимают заметно больше времени, чем чтение справочника, и один
    таймаут на всё был бы либо слишком коротким для первых, либо бесполезно
    долгим для вторых.
    """

    def __init__(self, base_url: str, *, timeout: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.aclose()

    async def get_data(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """GET одиночного ресурса."""
        response = await self._request("GET", path, params=params, timeout=timeout)
        return dict(response.json()["data"])

    async def get_items(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """GET списка."""
        response = await self._request("GET", path, params=params, timeout=timeout)
        return list(response.json()["items"])

    async def post_data(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """POST, возвращающий одиночный ресурс."""
        response = await self._request("POST", path, body=body, timeout=timeout)
        return dict(response.json()["data"])

    async def post_items(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """POST, возвращающий список.

        Нужен записи разобранного чека: она создаёт сразу N операций и отдаёт
        их все, потому что чек — одна транзакция, а не N запросов.
        """
        response = await self._request("POST", path, body=body, timeout=timeout)
        return list(response.json()["items"])

    async def post_empty(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> None:
        """POST без содержательного ответа (204 или 202)."""
        await self._request("POST", path, body=body, timeout=timeout)

    async def delete(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> None:
        """DELETE без содержательного ответа (204)."""
        await self._request("DELETE", path, params=params, timeout=timeout)

    async def delete_data(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """DELETE, возвращающий удалённый ресурс.

        Удаление операции и перевода отдаёт саму запись: только так бот может
        сказать «удалил такую-то», когда пользователь не называл идентификатор.
        """
        response = await self._request("DELETE", path, params=params, timeout=timeout)
        return dict(response.json()["data"])

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Выполняет запрос и превращает неуспешный ответ в исключение."""
        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                json=body,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
        except httpx.HTTPError as error:
            # Таймаут и обрыв соединения неотличимы для пользователя от «сервис
            # недоступен», и обрабатываются одинаково — предложением повторить.
            raise ApiUnavailableError(0, message=str(error)) from error

        if response.is_success:
            return response
        raise self._to_error(response)

    @staticmethod
    def _to_error(response: httpx.Response) -> ApiError:
        """Собирает исключение по конверту ошибки."""
        try:
            body = response.json()
        except ValueError:
            body = {}
        payload = body if isinstance(body, dict) else {}

        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            error_type: type[ApiError] = ApiUnavailableError
        else:
            error_type = _ERROR_BY_STATUS.get(response.status_code, ApiError)

        return error_type(
            response.status_code,
            code=str(payload.get("code", "")),
            message=str(payload.get("message", "")),
            details=payload.get("details"),
        )
