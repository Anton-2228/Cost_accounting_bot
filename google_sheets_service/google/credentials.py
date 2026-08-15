"""Загрузка учётных данных сервисного аккаунта Google."""

from __future__ import annotations

import json

from google.oauth2.service_account import Credentials

from google_sheets_service.config import GoogleSheetsServiceSettings

#: Sheets нужен для листов, Drive — для выдачи доступов и поиска уже созданного
#: документа по метке. Полный `drive`, а не `drive.file`: поиск по
#: `appProperties` работает только с ним.
SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)


class CredentialsLoader:
    """Создаёт `Credentials` из inline-JSON или из файла на диске.

    Два источника нужны потому, что в Compose ключ монтируется файлом и
    read-only, а в окружениях без файловой системы его удобнее держать
    переменной. Если заданы оба, выигрывает inline-JSON.
    """

    def __init__(self, settings: GoogleSheetsServiceSettings) -> None:
        self._settings = settings

    def load(self) -> Credentials:
        """Возвращает учётные данные с нужными областями доступа.

        Отсутствие обоих источников валит процесс на старте, а не посреди
        первого тика: сервис без ключа не может сделать ничего полезного.
        """
        if self._settings.google_credentials_json:
            info = json.loads(self._settings.google_credentials_json)
            return Credentials.from_service_account_info(info, scopes=list(SCOPES))
        if self._settings.google_credentials_path:
            return Credentials.from_service_account_file(
                self._settings.google_credentials_path, scopes=list(SCOPES)
            )
        raise RuntimeError(
            "Не заданы учётные данные Google: ожидается GOOGLE_CREDENTIALS_JSON "
            "либо GOOGLE_CREDENTIALS_PATH в env/google_sheets_service.env"
        )
