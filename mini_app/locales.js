// Тексты Mini App на языках бота.
//
// Отдельный файл, а не словарь внутри app.js: после присваивания здесь чистый
// JSON, и тест сервиса (tests/checks_service/test_mini_app_locales.py) сверяет
// языки между собой, с кодами отказов сервиса и с `data-i18n` страницы — без
// сборки и без интерпретатора JS.
//
// Ошибки выбираются по машинному коду ответа, а не по его `message`: тот на
// одном языке для всех и написан для журнала.
window.MINI_APP_LOCALES = {
    "ru": {
        "title": "Добавить чек",
        "hint": "Наведите камеру на QR-код в нижней части чека.",
        "scan": "Сканировать чек",
        "card_table": "Таблица",
        "card_total": "Сумма",
        "card_date": "Дата",
        "confirm": "Добавить",
        "cancel": "Отмена",
        "status_recognizing": "Распознаём чек…",
        "status_fetching": "Получаем состав чека…",
        "status_added": "Чек добавлен.",
        "scanner_text": "QR-код с чека",
        "scanner_unavailable": "Сканер доступен только в мобильном Telegram — откройте приложение с телефона.",
        "outside_telegram": "Откройте страницу из Telegram — вне клиента она не работает.",
        "error_generic": "Что-то пошло не так. Попробуйте позже.",
        "errors": {
            "format_not_supported": "Не удалось распознать чек. Это точно QR-код с чека?",
            "spreadsheet_not_found": "Сначала создайте таблицу командой /start в боте.",
            "check_already_saved": "Этот чек уже добавлен.",
            "receipt_not_found": "Чек не найден в налоговой базе. Иногда он появляется там не сразу.",
            "receipt_fetch_failed": "Сервис расшифровки чеков недоступен. Попробуйте позже.",
            "unauthorized": "Откройте приложение заново через меню бота.",
            "forbidden": "Доступ запрещён.",
            "api_error": "Сервис данных недоступен. Попробуйте позже."
        },
        "currency": {
            "RU_FNS": "₽",
            "SRB_SUF": "дин."
        }
    },
    "en": {
        "title": "Add a receipt",
        "hint": "Point the camera at the QR code at the bottom of the receipt.",
        "scan": "Scan a receipt",
        "card_table": "Spreadsheet",
        "card_total": "Amount",
        "card_date": "Date",
        "confirm": "Add",
        "cancel": "Cancel",
        "status_recognizing": "Recognizing the receipt…",
        "status_fetching": "Getting the receipt contents…",
        "status_added": "Receipt added.",
        "scanner_text": "Receipt QR code",
        "scanner_unavailable": "The scanner is only available in mobile Telegram — open the app on your phone.",
        "outside_telegram": "Open this page from Telegram — it doesn't work outside the app.",
        "error_generic": "Something went wrong. Please try again later.",
        "errors": {
            "format_not_supported": "Couldn't recognize the receipt. Is this really a receipt QR code?",
            "spreadsheet_not_found": "Create a spreadsheet first with /start in the bot.",
            "check_already_saved": "This receipt has already been added.",
            "receipt_not_found": "The receipt wasn't found in the tax database. Sometimes it takes a while to appear there.",
            "receipt_fetch_failed": "The receipt decoding service is unavailable. Please try again later.",
            "unauthorized": "Reopen the app from the bot's menu.",
            "forbidden": "Access denied.",
            "api_error": "The data service is unavailable. Please try again later."
        },
        "currency": {
            "RU_FNS": "₽",
            "SRB_SUF": "din."
        }
    },
    "hi": {
        "title": "रसीद जोड़ें",
        "hint": "कैमरे को रसीद के नीचे वाले QR कोड की ओर करें।",
        "scan": "रसीद स्कैन करें",
        "card_table": "स्प्रेडशीट",
        "card_total": "राशि",
        "card_date": "तारीख",
        "confirm": "जोड़ें",
        "cancel": "रद्द करें",
        "status_recognizing": "रसीद पहचानी जा रही है…",
        "status_fetching": "रसीद का विवरण लाया जा रहा है…",
        "status_added": "रसीद जोड़ दी गई।",
        "scanner_text": "रसीद का QR कोड",
        "scanner_unavailable": "स्कैनर केवल मोबाइल Telegram में उपलब्ध है — ऐप फ़ोन से खोलें।",
        "outside_telegram": "यह पेज Telegram से खोलें — ऐप के बाहर यह काम नहीं करता।",
        "error_generic": "कुछ गड़बड़ हो गई। बाद में फिर कोशिश करें।",
        "errors": {
            "format_not_supported": "रसीद पहचानी नहीं जा सकी। क्या यह सचमुच रसीद का QR कोड है?",
            "spreadsheet_not_found": "पहले बॉट में /start से एक स्प्रेडशीट बनाएँ।",
            "check_already_saved": "यह रसीद पहले ही जोड़ी जा चुकी है।",
            "receipt_not_found": "रसीद कर विभाग के डेटाबेस में नहीं मिली। कभी-कभी वह वहाँ देर से आती है।",
            "receipt_fetch_failed": "रसीद पढ़ने की सेवा उपलब्ध नहीं है। बाद में फिर कोशिश करें।",
            "unauthorized": "ऐप को बॉट के मेनू से फिर से खोलें।",
            "forbidden": "पहुँच अस्वीकृत।",
            "api_error": "डेटा सेवा उपलब्ध नहीं है। बाद में फिर कोशिश करें।"
        },
        "currency": {
            "RU_FNS": "₽",
            "SRB_SUF": "din."
        }
    },
    "es": {
        "title": "Añadir un recibo",
        "hint": "Apunta la cámara al código QR de la parte inferior del recibo.",
        "scan": "Escanear un recibo",
        "card_table": "Hoja de cálculo",
        "card_total": "Importe",
        "card_date": "Fecha",
        "confirm": "Añadir",
        "cancel": "Cancelar",
        "status_recognizing": "Reconociendo el recibo…",
        "status_fetching": "Obteniendo el contenido del recibo…",
        "status_added": "Recibo añadido.",
        "scanner_text": "Código QR del recibo",
        "scanner_unavailable": "El escáner solo está disponible en Telegram para móvil: abre la app desde el teléfono.",
        "outside_telegram": "Abre esta página desde Telegram: fuera de la app no funciona.",
        "error_generic": "Algo salió mal. Inténtalo más tarde.",
        "errors": {
            "format_not_supported": "No se pudo reconocer el recibo. ¿Seguro que es el código QR de un recibo?",
            "spreadsheet_not_found": "Primero crea una hoja de cálculo con /start en el bot.",
            "check_already_saved": "Este recibo ya se añadió.",
            "receipt_not_found": "El recibo no está en la base de datos fiscal. A veces tarda un poco en aparecer.",
            "receipt_fetch_failed": "El servicio de descifrado de recibos no está disponible. Inténtalo más tarde.",
            "unauthorized": "Vuelve a abrir la app desde el menú del bot.",
            "forbidden": "Acceso denegado.",
            "api_error": "El servicio de datos no está disponible. Inténtalo más tarde."
        },
        "currency": {
            "RU_FNS": "₽",
            "SRB_SUF": "din."
        }
    },
    "fr": {
        "title": "Ajouter un ticket",
        "hint": "Pointez l'appareil photo vers le code QR en bas du ticket.",
        "scan": "Scanner un ticket",
        "card_table": "Tableur",
        "card_total": "Montant",
        "card_date": "Date",
        "confirm": "Ajouter",
        "cancel": "Annuler",
        "status_recognizing": "Reconnaissance du ticket…",
        "status_fetching": "Récupération du contenu du ticket…",
        "status_added": "Ticket ajouté.",
        "scanner_text": "Code QR du ticket",
        "scanner_unavailable": "Le scanner n'est disponible que dans Telegram sur mobile — ouvrez l'appli sur votre téléphone.",
        "outside_telegram": "Ouvrez cette page depuis Telegram — elle ne fonctionne pas en dehors de l'appli.",
        "error_generic": "Une erreur s'est produite. Réessayez plus tard.",
        "errors": {
            "format_not_supported": "Impossible de reconnaître le ticket. Est-ce bien le code QR d'un ticket ?",
            "spreadsheet_not_found": "Créez d'abord un tableur avec /start dans le bot.",
            "check_already_saved": "Ce ticket a déjà été ajouté.",
            "receipt_not_found": "Le ticket est introuvable dans la base fiscale. Il met parfois un peu de temps à y apparaître.",
            "receipt_fetch_failed": "Le service de décodage des tickets est indisponible. Réessayez plus tard.",
            "unauthorized": "Rouvrez l'appli depuis le menu du bot.",
            "forbidden": "Accès refusé.",
            "api_error": "Le service de données est indisponible. Réessayez plus tard."
        },
        "currency": {
            "RU_FNS": "₽",
            "SRB_SUF": "din."
        }
    }
};
