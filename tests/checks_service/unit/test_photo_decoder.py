"""Тесты чтения QR-кодов с фотографии."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from checks_service.exceptions import PhotoUnreadableError
from checks_service.services.photo_decoder import decode_qr_codes
from tests.checks_service.factories import RU_FNS_QR, make_qr_photo

PROMO_QR = "https://shop.example/promo"


def test_reads_the_receipt_qr() -> None:
    """QR чека читается байт в байт — его дальше разбирает парсер формата."""
    assert decode_qr_codes(make_qr_photo(RU_FNS_QR)) == [RU_FNS_QR]


def test_reads_png_too() -> None:
    """Сжатие на странице может не сработать, и тогда приходит оригинал."""
    assert decode_qr_codes(make_qr_photo(RU_FNS_QR, image_format="PNG")) == [RU_FNS_QR]


def test_returns_every_qr_on_the_photo() -> None:
    """Выбор между кодами — не забота декодера: он отдаёт все."""
    assert set(decode_qr_codes(make_qr_photo(PROMO_QR, RU_FNS_QR))) == {PROMO_QR, RU_FNS_QR}


def test_photo_without_qr_is_empty() -> None:
    """Прочитанная картинка без QR — пустой список, а не ошибка чтения."""
    assert decode_qr_codes(make_qr_photo()) == []


def test_rotated_photo_is_read() -> None:
    """Телефон пишет поворот в EXIF: снимок «боком» читается так же."""
    source = Image.open(io.BytesIO(make_qr_photo(RU_FNS_QR))).rotate(90, expand=True)
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: повернуть на 90° по часовой
    buffer = io.BytesIO()
    source.save(buffer, "JPEG", exif=exif)

    assert decode_qr_codes(buffer.getvalue()) == [RU_FNS_QR]


@pytest.mark.parametrize("data", [b"", b"not an image", b"\xff\xd8\xff\xe0 truncated jpeg"])
def test_not_an_image_is_refused(data: bytes) -> None:
    """Файл, который не читается как картинка, — свой отказ, а не 500."""
    with pytest.raises(PhotoUnreadableError):
        decode_qr_codes(data)
