// Сайдкар чтения QR с фотографии чека моделью — фолбек для checks_service.
//
// checks_service сначала читает QR сам (zxing-cpp), и сюда фото попадает,
// только когда это не удалось. Модель просят вернуть содержимое QR как есть;
// годится ли строка, решает не она, а реестр форматов checks_service, а затем
// пользователь, подтверждающий плашку.
//
// Харнесс — pi (TypeScript SDK): у него нет SDK для Python, поэтому он живёт
// отдельным процессом, а checks_service ходит сюда по HTTP внутри docker-сети.
// Наружу порт не выведен: ключ OpenRouter есть только у этого контейнера, и
// звать модель за его счёт может лишь тот, кто уже внутри сети.
//
// Агент работает кодом, а не взглядом: модель почти не читает QR по пикселям,
// зато умеет запустить декодер и подобрать предобработку. Поэтому у неё полный
// набор инструментов pi (read, bash, edit, write) и Python с zxing-cpp, OpenCV
// WeChatQRCode и pyzbar.
//
// /workspace — постоянный том. Скрипты, которые агент написал (`scripts/`),
// библиотеки, которые он доставил (`.venv`), и его заметки (`NOTES.md`)
// переживают запрос и пересоздание контейнера: следующий запрос начинает не с
// нуля. Список скриптов и заметки сайдкар сам дописывает в промпт.
//
// ПРИНЯТЫЕ РИСКИ. bash не ограничен, а фото — чужой ввод: текст на нём может
// оказаться инструкцией для модели. Ключ OpenRouter лежит в окружении процесса
// и командам агента доступен; подложенный в `scripts/` файл выполнится и на
// следующих запросах. Сдерживает это список допуска checks_service и отдельный
// ключ OpenRouter с лимитом расходов (см. README).
//
// Каждый запрос — своя сессия pi в памяти: без расширений, скиллов и
// контекст-файлов. Запросы идут по одному — рабочий каталог у них общий.

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { randomUUID } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import {
    createAgentSession,
    createExtensionRuntime,
    ModelRuntime,
    type ResourceLoader,
    SessionManager,
    SettingsManager,
} from "@earendil-works/pi-coding-agent";

const PORT = Number(process.env.PORT ?? 8000);
const PROVIDER = "openrouter";
const MODEL_ID = process.env.QR_VISION_MODEL ?? "anthropic/claude-opus-5.5";
const API_KEY = process.env.OPENROUTER_API_KEY ?? "";
// Каталог pi: сюда SDK пишет служебные файлы. Временный — состояния между
// запросами сервис не держит.
const AGENT_DIR = process.env.PI_CODING_AGENT_DIR ?? "/tmp/pi";
// Постоянный рабочий каталог агента (том): scripts/, .venv, NOTES.md.
const WORKSPACE = process.env.QR_VISION_WORKSPACE ?? "/workspace";
const SCRIPTS_DIR = join(WORKSPACE, "scripts");
const REQUESTS_DIR = join(WORKSPACE, "requests");
const NOTES_PATH = join(WORKSPACE, "NOTES.md");
const WECHAT_MODELS = process.env.WECHAT_QRCODE_MODELS ?? "/opt/wechat_qrcode";
// Агент делает несколько ходов: посмотреть, написать скрипт, запустить,
// поправить. Меньше таймаута checks_service (120 с): ответить «не вышло» лучше,
// чем оборвать соединение на середине и оставить расход без учёта. Ожидание в
// очереди входит в этот же срок.
const TIMEOUT_MS = Number(process.env.QR_VISION_TIMEOUT_MS ?? 110_000);
// Сколько заметок и имён скриптов уезжает в промпт: память агента не должна
// съедать контекст и деньги каждого запроса.
const MAX_NOTES_CHARS = 6_000;
const MAX_SCRIPTS_LISTED = 60;
const EXTENSIONS: Record<string, string> = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
};
// Фото до 5 МБ, в base64 это ~6.7 МБ, плюс JSON вокруг.
const MAX_BODY_BYTES = 7 * 1024 * 1024;
const MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);

