# Сайдкар фолбека QR: pi (TypeScript SDK) + Opus через OpenRouter. Node — свой
# образ, а не доустановка в Python-образ checks_service: pi нужен Node >= 22.19,
# а в Debian bookworm он 18. Python здесь — рабочий инструмент агента, а не
# сервиса: им он запускает свои скрипты чтения QR.
FROM node:24-bookworm-slim AS build

WORKDIR /app
COPY qr_vision/package.json qr_vision/package-lock.json ./
# Скрипты пакетов не нужны: pi работает и без postinstall, а чужой код при
# сборке не выполняется.
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY qr_vision/tsconfig.json ./
COPY qr_vision/src ./src
RUN npm run build && npm prune --omit=dev
# npm-shrinkwrap pi тянет бинарники esbuild под все 26 платформ (~285 МБ);
# в образе нужна только своя.
RUN keep="$(node -p 'process.platform + "-" + process.arch')" \
    && find node_modules -path '*/@esbuild/*' -maxdepth 5 -mindepth 4 -type d \
        ! -name "$keep" -prune -exec rm -rf {} +

FROM node:24-bookworm-slim

# Агент работает кодом: bash и Python с библиотеками чтения QR. libzbar0 нужен
# pyzbar, git и ripgrep — стандартным инструментам pi.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip libzbar0 ca-certificates curl git ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY qr_vision/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Модели WeChatQRCode: без них детектор работает в упрощённом режиме. Коммит и
# суммы закреплены — файлы тянутся из чужого репозитория.
ARG WECHAT_MODELS=https://raw.githubusercontent.com/WeChatCV/opencv_3rdparty/3487ef7cde71d93c6a01bb0b84aa0f22c6128f6b
RUN mkdir -p /opt/wechat_qrcode && cd /opt/wechat_qrcode \
    && for f in detect.prototxt detect.caffemodel sr.prototxt sr.caffemodel; do \
        curl -fsSL -o "$f" "$WECHAT_MODELS/$f"; \
    done \
    && printf '%s  %s\n' \
        e8acfc395caf443a47f15686a9b9207b36cb8f7e6ceb8fbaf6466665e68a9466 detect.prototxt \
        cc49b8c9babaf45f3037610fe499df38c8819ebda29e90ca9f2e33270f6ef809 detect.caffemodel \
        8ae41acba97e8b4a8e741ee350481e49b8e01d787193f470a4c95ee1c02d5b61 sr.prototxt \
        e5d36889d8e6ef2f1c1f515f807cec03979320ac81792cd8fb927c31fd658ae3 sr.caffemodel \
        | sha256sum -c -

ENV NODE_ENV=production \
    PORT=8000 \
    PI_CODING_AGENT_DIR=/tmp/pi \
    PI_OFFLINE=1 \
    PI_TELEMETRY=0 \
    PI_SKIP_VERSION_CHECK=1 \
    QR_VISION_WORKSPACE=/workspace \
    WECHAT_QRCODE_MODELS=/opt/wechat_qrcode \
    VIRTUAL_ENV=/workspace/.venv \
    PATH=/workspace/.venv/bin:$PATH

WORKDIR /app
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY qr_vision/package.json ./
COPY qr_vision/entrypoint.sh ./entrypoint.sh

# Том получает владельца от каталога в образе, поэтому он создаётся заранее.
RUN mkdir -p /workspace && chown node:node /workspace
VOLUME /workspace

USER node
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
