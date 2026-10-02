"""QR-коды с фотографии чека.

Модуль только достаёт строки: что из них чек, решает реестр форматов, а дальше
строка идёт тем же путём, что и строка из сканера Telegram, — через плашку и
подтверждение. Сам по себе он ни в api, ни во внешний сервис не ходит.
"""

from __future__ import annotations

import io
import warnings

import zxingcpp
from PIL import Image, ImageOps, UnidentifiedImageError

from checks_service import constants
from checks_service.exceptions import PhotoUnreadableError


def decode_qr_codes(data: bytes) -> list[str]:
    """Все QR-строки снимка в порядке, в каком их нашёл zxing.

    Синхронная и нагружает процессор — из обработчика запроса её зовут в
    отдельном потоке. Пустой список — изображение прочитано, но QR на нём нет.
    """
    image = _open(data)
    barcodes = zxingcpp.read_barcodes(
        image,
        formats=zxingcpp.BarcodeFormats(zxingcpp.BarcodeFormat.QRCode),
        # Строка нужна байт в байт как в коде: её потом разбирает парсер формата.
        text_mode=zxingcpp.TextMode.Plain,
    )
    return [barcode.text for barcode in barcodes if barcode.valid and barcode.text]


def _open(data: bytes) -> Image.Image:
    """Читает снимок, повёрнутый так, как его видел человек."""
    try:
        # Предупреждение Pillow о большом изображении — ошибка: сжатый файл в
        # пару мегабайт может разворачиваться в гигабайты пикселей.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            opened = Image.open(io.BytesIO(data))
            if opened.width * opened.height > constants.MAX_PHOTO_PIXELS:
                raise PhotoUnreadableError(
                    "Изображение слишком большое",
                    details={"width": opened.width, "height": opened.height},
                )
            # Телефон пишет поворот в EXIF, а не в пиксели. zxing и сам пробует
            # поворачивать, но выровненный снимок читается надёжнее.
            return ImageOps.exif_transpose(opened).convert("L")
    except PhotoUnreadableError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise PhotoUnreadableError("Файл не читается как изображение") from exc
