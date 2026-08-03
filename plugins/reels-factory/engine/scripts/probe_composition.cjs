#!/usr/bin/env node
/*
 * Проба живой композиции HyperFrames: открыть, отмотать время, снять геометрию.
 *
 * Раскадровку агент пишет как хочет — судим по DOM в отмотанный момент.
 * Всё, что можно повторить их кодом, повторено их кодом:
 *
 *  - перемотка — каскад из `seekCompositionTimeline`
 *    (packages/cli/src/capture/captureCompositionFrame.ts:198-288) с их же
 *    настройками `AUDIT_SEEK_OPTIONS` (там же:14-19), которыми ходит `check`
 *    (packages/cli/src/utils/checkBrowser.ts:351-354). Предпочтительная цель
 *    каскада — `window.__player.renderSeek`: она заодно синхронизирует
 *    видимость `.clip` по `data-start`/`data-duration`, «raw timeline seeks
 *    leave off-window clips visible to audits» (captureCompositionFrame.ts:232-234),
 *    и она же канонична для рендера (packages/core/src/runtime/README.md:43) —
 *    значит DOM совпадёт с кадром;
 *  - готовность страницы — их `__renderReady` + `document.fonts.ready` + пауза
 *    (captureCompositionFrame.ts:89-91, 119-145);
 *  - прямоугольники текста — их собственный сборщик
 *    `window.__hyperframesGeometryCandidates({text:true})` из
 *    packages/cli/src/commands/layout-audit.browser.js:1386-1418: видимость
 *    (opacity/clip-path/checkVisibility), собственный текст, union клиентских
 *    прямоугольников — всё их правилами, а не нашей самоделкой;
 *  - «таймлайн вообще не двигался» — их отпечаток
 *    `window.__hyperframesLayoutGeometry()` (layout-audit.browser.js:1509-1527)
 *    и их же условие `sweep_static` (packages/cli/src/utils/checkPipeline.ts:480-515);
 *  - выдача страницы — как в `hyperframes play`: каталог проекта раздаётся как
 *    есть, рантайм врезается тегом перед `</body>`
 *    (packages/cli/src/utils/compositionServer.ts:66-72, commands/play.ts:227).
 *    Раздаём НЕсобранный index.html намеренно: сборка срезает с хоста
 *    `data-composition-src` (packages/core/src/compiler/inlineSubCompositions.ts:420-421),
 *    а по нему считается гейт подключённых блоков каталога.
 *
 * Сеть не трогаем вообще: и рантайм, и скрипт аудита берутся из уже
 * установленного пакета hyperframes, сервер слушает только 127.0.0.1.
 */
"use strict";

const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");

// Их флаги headless-Chrome для захвата — подмножество
// packages/engine/src/services/browserManager.ts:773-816. Взято то, что влияет
// на геометрию и на то, доиграет ли медиа: гонки шрифтов, троттлинг фоновой
// вкладки и autoplay-политика меняют DOM в момент выборки.
const CHROME_ARGS = [
  "--no-sandbox",
  "--disable-setuid-sandbox",
  "--disable-dev-shm-usage",
  "--font-render-hinting=none",
  "--force-color-profile=srgb",
  "--disable-background-timer-throttling",
  "--disable-backgrounding-occluded-windows",
  "--disable-renderer-backgrounding",
  "--disable-background-media-suspend",
  "--disable-extensions",
  "--disable-component-update",
  "--mute-audio",
  "--autoplay-policy=no-user-gesture-required",
];

// captureCompositionFrame.ts:14-19 — те же значения, что у `check`.
const AUDIT_SEEK = {
  fallbackToBridgeAndTimelines: true,
  animationFrameSettle: "double",
  waitForFontsMs: 500,
  settleMs: 120,
};
const CAPTURE_SETTLE_MS = 1500; // captureCompositionFrame.ts:8
const DEFAULT_VIEWPORT = { width: 1920, height: 1080 }; // compositionViewport.ts:3

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".mov": "video/quicktime",
  ".wav": "audio/wav",
  ".mp3": "audio/mpeg",
  ".m4a": "audio/mp4",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
};

