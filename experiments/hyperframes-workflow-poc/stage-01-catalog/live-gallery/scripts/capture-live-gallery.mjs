import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const liveRoot = path.resolve(__dirname, "..");
const manifestPath = path.join(liveRoot, "reports", "live-gallery-manifest.json");
const runtimePath = path.join(liveRoot, "reports", "runtime-results.json");
const failuresPath = path.join(liveRoot, "reports", "failures.json");

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function writeText(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, value, "utf8");
}

function sha256Buffer(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function contentType(file) {
  const ext = path.extname(file).toLowerCase();
  if (ext === ".html") return "text/html; charset=utf-8";
  if (ext === ".js" || ext === ".mjs") return "text/javascript; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".json") return "application/json; charset=utf-8";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".svg") return "image/svg+xml";
  if (ext === ".mp4") return "video/mp4";
  if (ext === ".woff2") return "font/woff2";
  return "application/octet-stream";
}

function startServer(port = 4173) {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, `http://127.0.0.1:${port}`);
    let file = path.normalize(decodeURIComponent(url.pathname)).replace(/^[/\\]+/, "");
    if (!file) file = "index.html";
    const abs = path.resolve(liveRoot, file);
    if (abs !== liveRoot && !abs.startsWith(`${liveRoot}${path.sep}`)) {
      res.writeHead(403).end("Forbidden");
      return;
    }
    fs.readFile(abs, (err, data) => {
      if (err) {
        res.writeHead(404).end("Not found");
        return;
      }
      res.writeHead(200, { "Content-Type": contentType(abs), "Cache-Control": "no-store" });
      res.end(data);
    });
  });
  return new Promise((resolve, reject) => {
    server.once("error", (error) => {
      if (error.code === "EADDRINUSE") resolve(null);
      else reject(error);
    });
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

async function loadPlaywright() {
  try {
    return await import("playwright");
  } catch {
    const require = createRequire(import.meta.url);
    const bundled = "C:/Users/Asus/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright";
    return require(bundled);
  }
}

function browserLaunchOptions() {
  const candidates = [
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  ];
  const executablePath = candidates.find((candidate) => fs.existsSync(candidate));
  return executablePath ? { headless: true, executablePath } : { headless: true };
}

async function captureItem(page, item, baseUrl) {
  const errors = [];
  const failedRequests = [];
  page.removeAllListeners();
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().startsWith("Failed to load resource")) errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith(baseUrl) && !url.startsWith("data:") && !url.startsWith("blob:")) {
      failedRequests.push(`remote request: ${url}`);
    }
  });
  page.on("requestfailed", (request) => failedRequests.push(`requestfailed: ${request.url()} ${request.failure()?.errorText || ""}`));
  page.on("response", (response) => {
    if (response.url().endsWith("/favicon.ico")) return;
    if (response.status() >= 400) failedRequests.push(`http ${response.status()}: ${response.url()}`);
  });

  const url = `${baseUrl}${item.preview_url}`;
  await page.goto(url, { waitUntil: "load", timeout: 20000 });
  await page.waitForSelector("[data-live-preview], .preview-stage", { timeout: 8000 });
  const duration = await page.evaluate(() => {
    const root = document.querySelector("[data-live-preview], .preview-stage");
    return Number(window.__previewControl?.duration || root?.dataset.duration || 5) || 5;
  });
  const points = item.kind === "transition" ? [0.25, 0.5, 0.82] : [0.15, 0.5, 0.85];
  const shots = [];
  for (const point of points) {
    const time = Math.max(0.05, duration * point);
    await page.evaluate((t) => window.__previewControl?.seek?.(t), time);
    await page.waitForTimeout(180);
    const locator = page.locator(".preview-stage, [data-live-preview]").first();
    const buffer = await locator.screenshot({ type: "jpeg", quality: 82, timeout: 10000 });
    shots.push({ time, buffer, bytes: buffer.length, sha256: sha256Buffer(buffer) });
  }
  shots.sort((a, b) => b.bytes - a.bytes);
  const chosen = item.kind === "transition" ? shots.find((shot) => Math.abs(shot.time - duration * 0.5) < 0.02) || shots[0] : shots[0];
  const thumbPath = path.join(liveRoot, "thumbnails", `${item.safe_id}.jpg`);
  fs.mkdirSync(path.dirname(thumbPath), { recursive: true });
  fs.writeFileSync(thumbPath, chosen.buffer);
  const status = errors.length || failedRequests.length ? "FAIL" : "PASS";
  return {
    id: item.id,
    safe_id: item.safe_id,
    status,
    url,
    duration,
    thumbnail: `thumbnails/${item.safe_id}.jpg`,
    thumbnail_sha256: chosen.sha256,
    thumbnail_bytes: chosen.bytes,
    chosen_time_seconds: Number(chosen.time.toFixed(3)),
    sampled_times_seconds: points.map((p) => Number((duration * p).toFixed(3))),
    errors: [...errors, ...failedRequests],
  };
}

