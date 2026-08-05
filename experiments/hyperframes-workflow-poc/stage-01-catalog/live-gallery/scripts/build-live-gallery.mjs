import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const liveRoot = path.resolve(__dirname, "..");
const stageRoot = path.resolve(liveRoot, "..");
const repoRoot = path.resolve(stageRoot, "..", "..", "..");
const inventoryPath = path.join(stageRoot, "inventory", "items.json");
const sourceManifestPath = path.join(stageRoot, "source-manifest.json");
const runtimeRoot = path.join(liveRoot, "assets", "runtime");
const fixturesRoot = path.join(liveRoot, "assets", "fixtures");
const upstreamRoot = "C:/Users/Asus/Documents/personal_ai/projects/content_factory/reference-audit/hyperframes-main-20260801-complete/hyperframes-main";
const approvedRoot = "C:/Users/Asus/Documents/personal_ai/projects/content_factory/plan-previews/two-reel-catalog-proxy-20260729";
const avatarSource = "C:/Users/Asus/Downloads/Продажи/1.mp4";
const gsapSource = path.join(repoRoot, "experiments/hyperframes-workflow-poc/stage-03-render/project/assets/vendor/gsap.min.js");

const EXPECTED = {
  "upstream:block": 113,
  "upstream:component": 25,
  "local:block": 8,
  "approved:layout": 10,
  "approved:transition": 5,
};

const LOCAL_DEFAULTS = {
  before_after: {
    duration: 4.2,
    variables: { before_value: "хаос", after_value: "система", before_label: "было", after_label: "стало" },
  },
  complexity_cloud: {
    duration: 5,
    variables: { title: "СЛОЖНОСТЬ", items: ["бриф", "сценарий", "монтаж", "проверка"], resolution: "один понятный процесс" },
  },
  concept_nodes: {
    duration: 4.5,
    variables: { title: "главная идея", items: ["контекст", "темп", "результат"] },
  },
  persona_card: {
    duration: 4.5,
    variables: { title: "ДЛЯ КОГО", items: ["основатель", "эксперт", "команда", "клиент"] },
  },
  sequence_flow: {
    duration: 4.8,
    variables: { title: "путь от идеи до ролика", items: ["тезис", "сцена", "проверка", "экспорт"] },
  },
  stat_number: {
    duration: 4,
    variables: { value: 161, prefix: "", suffix: "", label_top: "в каталоге", label_bottom: "живой HTML preview" },
  },
  task_list: {
    duration: 4.8,
    variables: { title: "ПРОВЕРИТЬ", items: ["source", "preview", "thumbnail", "+ validation"] },
  },
  value_layers: {
    duration: 4.5,
    variables: { title: "ЦЕННОСТЬ", offer: "набор шаблонов", actual: "монтажный язык" },
  },
};

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

function copyFile(src, dst) {
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.copyFileSync(src, dst);
}

function copyDir(src, dst) {
  if (!fs.existsSync(src)) return;
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const from = path.join(src, entry.name);
    const to = path.join(dst, entry.name);
    if (entry.isDirectory()) copyDir(from, to);
    else copyFile(from, to);
  }
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function safeId(id) {
  return id.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
}

function rel(from, to) {
  return path.relative(from, to).replaceAll("\\", "/");
}

function assertInside(child, parent) {
  const c = path.resolve(child);
  const p = path.resolve(parent);
  if (c !== p && !c.startsWith(`${p}${path.sep}`)) {
    throw new Error(`Refusing to write outside ${p}: ${c}`);
  }
}

function resetOutput() {
  for (const name of ["assets", "previews", "thumbnails", "contact-sheets", "reports"]) {
    const target = path.join(liveRoot, name);
    assertInside(target, liveRoot);
    fs.rmSync(target, { recursive: true, force: true });
  }
  fs.mkdirSync(liveRoot, { recursive: true });
}