class ProbeError extends Error {}

function parseArgs(argv) {
  const args = { interval: 0.25, timeout: 15000 };
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new ProbeError(`неизвестный аргумент ${key}`);
    const value = argv[i + 1];
    if (value === undefined) throw new ProbeError(`у ${key} нет значения`);
    i += 1;
    if (key === "--project") args.project = value;
    else if (key === "--out") args.out = value;
    else if (key === "--interval") args.interval = Number(value);
    else if (key === "--timeout") args.timeout = Number(value);
    else if (key === "--chrome") args.chrome = value;
    else if (key === "--runtime") args.runtime = value;
    else if (key === "--audit") args.audit = value;
    else if (key === "--hf-version") args.hfVersion = value;
    else throw new ProbeError(`неизвестный флаг ${key}`);
  }
  if (!args.project) throw new ProbeError("не задан --project");
  if (!args.out) throw new ProbeError("не задан --out");
  if (!(args.interval > 0)) throw new ProbeError("--interval должен быть больше нуля");
  return args;
}

/* ---------------------------------------------------------------- пакет */

/** Каталоги, где может лежать распакованный пакет hyperframes. */
function packageRoots() {
  const roots = [];
  const caches = [
    path.join(os.homedir(), "AppData", "Local", "npm-cache", "_npx"),
    path.join(os.homedir(), ".npm", "_npx"),
  ];
  for (const cache of caches) {
    let entries = [];
    try {
      entries = fs.readdirSync(cache);
    } catch {
      continue;
    }
    for (const entry of entries) {
      roots.push(path.join(cache, entry, "node_modules", "hyperframes"));
    }
  }
  roots.push(path.join(os.homedir(), "AppData", "Roaming", "npm", "node_modules", "hyperframes"));
  roots.push("/usr/lib/node_modules/hyperframes");
  roots.push("/usr/local/lib/node_modules/hyperframes");
  return roots.filter((root) => fs.existsSync(path.join(root, "package.json")));
}

/**
 * Файл из dist установленного пакета. Из нескольких копий берём самую свежую
 * версию: скрипт аудита и рантайм должны быть одной сборки, иначе проба меряет
 * одним движком то, что рендерит другой.
 */
function resolveFromPackage(relatives, what, wanted) {
  const found = [];
  for (const root of packageRoots()) {
    let version = "0.0.0";
    try {
      version = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf-8")).version;
    } catch {
      /* версия не читается — сортировка положит копию в конец */
    }
    for (const relative of relatives) {
      const file = path.join(root, relative);
      if (fs.existsSync(file)) {
        found.push({ file, version, root });
        break;
      }
    }
  }
  if (found.length === 0) {
    throw new ProbeError(
      `не найден ${what} ни в одной установленной копии hyperframes; ` +
        "выполни `npx --yes hyperframes@<версия> browser path`, чтобы пакет распаковался",
    );
  }
  const pinned = wanted && found.find((entry) => entry.version === wanted);
  if (pinned) return pinned;
  found.sort((a, b) => compareVersions(b.version, a.version));
  return found[0];
}

