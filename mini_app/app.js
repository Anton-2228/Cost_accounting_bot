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
//
// Язык страницы — язык, выбранный в боте. Страница спрашивает его у сервиса
// (`GET /me`) раньше, чем откроет сканер: подпись сканера и все статусы уже
// должны быть на нём. Не ответил сервис — язык клиента Telegram, если бот на
// нём говорит, иначе английский: без ответа сервиса страница всё равно
// работает, а не молчит.

(function () {
    "use strict";

    const tg = window.Telegram && window.Telegram.WebApp;
    const api = window.CHECKS_API_BASE;
    const LOCALES = window.MINI_APP_LOCALES;

    // Язык тех, кого бот ещё не знает. Повторяет умолчание бота и api.
    const DEFAULT_LANGUAGE = "en";

    // Сколько ждать ответа про язык. Дольше — и человек смотрит на пустой экран
    // вместо сканера, а на запасном языке страница работает ничуть не хуже.
    const LANGUAGE_TIMEOUT_MS = 3000;

    let lang = DEFAULT_LANGUAGE;
    let texts = LOCALES[DEFAULT_LANGUAGE];

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

    let pendingQr = null;

    function authorization() {
        // Подпись Telegram едет с каждым запросом: своих сессий у сервиса нет.
        return "tma " + ((tg && tg.initData) || "");
    }

    // Код языка, если бот на нём говорит: «pt-br» → null, «en-US» → «en».
    function supported(code) {
        if (!code) {
            return null;
        }
        const short = String(code).toLowerCase().split("-")[0];
        return Object.prototype.hasOwnProperty.call(LOCALES, short) ? short : null;
    }

    async function loadLanguage() {
        const controller = new AbortController();
        const timer = setTimeout(function () {
            controller.abort();
        }, LANGUAGE_TIMEOUT_MS);
        try {
            const response = await fetch(api + "/me", {
                headers: { "Authorization": authorization() },
                signal: controller.signal,
            });
            if (response.ok) {
                const body = await response.json();
                const chosen = supported(body && body.language);
                if (chosen) {
                    return chosen;
                }
            }
        } catch (error) {
            // Сеть, таймаут, не тот ответ — идём по запасному пути.
        } finally {
            clearTimeout(timer);
        }
        const user = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
        return supported(user && user.language_code) || DEFAULT_LANGUAGE;
    }

    function useLanguage(code) {
        lang = code;
        texts = LOCALES[code];
        document.documentElement.lang = code;
        document.title = texts.title;
        document.querySelectorAll("[data-i18n]").forEach(function (element) {
            const key = element.getAttribute("data-i18n");
            if (texts[key]) {
                element.textContent = texts[key];
            }
        });
    }

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

    // Разделитель разрядов — обычный пробел: узкий и неразрывный, которые
    // ставит Intl для русского и французского, разные клиенты Telegram рисуют
    // по-разному.
    function plainSpaces(text) {
        return text.replace(/[\u00A0\u202F]/g, " ");
    }

    // Валюта — свойство формата, а не общей модели. Неизвестный формат
    // показывает сумму без знака, а не с чужим: чужой знак хуже отсутствующего,
    // потому что читается как утверждение.
    function formatMoney(value, kind) {
        if (value === null || value === undefined) {
            return null;
        }
        const number = Number(value);
        if (!isFinite(number)) {
            return String(value);
        }
        const amount = new Intl.NumberFormat(lang, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(number);
        const sign = texts.currency[kind];
        return plainSpaces(amount) + (sign ? " " + sign : "");
    }

    function formatDate(value) {
        if (!value) {
            return null;
        }
        const parsed = new Date(value);
        if (isNaN(parsed.getTime())) {
            return String(value);
        }
        return plainSpaces(
            new Intl.DateTimeFormat(lang, {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                hourCycle: "h23",
            }).format(parsed)
        );
    }

    async function call(path, qrRaw) {
        const response = await fetch(api + path, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": authorization(),
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
            // Текст — по машинному коду и на языке пользователя. `message`
            // сервера не показывается: он на одном языке для всех.
            const code = body && body.code;
            const failure = new Error(texts.errors[code] || texts.error_generic);
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
        setStatus(texts.status_recognizing, false);
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
        setStatus(texts.status_fetching, false);
        try {
            await call("/checks", pendingQr);
            resetCard();
            setStatus(texts.status_added, false);
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
        setStatus(texts.scanner_unavailable, true);
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
            tg.showScanQrPopup({ text: texts.scanner_text }, function (text) {
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
            // Ловим потому, что этот вызов стоит на старте приложения:
            // непойманный бросок оборвал бы всё, что идёт после него.
            scannerUnavailable();
        }
    }

    async function init() {
        if (!tg) {
            // Вне Telegram спросить сервис не с чем — подписи нет. Говорим на
            // языке браузера, если бот на нём говорит.
            useLanguage(supported(navigator.language) || DEFAULT_LANGUAGE);
            els.hint.textContent = texts.outside_telegram;
            els.scan.disabled = true;
            return;
        }
        tg.ready();
        tg.expand();

        // Кнопка сканера заблокирована в разметке, пока язык не известен:
        // иначе подпись сканера успела бы открыться на чужом языке.
        useLanguage(await loadLanguage());
        els.scan.disabled = false;

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