const SYSTEM_PROMPT = `You extract the text encoded in the QR code of a fiscal receipt photo.

You almost never can read a QR code by looking at it, so decode it with code. You have bash and
Python in a persistent workspace:
- ${WORKSPACE} is your working directory and it persists between requests.
- ${WORKSPACE}/.venv is the active Python environment (python, pip on PATH). Installed:
  zxing-cpp (import zxingcpp), opencv-contrib-python-headless (import cv2), pyzbar, pillow, numpy.
  WeChatQRCode model files: ${WECHAT_MODELS}/detect.prototxt, detect.caffemodel, sr.prototxt,
  sr.caffemodel — pass all four to cv2.wechat_qrcode_WeChatQRCode(...).
  You may pip install anything else; it stays installed for later requests.
- ${SCRIPTS_DIR} holds scripts written on earlier requests. Try them first. When you write a
  script that works or is worth reusing, save it there (take the image path as an argument).
- ${NOTES_PATH} is your memory: keep it short and current — what works, what does not, how to
  call your scripts. Update it when you learn something.
- The photo of this request is saved as a file; its path is in the user message. Put temporary
  files next to it — that directory is deleted after the request.

Try several decoders and, if they fail, preprocessing: crop to the QR, upscale, grayscale,
contrast, thresholding, sharpening, rotation, inversion. You have about 90 seconds in total, so
start with what already works and do not waste turns.

Return the decoded text exactly as decoded, character for character, without adding, removing or
normalising anything. Never guess and never reconstruct the text from anything else printed on
the receipt: a made-up string is worse than no answer.

Your final message must be a single JSON object and nothing else:
{"qr": "<the decoded text>"} — when a decoder actually returned it;
{"qr": null} — when nothing could decode it.`;

// Память агента: что уже лежит в scripts/ и что он записал в NOTES.md.
function workspaceMemory(): string {
    let scripts: string[] = [];
    try {
        scripts = readdirSync(SCRIPTS_DIR).sort();
    } catch {
        // Каталога ещё нет — скриптов нет.
    }
    let notes = "";
    try {
        notes = readFileSync(NOTES_PATH, "utf-8").trim();
    } catch {
        // Заметок ещё нет.
    }
    const listed = scripts.slice(0, MAX_SCRIPTS_LISTED);
    const more = scripts.length > listed.length ? `\n(and ${scripts.length - listed.length} more)` : "";
    return [
        `Scripts in ${SCRIPTS_DIR}:`,
        listed.length > 0 ? listed.join("\n") + more : "(none yet)",
        "",
        `${NOTES_PATH}:`,
        notes ? notes.slice(0, MAX_NOTES_CHARS) : "(empty)",
    ].join("\n");
}

function userPrompt(imagePath: string): string {
    return `The receipt photo is attached and saved at ${imagePath}.

${workspaceMemory()}

Decode the receipt's QR code and answer with the JSON object.`;
}

// Ресурсы pi не ищутся ни на диске, ни в окружении: расширений, скиллов и
// контекст-файлов нет. Память агента — только то, что сайдкар сам кладёт в
// промпт (см. `workspaceMemory`).
const resourceLoader: ResourceLoader = {
    getExtensions: () => ({ extensions: [], errors: [], runtime: createExtensionRuntime() }),
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => SYSTEM_PROMPT,
    getSystemPromptSource: () => undefined,
    getAppendSystemPrompt: () => [],
    getAppendSystemPromptSources: () => [],
    extendResources: () => {},
    reload: async () => {},
};

interface UsageTotals {
    input: number;
    output: number;
    cacheRead: number;
    cacheWrite: number;
    totalTokens: number;
    cost: number;
}

interface DecodeResult {
    qr: string | null;
    model: string | null;
    usage: UsageTotals | null;
    // Сколько раз ответила модель: один ход — это один оплаченный запрос.
    turns: number;
}

interface AssistantLike {
    role: "assistant";
    model?: string;
    responseModel?: string;
    stopReason?: string;
    errorMessage?: string;
    usage?: {
        input: number;
        output: number;
        cacheRead: number;
        cacheWrite: number;
        totalTokens: number;
        cost?: { total: number };
    };
}