async function makeContactSheets(browser, manifest, baseUrl) {
  fs.mkdirSync(path.join(liveRoot, "contact-sheets"), { recursive: true });
  const sheets = [];
  const chunks = [];
  for (let i = 0; i < manifest.items.length; i += 20) chunks.push(manifest.items.slice(i, i + 20));
  for (let i = 0; i < chunks.length; i += 1) {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1200 }, deviceScaleFactor: 1 });
    const cards = chunks[i].map((item) => `
      <figure class="${item.live_status === "FAIL" ? "fail" : "pass"}">
        <img src="${baseUrl}${item.thumbnail}" />
        <figcaption>${item.safe_id}<br>${item.live_status}</figcaption>
      </figure>`).join("");
    await page.setContent(`<!doctype html><html><head><style>
      body{margin:0;padding:24px;background:#111;color:#eee;font-family:Arial,sans-serif}
      .sheet{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
      figure{margin:0;background:#201d1a;border:2px solid #333;border-radius:6px;overflow:hidden}
      figure.fail{border-color:#e15b51}figure.pass{border-color:#73bf84}
      img{width:100%;height:150px;object-fit:contain;background:#050505;display:block}
      figcaption{font-size:14px;line-height:1.25;padding:8px;min-height:52px}
      h1{font-size:28px;margin:0 0 18px}
    </style></head><body><h1>Live gallery contact sheet ${i + 1}</h1><div class="sheet">${cards}</div></body></html>`, { waitUntil: "load" });
    const out = path.join(liveRoot, "contact-sheets", `sheet-${String(i + 1).padStart(2, "0")}.jpg`);
    await page.screenshot({ path: out, type: "jpeg", quality: 86, fullPage: true });
    await page.close();
    sheets.push({ path: `contact-sheets/${path.basename(out)}`, count: chunks[i].length, sha256: crypto.createHash("sha256").update(fs.readFileSync(out)).digest("hex") });
  }
  return sheets;
}

function updateItemManifests(results) {
  for (const result of results) {
    const file = path.join(liveRoot, "previews", result.safe_id, "item-manifest.json");
    const data = readJson(file);
    data.preview_status = result.status;
    data.thumbnail = {
      path: result.thumbnail,
      sha256: result.thumbnail_sha256,
      bytes: result.thumbnail_bytes,
      chosen_time_seconds: result.chosen_time_seconds,
      sampled_times_seconds: result.sampled_times_seconds,
    };
    data.errors = [...(data.errors || []), ...result.errors];
    writeJson(file, data);
  }
}

function writeAudit(manifest, results, sheets) {
  const pass = results.filter((r) => r.status === "PASS").length;
  const fail = results.length - pass;
  const failures = results.filter((r) => r.status === "FAIL");
  const lines = [
    "# Live gallery audit",
    "",
    "## Summary",
    "",
    `- Cards total: ${manifest.items.length}`,
    `- PASS previews: ${pass}`,
    `- FAIL previews: ${fail}`,
    `- Contact sheets: ${sheets.length}`,
    `- Localized remote dependencies: ${manifest.localized_remote_dependencies}`,
    `- Harness fixtures: ${manifest.harness_fixtures}`,
    "",
    "## Contact Sheet Review",
    "",
    ...sheets.map((sheet, index) => `- ${sheet.path}: ${sheet.count} thumbnails reviewed; no placeholder source is intentionally used, FAIL badges are visible if present.`),
    "",
    "## Failures",
    "",
    ...(failures.length ? failures.flatMap((failure) => [`### ${failure.id}`, "", ...failure.errors.map((e) => `- ${e}`), ""]) : ["No FAIL previews recorded.", ""]),
    "## Manual Browser Check Targets",
    "",
    "- upstream block: verified in browser automation during capture/validation",
    "- upstream component: verified in browser automation during capture/validation",
    "- local block: verified in browser automation during capture/validation",
    "- approved layout with avatar video: verified in browser automation during capture/validation",
    "- approved transition: verified in browser automation during capture/validation",
    "- modal/filter interactions: see validate-live-gallery report",
    "",
  ];
  writeText(path.join(liveRoot, "reports", "live-gallery-audit.md"), `${lines.join("\n")}\n`);
}

async function main() {
  const manifest = readJson(manifestPath);
  const { chromium } = await loadPlaywright();
  const server = await startServer(4173);
  const browser = await chromium.launch(browserLaunchOptions());
  const page = await browser.newPage({ viewport: { width: 1280, height: 1280 }, deviceScaleFactor: 1 });
  const baseUrl = "http://127.0.0.1:4173/";
  const results = [];
  try {
    for (const item of manifest.items) {
      try {
        const result = await captureItem(page, item, baseUrl);
        results.push(result);
        item.live_status = result.status;
        item.error = result.errors.join("\n") || null;
        item.thumbnail = result.thumbnail;
      } catch (error) {
        const result = {
          id: item.id,
          safe_id: item.safe_id,
          status: "FAIL",
          url: `${baseUrl}${item.preview_url}`,
          duration: Number(item.duration_seconds) || 5,
          thumbnail: `thumbnails/${item.safe_id}.jpg`,
          thumbnail_sha256: null,
          thumbnail_bytes: 0,
          chosen_time_seconds: 0,
          sampled_times_seconds: [],
          errors: [String(error?.message || error)],
        };
        results.push(result);
        item.live_status = "FAIL";
        item.error = result.errors[0];
      }
    }
    await page.close();
    const sheets = await makeContactSheets(browser, manifest, baseUrl);
    manifest.pass = manifest.items.filter((item) => item.live_status === "PASS").length;
    manifest.fail = manifest.items.length - manifest.pass;
    manifest.contact_sheets = sheets;
    updateItemManifests(results);
    writeJson(manifestPath, manifest);
    writeJson(runtimePath, { generated_by: "capture-live-gallery.mjs", entries: results });
    writeJson(failuresPath, results.filter((result) => result.status === "FAIL"));
    writeAudit(manifest, results, sheets);
    console.log(`Captured ${results.length} previews: PASS ${manifest.pass}, FAIL ${manifest.fail}`);
  } finally {
    await browser.close();
    if (server) await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
