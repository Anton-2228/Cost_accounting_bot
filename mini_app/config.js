// Единственная настройка страницы: где живёт бэкенд.
// Адрес относительный, потому что статику и /api отдаёт один и тот же
// поддомен: один origin — ни CORS, ни mixed content. Абсолютный адрес здесь
// потребовал бы CORSMiddleware в checks_service, которого нет.
window.CHECKS_API_BASE = "/api/v1/mini-app";
