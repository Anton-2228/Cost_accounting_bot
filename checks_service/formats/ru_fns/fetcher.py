"""Расшифровка чека ФНС через proverkacheka.com.

Отличий от старой реализации три, и все существенные:

* **явный таймаут** — прежний `requests.post` без таймаута вызывался прямо из
  асинхронного кода, и зависший proverkacheka останавливал весь бот;
* **проверка кода ответа** — прежняя версия отдавала тело дальше не глядя, и
  «чек не найден» доезжал до разбора как пустой чек;
* **никакого LLM** — реквизиты приходят от парсера готовыми.
"""

from __future__ import annotations

from typing import Any

import httpx

from checks_service import constants
from checks_service.exceptions import ReceiptFetchError, ReceiptNotFoundError
from checks_service.formats.base import ParsedCheck
from checks_service.logging import get_logger

logger = get_logger(__name__)


class ProverkachekaFetcher:
    """Клиент внешнего сервиса расшифровки российских чеков."""

    def __init__(self, base_url: str, *, token: str, timeout: float) -> None:
        self._url = base_url
        self._token = token
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.aclose()

    async def fetch(self, parsed: ParsedCheck) -> dict[str, Any]:
        """Возвращает ответ сервиса целиком.

        Целиком — потому что разбор придёт позже и возьмёт из него поля, о
        которых сейчас неизвестно, что они понадобятся. Суммы в ответе в
        копейках; переводить их в рубли здесь нельзя — это уже интерпретация,
        и делать её надо `Decimal(копейки) / 100`, а не делением float, как в
        старой версии.
        """
        body = {"token": self._token, **parsed.credentials}
        try:
            response = await self._client.post(self._url, json=body)
        except httpx.HTTPError as error:
            logger.warning("proverkacheka недоступен: %s", error)
            raise ReceiptFetchError("Сервис расшифровки чеков недоступен") from error

        if response.status_code != httpx.codes.OK:
            logger.warning("proverkacheka ответил %s", response.status_code)
            raise ReceiptFetchError(
                "Сервис расшифровки чеков ответил ошибкой",
                details={"status_code": response.status_code},
            )

        payload = self._payload(response)
        code = payload.get("code")
        if code == constants.PROVERKACHEKA_SUCCESS_CODE:
            return payload
        if code in constants.PROVERKACHEKA_NOT_FOUND_CODES:
            raise ReceiptNotFoundError(
                "Чек не найден в базе ФНС",
                details={"code": code, "data": payload.get("data")},
            )
        raise ReceiptFetchError(
            "Сервис расшифровки чеков вернул неизвестный ответ",
            details={"code": code},
        )

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        """Тело ответа как объект JSON.

        Не-JSON и JSON-не-объект — это сбой сервиса, а не чек: сохранять такое
        в `raw_payload` значило бы записать мусор под видом расшифровки.
        """
        try:
            payload = response.json()
        except ValueError as error:
            raise ReceiptFetchError("Сервис расшифровки чеков ответил не JSON") from error
        if not isinstance(payload, dict):
            raise ReceiptFetchError("Сервис расшифровки чеков ответил неожиданной структурой")
        return payload
