"""Фикстуры тестов `checks_service`.

Переменные окружения выставляются ДО первого импорта `checks_service.*`:
настройки читаются на импорте модуля `checks_service.config`, и потом их уже не
переопределить. Токен здесь заведомо ненастоящий — им подписывается тестовая
`initData`, и проверяется она тем же кодом, что работает в бою.
"""

from __future__ import annotations

import os

BOT_TOKEN = "123456:TEST-BOT-TOKEN"
ALLOWED_ID = 555_000_111
STRANGER_ID = 999_000_222

os.environ.setdefault("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", str(ALLOWED_ID))
os.environ.setdefault("API_BASE_URL", "http://api.test/api/v1")
os.environ.setdefault("PROVERKACHEKA_API_TOKEN", "test-token")