function compareVersions(a, b) {
  const pa = String(a).split(".").map(Number);
  const pb = String(b).split(".").map(Number);
  for (let i = 0; i < 3; i += 1) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

/** Chrome для headless. Их `browser path` печатает то же самое. */
function resolveChrome(explicit) {
  const candidates = [];
  if (explicit) candidates.push(explicit);
  if (process.env.PUPPETEER_EXECUTABLE_PATH) {
    candidates.push(process.env.PUPPETEER_EXECUTABLE_PATH);
  }
  if (process.env.CHROME_PATH) candidates.push(process.env.CHROME_PATH);
  candidates.push(
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    path.join(os.homedir(), "AppData", "Local", "Google", "Chrome", "Application", "chrome.exe"),
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  );
  const found = candidates.find((candidate) => candidate && fs.existsSync(candidate));
  if (!found) {
    throw new ProbeError(
      "не найден Chrome для headless; передай --chrome <путь> " +
        "(путь печатает `npx --yes hyperframes@<версия> browser path`)",
    );
  }
  return found;
}

/* ---------------------------------------------------------------- сервер */

/** Уже врезанный рантайм: htmlDocument.ts:5-22 — их же маркеры. */
const RUNTIME_MARKERS = [
  "hyperframe.runtime.iife.js",
  "hyperframes-runtime.modular.inline.js",
  "hyperframe-runtime.modular-runtime.inline.js",
  "data-hyperframes-preview-runtime",
  "__hyperframeRuntimeBootstrapped",
  "__hyperframeRuntime",
  "window.__player =",
];

/** compositionServer.ts:66-72 — тег рантайма перед `</body>`. */
function injectRuntime(html) {
  if (RUNTIME_MARKERS.some((marker) => html.includes(marker))) return html;
  const tag = '<script src="/__hf-runtime.js"></script>';
  return html.includes("</body>") ? html.replace("</body>", `${tag}\n</body>`) : `${html}\n${tag}`;
}

/** compositionViewport.ts:19-28 — размеры берём с корня композиции. */
function viewportFromHtml(html) {
  const root = /<[^>]*data-composition-id[^>]*>/gi;
  let match;
  while ((match = root.exec(html)) !== null) {
    const tag = match[0];
    const width = /data-width\s*=\s*"(\d+)"/i.exec(tag);
    const height = /data-height\s*=\s*"(\d+)"/i.exec(tag);
    if (width && height) {
      return {
        width: Math.min(Number(width[1]), 4096),
        height: Math.min(Number(height[1]), 4096),
      };
    }
  }
  return { ...DEFAULT_VIEWPORT };
}

/**
 * Раздача каталога проекта с поддержкой Range: без неё Chrome считает медиа
 * неперематываемым и не отдаёт длительность (staticProjectServer.ts:27-33).
 */
function serveProject(projectDir, indexHtml, runtimeFile) {
  const server = http.createServer((req, res) => {
    const url = req.url || "/";
    const pathOnly = decodeURIComponent(url.split("?")[0]);
    if (pathOnly === "/" || pathOnly === "/index.html") {
      res.writeHead(200, { "Content-Type": MIME[".html"] });
      res.end(indexHtml);
      return;
    }
    if (pathOnly === "/__hf-runtime.js") {
      res.writeHead(200, { "Content-Type": MIME[".js"] });
      res.end(fs.readFileSync(runtimeFile));
      return;
    }
    const file = path.resolve(projectDir, pathOnly.replace(/^\/+/, ""));
    const relative = path.relative(projectDir, file);
    if (relative.startsWith("..") || path.isAbsolute(relative) || !fs.existsSync(file)) {
      res.writeHead(404);
      res.end();
      return;
    }
    serveWithRange(file, req.headers.range, res);
  });

  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({
        url: `http://127.0.0.1:${port}/`,
        close: () => new Promise((done) => server.close(() => done())),
      });
    });
  });
}

function serveWithRange(file, rangeHeader, res) {
  const size = fs.statSync(file).size;
  const type = MIME[path.extname(file).toLowerCase()] || "application/octet-stream";
  const headers = { "Content-Type": type, "Accept-Ranges": "bytes" };
  const last = size - 1;
  let start = 0;
  let end = last;
  let status = 200;
  const match = rangeHeader ? /^bytes=(\d*)-(\d*)$/.exec(String(rangeHeader).trim()) : null;
  if (match) {
    const hasStart = match[1] !== "";
    start = hasStart ? Number(match[1]) : Math.max(0, size - Number(match[2]));
    end = !hasStart ? last : match[2] !== "" ? Math.min(Number(match[2]), last) : last;
    if (start > end || start > last) {
      res.writeHead(416, { ...headers, "Content-Range": `bytes */${size}` });
      res.end();
      return;
    }
    status = 206;
    headers["Content-Range"] = `bytes ${start}-${end}/${size}`;
  }
  headers["Content-Length"] = String(end - start + 1);
  const stream = fs.createReadStream(file, { start, end });
  stream.on("open", () => {
    res.writeHead(status, headers);
    stream.pipe(res);
  });
  stream.on("error", () => {
    if (!res.headersSent) res.writeHead(500);
    res.end();
    stream.destroy();
  });
}

