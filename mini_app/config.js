// Единственная настройка страницы: где живёт бэкенд.
// Адрес относительный, потому что Caddy отдаёт и статику, и /api с одного
// имени: один origin — ни CORS, ни mixed content.
window.CHECKS_API_BASE = "/api/v1/mini-app";