function log(message: string, extra: Record<string, unknown> = {}): void {
    process.stderr.write(JSON.stringify({ ts: new Date().toISOString(), message, ...extra }) + "\n");
}

async function createRuntime(): Promise<ModelRuntime> {
    mkdirSync(AGENT_DIR, { recursive: true });
    const runtime = await ModelRuntime.create({
        authPath: `${AGENT_DIR}/auth.json`,
        modelsPath: null,
        // Модель есть во встроенном каталоге pi; ходить за обновлением каталога
        // в сеть на старте контейнера незачем.
        allowModelNetwork: false,
        refreshOnCreate: false,
    });
    await runtime.setRuntimeApiKey(PROVIDER, API_KEY);
    return runtime;
}

// Все ответы ассистента за сессию: pi сам повторяет упавший запрос, и платим
// мы за каждую попытку, а не только за последнюю.
function assistantMessages(messages: readonly unknown[]): AssistantLike[] {
    return messages.filter(
        (message): message is AssistantLike =>
            typeof message === "object" && message !== null && (message as { role?: unknown }).role === "assistant",
    );
}

function sumUsage(messages: AssistantLike[]): UsageTotals | null {
    const withUsage = messages.filter((message) => message.usage);
    if (withUsage.length === 0) {
        return null;
    }
    const totals: UsageTotals = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: 0 };
    for (const { usage } of withUsage) {
        totals.input += usage!.input;
        totals.output += usage!.output;
        totals.cacheRead += usage!.cacheRead;
        totals.cacheWrite += usage!.cacheWrite;
        totals.totalTokens += usage!.totalTokens;
        totals.cost += usage!.cost?.total ?? 0;
    }
    return totals;
}

// Модель иногда оборачивает JSON в ```json … ``` вопреки промпту.
export function parseAnswer(text: string | undefined): string | null {
    if (!text) {
        return null;
    }
    const unfenced = text.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
    try {
        const parsed: unknown = JSON.parse(unfenced);
        if (typeof parsed === "object" && parsed !== null) {
            const qr = (parsed as { qr?: unknown }).qr;
            if (typeof qr === "string" && qr.length > 0) {
                return qr;
            }
        }
    } catch {
        // Не JSON — считаем, что прочитать не вышло.
    }
    return null;
}

// Запросы идут по одному: скрипты, заметки и .venv у них общие, и два агента
// разом правили бы одно и то же.
let queue: Promise<unknown> = Promise.resolve();

function inTurn<T>(task: () => Promise<T>): Promise<T> {
    const run = queue.then(task, task);
    queue = run.catch(() => undefined);
    return run;
}

async function decode(
    runtime: ModelRuntime,
    image: string,
    mimeType: string,
    deadline: number,
): Promise<DecodeResult> {
    const model = runtime.getModel(PROVIDER, MODEL_ID);
    if (!model) {
        throw new Error(`Модель ${PROVIDER}/${MODEL_ID} не найдена в каталоге pi`);
    }
    // Очередь могла съесть весь срок: начинать работу, за которую заплатим, но
    // ответа которой уже никто не ждёт, незачем.
    if (deadline - Date.now() < 5_000) {
        throw new HttpError(503, "busy");
    }

    // Фото — файлом: декодерам нужен путь, а не картинка в сообщении. Каталог
    // запроса временный и удаляется вместе со всем, что агент рядом положил.
    const requestDir = join(REQUESTS_DIR, randomUUID());
    mkdirSync(requestDir, { recursive: true });
    const imagePath = join(requestDir, `receipt.${EXTENSIONS[mimeType]}`);
    writeFileSync(imagePath, Buffer.from(image, "base64"));

    const { session } = await createAgentSession({
        cwd: WORKSPACE,
        agentDir: AGENT_DIR,
        model,
        // Ниже `low` эта модель не умеет: `off` и `minimal` у неё не определены.
        thinkingLevel: "low",
        modelRuntime: runtime,
        resourceLoader,
        tools: ["read", "bash", "edit", "write"],
        sessionManager: SessionManager.inMemory(WORKSPACE),
        settingsManager: SettingsManager.inMemory({
            compaction: { enabled: false },
            retry: { enabled: true, maxRetries: 1 },
        }),
    });

    const timer = setTimeout(() => {
        void session.abort();
    }, deadline - Date.now());
    try {
        await session.prompt(userPrompt(imagePath), {
            expandPromptTemplates: false,
            images: [{ type: "image", data: image, mimeType }],
        });

        const answers = assistantMessages(session.messages);
        const last = answers.at(-1);
        if (last?.stopReason === "error" || last?.stopReason === "aborted") {
            log("Агент не закончил", { stopReason: last.stopReason, error: last.errorMessage });
        }
        return {
            qr: last?.stopReason === "stop" ? parseAnswer(session.getLastAssistantText()) : null,
            model: last?.responseModel ?? last?.model ?? null,
            usage: sumUsage(answers),
            turns: answers.length,
        };
    } finally {
        clearTimeout(timer);
        session.dispose();
        rmSync(requestDir, { recursive: true, force: true });
    }
}