/* ------------------------------------------------------------ перемотка */

/**
 * Каскад целей перемотки, слово в слово по captureCompositionFrame.ts:207-257.
 * Повторён здесь, а не импортирован, потому что их CLI — TypeScript-исходники
 * без публичного входа для node; менять порядок целей нельзя: он и решает,
 * совпадёт ли DOM с кадром рендера.
 */
async function seekCompositionTimeline(page, timeSeconds) {
  await page.evaluate(
    (t, fallbackToBridgeAndTimelines) => {
      const getProperty = (target, key) => {
        if ((typeof target !== "object" || target === null) && typeof target !== "function") {
          return undefined;
        }
        return Reflect.get(target, key);
      };
      const call = (fn, receiver, args) => {
        if (typeof fn !== "function") return false;
        Reflect.apply(fn, receiver, args);
        return true;
      };

      const player = Reflect.get(window, "__player");
      if (!player && !fallbackToBridgeAndTimelines) return;

      const safe = Math.max(0, Number(t) || 0);
      const renderSeek = getProperty(player, "renderSeek");
      const playerSeek = getProperty(player, "seek");
      const hf = Reflect.get(window, "__hf");
      const bridgeSeek = getProperty(hf, "seek");

      if (call(renderSeek, player, [safe])) {
        // предпочтительная цель: заодно синхронизирует видимость клипов
      } else if (fallbackToBridgeAndTimelines && call(bridgeSeek, hf, [safe])) {
        // мост продюсера
      } else if (call(playerSeek, player, [safe])) {
        // старый плеер
      } else if (fallbackToBridgeAndTimelines) {
        const timelines = Reflect.get(window, "__timelines");
        if (typeof timelines === "object" && timelines !== null) {
          for (const key of Object.keys(timelines)) {
            const timeline = Reflect.get(timelines, key);
            call(getProperty(timeline, "pause"), timeline, []);
            call(getProperty(timeline, "seek"), timeline, [safe]);
          }
        }
      }

      const gsap = Reflect.get(window, "gsap");
      const ticker = getProperty(gsap, "ticker");
      call(getProperty(ticker, "tick"), ticker, []);
    },
    timeSeconds,
    AUDIT_SEEK.fallbackToBridgeAndTimelines,
  );

  await page.evaluate(
    () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))),
  );
  await waitForCompositionFonts(page, AUDIT_SEEK.waitForFontsMs);
  await new Promise((done) => setTimeout(done, AUDIT_SEEK.settleMs));
}

/** captureCompositionFrame.ts:315-350 — перемотка может открыть новые глифы. */
async function waitForCompositionFonts(page, timeoutMs) {
  await page
    .evaluate((ms) => {
      const fonts = Reflect.get(document, "fonts");
      if (typeof fonts !== "object" || fonts === null) return Promise.resolve();
      void document.body?.offsetHeight;
      return new Promise((done) => {
        const deadline = setTimeout(done, ms);
        requestAnimationFrame(() => {
          const status = Reflect.get(fonts, "status");
          const ready = Reflect.get(fonts, "ready");
          if (status !== "loading" || !ready) {
            clearTimeout(deadline);
            done();
            return;
          }
          Promise.resolve(ready).then(() => {
            clearTimeout(deadline);
            done();
          });
        });
      });
    }, timeoutMs)
    .catch(() => {});
}

/** captureCompositionFrame.ts:290-313 — дождаться появления renderSeek. */
async function waitForPreferredSeekTarget(page, timeoutMs) {
  try {
    await page.waitForFunction(
      () => {
        const player = Reflect.get(window, "__player");
        const hf = Reflect.get(window, "__hf");
        const renderSeek =
          typeof player === "object" && player !== null
            ? Reflect.get(player, "renderSeek")
            : undefined;
        const bridgeSeek = typeof hf === "object" && hf !== null ? Reflect.get(hf, "seek") : undefined;
        return typeof renderSeek === "function" || typeof bridgeSeek === "function";
      },
      { timeout: timeoutMs },
    );
    return true;
  } catch {
    return false;
  }
}

