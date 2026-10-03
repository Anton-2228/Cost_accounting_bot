#!/bin/sh
# Готовит постоянный рабочий каталог агента и запускает сервер.
#
# /workspace — том: скрипты, заметки и доставленные агентом библиотеки
# переживают пересоздание контейнера. Окружение создаётся здесь, а не в
# образе: в образе оно было бы закрыто томом. `--system-site-packages` даёт
# ему базовые библиотеки образа (zxing-cpp, OpenCV, pyzbar).
set -eu

WORKSPACE="${QR_VISION_WORKSPACE:-/workspace}"

if [ ! -x "$WORKSPACE/.venv/bin/python" ]; then
    python3 -m venv --system-site-packages "$WORKSPACE/.venv"
fi
mkdir -p "$WORKSPACE/scripts" "$WORKSPACE/requests"
[ -f "$WORKSPACE/NOTES.md" ] || : > "$WORKSPACE/NOTES.md"
# Каталоги запросов, оставшиеся от оборванного прошлого запуска.
rm -rf "$WORKSPACE/requests"/*

exec node /app/dist/server.js
