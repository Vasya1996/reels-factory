#!/usr/bin/env node
/*
 * Ширина нарисованного внутри позиции каталога — на её родном канвасе, до
 * всякого масштаба.
 *
 * Открывает готовую копию позиции (`_stage_overlay` в hf_compose.py уже
 * вписал в неё слова плана) файлом `file://`, ставит вьюпорт её родным
 * канвасом, отматывает таймлайн на секунду устоявшегося кадра — вход давно
 * закончился, выход ещё не начался — и меряет объединённый прямоугольник
 * всего НАРИСОВАННОГО внутри `#root`.
 *
 * «Нарисовано» — тот же вопрос и тот же ответ, что у `drawn` в
 * `probe_composition.cjs` (`nodeShown`/`nodePaints`): видимость по
 * display/visibility/opacity-цепочке, краска — картинка/видео/канвас/SVG,
 * заливка или свой текстовый узел. Там это булев вопрос «нарисовано ли хоть
 * что-то», здесь — объединённый прямоугольник, но правило одно и то же, и
 * держим его тем же кодом, а не отдельной догадкой.
 *
 * Ни сервера, ни их рантайма, ни их аудита: копия — самодостаточный файл
 * (свой GSAP, свой скрипт, свои стили), и `document.fonts.ready` плюс сама
 * позиция — всё, что нужно для устоявшегося кадра.
 */
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const CHROME_ARGS = [
  "--no-sandbox",
  "--disable-setuid-sandbox",
  "--disable-dev-shm-usage",
  "--font-render-hinting=none",
  "--force-color-profile=srgb",
  "--disable-extensions",
  "--disable-component-update",
  "--mute-audio",
  "--autoplay-policy=no-user-gesture-required",
];

class MeasureError extends Error {}

function parseArgs(argv) {
  const args = { at: null };
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new MeasureError(`неизвестный аргумент ${key}`);
    const value = argv[i + 1];
    if (value === undefined) throw new MeasureError(`у ${key} нет значения`);
    i += 1;
    if (key === "--file") args.file = value;
    else if (key === "--width") args.width = Number(value);
    else if (key === "--height") args.height = Number(value);
    else if (key === "--at") args.at = Number(value);
    else if (key === "--chrome") args.chrome = value;
    else throw new MeasureError(`неизвестный аргумент ${key}`);
  }
  for (const required of ["file", "width", "height", "chrome"]) {
    if (!args[required]) throw new MeasureError(`нет обязательного --${required}`);
  }
  return args;
}

/** Объединённый прямоугольник нарисованного внутри `root` — тот же критерий
 * «нарисовано», что у `nodePaints`/`drawnInside` в `probe_composition.cjs`. */
/* eslint-disable */
function measureInPage() {
  const PAINTED_TAGS = new Set(["IMG", "VIDEO", "CANVAS", "SVG", "PICTURE"]);
  const nodeShown = (node) => {
    const own = getComputedStyle(node);
    if (own.display === "none" || own.visibility === "hidden" || own.visibility === "collapse") {
      return false;
    }
    let alpha = 1;
    for (let up = node; up; up = up.parentElement) {
      const parsed = Number.parseFloat(getComputedStyle(up).opacity || "1");
      if (Number.isFinite(parsed)) alpha *= parsed;
    }
    return alpha >= 0.05;
  };
  const nodePaints = (node) => {
    const box = node.getBoundingClientRect();
    if (box.width < 0.5 || box.height < 0.5) return false;
    if (PAINTED_TAGS.has(node.tagName.toUpperCase())) return true;
    const own = getComputedStyle(node);
    if (own.backgroundImage && own.backgroundImage !== "none") return true;
    const parts = /rgba?\(([^)]*)\)/.exec(own.backgroundColor || "");
    if (parts) {
      const channels = parts[1].split(",").map((one) => Number.parseFloat(one));
      if (channels.length < 4 || channels[3] >= 0.05) return true;
    }
    for (const child of node.childNodes) {
      if (child.nodeType === 3 && child.textContent.trim()) return true;
    }
    return false;
  };
  const root = document.getElementById("root") || document.body;
  let union = null;
  const stack = [root];
  while (stack.length) {
    const node = stack.pop();
    if (!nodeShown(node)) continue;
    if (nodePaints(node)) {
      const box = node.getBoundingClientRect();
      union = union
        ? {
            left: Math.min(union.left, box.left),
            top: Math.min(union.top, box.top),
            right: Math.max(union.right, box.right),
            bottom: Math.max(union.bottom, box.bottom),
          }
        : { left: box.left, top: box.top, right: box.right, bottom: box.bottom };
    }
    for (const child of node.children) stack.push(child);
  }
  if (!union) return null;
  return {
    left: union.left,
    top: union.top,
    width: union.right - union.left,
    height: union.bottom - union.top,
  };
}
/* eslint-enable */

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const file = path.resolve(args.file);
  if (!fs.existsSync(file)) throw new MeasureError(`нет файла ${file}`);

  const puppeteer = require(process.env.REELS_PUPPETEER_PATH || "puppeteer-core");
  let browser;
  try {
    browser = await puppeteer.launch({
      headless: true,
      executablePath: args.chrome,
      args: [...CHROME_ARGS, `--window-size=${args.width},${args.height}`],
    });
    const page = await browser.newPage();
    await page.evaluateOnNewDocument("self.__name = self.__name || ((fn) => fn);");
    await page.setViewport({ width: args.width, height: args.height });
    await page.goto(pathToFileURL(file).href, { waitUntil: "load", timeout: 15000 });
    await page.evaluate(() => document.fonts.ready);

    // Устоявшийся кадр: секунда, названная снаружи (входа давно нет, выхода
    // ещё нет), либо середина родной длительности позиции — разумная
    // догадка, когда вызывающий её не знает.
    const at = Number.isFinite(args.at)
      ? args.at
      : await page.evaluate(() => {
          const timelines = window.__timelines || {};
          const key = Object.keys(timelines)[0];
          const duration = key && typeof timelines[key].duration === "function"
            ? timelines[key].duration()
            : 0;
          return duration ? duration / 2 : 0;
        });
    await page.evaluate((seekAt) => {
      const timelines = window.__timelines || {};
      const key = Object.keys(timelines)[0];
      if (key && typeof timelines[key].seek === "function") {
        timelines[key].seek(seekAt, false);
      }
    }, at);

    const box = await page.evaluate(measureInPage);
    if (!box) {
      process.stdout.write("null\n");
      return;
    }
    process.stdout.write(`${JSON.stringify(box)}\n`);
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
}

main().catch((error) => {
  process.stderr.write(
    `измерить содержимое не вышло: ${error && error.message ? error.message : error}\n`,
  );
  process.exit(1);
});