/** checkBrowser.ts:380-411 — тот же каскад источников длительности. */
async function compositionDuration(page) {
  return page.evaluate(() => {
    const value = (target, key) =>
      typeof target === "object" && target !== null ? Reflect.get(target, key) : undefined;
    const positive = (candidate) =>
      typeof candidate === "number" && candidate > 0 ? candidate : null;
    const callDuration = (target) => {
      const duration = value(target, "duration");
      if (typeof duration === "function") return positive(Reflect.apply(duration, target, []));
      return positive(duration);
    };
    const hfDuration = positive(value(Reflect.get(window, "__hf"), "duration"));
    if (hfDuration) return hfDuration;
    const playerDuration = callDuration(Reflect.get(window, "__player"));
    if (playerDuration) return playerDuration;
    const root = document.querySelector("[data-composition-id][data-duration]");
    const authored = root ? parseFloat(root.getAttribute("data-duration") || "0") : 0;
    if (authored > 0) return authored;
    const timelines = Reflect.get(window, "__timelines");
    if (typeof timelines !== "object" || timelines === null) return 0;
    for (const key of Object.keys(timelines)) {
      const duration = callDuration(Reflect.get(timelines, key));
      if (duration) return duration;
    }
    return 0;
  });
}

/* -------------------------------------------------------------- выборка */

/** Одна выборка: всё, что видно на экране в момент t. */
async function collectSample(page) {
  return page.evaluate(() => {
    const rect = (element) => {
      const box = element.getBoundingClientRect();
      return {
        left: box.left,
        top: box.top,
        width: box.width,
        height: box.height,
        right: box.right,
        bottom: box.bottom,
      };
    };

    // Окно ведущей. Сначала их же договорённость `#video-wrap`
    // (talking-head-recut/references/DESIGN_INDEX.md:27), потом — обёртка
    // любого <video>: у неё overflow:hidden, и именно её границы видит зритель,
    // а не бокс самого <video>.
    const presenterElement = () => {
      const wrap = document.querySelector("#video-wrap");
      if (wrap) return { element: wrap, how: "#video-wrap" };
      const videos = Array.from(document.querySelectorAll("video"));
      const clip = videos.find((v) => /(^|\/)clips\//.test(v.getAttribute("src") || ""));
      const video = clip || videos[0];
      if (!video) return null;
      const parent = video.parentElement;
      const wrapped =
        parent && parent !== document.body && getComputedStyle(parent).overflow !== "visible"
          ? parent
          : video;
      return { element: wrapped, how: clip ? "video[src^=clips/]" : "video" };
    };

    const presenter = presenterElement();
    // `visible` нужен гейту лица: где ведущей на экране нет (аватар на этот
    // кусок не заказан — движок прячет <video> вне его окна), проверять
    // перекрытие лица нечем и незачем.
    const presenterVisible = (element) => {
      const box = element.getBoundingClientRect();
      if (box.width <= 0.5 || box.height <= 0.5) return false;
      for (let node = element; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.display === "none" || style.visibility === "hidden") return false;
        const opacity = Number.parseFloat(style.opacity || "1");
        if (Number.isFinite(opacity) && opacity < 0.2) return false;
      }
      return true;
    };
    const presenterVideo = presenter
      ? presenter.element.querySelector("video") || presenter.element
      : null;
    const videoRect = presenter
      ? {
          ...rect(presenter.element),
          source: presenter.how,
          tag: presenter.element.tagName.toLowerCase(),
          visible: presenterVisible(presenter.element) && presenterVisible(presenterVideo),
        }
      : null;

    // Текст — их сборщик, целиком их правилами видимости и их же union
    // клиентских прямоугольников (layout-audit.browser.js:1386-1418).
    const collect = Reflect.get(window, "__hyperframesGeometryCandidates");
    if (typeof collect !== "function") {
      return { error: "__hyperframesGeometryCandidates не определён — скрипт аудита не встал" };
    }
    const texts = collect({ text: true, media: false, tolerance: 2 })
      .filter((candidate) => candidate.kind === "text")
      .map((candidate) => ({
        selector: candidate.selector,
        tag: candidate.tag,
        text: candidate.text,
        rect: candidate.rect,
        elementRect: candidate.elementRect,
        sourceFile: candidate.sourceFile,
      }));

    // Клипы: что движок обязан показать/спрятать по data-start/data-duration.
    const clips = Array.from(document.querySelectorAll(".clip")).map((element) => {
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      let opacity = 1;
      for (let node = element; node; node = node.parentElement) {
        const parsed = Number.parseFloat(getComputedStyle(node).opacity || "1");
        if (Number.isFinite(parsed)) opacity *= parsed;
      }
      return {
        id: element.id || null,
        tag: element.tagName.toLowerCase(),
        cardId: element.getAttribute("data-card-id"),
        start: Number.parseFloat(element.getAttribute("data-start") || "0"),
        duration: Number.parseFloat(element.getAttribute("data-duration") || "0"),
        visible:
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          style.visibility !== "collapse" &&
          opacity >= 0.2 &&
          box.width > 0.5 &&
          box.height > 0.5,
        rect: rect(element),
      };
    });

    // Подключённые блоки. `data-composition-src` живёт в несобранном
    // index.html; после их сборки хост несёт `data-composition-file`
    // (inlineSubCompositions.ts:420-421) — принимаем оба, иначе гейт зависел бы
    // от того, собран проект или нет.
    const sources = new Set();
    for (const host of document.querySelectorAll("[data-composition-src]")) {
      sources.add(host.getAttribute("data-composition-src"));
    }
    for (const host of document.querySelectorAll("[data-composition-file]")) {
      sources.add(host.getAttribute("data-composition-file"));
    }

    const fingerprint = Reflect.get(window, "__hyperframesLayoutGeometry");
    return {
      videoRect,
      texts,
      clips,
      compositionSrc: Array.from(sources),
      fingerprint: typeof fingerprint === "function" ? fingerprint() : null,
      canvas: { width: window.innerWidth, height: window.innerHeight },
    };
  });
}

