import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const liveRoot = path.resolve(__dirname, "..");
const stageRoot = path.resolve(liveRoot, "..");
const manifestPath = path.join(liveRoot, "reports", "live-gallery-manifest.json");
const runtimePath = path.join(liveRoot, "reports", "runtime-results.json");
const auditPath = path.join(liveRoot, "reports", "live-gallery-audit.md");
const inventoryPath = path.join(stageRoot, "inventory", "items.json");
const EXPECTED = {
  "upstream:block": 113,
  "upstream:component": 25,
  "local:block": 8,
  "approved:layout": 10,
  "approved:transition": 5,
};

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function existsRel(relPath) {
  const abs = path.resolve(liveRoot, relPath);
  return (abs === liveRoot || abs.startsWith(`${liveRoot}${path.sep}`)) && fs.existsSync(abs);
}

function scanFiles(dir, predicate, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) scanFiles(abs, predicate, out);
    else if (predicate(abs)) out.push(abs);
  }
  return out;
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
    return require("C:/Users/Asus/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
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

async function browserChecks(errors, warnings) {
  const { chromium } = await loadPlaywright();
  const server = await startServer(4173);
  const browser = await chromium.launch(browserLaunchOptions());
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const remoteRequests = [];
  const consoleErrors = [];
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith("http://127.0.0.1:4173/") && !url.startsWith("data:") && !url.startsWith("blob:")) remoteRequests.push(url);
  });
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().startsWith("Failed to load resource")) consoleErrors.push(msg.text());
  });
  try {
    await page.goto("http://127.0.0.1:4173/", { waitUntil: "networkidle", timeout: 20000 });
    const cardCount = await page.locator(".card").count();
    if (cardCount !== 161) errors.push(`main gallery card count ${cardCount} !== 161`);
    const searchInput = page.locator("#search");
    await searchInput.fill("avatar");
    const avatarCount = await page.locator(".card").count();
    if (avatarCount <= 0 || avatarCount >= 161) errors.push(`search filter suspicious count: ${avatarCount}`);
    await searchInput.fill("");
    await page.selectOption("#sourceFilter", "local");
    const localCount = await page.locator(".card").count();
    if (localCount !== 8) errors.push(`source filter local count ${localCount} !== 8`);
    await page.selectOption("#sourceFilter", "");
    await page.selectOption("#kindFilter", "transition");
    const transitionCount = await page.locator(".card").count();
    if (transitionCount !== 5) errors.push(`kind filter transition count ${transitionCount} !== 5`);
    await page.selectOption("#kindFilter", "");
    const firstPass = page.locator(".card button").first();
    await firstPass.click();
    await page.waitForSelector("#iframeBox iframe", { timeout: 5000 });
    await page.locator("#playBtn").click();
    await page.waitForTimeout(250);
    await page.locator("#pauseBtn").click();
    await page.locator("[data-jump='0.5']").click();
    await page.keyboard.press("Escape");
    await page.waitForTimeout(150);
    const iframeCount = await page.locator("#iframeBox iframe").count();
    if (iframeCount !== 0) errors.push("modal did not unload iframe after Escape");
    if (remoteRequests.length) errors.push(`browser made remote requests: ${[...new Set(remoteRequests)].join(", ")}`);
    if (consoleErrors.length) warnings.push(`gallery console errors: ${consoleErrors.join(" | ")}`);
  } finally {
    await browser.close();
    if (server) await new Promise((resolve) => server.close(resolve));
  }
}

