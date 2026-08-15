"""Тестовые данные `checks_service`.

`initData` подписывается **тем же алгоритмом**, который её проверяет. Это не
тавтология: проверка ловит не расхождение двух реализаций, а расхождение с
клиентом Telegram — а его подпись мы всё равно воспроизвести не можем.
Существенно другое: тест умеет собрать и заведомо испорченную строку, и
протухшую, и подписанную чужим токеном.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from urllib.parse import urlencode

from checks_service import constants

#: Пример настоящей QR-строки российского чека.
RU_FNS_QR = "t=20260725T1507&s=1214.95&fn=7384440901402798&i=145&fp=698610272&n=1"
RU_FNS_KEY = "7384440901402798:145:698610272"

#: Правдоподобный ответ proverkacheka: суммы в копейках, как и в жизни.
PROVERKACHEKA_PAYLOAD = {
    "code": 1,
    "data": {
        "json": {
            "totalSum": 121495,
            "items": [
                {"name": "Молоко 3.2%", "sum": 8990, "quantity": 1},
                {"name": "Хлеб бородинский", "sum": 4010, "quantity": 1},
            ],
        }
    },
}


def make_init_data(
    *,
    telegram_id: int,
    bot_token: str,
    auth_date: datetime | None = None,
    tamper: bool = False,
) -> str:
    """Собирает подписанную `initData` Telegram Mini App."""
    moment = auth_date if auth_date is not None else datetime.now(UTC)
    fields = {
        "auth_date": str(int(moment.timestamp())),
        "query_id": "AAF_test",
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Тест", "language_code": "ru"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }

    secret = hmac.new(constants.INIT_DATA_SECRET_KEY, bot_token.encode(), hashlib.sha256).digest()
    payload = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    signature = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()

    if tamper:
        # Меняем поле уже после подписи: ровно то, что сделал бы подделыватель.
        fields["user"] = json.dumps(
            {"id": telegram_id + 1, "first_name": "Чужой"},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    return urlencode({**fields, constants.INIT_DATA_HASH_FIELD: signature})
