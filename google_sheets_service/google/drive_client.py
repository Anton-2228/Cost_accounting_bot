"""Асинхронная обёртка над Google Drive API.

От Drive нужны две вещи: выдать пользователю доступ к документу и найти уже
созданный документ по метке — на случай, если ответ api потерялся и повтор
задачи иначе создал бы второй.
"""

from __future__ import annotations

from typing import Any

import anyio
import google_auth_httplib2
import httplib2
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from google_sheets_service.google.retry import RetryPolicy, to_dict
from google_sheets_service.logging import get_logger

logger = get_logger(__name__)


class GoogleDriveClient:
    """Обёртка над `files` и `permissions` из `googleapiclient`."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        timeout_seconds: float = 20.0,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._http = httplib2.Http(timeout=timeout_seconds)
        authorized_http = google_auth_httplib2.AuthorizedHttp(credentials, http=self._http)
        self._service = build("drive", "v3", http=authorized_http, cache_discovery=False)

        policy = retry or RetryPolicy()
        self.find_by_app_property = policy(self._find_by_app_property)
        self.set_app_property = policy(self._set_app_property)
        self.grant_access = policy(self._grant_access)

    async def _find_by_app_property(self, key: str, value: str) -> str | None:
        """Ищет документ по пользовательской метке.

        Метка ставится сервисом при создании и делает создание идемпотентным:
        повтор задачи находит уже созданный документ вместо того, чтобы завести
        второй и бросить первый сиротой. Поиск ограничен файлами, которыми
        владеет сам сервисный аккаунт, — чужие документы с той же меткой в
        выдачу не попадут.
        """
        query = (
            f"appProperties has {{ key='{key}' and value='{value}' }}"
            " and mimeType='application/vnd.google-apps.spreadsheet'"
            " and trashed=false"
        )

        def call() -> dict[str, Any]:
            request = self._service.files().list(
                q=query,
                spaces="drive",
                fields="files(id)",
                pageSize=2,
            )
            return to_dict(request.execute())

        body = await anyio.to_thread.run_sync(call)
        files = body.get("files", [])
        if not files:
            return None
        if len(files) > 1:
            # Метка уникальна по построению. Дубль означает, что документ
            # создавался в обход сервиса; берём первый и говорим об этом вслух,
            # потому что второй останется невидимым для системы навсегда.
            logger.warning("По метке %s=%s найдено несколько документов", key, value)
        return str(files[0]["id"])

    async def _set_app_property(self, file_id: str, key: str, value: str) -> None:
        """Проставляет метку уже существующему документу.

        Нужна отдельным вызовом: `spreadsheets.create` умеет задавать свойства
        таблицы, но не свойства файла в Drive.
        """

        def call() -> dict[str, Any]:
            request = self._service.files().update(
                fileId=file_id,
                body={"appProperties": {key: value}},
                fields="id",
            )
            return to_dict(request.execute())

        await anyio.to_thread.run_sync(call)

    async def _grant_access(self, file_id: str, email: str, *, role: str) -> None:
        """Открывает доступ к документу на указанную почту.

        Уведомление Google отправляет сам: пользователь должен получить ссылку,
        даже если бот в этот момент до него не достучится.
        """

        def call() -> dict[str, Any]:
            request = self._service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": role, "emailAddress": email},
                fields="id",
                sendNotificationEmail=True,
            )
            return to_dict(request.execute())

        await anyio.to_thread.run_sync(call)
