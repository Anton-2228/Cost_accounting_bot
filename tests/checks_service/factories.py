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
from pathlib import Path
from urllib.parse import urlencode

from checks_service import constants

#: Пример настоящей QR-строки российского чека.
RU_FNS_QR = "t=20260725T1507&s=1214.95&fn=7384440901402798&i=145&fp=698610272&n=1"
RU_FNS_KEY = "7384440901402798:145:698610272"

#: Настоящая ссылка с сербского чека: Maxi, Светогорская 7, 610,38 динара.
#: Именно она, а не выдуманная: двоичный заголовок внутри `vl` подписан, и
#: собрать правдоподобный вручную нельзя — а всё, что читает парсер, лежит
#: именно в нём.
SRB_SUF_QR = (
    "https://suf.purs.gov.rs/v/?vl=A1lNUVFXR0tDWU1RUVdHS0OLPwEAiz8BAPgiXQAAAAAAAAAB"
    "oENOTOwAAACfwGj7WquwePtJXDLnfYA%2B8IQeMogbiwiVLcLe8pz3hOEdSKAER3x64OYI%2BWid4"
    "byzQ5dFulWkeQPlyuYTUPu6uri40%2BVYSWSpZ86mn8zqkGZwfJ1m9FQ7pIO18xSN3wZtXg6GOlZT"
    "jRjnVjIFk9Evi9TGEmN5Dt4a%2FN8U35J62R4PpiWIl9PDhLyhlVsqTBr%2FNVJ8DS7tNjVxB5Ve2"
    "nWiYEEYkntAwr2nraFCLuS2YYzM71uJT1vuT%2BQCX%2FcAWQXOVcTC1xC%2FWlBFfwHc6ZHCuIl2"
    "S73kNbMsNTazeWeet4w8vT%2BRd%2FI5Mb106%2FNstpB9YO3ByXb8ECNnnkUeWpfhWKpFSbLnkk%"
    "2BpkdMdFLATjBQ%2B8qFSWcJqv3pkR59fM97V1%2FDD6bT64jNXOgjHnIKSz8dZurPrTVcrCYR73U"
    "a%2BXyHdjtxJnL3B82yGxnGvfvX9zHAj1ilSZntOAPBUOE7x1K4J4Y9Eu%2Blc%2FussKKe6uXJcu"
    "27nWafTzWLCjxupJorcNRSdJGCurHMJH%2B%2Bw0yScKKI1nafE1p0EKW3CbuMM26dpzjCHMtjf7U"
    "cvZuK%2BxMFUQ4xzcnDEHZRJ204rKO11K5CpjKI8mx8c8ED3jZm86SFpzNlQrEst%2BDJerWR1kD4"
    "tuLP0TNGGI%2Bqw4caaQ%2BHnmlcTKl0I46FxDcUBUCRYhsJNuCS44rrqhZl7nu6p%2Fyg%3D"
)
SRB_SUF_KEY = "YMQQWGKC-YMQQWGKC-81803"

#: Второй настоящий чек, и взят он ровно за тем, чем отличается от первого: в
#: заголовке первого оба счётчика равны (81803), а здесь расходятся — общий
#: 79404, свой 77869. На чеке с равными счётчиками номер собирался правильно из
#: любого из двух, и подмена одного другим не проявлялась ничем. На этом
#: проявляется: `/specifications` отвечает на чужой номер `success: false`.
SRB_SUF_QR_DIFFERING_COUNTERS = (
    "https://suf.purs.gov.rs/v/?vl=A04yVjVZUFA3TjJWNVlQUDcsNgEALTABACDfUAAAAAAAAA"
    "ABoHyR0HAAAAA8ouKr63v1JiJBmQI8n80YP8vgpeGrMVCsBG3fVPdsNnPnVCgLX1qNybB7NEZCSZ"
    "iJjTQvpx4a7i888JqFlnJXZpweH%2F1aPIWPbFterNQta2ZBYdo8wjJ3N3UMtNRNU%2B%2Fmx828"
    "rZ6XQ7yTgOVChjBS1J%2BQJ3pBdz0ay5DAjNyBnQrOzAMIcoOmi6iFlzCdSYPbafi5QFxFpI%2Br"
    "0u1y%2Fq9YtXLyOahl74CP9kkifHsV5senmahnQvmB2h25YiWuRBZ8rMhQiT%2BoZXAqB7%2B%2F"
    "vEQeUDEJnrp11j9vXKYrtFDWDnedBu%2F%2F4Bc0BiM4%2BQfqryduA9lIsJmvXXTdtJ9G3vMDno"
    "mwjj8P6FbEpnO%2BZsTx5166xtkW%2BYbKufI4B0i2rsrvGW33QREwj2B%2FUVqtTvAcJTI4upQp"
    "Szl3x9BPnfZ9EoJNMfX%2Fm4khQkkFeZ2aUu4jt6fsV2sE8HMAPwpuc%2BCyW2B%2FOnQLt0FIZn"
    "t9%2Fr77tTlygIot03JGp%2B5XeFXuIUs7q685gqakKtkfYFqZ0eu3vtqG7Gbs6ngmHyMiCIMQMo"
    "f6YLomsolQpywLB38LKTg%2FwP%2BP3Q%2BNDE7IjupEu4RAv2%2F82adPcVlZ1OCg6qIVGS0zpk"
    "UJ5V1zpTA0EnGGtD1bJoCBz8cTd46dWTpTKnkmJT5ysg5NwWNMBgsYefWq68sdCJRvEUWcZiksqZ"
    "ZNHjw%3D"
)
#: Номер этого чека — тот, который печатает сама страница ПУРС.
SRB_SUF_KEY_DIFFERING_COUNTERS = "N2V5YPP7-N2V5YPP7-79404"

#: Токен запроса позиций — он же лежит в фикстурах страниц.
SRB_SUF_TOKEN = "68d61815-760e-45d6-a230-7a300d363837"

_FIXTURES = Path(__file__).parent / "fixtures"


def suf_page(locale: str) -> str:
    """Сохранённая страница чека на указанном языке.

    Страницы настоящие, снятые с `suf.purs.gov.rs`, — из них вырезаны только
    base64-картинки и внешние ресурсы. Именно настоящие: разметка страницы
    содержит незакрытые теги, и фикстура «как надо бы» проверяла бы разбор
    HTML, которого в жизни не встретится.
    """
    name = "suf_sr.html" if locale == constants.SRB_SUF_LOCALE_SR else "suf_en.html"
    return (_FIXTURES / name).read_text(encoding="utf-8")


def suf_specifications() -> str:
    """Сохранённый ответ `/specifications` с позициями чека."""
    return (_FIXTURES / "suf_specifications.json").read_text(encoding="utf-8")


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
