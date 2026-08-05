import fs from "node:fs";
import path from "node:path";

const ROOT = process.cwd();
const CONTENT_ROOT = path.resolve(ROOT, "..");
const STAGE = path.join(ROOT, "experiments/hyperframes-workflow-poc/stage-01-catalog");
const POSTERS = path.join(STAGE, "gallery/assets/posters");
const REPORT = path.join(STAGE, "reports/preview-downloads.json");
const UPSTREAM = path.join(CONTENT_ROOT, "reference-audit/hyperframes-main-20260801-complete/hyperframes-main");
const MAX = 2 * 1024 * 1024;
const MIME_EXT = { "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif" };

function readJson(file) { return JSON.parse(fs.readFileSync(file, "utf8")); }
function writeJson(file, data) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, `${JSON.stringify(data, null, 2)}\n`, "utf8"); }
function posix(p) { return p.split(path.sep).join("/"); }
function idFileBase(id) { return id.replaceAll(":", "-"); }
function listManifest(kind, dirName) {
  const root = path.join(UPSTREAM, "registry", dirName);
  return fs.readdirSync(root, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => {
    const manifest = readJson(path.join(root, d.name, "registry-item.json"));
    return { id: `upstream:${kind}:${d.name}`, poster: manifest.preview?.poster || null };
  });
}
function signatureMime(file) {
  if (!fs.existsSync(file)) return null;
  const b = fs.readFileSync(file).subarray(0, 16);
  if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) return "image/png";
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if (b.toString("ascii", 0, 4) === "RIFF" && b.toString("ascii", 8, 12) === "WEBP") return "image/webp";
  if (b.toString("ascii", 0, 3) === "GIF") return "image/gif";
  return null;
}
function existingFor(id) {
  for (const ext of Object.values(MIME_EXT)) {
    const file = path.join(POSTERS, `${idFileBase(id)}${ext}`);
    if (fs.existsSync(file)) {
      const type = signatureMime(file);
      const size = fs.statSync(file).size;
      if (type && size <= MAX && MIME_EXT[type] === ext) return { file, type, size };
    }
  }
  return null;
}
async function downloadOne(id, url) {
  const cached = existingFor(id);
  if (cached) return entry(id, url, "cached", cached.file, cached.type, cached.size, 200, null);
  if (!url) return entry(id, null, "not_applicable", null, null, 0, null, "У item нет remote poster в frozen manifest.");
  let parsed;
  try { parsed = new URL(url); } catch { return entry(id, url, "failed", null, null, 0, null, "Некорректный poster URL."); }
  if (!["http:", "https:"].includes(parsed.protocol)) return entry(id, url, "failed", null, null, 0, null, "Poster URL имеет запрещённый protocol.");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  let tmp = null;
  try {
    const res = await fetch(url, { signal: controller.signal });
    const type = (res.headers.get("content-type") || "").split(";")[0].toLowerCase();
    const len = Number(res.headers.get("content-length") || 0);
    if (!res.ok) return entry(id, url, "failed", null, type || null, 0, res.status, `HTTP ${res.status}`);
    if (!MIME_EXT[type]) return entry(id, url, "failed", null, type || null, 0, res.status, `Недопустимый Content-Type: ${type || "missing"}`);
    if (len > MAX) return entry(id, url, "failed", null, type, 0, res.status, `Content-Length больше 2 MB: ${len}`);
    const ext = MIME_EXT[type];
    const finalFile = path.join(POSTERS, `${idFileBase(id)}${ext}`);
    tmp = path.join(POSTERS, `${idFileBase(id)}.partial-${process.pid}${ext}`);
    const chunks = [];
    let bytes = 0;
    for await (const chunk of res.body) {
      bytes += chunk.length;
      if (bytes > MAX) throw new Error(`Размер body превысил 2 MB: ${bytes}`);
      chunks.push(chunk);
    }
    fs.writeFileSync(tmp, Buffer.concat(chunks));
    const actual = signatureMime(tmp);
    if (actual !== type) throw new Error(`MIME signature mismatch: header ${type}, file ${actual}`);
    fs.renameSync(tmp, finalFile);
    tmp = null;
    return entry(id, url, "downloaded", finalFile, type, bytes, res.status, null);
  } catch (error) {
    if (tmp && fs.existsSync(tmp)) fs.rmSync(tmp, { force: true });
    return entry(id, url, "failed", null, null, 0, null, error?.name === "AbortError" ? "Timeout 20 seconds" : String(error.message || error));
  } finally {
    clearTimeout(timer);
  }
}
function entry(id, url, status, file, contentType, bytes, httpStatus, error) {
  return {
    id,
    url,
    status,
    local_path: file ? posix(path.relative(STAGE, file)) : null,
    content_type: contentType,
    bytes,
    http_status: httpStatus,
    error,
  };
}
async function main() {
  fs.mkdirSync(POSTERS, { recursive: true });
  const items = readJson(path.join(STAGE, "inventory/items.json"));
  const upstream = new Map([...listManifest("block", "blocks"), ...listManifest("component", "components")].map((i) => [i.id, i.poster]));
  const entries = [];
  for (const item of items) {
    if (upstream.has(item.id)) entries.push(await downloadOne(item.id, upstream.get(item.id)));
    else entries.push(entry(item.id, null, "not_applicable", null, null, 0, null, "Для local/approved item remote upstream poster не применяется."));
  }
  const counts = { downloaded: 0, cached: 0, failed: 0, not_applicable: 0 };
  for (const e of entries) counts[e.status] += 1;
  writeJson(REPORT, { attempted: true, entries: entries.sort((a, b) => a.id.localeCompare(b.id)), counts });
  if (counts.failed > 0) {
    console.log(`poster download PARTIAL: ${JSON.stringify(counts)}`);
  } else {
    console.log(`poster download PASS: ${JSON.stringify(counts)}`);
  }
}
main().catch((error) => {
  writeJson(REPORT, { attempted: true, entries: [], counts: { downloaded: 0, cached: 0, failed: 0, not_applicable: 0 }, fatal_error: String(error.message || error) });
  console.error(error);
  process.exit(1);
});