/* ----------------------------------------------------------------- ход */

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const projectDir = path.resolve(args.project);
  const indexPath = path.join(projectDir, "index.html");
  if (!fs.existsSync(indexPath)) {
    throw new ProbeError(`нет композиции: ${indexPath}`);
  }

  const rawHtml = fs.readFileSync(indexPath, "utf-8");
  const viewport = viewportFromHtml(rawHtml);
  const runtime = args.runtime
    ? { file: args.runtime, version: "override" }
    : resolveFromPackage(
        [
          path.join("dist", "hyperframe-runtime.js"),
          path.join("dist", "hyperframe.runtime.iife.js"),
        ],
        "рантайм hyperframe.runtime.iife.js",
        args.hfVersion,
      );
  const audit = args.audit
    ? { file: args.audit, version: "override" }
    : resolveFromPackage(
        [path.join("dist", "commands", "layout-audit.browser.js")],
        "скрипт аудита layout-audit.browser.js",
        args.hfVersion,
      );
  const chrome = resolveChrome(args.chrome);

  const server = await serveProject(projectDir, injectRuntime(rawHtml), runtime.file);
  const puppeteer = require("puppeteer-core");
  let browser;
  const consoleErrors = [];
  const failedRequests = [];

  try {
    browser = await puppeteer.launch({
      headless: true,
      executablePath: chrome,
      args: [...CHROME_ARGS, `--window-size=${viewport.width},${viewport.height}`],
    });
    const page = await browser.newPage();
    // captureCompositionFrame.ts:154-158 — иначе сериализованные замыкания
    // падают на `__name is not defined`.
    await page.evaluateOnNewDocument("self.__name = self.__name || ((fn) => fn);");
    await page.setViewport(viewport);
    page.on("pageerror", (error) => consoleErrors.push(String(error && error.message) || String(error)));
    page.on("console", (message) => {
      // «Failed to load resource» их `check` в ошибки не пишет
      // (checkBrowser.ts:271) — сетевые сбои учитываются отдельным слушателем.
      if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) {
        consoleErrors.push(message.text());
      }
    });
    page.on("requestfailed", (request) => {
      const url = request.url();
      if (url.includes("favicon") || url.startsWith("data:")) return;
      const errorText = (request.failure() || {}).errorText;
      // ERR_ABORTED на медиа — норма: Chrome бросает загрузку при перемотке
      // (их же исключение, validate.ts:77-89).
      if (
        errorText === "net::ERR_ABORTED" &&
        (request.resourceType() === "media" || /\.(mp4|webm|mov|m4v|wav|mp3|m4a|ogg)$/i.test(url))
      ) {
        return;
      }
      failedRequests.push(`${url}: ${errorText || "ERR_FAILED"}`);
    });
    page.on("response", (response) => {
      const url = response.url();
      if (response.status() < 400 || url.includes("favicon")) return;
      failedRequests.push(`${url}: HTTP ${response.status()}`);
    });

    await page.goto(server.url, { waitUntil: "domcontentloaded", timeout: Math.max(10000, args.timeout) });

    // captureCompositionFrame.ts:119-145 — готовность рантайма, шрифты, пауза.
    const renderReady = await page
      .waitForFunction(() => Boolean(Reflect.get(window, "__renderReady")), { timeout: args.timeout })
      .then(() => true)
      .catch(() => false);
    await page.evaluate(() => document.fonts.ready).catch(() => {});
    await new Promise((done) => setTimeout(done, CAPTURE_SETTLE_MS));

    const seekTargetReady = await waitForPreferredSeekTarget(page, 500);
    await page.addScriptTag({ content: fs.readFileSync(audit.file, "utf-8") });

    const duration = await compositionDuration(page);
    if (!(duration > 0)) {
      throw new ProbeError(
        "композиция не сообщила длительность: ни __hf.duration, ни __player, " +
          "ни data-duration на корне, ни __timelines — мерить нечего",
      );
    }

    const times = [];
    for (let t = 0; t < duration; t += args.interval) times.push(Number(t.toFixed(3)));
    const lastFrame = Number(Math.max(0, duration - 0.001).toFixed(3));
    if (times[times.length - 1] !== lastFrame) times.push(lastFrame);

    const samples = [];
    for (const time of times) {
      await seekCompositionTimeline(page, time);
      const sample = await collectSample(page);
      if (sample.error) throw new ProbeError(sample.error);
      samples.push({ time, ...sample });
    }

    // Их условие sweep_static (checkPipeline.ts:480-515): один и тот же
    // отпечаток на всех выборках означает, что таймлайн не двигался и любой
    // зелёный вердикт этого прогона недостоверен.
    const prints = samples.map((sample) => sample.fingerprint).filter((print) => print !== null);
    const sweepStatic =
      duration >= 3 && prints.length >= 2 && prints.every((print) => print === prints[0]);

    const report = {
      project: projectDir,
      viewport,
      duration,
      interval: args.interval,
      renderReady,
      seekTargetReady,
      sweepStatic,
      runtime: { file: runtime.file, version: runtime.version },
      audit: { file: audit.file, version: audit.version },
      // Просили одну версию, нашли другую: проба мерит не тем движком, каким
      // пойдёт рендер. Не обрываем прогон, но записываем — иначе расхождение
      // всплывёт только на готовом ролике.
      versionMismatch:
        args.hfVersion && runtime.version !== args.hfVersion
          ? `просили ${args.hfVersion}, взяли ${runtime.version}`
          : null,
      chrome,
      consoleErrors,
      failedRequests,
      compositionSrc: Array.from(new Set(samples.flatMap((sample) => sample.compositionSrc))),
      samples,
    };
    fs.mkdirSync(path.dirname(path.resolve(args.out)), { recursive: true });
    fs.writeFileSync(path.resolve(args.out), JSON.stringify(report, null, 1), "utf-8");
    process.stdout.write(
      `${samples.length} выборок за ${duration.toFixed(2)}с → ${path.resolve(args.out)}\n`,
    );
  } finally {
    if (browser) await browser.close().catch(() => {});
    await server.close();
  }
}

main().catch((error) => {
  process.stderr.write(`проба композиции не состоялась: ${error && error.message ? error.message : error}\n`);
  process.exit(1);
});