function patchRuntimeUrls(html, depthToLiveRoot) {
  const gsapRel = `${"../".repeat(depthToLiveRoot)}assets/runtime/gsap.min.js`;
  return html
    .replace(/<link\b(?=[^>]*rel=["']preconnect["'])[^>]*>\s*/gi, "")
    .replace(/<link\b(?=[^>]*https:\/\/fonts\.(?:googleapis|gstatic)\.com)[^>]*>\s*/gi, "")
    .replace(/@import\s+url\(["']?https:\/\/fonts\.googleapis\.com[^)]*\);\s*/gi, "")
    .replace(/<script\b[^>]+src=["'](https:\/\/(?:cdn\.jsdelivr\.net\/npm\/gsap@|cdnjs\.cloudflare\.com\/ajax\/libs\/gsap\/)[^"']+)["'][^>]*><\/script>/gi, `<script src="${gsapRel}"></script>`)
    .replace(/<script\b[^>]+src=["'](https:\/\/(?:cdn\.jsdelivr\.net\/npm\/(?:three|d3|topojson-client)@|cdnjs\.cloudflare\.com\/ajax\/libs\/three\.js\/)[^"']+)["'][^>]*><\/script>/gi, (_all, url) => `<script>throw new Error("Missing local runtime dependency: ${url}");</script>`)
    .replace(/"compositions\/components\/"\s*\+\s*TEXTURE\s*\+\s*"\.png"/g, `"./" + TEXTURE + ".png"`)
    .replace(/https?:\/\/(?!(?:127\.0\.0\.1|localhost|www\.w3\.org))[^\s"'<>)]+/g, (url) => `about:blank#remote-dependency-not-localized:${encodeURIComponent(url)}`);
}

function stripRemoteComments(html) {
  return html.replace(/<!--[\s\S]*?-->/g, (comment) => comment.includes("http://") || comment.includes("https://") ? "" : comment);
}

function copyUpstreamImplementation(item, previewDir) {
  const manifestAbs = path.join(upstreamRoot, item.source_ref.manifest);
  const itemDir = path.dirname(manifestAbs);
  const sourceDir = path.join(previewDir, "assets", "item");
  const copied = [];
  const files = new Map();
  for (const sourceRel of item.source_ref.implementation) files.set(path.join(upstreamRoot, sourceRel), sourceRel);
  for (const abs of scanFiles(itemDir)) {
    const base = path.basename(abs).toLowerCase();
    if (base === "registry-item.json" || base === "demo.html") continue;
    if (!files.has(abs) && !/\.(png|jpg|jpeg|webp|gif|svg|json|css|js|mjs|woff2)$/i.test(abs)) continue;
    files.set(abs, rel(upstreamRoot, abs));
  }
  for (const [abs, sourceRel] of [...files.entries()].sort((a, b) => a[1].localeCompare(b[1]))) {
    if (!fs.existsSync(abs)) throw new Error(`${item.id}: missing implementation ${sourceRel}`);
    const localRel = rel(itemDir, abs);
    const dst = path.join(sourceDir, localRel);
    copyFile(abs, dst);
    if (/\.(html|js|mjs|css)$/i.test(abs)) {
      const patched = stripRemoteComments(patchRuntimeUrls(fs.readFileSync(dst, "utf8"), 4));
      fs.writeFileSync(dst, patched, "utf8");
    }
    copied.push({
      source_path: sourceRel,
      preview_path: rel(liveRoot, dst),
      sha256: sha256(dst),
    });
  }
  const mainSource = item.source_ref.implementation.find((p) => p.endsWith(".html"));
  if (!mainSource) throw new Error(`${item.id}: no HTML implementation`);
  const mainLocal = path.join(sourceDir, rel(itemDir, path.join(upstreamRoot, mainSource)));
  const mainText = fs.readFileSync(mainLocal, "utf8");
  if (mainText.includes('fetch("./caption-data.json")')) {
    const captionData = path.join(path.dirname(mainLocal), "caption-data.json");
    writeJson(captionData, captionFixtureData());
    copied.push({
      source_path: "technical-fixture/caption-data.json",
      preview_path: rel(liveRoot, captionData),
      sha256: sha256(captionData),
      fixture: true,
    });
  }
  return { main: rel(path.join(previewDir), mainLocal), copied };
}

function scanFiles(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) scanFiles(abs, out);
    else out.push(abs);
  }
  return out;
}

function captionFixtureData() {
  const words = ["тест", "живого", "эффекта", "каталога"].map((word, index) => ({
    word,
    start: index * 0.42,
    end: index * 0.42 + 0.38,
  }));
  return {
    version: 1,
    displayMode: "full",
    resolution: { width: 1920, height: 1080 },
    brand: { primaryColor: "#ffffff", accentColor: "#FFE500" },
    segments: [{ words }],
  };
}

function hostHtml(item, src, options = {}) {
  const width = Number(item.dimensions?.width) || (item.kind === "component" ? 1080 : 1920);
  const height = Number(item.dimensions?.height) || (item.kind === "component" ? 1080 : 1080);
  const duration = Number(item.duration_seconds) || options.duration || (item.kind === "transition" ? 3.2 : 5);
  const hostFixture = options.hostFixture ? "true" : "false";
  const backdrop = options.backdrop || "";
  return `<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${escapeHtml(item.title)} — live preview</title>
    <style>
      html, body { margin: 0; width: 100%; height: 100%; background: #111; overflow: hidden; font-family: Arial, sans-serif; }
      .preview-stage { position: relative; width: ${width}px; height: ${height}px; overflow: hidden; background: #111; }
      .backdrop { position: absolute; inset: 0; z-index: 0; ${backdrop} }
      iframe { position: absolute; inset: 0; z-index: 1; width: 100%; height: 100%; border: 0; background: transparent; }
      .fail { position: absolute; inset: 0; display: grid; place-items: center; color: #fff; background: #3a1212; padding: 32px; text-align: center; }
    </style>
  </head>
  <body>
    <main class="preview-stage"
      data-live-preview
      data-catalog-id="${escapeAttr(item.id)}"
      data-composition-id="${escapeAttr(item.name)}"
      data-composition-src="${escapeAttr(src)}"
      data-duration="${duration}"
      data-width="${width}"
      data-height="${height}"
      data-host-fixture="${hostFixture}">
      <div class="backdrop"></div>
      <iframe id="previewFrame" src="${escapeAttr(src)}" allow="autoplay" allowtransparency="true"></iframe>
    </main>
    <script>
      const duration = ${JSON.stringify(duration)};
      const frame = document.getElementById("previewFrame");
      let playing = false;
      let started = 0;
      let base = 0;
      function timelines() {
        try { return Object.values(frame.contentWindow.__timelines || {}); } catch { return []; }
      }
      function seek(time) {
        const t = Math.max(0, Math.min(duration, Number(time) || 0));
        for (const tl of timelines()) {
          if (tl && typeof tl.time === "function") tl.time(Math.min(t, tl.duration ? tl.duration() : t), false);
          else if (tl && typeof tl.progress === "function") tl.progress(duration ? t / duration : 0, false);
        }
        for (const video of frame.contentDocument ? frame.contentDocument.querySelectorAll("video,audio") : []) {
          try { video.muted = true; if (Number.isFinite(video.duration)) video.currentTime = Math.min(video.duration - 0.05, Math.max(0, t)); } catch {}
        }
        return t;
      }
      function tick(now) {
        if (!playing) return;
        const t = Math.min(duration, base + (now - started) / 1000);
        seek(t);
        if (t >= duration) { playing = false; return; }
        requestAnimationFrame(tick);
      }
      window.__previewControl = {
        duration,
        play() { playing = true; started = performance.now(); requestAnimationFrame(tick); },
        pause() { playing = false; },
        restart() { base = 0; seek(0); },
        seek(time) { base = seek(time); return base; },
        status() { return { ready: true, timelines: timelines().length, duration }; },
      };
      frame.addEventListener("load", () => setTimeout(() => seek(duration * 0.5), 80));
    </script>
  </body>
</html>
`;
}

function componentHarnessHtml(item, snippet, assets) {
  const duration = 5;
  let patched = stripRemoteComments(patchRuntimeUrls(snippet, 2));
  patched = patched.replaceAll("/assets/texture-mask-text/masks/", "assets/item/masks/");
  for (const asset of assets) {
    const original = asset.localRel.replaceAll("\\", "/");
    const replacement = `assets/item/${original}`;
    patched = patched.split(`"${original}"`).join(`"${replacement}"`);
    patched = patched.split(`'${original}'`).join(`'${replacement}'`);
    patched = patched.replaceAll(`url(${original})`, `url(${replacement})`);
    patched = patched.replaceAll(`url("${original}")`, `url("${replacement}")`);
    patched = patched.replaceAll(`url('${original}')`, `url('${replacement}')`);
  }
  const name = item.name;
  const captionClass = name === "caption-blend-difference" ? "blend-difference" : "";
  const targetClass = [
    name === "shimmer-sweep" ? "shimmer-sweep-target" : "",
    name === "texture-mask-text" ? "hf-texture-text hf-texture-lava" : "",
    name === "motion-blur" ? "motion-target" : "",
    name.includes("parallax-zoom") ? "parallax-zoom-grid" : "",
    name.includes("parallax-unzoom") ? "parallax-unzoom-grid" : "",
  ].filter(Boolean).join(" ");
  const parallaxCards = name.includes("parallax")
    ? Array.from({ length: 9 }, (_, i) => `<div class="${name.includes("unzoom") ? "parallax-unzoom-card" : "parallax-zoom-card"}" data-${name.includes("unzoom") ? "pu" : "pz"}-focus="${i === 4 ? "true" : "false"}">${i + 1}</div>`).join("")
    : "";
  return `<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1080" />
    <title>${escapeHtml(item.title)} — component host</title>
    <script src="../../assets/runtime/gsap.min.js"></script>
    <style>
      html, body { width: 1080px; height: 1080px; margin: 0; overflow: hidden; background: #171310; font-family: Arial, sans-serif; }
      #host { isolation: isolate; position: relative; width: 1080px; height: 1080px; overflow: hidden; background: linear-gradient(135deg, #171310 0%, #304b6f 50%, #f3efe7 50%, #d83a32 100%); }
      .scene-a, .scene-b { position:absolute; inset:0; display:grid; place-items:center; font-size:140px; font-weight:900; color:white; }
      .scene-b { opacity:0; background:#f3efe7; color:#171310; }
      .caption-fixture { position:absolute; left:90px; right:90px; bottom:130px; z-index:20; text-align:center; font-size:82px; line-height:1; font-weight:900; text-transform:uppercase; color:white; }
      .effect-target { position:absolute; inset:170px 110px; z-index:15; display:grid; place-items:center; color:white; font-size:86px; font-weight:900; text-align:center; }
      .motion-target { width:240px; height:160px; background:#ffe500; color:#171310; border-radius:18px; display:grid; place-items:center; }
      .parallax-zoom-grid, .parallax-unzoom-grid { position:absolute; inset:120px; z-index:12; display:grid; grid-template-columns:repeat(3,1fr); gap:18px; }
      .parallax-zoom-card, .parallax-unzoom-card { display:grid; place-items:center; border-radius:18px; background:#f3efe7; color:#171310; font-size:56px; font-weight:900; }
      .host-note { position:absolute; left:32px; top:28px; z-index:1000; color:#fff; background:rgba(0,0,0,.35); padding:10px 12px; border-radius:6px; font-size:22px; }
    </style>
  </head>
  <body>
    <main id="host" class="preview-stage" data-live-preview data-catalog-id="${escapeAttr(item.id)}" data-composition-id="component-host" data-duration="${duration}" data-width="1080" data-height="1080" data-host-fixture="true">
      <div id="scene-a" class="scene-a">A</div>
      <div id="scene-b" class="scene-b">B</div>
      <div class="caption-fixture ${captionClass}">тест эффекта</div>
      <div class="effect-target ${targetClass}">${parallaxCards || "ТЕКСТУРА"}</div>
      <div class="host-note">technical host</div>
      ${patched}
    </main>
    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });
      if (document.querySelector("#grid-pixelate-overlay .grid-cell")) {
        tl.to("#grid-pixelate-overlay .grid-cell", { scale: 1, duration: .7, stagger: { amount: .45, from: "center" }, ease: "power2.inOut" }, 1);
        tl.set("#scene-a", { opacity: 0 }, 1.72).set("#scene-b", { opacity: 1 }, 1.72);
        tl.to("#grid-pixelate-overlay .grid-cell", { scale: 0, duration: .7, stagger: { amount: .45, from: "edges" }, ease: "power2.inOut" }, 1.75);
      }
      if (document.getElementById("hf-vignette")) {
        tl.fromTo("#hf-vignette", { "--vignette-color": "rgba(0,0,0,0)" }, { "--vignette-color": "rgba(0,0,0,.75)", duration: 1 }, 0);
      }
      if (document.querySelector(".motion-target")) {
        tl.fromTo(".motion-target", { x: -360 }, { x: 360, duration: 2.2, ease: "power2.inOut" }, .5);
        if (window.attachMotionBlur) window.attachMotionBlur(".motion-target", tl);
      }
      if (document.querySelector(".shimmer-sweep-target")) {
        tl.fromTo(".shimmer-sweep-target", { opacity: .6 }, { opacity: 1, duration: 1.2, yoyo: true, repeat: 2 }, .2);
      }
      if (document.querySelector(".parallax-zoom-card")) {
        tl.to(".parallax-zoom-card", { scale: (i, el) => el.dataset.pzFocus ? 2.4 : .7, x: (i) => (i % 3 - 1) * -120, y: (i) => (Math.floor(i / 3) - 1) * -120, duration: 1.5, ease: "power3.inOut" }, .7);
      }
      if (document.querySelector(".parallax-unzoom-card")) {
        gsap.set(".parallax-unzoom-card", { scale: (i, el) => el.dataset.puFocus ? 2.2 : .7 });
        tl.to(".parallax-unzoom-card", { scale: 1, x: 0, y: 0, duration: 1.5, ease: "power3.inOut" }, .7);
      }
      tl.fromTo(".caption-fixture", { y: 80, opacity: 0 }, { y: 0, opacity: 1, duration: .7, ease: "expo.out" }, .25);
      window.__timelines["component-host"] = tl;
      window.__previewControl = {
        duration: ${duration},
        seek(t) { tl.time(Math.max(0, Math.min(${duration}, Number(t) || 0)), false); return t; },
        play() { tl.play(); },
        pause() { tl.pause(); },
        restart() { tl.restart(); tl.pause(); },
        status() { return { ready: true, timelines: Object.keys(window.__timelines).length, duration: ${duration} }; }
      };
      window.__previewControl.seek(${duration * 0.5});
    </script>
  </body>
</html>
`;
}

function approvedHtml(item) {
  const duration = item.kind === "transition" ? 4.2 : 4.8;
  const name = item.name;
  const isTransition = item.kind === "transition";
  const firstLayout = isTransition ? "progressive_text_card" : name;
  const secondLayout = isTransition ? "broll_fullscreen" : name;
  const windows = isTransition
    ? [
        baseWindow("a", firstLayout, 0, 2.05, "первая сцена держит контекст", "переход"),
        { ...baseWindow("b", secondLayout, 2.05, duration, "вторая сцена показывает результат", "результат"), transition: name },
      ]
    : [baseWindow("single", name, 0, duration, "короткий нейтральный текст для проверки", "проверка")];
  const spec = {
    id: safeId(item.id),
    duration,
    baseVideo: "../../assets/fixtures/avatar.mp4",
    brollVideo: "../../assets/fixtures/neutral-video.mp4",
    cutoutImage: "../../assets/fixtures/neutral-square.png",
    windows,
  };
  return `<!doctype html>
<html lang="ru" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="../../assets/runtime/gsap.min.js"></script>
    <link rel="stylesheet" href="assets/source/catalog.css" />
  </head>
  <body>
    <div id="root" class="preview-stage" data-live-preview data-composition-id="${spec.id}" data-start="0" data-duration="${duration}" data-width="1080" data-height="1920" data-host-fixture="${isTransition}">
      <video id="${spec.id}-base-video" class="base-video clip" src="../../assets/fixtures/avatar.mp4" muted playsinline data-start="0" data-duration="${duration}" data-track-index="0"></video>
      <audio id="${spec.id}-master-audio" class="clip" data-start="0" data-duration="${duration}" data-track-index="20" data-volume="0"></audio>
    </div>
    <script>window.REEL_SPEC = ${JSON.stringify(spec)};</script>
    <script src="assets/source/catalog.js"></script>
    <script>
      const tl = window.__timelines[${JSON.stringify(spec.id)}];
      window.__previewControl = {
        duration: ${duration},
        seek(t) { tl.time(Math.max(0, Math.min(${duration}, Number(t) || 0)), false); document.querySelectorAll("video,audio").forEach((m) => { m.muted = true; try { if (Number.isFinite(m.duration)) m.currentTime = Math.max(0, Math.min(m.duration - .05, Number(t) || 0)); } catch {} }); return t; },
        play() { tl.play(); },
        pause() { tl.pause(); },
        restart() { tl.restart(); tl.pause(); },
        status() { return { ready: true, timelines: Object.keys(window.__timelines || {}).length, duration: ${duration} }; }
      };
      window.__previewControl.seek(${duration * 0.5});
    </script>
  </body>
</html>
`;
}

function baseWindow(id, layout, start, end, text, hit) {
  return {
    id,
    layout,
    role: layout === "social_outro" ? "cta" : "body",
    motion: layout,
    start,
    end,
    text,
    purpose: "technical fixture",
    emphasis: [hit],
    hits: [hit],
    captionPosition: "hidden",
    transition: "hard_cut",
  };
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("\n", " ");
}

function resolvePython() {
  const candidates = [
    process.env.PYTHON,
    "python",
    "py",
    "C:/Users/Asus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe",
  ].filter(Boolean);
  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ["--version"], { encoding: "utf8" });
    if (!probe.error && probe.status === 0) return candidate;
  }
  throw new Error("Python runtime not found for local HyperFrames block generators");
}

function renderLocalBlock(item, previewDir) {
  const py = resolvePython();
  const defaults = LOCAL_DEFAULTS[item.name];
  if (!defaults) throw new Error(`${item.id}: no documented local defaults`);
  const code = `
import json, sys
sys.path.insert(0, ${JSON.stringify(path.join(repoRoot, "plugins/reels-factory/engine/src"))})
from reels_factory import hyperframes_blocks as h
name = ${JSON.stringify(item.name)}
data = ${JSON.stringify(defaults)}
builder = h.BLOCKS[name][1]
print(builder(duration=data["duration"], **data["variables"]))
`;
  const result = spawnSync(py, ["-c", code], {
    encoding: "utf8",
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    maxBuffer: 50 * 1024 * 1024,
  });
  if (result.status !== 0) throw new Error(`${item.id}: Python generator failed: ${result.stderr || result.error?.message}`);
  const out = path.join(previewDir, "assets", "item", "index.html");
  writeText(out, stripRemoteComments(patchRuntimeUrls(result.stdout, 4)));
  return {
    main: "assets/item/index.html",
    copied: [{ source_path: item.source_ref.implementation[0], preview_path: rel(liveRoot, out), sha256: sha256(out), generated_by: item.name }],
  };
}

function makeCardData(item, safe, manifestRel) {
  return {
    id: item.id,
    safe_id: safe,
    title: item.title,
    description: item.description,
    source: item.source,
    kind: item.kind,
    name: item.name,
    review_status: item.assessment?.review_status || "unknown",
    orientation: item.dimensions?.orientation || "unknown",
    dimensions: item.dimensions,
    duration_seconds: item.duration_seconds,
    roles: item.capabilities?.roles || [],
    source_ref: item.source_ref,
    preview_url: `previews/${safe}/index.html`,
    item_manifest_url: manifestRel,
    thumbnail: `thumbnails/${safe}.jpg`,
    live_status: "PENDING",
    host_fixture: item.kind === "component" || item.kind === "transition",
    error: null,
  };
}

function buildPreview(item) {
  const safe = safeId(item.id);
  const previewDir = path.join(liveRoot, "previews", safe);
  fs.mkdirSync(previewDir, { recursive: true });
  const manifest = {
    id: item.id,
    safe_id: safe,
    source: item.source,
    kind: item.kind,
    title: item.title,
    source_ref: item.source_ref,
    dimensions: item.dimensions,
    duration_seconds: Number(item.duration_seconds) || (item.kind === "transition" ? 4.2 : 5),
    preview_status: "PENDING",
    host_fixture: item.kind === "component" || item.kind === "transition",
    host_fixture_reason: null,
    implementation_provenance: [],
    localized_remote_dependencies: [],
    errors: [],
    thumbnail: null,
  };

  try {
    if (item.source === "upstream") {
      const impl = copyUpstreamImplementation(item, previewDir);
      manifest.implementation_provenance = impl.copied;
      const sourceAbs = path.join(previewDir, impl.main);
      const sourceText = fs.readFileSync(sourceAbs, "utf8");
      const isStandalone = /<!doctype|<html[\s>]/i.test(sourceText);
      if (item.kind === "component" && !isStandalone) {
        const assets = impl.copied
          .map((p) => ({ ...p, localRel: rel(path.join(previewDir, "assets", "item"), path.join(liveRoot, p.preview_path)) }))
          .filter((p) => !p.localRel.endsWith(".html"));
        writeText(path.join(previewDir, "index.html"), componentHarnessHtml(item, sourceText, assets));
        manifest.host_fixture_reason = "Neutral component host fixture wraps upstream snippet target.";
      } else {
        const bg = item.kind === "component" ? "background: linear-gradient(135deg,#171310,#31506f 48%,#f3efe7 48%,#d83a32);" : "";
        writeText(path.join(previewDir, "index.html"), hostHtml(item, impl.main, { hostFixture: item.kind === "component", backdrop: bg, duration: Number(item.duration_seconds) || 5 }));
        if (item.kind === "component") manifest.host_fixture_reason = "Neutral iframe host supplies backdrop for transparent upstream component.";
      }
      manifest.localized_remote_dependencies.push({ from: "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js", to: "../../assets/runtime/gsap.min.js" });
    } else if (item.source === "local") {
      const impl = renderLocalBlock(item, previewDir);
      manifest.implementation_provenance = impl.copied;
      writeText(path.join(previewDir, "index.html"), hostHtml(item, impl.main, { duration: Number(LOCAL_DEFAULTS[item.name]?.duration) || 5 }));
      manifest.localized_remote_dependencies.push({ from: "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js", to: "../../assets/runtime/gsap.min.js" });
    } else if (item.source === "approved") {
      const sourceDir = path.join(previewDir, "assets", "source");
      copyFile(path.join(approvedRoot, "assets", "catalog.js"), path.join(sourceDir, "catalog.js"));
      copyFile(path.join(approvedRoot, "assets", "catalog.css"), path.join(sourceDir, "catalog.css"));
      copyDir(path.join(approvedRoot, "assets", "fonts"), path.join(sourceDir, "fonts"));
      writeText(path.join(previewDir, "index.html"), approvedHtml(item));
      for (const source_path of ["assets/catalog.js", "assets/catalog.css"]) {
        const dst = path.join(sourceDir, path.basename(source_path));
        manifest.implementation_provenance.push({ source_path, preview_path: rel(liveRoot, dst), sha256: sha256(dst) });
      }
      manifest.host_fixture_reason = item.kind === "transition" ? "Neutral A/B scenes host approved transition." : null;
    } else {
      throw new Error(`${item.id}: unsupported source`);
    }
  } catch (error) {
    manifest.preview_status = "FAIL";
    manifest.errors.push(String(error?.message || error));
    writeText(path.join(previewDir, "index.html"), failureHtml(item, manifest.errors[0]));
  }

  writeJson(path.join(previewDir, "item-manifest.json"), manifest);
  return { safe, manifest };
}

function failureHtml(item, error) {
  return `<!doctype html><html lang="ru"><head><meta charset="UTF-8"><title>${escapeHtml(item.title)} — FAIL</title><style>html,body{margin:0;width:100%;height:100%;background:#3a1212;color:white;font-family:Arial,sans-serif}.preview-stage{width:1080px;height:1080px;display:grid;place-items:center;padding:48px;box-sizing:border-box;text-align:center}</style></head><body><main class="preview-stage" data-live-preview data-duration="1" data-width="1080" data-height="1080"><div><h1>FAIL</h1><p>${escapeHtml(error)}</p></div></main><script>window.__previewControl={duration:1,seek(){},play(){},pause(){},restart(){},status(){return {ready:false,error:${JSON.stringify(error)}}}}</script></body></html>`;
}

function writeGalleryShell(cards) {
  writeText(path.join(liveRoot, "index.html"), `<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>HyperFrames Live Gallery</title>
    <link rel="stylesheet" href="assets/gallery.css" />
  </head>
  <body>
    <header class="topbar">
      <div>
        <h1>HyperFrames Live Gallery</h1>
        <p>161 существующий catalog item, каждый preview собирается из реального source_ref.</p>
      </div>
      <div class="summary" id="summary"></div>
    </header>
    <section class="filters" aria-label="Фильтры">
      <input id="search" type="search" placeholder="Поиск по title, ID, description" />
      <select id="sourceFilter"><option value="">source</option></select>
      <select id="kindFilter"><option value="">kind</option></select>
      <select id="statusFilter"><option value="">review status</option></select>
      <select id="orientationFilter"><option value="">orientation</option></select>
      <select id="liveFilter"><option value="">live status</option><option>PASS</option><option>FAIL</option></select>
    </section>
    <main id="grid" class="grid" aria-live="polite"></main>
    <dialog id="modal">
      <div class="modal-shell">
        <div class="modal-head">
          <div><strong id="modalTitle"></strong><span id="modalMeta"></span></div>
          <button id="closeModal" type="button" aria-label="Закрыть">×</button>
        </div>
        <div id="iframeBox" class="iframe-box"></div>
        <div class="modal-controls">
          <button id="playBtn" type="button">Play</button>
          <button id="pauseBtn" type="button">Pause</button>
          <button id="restartBtn" type="button">Restart</button>
          <button data-jump="0" type="button">Start</button>
          <button data-jump="0.5" type="button">Middle</button>
          <button data-jump="0.95" type="button">End</button>
          <input id="scrubber" type="range" min="0" max="1" step="0.001" value="0" />
          <a id="manifestLink" target="_blank" rel="noreferrer">item manifest</a>
        </div>
        <pre id="modalError"></pre>
      </div>
    </dialog>
    <script src="assets/gallery.js"></script>
  </body>
</html>
`);
  writeText(path.join(liveRoot, "assets", "gallery.css"), galleryCss());
  writeText(path.join(liveRoot, "assets", "gallery.js"), galleryJs());
}

function galleryCss() {
  return `:root{color-scheme:dark;--bg:#11100f;--panel:#1e1c1a;--line:#38332f;--text:#f5f0e8;--muted:#b9aea4;--accent:#e7c75f;--bad:#e15b51;--ok:#7fcf91}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Arial,sans-serif}.topbar{display:flex;gap:24px;align-items:end;justify-content:space-between;padding:24px 28px;border-bottom:1px solid var(--line);background:#171513}.topbar h1{margin:0;font-size:28px}.topbar p{margin:6px 0 0;color:var(--muted)}.summary{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.chip,.badge{display:inline-flex;align-items:center;height:24px;padding:0 8px;border-radius:5px;background:#2b2723;color:#ddd;font-size:12px}.filters{position:sticky;top:0;z-index:5;display:grid;grid-template-columns:minmax(260px,1fr) repeat(5,150px);gap:10px;padding:14px 28px;background:#151311;border-bottom:1px solid var(--line)}input,select,button{height:36px;border:1px solid var(--line);border-radius:6px;background:#23201d;color:var(--text);padding:0 10px}button{cursor:pointer}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;padding:22px 28px}.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden;min-width:0}.thumb{position:relative;aspect-ratio:16/10;background:#0b0b0b;display:grid;place-items:center;overflow:hidden}.thumb img{width:100%;height:100%;object-fit:contain;background:#080808}.card-body{padding:12px}.card h2{font-size:16px;margin:0 0 6px}.id{font-size:11px;color:var(--muted);word-break:break-all}.meta{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.desc{font-size:12px;line-height:1.35;color:#d8d1c9;min-height:34px}.actions{display:flex;gap:8px;margin-top:12px}.actions button,.actions a{flex:1;display:inline-flex;align-items:center;justify-content:center;height:34px;border-radius:6px;border:1px solid var(--line);background:#2a2723;color:var(--text);text-decoration:none;font-size:12px}.pass{color:#0d2214;background:#a4e7b4}.fail{color:#fff;background:#9d2e28}.forbidden{border-color:var(--bad);box-shadow:inset 0 0 0 2px rgba(225,91,81,.25)}.forbidden-banner{background:var(--bad);color:white;padding:6px 10px;font-weight:700;font-size:12px}dialog{width:min(1160px,94vw);border:1px solid var(--line);border-radius:8px;background:#171513;color:var(--text);padding:0}dialog::backdrop{background:rgba(0,0,0,.72)}.modal-shell{display:grid;grid-template-rows:auto minmax(260px,70vh) auto auto}.modal-head{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:12px 14px;border-bottom:1px solid var(--line)}#modalMeta{display:block;color:var(--muted);font-size:12px;margin-top:3px}#closeModal{width:38px;font-size:24px}.iframe-box{display:grid;place-items:center;padding:12px;background:#080808;overflow:hidden}.preview-frame-wrap{position:relative;overflow:hidden;flex:0 0 auto}.preview-frame-wrap iframe{display:block;border:0;background:#111;max-width:none;max-height:none;transform-origin:0 0}.modal-controls{display:flex;gap:8px;align-items:center;padding:12px 14px;border-top:1px solid var(--line);flex-wrap:wrap}.modal-controls a{color:var(--accent)}#scrubber{flex:1;min-width:180px}#modalError{margin:0;padding:0 14px 14px;color:#ffb2aa;white-space:pre-wrap;font-size:12px}@media(max-width:900px){.topbar{display:block}.filters{grid-template-columns:1fr 1fr}.filters input{grid-column:1/-1}}`;
}

function galleryJs() {
  return `let manifest;let cards=[];const $=(id)=>document.getElementById(id);async function init(){manifest=await fetch('reports/live-gallery-manifest.json').then(r=>r.json());cards=manifest.items;fillFilters();renderSummary();render();wireModal();}function uniq(k){return [...new Set(cards.map(c=>c[k]).filter(Boolean))].sort()}function fillFilters(){for(const [id,key] of [['sourceFilter','source'],['kindFilter','kind'],['statusFilter','review_status'],['orientationFilter','orientation']]){const s=$(id);for(const v of uniq(key)){const o=document.createElement('option');o.value=v;o.textContent=v;s.appendChild(o)}s.addEventListener('change',render)}$('search').addEventListener('input',render);$('liveFilter').addEventListener('change',render)}function renderSummary(){const counts={total:cards.length,pass:cards.filter(c=>c.live_status==='PASS').length,fail:cards.filter(c=>c.live_status==='FAIL').length};$('summary').innerHTML=['total '+counts.total,'PASS '+counts.pass,'FAIL '+counts.fail].map(t=>'<span class=\"chip\">'+t+'</span>').join('')}function match(c){const q=$('search').value.toLowerCase();if(q&&!JSON.stringify([c.id,c.title,c.description,c.name]).toLowerCase().includes(q))return false;for(const [id,key] of [['sourceFilter','source'],['kindFilter','kind'],['statusFilter','review_status'],['orientationFilter','orientation'],['liveFilter','live_status']]){const v=$(id).value;if(v&&c[key]!==v)return false}return true}function render(){const grid=$('grid');const shown=cards.filter(match);grid.innerHTML=shown.map(cardHtml).join('')}function cardHtml(c){const forbidden=c.review_status==='forbidden';return '<article class=\"card '+(forbidden?'forbidden':'')+'\">'+(forbidden?'<div class=\"forbidden-banner\">FORBIDDEN</div>':'')+'<div class=\"thumb\"><img src=\"'+c.thumbnail+'\" alt=\"\"></div><div class=\"card-body\"><h2>'+esc(c.title)+'</h2><div class=\"id\">'+esc(c.id)+'</div><div class=\"meta\"><span class=\"badge\">'+c.source+'</span><span class=\"badge\">'+c.kind+'</span><span class=\"badge\">'+c.review_status+'</span><span class=\"badge\">'+c.orientation+'</span><span class=\"badge '+(c.live_status==='PASS'?'pass':'fail')+'\">'+c.live_status+'</span>'+(c.host_fixture?'<span class=\"badge\">host fixture</span>':'')+'</div><p class=\"desc\">'+esc(c.description||'')+'</p><div class=\"meta\"><span class=\"badge\">'+dims(c)+'</span><span class=\"badge\">'+dur(c)+'</span></div><div class=\"actions\"><button type=\"button\" onclick=\"openPreview(\\''+c.safe_id+'\\')\">Открыть live preview</button><a href=\"'+c.item_manifest_url+'\" target=\"_blank\">Показать source</a></div></div></article>'}function dims(c){return (c.dimensions?.width||'?')+'x'+(c.dimensions?.height||'?')}function dur(c){return (c.duration_seconds||'?')+'s'}function esc(s){return String(s??'').replace(/[&<>\"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[m]))}window.openPreview=function(safe){const c=cards.find(x=>x.safe_id===safe);const box=$('iframeBox');box.innerHTML='';if(window.currentResize)window.removeEventListener('resize',window.currentResize);const wrap=document.createElement('div');wrap.className='preview-frame-wrap';const iframe=document.createElement('iframe');iframe.src=c.preview_url;const w=c.dimensions?.width||1080,h=c.dimensions?.height||1080;iframe.width=w;iframe.height=h;iframe.style.width=w+'px';iframe.style.height=h+'px';iframe.dataset.loaded='true';wrap.appendChild(iframe);box.appendChild(wrap);const resize=()=>{const bw=Math.max(1,box.clientWidth-24),bh=Math.max(1,box.clientHeight-24);const scale=Math.min(bw/w,bh/h);wrap.style.width=(w*scale)+'px';wrap.style.height=(h*scale)+'px';iframe.style.transform='scale('+scale+')'};window.currentResize=resize;window.addEventListener('resize',resize);requestAnimationFrame(resize);$('modalTitle').textContent=c.title;$('modalMeta').textContent=c.id+' · '+dims(c)+' · '+dur(c);$('manifestLink').href=c.item_manifest_url;$('modalError').textContent=c.error||'';$('scrubber').value=0;$('modal').showModal();window.currentFrame=iframe;window.currentCard=c};function ctrl(fn,arg){const w=window.currentFrame?.contentWindow;try{w?.__previewControl?.[fn]?.(arg)}catch(e){$('modalError').textContent=String(e)}}function wireModal(){$('closeModal').onclick=close;$('modal').addEventListener('close',()=>{$('iframeBox').innerHTML=''});$('playBtn').onclick=()=>ctrl('play');$('pauseBtn').onclick=()=>ctrl('pause');$('restartBtn').onclick=()=>ctrl('restart');document.querySelectorAll('[data-jump]').forEach(b=>b.onclick=()=>{const d=window.currentCard?.duration_seconds||5;ctrl('seek',d*Number(b.dataset.jump))});$('scrubber').oninput=(e)=>{const d=window.currentCard?.duration_seconds||5;ctrl('seek',d*Number(e.target.value))};document.addEventListener('keydown',(e)=>{if(e.key==='Escape'&&$('modal').open)close()})}function close(){if(window.currentResize)window.removeEventListener('resize',window.currentResize);window.currentResize=null;$('modal').close();$('iframeBox').innerHTML=''}init();`;
}

function writeReadme() {
  writeText(path.join(liveRoot, "README.md"), `# Stage 01.2 Live Gallery

Галерея показывает ровно 161 существующий catalog item из \`inventory/items.json\`: upstream blocks/components, local blocks, approved layouts и approved transitions.

## Команды

\`\`\`powershell
node experiments/hyperframes-workflow-poc/stage-01-catalog/live-gallery/scripts/build-live-gallery.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/live-gallery/scripts/capture-live-gallery.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/live-gallery/scripts/validate-live-gallery.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/live-gallery/scripts/serve-live-gallery.mjs
\`\`\`

Server слушает только \`http://127.0.0.1:4173/\`.

Preview pages лежат в \`previews/<safe-catalog-id>/index.html\`, thumbnails сняты локально из этих pages, contact sheets лежат в \`contact-sheets/\`.
`);
}

function main() {
  const sourceManifest = readJson(sourceManifestPath);
  const items = readJson(inventoryPath);
  const ids = new Set(items.map((item) => item.id));
  if (items.length !== 161 || ids.size !== 161) throw new Error(`Expected 161 unique items, got ${items.length}/${ids.size}`);
  const counts = {};
  for (const item of items) counts[`${item.source}:${item.kind}`] = (counts[`${item.source}:${item.kind}`] || 0) + 1;
  for (const [key, value] of Object.entries(EXPECTED)) {
    if (counts[key] !== value) throw new Error(`Count mismatch ${key}: ${counts[key]} !== ${value}`);
  }
  if (!fs.existsSync(gsapSource)) throw new Error(`Missing local GSAP runtime: ${gsapSource}`);
  if (!fs.existsSync(avatarSource)) throw new Error(`Missing avatar fixture video: ${avatarSource}`);

  resetOutput();
  fs.mkdirSync(runtimeRoot, { recursive: true });
  fs.mkdirSync(fixturesRoot, { recursive: true });
  copyFile(gsapSource, path.join(runtimeRoot, "gsap.min.js"));
  copyFile(avatarSource, path.join(fixturesRoot, "avatar.mp4"));
  try { fs.linkSync(path.join(fixturesRoot, "avatar.mp4"), path.join(fixturesRoot, "neutral-video.mp4")); }
  catch { copyFile(avatarSource, path.join(fixturesRoot, "neutral-video.mp4")); }
  copyFile(path.join(stageRoot, "gallery/assets/posters/approved-contact-sheet.jpg"), path.join(fixturesRoot, "neutral-image.jpg"));
  const firstPng = fs.readdirSync(path.join(stageRoot, "gallery/assets/posters")).find((name) => name.endsWith(".png"));
  copyFile(path.join(stageRoot, "gallery/assets/posters", firstPng), path.join(fixturesRoot, "neutral-square.png"));
  writeText(path.join(fixturesRoot, "neutral-code.txt"), "const preview = 'real source_ref implementation';\nconsole.log(preview);\n");

  const reverse_mapping = {};
  const manifestItems = [];
  let localized = 0;
  let harness = 0;
  for (const item of items) {
    const { safe, manifest } = buildPreview(item);
    if (manifest.host_fixture) harness += 1;
    localized += manifest.localized_remote_dependencies.length;
    reverse_mapping[safe] = item.id;
    const manifestRel = `previews/${safe}/item-manifest.json`;
    manifestItems.push(makeCardData(item, safe, manifestRel));
  }
  writeGalleryShell(manifestItems);
  writeReadme();
  const liveManifest = {
    generated_by: "build-live-gallery.mjs",
    source_inventory: rel(liveRoot, inventoryPath),
    source_manifest_sha256: sha256(sourceManifestPath),
    source_manifest: sourceManifest,
    counts,
    total: manifestItems.length,
    pass: 0,
    fail: 0,
    localized_remote_dependencies: localized,
    harness_fixtures: harness,
    reverse_mapping,
    items: manifestItems,
  };
  writeJson(path.join(liveRoot, "reports", "live-gallery-manifest.json"), liveManifest);
  writeJson(path.join(liveRoot, "reports", "runtime-results.json"), { generated_by: "build-live-gallery.mjs", entries: [] });
  writeJson(path.join(liveRoot, "reports", "failures.json"), []);
  writeText(path.join(liveRoot, "reports", "live-gallery-audit.md"), "# Live gallery audit\n\nCapture and validation have not been run yet.\n");
  console.log(`Built live gallery previews: ${manifestItems.length}`);
  console.log(`Counts: ${JSON.stringify(counts)}`);
}

main();