async function main() {
  const errors = [];
  const warnings = [];
  const checks = [];
  const manifest = readJson(manifestPath);
  const inventory = readJson(inventoryPath);
  const runtime = readJson(runtimePath);
  const inventoryIds = new Set(inventory.map((item) => item.id));
  const manifestIds = new Set(manifest.items.map((item) => item.id));

  if (manifest.items.length !== 161) errors.push(`manifest has ${manifest.items.length} items, expected 161`);
  if (manifestIds.size !== 161) errors.push(`manifest unique IDs ${manifestIds.size} !== 161`);
  for (const id of inventoryIds) if (!manifestIds.has(id)) errors.push(`missing inventory ID: ${id}`);
  for (const id of manifestIds) if (!inventoryIds.has(id)) errors.push(`unknown manifest ID: ${id}`);
  const counts = {};
  for (const item of manifest.items) counts[`${item.source}:${item.kind}`] = (counts[`${item.source}:${item.kind}`] || 0) + 1;
  for (const [key, value] of Object.entries(EXPECTED)) {
    if (counts[key] !== value) errors.push(`count ${key} ${counts[key]} !== ${value}`);
  }
  checks.push("counts and IDs");

  for (const item of manifest.items) {
    if (!existsRel(item.preview_url)) errors.push(`${item.id}: missing preview ${item.preview_url}`);
    if (!existsRel(item.item_manifest_url)) errors.push(`${item.id}: missing item manifest ${item.item_manifest_url}`);
    if (!existsRel(item.thumbnail)) errors.push(`${item.id}: missing thumbnail ${item.thumbnail}`);
    else {
      const size = fs.statSync(path.join(liveRoot, item.thumbnail)).size;
      if (size < 1500) errors.push(`${item.id}: thumbnail too small (${size} bytes)`);
    }
    const im = existsRel(item.item_manifest_url) ? readJson(path.join(liveRoot, item.item_manifest_url)) : null;
    if (im && (!im.implementation_provenance || im.implementation_provenance.length === 0)) {
      errors.push(`${item.id}: implementation provenance missing`);
    }
    if (item.kind === "component" && im && !im.host_fixture_reason) {
      errors.push(`${item.id}: component host fixture reason missing`);
    }
    if (item.kind === "transition" && im && !im.host_fixture_reason) {
      errors.push(`${item.id}: transition host fixture reason missing`);
    }
  }
  checks.push("preview directories, manifests, thumbnails, provenance");

  const textFiles = scanFiles(liveRoot, (file) => {
    if (!/\.(html|js|mjs|css)$/i.test(file)) return false;
    if (file.includes(`${path.sep}scripts${path.sep}`)) return false;
    if (file.includes(`${path.sep}assets${path.sep}runtime${path.sep}gsap.min.js`)) return false;
    return true;
  });
  for (const file of textFiles) {
    const text = fs.readFileSync(file, "utf8");
    const withoutMetadata = text
      .replace(/https:\/\/hyperframes\.heygen\.com\/schema\/registry-item\.json/g, "")
      .replace(/https?:\/\/www\.w3\.org\/[^\s"'<>\\)]+/g, "");
    const remote = withoutMetadata.match(/https?:\/\/(?!127\.0\.0\.1|localhost|www\.w3\.org)[^\s"'<>\\)]+/g);
    if (remote) errors.push(`${path.relative(liveRoot, file)} contains remote URL: ${[...new Set(remote)].slice(0, 3).join(", ")}`);
  }
  checks.push("remote dependency scan");

  if (!runtime.entries || runtime.entries.length !== 161) errors.push(`runtime results entries ${runtime.entries?.length || 0} !== 161`);
  const pass = manifest.items.filter((item) => item.live_status === "PASS").length;
  const fail = manifest.items.filter((item) => item.live_status === "FAIL").length;
  if (pass + fail !== 161) errors.push(`PASS+FAIL ${pass + fail} !== 161`);
  if (manifest.pass !== pass || manifest.fail !== fail) errors.push("manifest PASS/FAIL totals do not match item statuses");
  checks.push("runtime result accounting");

  const hashes = new Map();
  for (const item of manifest.items) {
    const im = readJson(path.join(liveRoot, item.item_manifest_url));
    const h = im.thumbnail?.sha256;
    if (!h) errors.push(`${item.id}: thumbnail hash missing`);
    else {
      if (!hashes.has(h)) hashes.set(h, []);
      hashes.get(h).push(item.id);
    }
  }
  const duplicateHashes = [...hashes.entries()].filter(([, ids]) => ids.length > 1);
  if (duplicateHashes.length) warnings.push(`duplicate thumbnail hashes documented: ${duplicateHashes.map(([, ids]) => ids.join(" + ")).join("; ")}`);
  checks.push("thumbnail hash coverage");

  if (!manifest.contact_sheets || manifest.contact_sheets.length < 1) errors.push("no contact sheets recorded");
  for (const sheet of manifest.contact_sheets || []) if (!existsRel(sheet.path)) errors.push(`missing contact sheet ${sheet.path}`);
  if (!fs.existsSync(auditPath) || !fs.readFileSync(auditPath, "utf8").includes("Contact Sheet Review")) errors.push("audit missing contact sheet review");
  checks.push("contact sheets and audit");

  await browserChecks(errors, warnings);
  checks.push("browser modal/filter validation");

  const report = {
    ok: errors.length === 0,
    checks,
    errors,
    warnings,
    counts: {
      ...counts,
      total: manifest.items.length,
      pass,
      fail,
      localized_remote_dependencies: manifest.localized_remote_dependencies,
      harness_fixtures: manifest.harness_fixtures,
    },
  };
  writeJson(path.join(liveRoot, "reports", "validation.json"), report);
  if (errors.length) {
    console.error(`Live gallery validation FAIL (${errors.length} errors)`);
    for (const error of errors.slice(0, 30)) console.error(`- ${error}`);
    process.exit(1);
  }
  console.log(`Live gallery validation PASS: ${pass} PASS, ${fail} FAIL previews`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
