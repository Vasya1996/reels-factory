import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const liveRoot = path.resolve(__dirname, "..");
const port = 4173;
const host = "127.0.0.1";

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
  if (ext === ".txt") return "text/plain; charset=utf-8";
  return "application/octet-stream";
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${host}:${port}`);
  let file = path.normalize(decodeURIComponent(url.pathname)).replace(/^[/\\]+/, "");
  if (!file) file = "index.html";
  const abs = path.resolve(liveRoot, file);
  if (abs !== liveRoot && !abs.startsWith(`${liveRoot}${path.sep}`)) {
    res.writeHead(403).end("Forbidden");
    return;
  }
  fs.readFile(abs, (error, data) => {
    if (error) {
      res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }).end("Not found");
      return;
    }
    res.writeHead(200, {
      "Content-Type": contentType(abs),
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    res.end(data);
  });
});

server.listen(port, host, () => {
  console.log(`Live gallery server: http://${host}:${port}/`);
});
