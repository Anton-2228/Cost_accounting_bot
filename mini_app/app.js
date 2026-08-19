// Mini App добавления чеков.
//
// Страница не знает ни одного формата чека: она отдаёт отсканированную строку
// на сервер и показывает то, что он вернул. Поэтому сербский чек появится без
// единой правки этого файла.
//
// Сканер — штатный `showScanQrPopup` Telegram: ноль зависимостей и ноль возни
// с разрешениями камеры. Следствие принятое сознательно: на Telegram Desktop
// сканера нет, приложение мобильное.
//
// Сканер открывается сам при запуске: сканирование — единственный сценарий
// приложения, и лишний тап по кнопке ничего не решает. Кнопка остаётся путём
// повтора — после отмены сканера, ошибки или добавленного чека.

(function () {
    "use strict";

    const tg = window.Telegram && window.Telegram.WebApp;
    const api = window.CHECKS_API_BASE;

    const els = {
        hint: document.getElementById("hint"),
        scan: document.getElementById("scan"),
        card: document.getElementById("card"),
        table: document.getElementById("card-table"),
        totalRow: document.getElementById("card-total-row"),
        total: document.getElementById("card-total"),
        dateRow: document.getElementById("card-date-row"),
        date: document.getElementById("card-date"),
        confirm: document.getElementById("confirm"),
        cancel: document.getElementById("cancel"),
        status: document.getElementById("status"),
    };

    // Русский текст выбирается по машинному коду ответа: сообщение сервера
    // можно переписать, не трогая страницу, а незнакомый код всё равно будет
    // показан — молчать об ошибке хуже, чем показать чужую формулировку.
    const MESSAGES = {
        format_not_supported: "Не удалось распознать чек. Это точно QR-код с чека?",
        spreadsheet_not_found: "Сначала создайте таблицу командой /start в боте.",
        check_already_saved: "Этот чек уже добавлен.",
        receipt_not_found: "Чек не найден в базе ФНС. Иногда он появляется там не сразу.",
        receipt_fetch_failed: "Сервис расшифровки чеков недоступен. Попробуйте позже.",
        unauthorized: "Откройте приложение заново через меню бота.",
        forbidden: "Доступ запрещён.",
        api_error: "Сервис данных недоступен. Попробуйте позже.",
    };

    let pendingQr = null;

    function show(element, visible) {
        element.hidden = !visible;
    }

    function setStatus(text, isError) {
        els.status.textContent = text;
        els.status.classList.toggle("status--error", Boolean(isError));
        show(els.status, Boolean(text));
    }

    function busy(isBusy) {
        els.scan.disabled = isBusy;
        els.confirm.disabled = isBusy;
        els.cancel.disabled = isBusy;
    }

    function resetCard() {
        pendingQr = null;
        show(els.card, false);
    }

    // Валюта — свойство формата, а не общей модели: у сербского чека она будет
    // своя. Неизвестный формат показывает сумму без знака, а не с чужим.
    const CURRENCY = { RU_FNS: "₽" };

    function formatMoney(value, kind) {
        if (value === null || value === undefined) {
            return null;
        }
        const number = Number(value);
        if (!isFinite(number)) {
            return String(value);
        }
        const parts = number.toFixed(2).split(".");
        // Разделитель разрядов — обычный пробел: узкий и неразрывный разные
        // клиенты Telegram рисуют по-разному.
        const whole = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
        const sign = CURRENCY[kind];
        return whole + "," + parts[1] + (sign ? " " + sign : "");
    }

    function formatDate(value) {
        if (!value) {
            return null;
        }
        const parsed = new Date(value);
        if (isNaN(parsed.getTime())) {
            return String(value);
        }
        const pad = (n) => String(n).padStart(2, "0");
        return (
            pad(parsed.getDate()) + "." + pad(parsed.getMonth() + 1) + "." + parsed.getFullYear() +
            " " + pad(parsed.getHours()) + ":" + pad(parsed.getMinutes())
        );
    }

    async function call(path, qrRaw) {
        const response = await fetch(api + path, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                // Подпись Telegram едет с каждым запросом: своих сессий у
                // сервиса нет вовсе.
                "Authorization": "tma " + ((tg && tg.initData) || ""),
            },
            body: JSON.stringify({ qr_raw: qrRaw }),
        });

        let body = null;
        try {
            body = await response.json();
        } catch (error) {
            body = null;
        }

        if (!response.ok) {
            const code = body && body.code;
            const message = MESSAGES[code] || (body && body.message) ||
                "Что-то пошло не так. Попробуйте позже.";
            const failure = new Error(message);
            failure.code = code;
            throw failure;
        }
        return body;
    }

    function renderPreview(preview) {
        els.table.textContent = preview.spreadsheet_title;

        const total = formatMoney(preview.total, preview.kind);
        els.total.textContent = total || "";
        show(els.totalRow, Boolean(total));

        const purchased = formatDate(preview.purchased_at);
        els.date.textContent = purchased || "";
        show(els.dateRow, Boolean(purchased));

        show(els.card, true);
    }

    async function onScanned(qrRaw) {
        busy(true);
        setStatus("Распознаём чек…", false);
        try {
            const preview = await call("/checks/preview", qrRaw);
            pendingQr = qrRaw;
            renderPreview(preview);
            setStatus("", false);
        } catch (error) {
            resetCard();
            setStatus(error.message, true);
        } finally {
            busy(false);
        }
    }

    async function onConfirm() {
        if (!pendingQr) {
            return;
        }
        busy(true);
        setStatus("Получаем состав чека…", false);
        try {
            await call("/checks", pendingQr);
            resetCard();
            setStatus("Чек добавлен.", false);
            if (tg && tg.HapticFeedback) {
                tg.HapticFeedback.notificationOccurred("success");
            }
        } catch (error) {
            resetCard();
            setStatus(error.message, true);
        } finally {
            busy(false);
        }
    }

    function scannerUnavailable() {
        setStatus(
            "Сканер доступен только в мобильном Telegram — откройте приложение с телефона.",
            true
        );
    }

    function openScanner() {
        setStatus("", false);
        resetCard();

        // Проверяем версию, а не наличие метода: `showScanQrPopup` в SDK
        // определён всегда и на неподдерживающем клиенте бросает, а не молчит.
        if (!tg || !tg.isVersionAtLeast || !tg.isVersionAtLeast("6.4")) {
            scannerUnavailable();
            return;
        }

        try {
            tg.showScanQrPopup({ text: "QR-код с чека" }, function (text) {
                // Возврат true закрывает окно сканера. Без этого оно осталось бы
                // висеть поверх результата.
                tg.closeScanQrPopup();
                if (text) {
                    onScanned(text);
                }
                return true;
            });
        } catch (error) {
            // Сюда попадает клиент, который версию заявил, а метод не тянет.
            // Ловим потому, что этот вызов теперь стоит на старте приложения:
            // непойманный бросок оборвал бы всё, что идёт после него.
            scannerUnavailable();
        }
    }

    function init() {
        if (tg) {
            tg.ready();
            tg.expand();
        } else {
            els.hint.textContent = "Откройте страницу из Telegram — вне клиента она не работает.";
            els.scan.disabled = true;
            return;
        }
        els.scan.addEventListener("click", openScanner);
        els.confirm.addEventListener("click", onConfirm);
        els.cancel.addEventListener("click", function () {
            resetCard();
            setStatus("", false);
        });

        // Сканер поднимаем последним и отдельным тиком: слушатели к этому
        // моменту уже на месте, а страница успевает отрисоваться — иначе
        // закрывший сканер видит, как экран появляется только сейчас.
        setTimeout(openScanner, 0);
    }

    init();
})();