async function readBody(request: IncomingMessage): Promise<Buffer> {
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const chunk of request) {
        size += (chunk as Buffer).length;
        if (size > MAX_BODY_BYTES) {
            throw new HttpError(413, "body_too_large");
        }
        chunks.push(chunk as Buffer);
    }
    return Buffer.concat(chunks);
}

class HttpError extends Error {
    constructor(
        readonly status: number,
        readonly code: string,
    ) {
        super(code);
    }
}

function send(response: ServerResponse, status: number, body: unknown): void {
    response.writeHead(status, { "Content-Type": "application/json" });
    response.end(JSON.stringify(body));
}

async function handleDecode(runtime: ModelRuntime, request: IncomingMessage, response: ServerResponse): Promise<void> {
    let payload: { image?: unknown; mimeType?: unknown };
    try {
        payload = JSON.parse((await readBody(request)).toString("utf-8"));
    } catch (error) {
        if (error instanceof HttpError) {
            throw error;
        }
        throw new HttpError(400, "invalid_json");
    }
    const { image, mimeType } = payload;
    if (typeof image !== "string" || image.length === 0) {
        throw new HttpError(400, "image_required");
    }
    if (typeof mimeType !== "string" || !MIME_TYPES.has(mimeType)) {
        throw new HttpError(400, "unsupported_mime_type");
    }

    const started = Date.now();
    const deadline = started + TIMEOUT_MS;
    const { turns, ...result } = await inTurn(() => decode(runtime, image, mimeType, deadline));
    log("Фото обработано", {
        found: result.qr !== null,
        model: result.model,
        turns,
        cost: result.usage?.cost,
        ms: Date.now() - started,
    });
    send(response, 200, result);
}

async function main(): Promise<void> {
    if (!API_KEY) {
        throw new Error("OPENROUTER_API_KEY не задан");
    }
    mkdirSync(SCRIPTS_DIR, { recursive: true });
    mkdirSync(REQUESTS_DIR, { recursive: true });
    const runtime = await createRuntime();
    if (!runtime.getModel(PROVIDER, MODEL_ID)) {
        throw new Error(`Модель ${PROVIDER}/${MODEL_ID} не найдена в каталоге pi`);
    }

    const server = createServer((request, response) => {
        const route = `${request.method} ${request.url}`;
        if (route === "GET /health") {
            send(response, 200, { status: "ok" });
            return;
        }
        if (route !== "POST /decode") {
            send(response, 404, { code: "not_found" });
            return;
        }
        handleDecode(runtime, request, response).catch((error: unknown) => {
            if (error instanceof HttpError) {
                send(response, error.status, { code: error.code });
                return;
            }
            log("Сбой обработки фото", { error: String(error) });
            send(response, 502, { code: "model_failed" });
        });
    });
    server.listen(PORT, () =>
        log("qr-vision слушает", { port: PORT, model: `${PROVIDER}/${MODEL_ID}`, workspace: WORKSPACE }),
    );
}

main().catch((error: unknown) => {
    log("Не удалось запуститься", { error: String(error) });
    process.exit(1);
});
