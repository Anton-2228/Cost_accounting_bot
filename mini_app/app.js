// Mini App добавления чеков.
//
// Страница не знает ни одного формата чека: она отдаёт отсканированную строку
// на сервер и показывает то, что он вернул. Поэтому сербский чек появится без
// единой правки этого файла.
//
// QR попадает на страницу двумя путями, дальше путь у чека один (плашка →
// подтверждение → добавление):
// - сканер — штатный `showScanQrPopup` Telegram: ноль зависимостей и ноль
//   возни с разрешениями камеры, но на Telegram Desktop его нет;
// - фото — снимок или файл из галереи. Страница его ужимает и отдаёт серверу,
//   а тот возвращает строку QR (`POST /checks/decode-photo`). На Desktop это
//   единственный путь.
//
// При запуске страница ничего сама не открывает: показывает обе кнопки и
// список отложенных чеков — отсканированы, но налоговая их пока не отдала. Они
// живут на сервере и переживают закрытие приложения.
//
// Язык страницы — язык, выбранный в боте. Страница спрашивает его у сервиса
// (`GET /me`) раньше, чем откроет кнопки: подпись сканера и все статусы уже
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

    // Сколько ждать ответа про язык. Дольше — и человек смотрит на неактивные
    // кнопки, а на запасном языке страница работает ничуть не хуже.
    const LANGUAGE_TIMEOUT_MS = 3000;

    // Фото ужимается до отправки: снимок телефона весит мегабайты, а для QR
    // хватает и двух тысяч точек по длинной стороне — это сотни килобайт,
    // быстро и на мобильном интернете. Предел сервера и nginx — 5 МБ.
    const PHOTO_MAX_SIDE = 2000;
    const PHOTO_QUALITY = 0.9;

    let lang = DEFAULT_LANGUAGE;
    let texts = LOCALES[DEFAULT_LANGUAGE];

    const els = {
        hint: document.getElementById("hint"),
        scan: document.getElementById("scan"),
        photo: document.getElementById("photo"),
        photoInput: document.getElementById("photo-input"),
        card: document.getElementById("card"),
        table: document.getElementById("card-table"),
        totalRow: document.getElementById("card-total-row"),
        total: document.getElementById("card-total"),
        dateRow: document.getElementById("card-date-row"),
        date: document.getElementById("card-date"),
        confirm: document.getElementById("confirm"),
        cancel: document.getElementById("cancel"),
        status: document.getElementById("status"),
        pending: document.getElementById("pending"),
        pendingList: document.getElementById("pending-list"),
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
        els.photo.disabled = isBusy;
        els.confirm.disabled = isBusy;
        els.cancel.disabled = isBusy;
        els.pendingList.querySelectorAll("button").forEach(function (button) {
            button.disabled = isBusy;
        });
    }

    function resetCard() {
        pendingQr = null;
        els.confirm.textContent = texts.confirm;
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
        return request("POST", path, { qr_raw: qrRaw });
    }

    async function request(method, path, payload) {
        const headers = { "Authorization": authorization() };
        const init = { method: method, headers: headers };
        if (payload instanceof FormData) {
            // Заголовок с границей частей браузер ставит сам.
            init.body = payload;
        } else if (payload !== undefined) {
            headers["Content-Type"] = "application/json";
            init.body = JSON.stringify(payload);
        }
        const response = await fetch(api + path, init);

        let body = null;
        if (response.status !== 204) {
            try {
                body = await response.json();
            } catch (error) {
                body = null;
            }
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

        els.confirm.textContent = texts.confirm;
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

    // Снимок → JPEG не больше PHOTO_MAX_SIDE по длинной стороне. Поворот из
    // EXIF браузер применяет сам при отрисовке. Не вышло сжать (старый WebView,
    // экзотический формат) — уходит оригинал: сервер прочитает и его, если он
    // уложится в предел.
    async function shrinkPhoto(file) {
        try {
            const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
            const scale = Math.min(1, PHOTO_MAX_SIDE / Math.max(bitmap.width, bitmap.height));
            const canvas = document.createElement("canvas");
            canvas.width = Math.round(bitmap.width * scale);
            canvas.height = Math.round(bitmap.height * scale);
            canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
            if (bitmap.close) {
                bitmap.close();
            }
            const blob = await new Promise(function (resolve) {
                canvas.toBlob(resolve, "image/jpeg", PHOTO_QUALITY);
            });
            return blob || file;
        } catch (error) {
            return file;
        }
    }

    async function onPhoto(file) {
        setStatus("", false);
        resetCard();
        busy(true);
        setStatus(texts.status_uploading, false);
        let qrRaw = null;
        try {
            const form = new FormData();
            form.append("photo", await shrinkPhoto(file), "receipt.jpg");
            const decoded = await request("POST", "/checks/decode-photo", form);
            qrRaw = decoded && decoded.qr_raw;
        } catch (error) {
            setStatus(error.message, true);
        } finally {
            busy(false);
        }
        // Дальше — ровно как после сканера.
        if (qrRaw) {
            await onScanned(qrRaw);
        }
    }

    async function onConfirm() {
        if (!pendingQr) {
            return;
        }
        busy(true);
        setStatus(texts.status_fetching, false);
        try {
            const result = await call("/checks", pendingQr);
            resetCard();
            // Чек, который касса ещё не передала, сервер откладывает (202):
            // фон будет спрашивать о нём сам, а здесь он встаёт в список, где
            // его можно повторить и после закрытия приложения.
            if (result && result.status === "pending") {
                setStatus(texts.status_deferred, false);
                await loadPending();
            } else {
                setStatus(texts.status_added, false);
                haptic("success");
            }
        } catch (error) {
            resetCard();
            setStatus(error.message, true);
        } finally {
            busy(false);
        }
    }

    function haptic(kind) {
        if (tg && tg.HapticFeedback) {
            tg.HapticFeedback.notificationOccurred(kind);
        }
    }

    function pendingLabel(item) {
        const parts = [formatMoney(item.total, item.kind), formatDate(item.purchased_at)];
        const label = parts.filter(Boolean).join(" · ");
        return label || texts.pending_unnamed;
    }

    function renderPending(items) {
        els.pendingList.replaceChildren();
        items.forEach(function (item) {
            const row = document.createElement("li");
            row.className = "pending__item";

            const label = document.createElement("span");
            label.className = "pending__label";
            label.textContent = pendingLabel(item);

            const retry = document.createElement("button");
            retry.type = "button";
            retry.className = "button button--primary";
            retry.textContent = texts.retry;
            retry.addEventListener("click", function () {
                onRetryPending(item.id);
            });

            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "button";
            remove.textContent = texts.delete;
            remove.addEventListener("click", function () {
                onDeletePending(item.id);
            });

            const actions = document.createElement("div");
            actions.className = "pending__actions";
            actions.append(retry, remove);
            row.append(label, actions);
            els.pendingList.append(row);
        });
        show(els.pending, items.length > 0);
    }

    // Список отложенных; `null`, если спросить не вышло. Сбой здесь не повод
    // для ошибки на экране: главный сценарий — скан — работает и без списка.
    async function loadPending() {
        try {
            const body = await request("GET", "/pending-checks");
            const items = (body && body.items) || [];
            renderPending(items);
            return items;
        } catch (error) {
            return null;
        }
    }

    // Чека в отложенных больше нет — ни повторять, ни удалять нечего: его
    // добавили или убрали, возможно, с другого экрана или фоном.
    function isGone(code) {
        return code === "check_already_saved" || code === "pending_check_not_found";
    }

    async function onRetryPending(id) {
        busy(true);
        setStatus(texts.status_fetching, false);
        try {
            await request("POST", "/pending-checks/" + id + "/retry");
            setStatus(texts.status_added, false);
            haptic("success");
        } catch (error) {
            setStatus(error.message, !isGone(error.code));
        } finally {
            await loadPending();
            busy(false);
        }
    }

    async function onDeletePending(id) {
        busy(true);
        try {
            await request("DELETE", "/pending-checks/" + id);
            setStatus("", false);
        } catch (error) {
            if (!isGone(error.code)) {
                setStatus(error.message, true);
            }
        } finally {
            await loadPending();
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
            // Ловим, чтобы человек увидел подсказку про фото, а не тишину.
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
            els.photo.disabled = true;
            return;
        }
        tg.ready();
        tg.expand();

        // Кнопки заблокированы в разметке, пока язык не известен: иначе подпись
        // сканера и статусы успели бы показаться на чужом языке.
        useLanguage(await loadLanguage());
        els.scan.disabled = false;
        els.photo.disabled = false;

        els.scan.addEventListener("click", openScanner);
        els.photo.addEventListener("click", function () {
            els.photoInput.click();
        });
        els.photoInput.addEventListener("change", function () {
            const file = els.photoInput.files && els.photoInput.files[0];
            // Сбрасываем выбор, иначе то же фото второй раз не вызовет `change`.
            els.photoInput.value = "";
            if (file) {
                onPhoto(file);
            }
        });
        els.confirm.addEventListener("click", onConfirm);
        els.cancel.addEventListener("click", function () {
            resetCard();
            setStatus("", false);
        });

        await loadPending();
    }

    init();
})();
