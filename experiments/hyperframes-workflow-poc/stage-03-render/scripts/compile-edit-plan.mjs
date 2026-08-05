import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const stageDir = resolve(here, "..");
const repoRoot = resolve(stageDir, "..", "..", "..");
const projectDir = resolve(stageDir, "project");
const compositionDir = resolve(projectDir, "compositions");
const reportsDir = resolve(stageDir, "reports");

const WIDTH = 1080;
const HEIGHT = 1920;
const DURATION = 42.32;
const FPS = 30;

const localBlockSource = {
  "local:block:stat_number": "plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py#build_stat_number_html",
  "local:block:complexity_cloud": "plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py#build_complexity_cloud_html",
  "local:block:task_list": "plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py#build_task_list_html",
  "local:block:concept_nodes": "plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py#build_concept_nodes_html",
  "local:block:persona_card": "plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py#build_persona_card_html",
  "local:block:value_layers": "plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py#build_value_layers_html",
  "local:block:sequence_flow": "plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py#build_sequence_flow_html",
};

const layoutAdapterSource = "plan-previews/two-reel-catalog-proxy-20260729/assets/catalog.js + catalog.css";

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function num(value) {
  return Number.parseFloat(Number(value).toFixed(3));
}

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

function assertTimeline(plan) {
  if (Math.abs(Number(plan.duration_seconds) - DURATION) > 0.001) {
    throw new Error(`Plan duration changed: ${plan.duration_seconds}`);
  }
  if (plan.scenes.length !== 13) throw new Error(`Expected 13 scenes, got ${plan.scenes.length}`);
  let cursor = 0;
  for (const scene of plan.scenes) {
    if (Math.abs(scene.start - cursor) > 0.001) {
      throw new Error(`${scene.scene_id}: non-contiguous start ${scene.start}, expected ${cursor}`);
    }
    if (Math.abs(scene.duration - (scene.end - scene.start)) > 0.001) {
      throw new Error(`${scene.scene_id}: duration mismatch`);
    }
    cursor = scene.end;
  }
  if (Math.abs(cursor - DURATION) > 0.001) throw new Error(`Timeline end ${cursor} != ${DURATION}`);
}

function inventoryLookup(items, id) {
  if (!id) return null;
  const item = items.find((entry) => entry.id === id);
  if (!item) throw new Error(`Catalog item not found: ${id}`);
  return item;
}

function normalizeWord(value) {
  return String(value || "").toLocaleLowerCase("ru").replace(/[^\p{L}\p{N}]+/gu, "");
}

function captionGroups(scene, words) {
  if (scene.captions === "hidden") return [];
  const sceneWords = words.filter((word) => word.index >= scene.word_start && word.index <= scene.word_end);
  const groups = [];
  for (let i = 0; i < sceneWords.length; i += 6) {
    const chunk = sceneWords.slice(i, i + 6);
    if (!chunk.length) continue;
    groups.push({
      id: `${scene.scene_id}-cap-${String(groups.length + 1).padStart(2, "0")}`,
      start: Math.max(scene.start, chunk[0].start),
      end: Math.min(scene.end, chunk.at(-1).end),
      words: chunk,
    });
  }
  return groups;
}

function captionHtml(scene, group) {
  const emphasis = new Set((scene.content.emphasis_words || []).map(normalizeWord));
  const words = group.words.map((word, index) => {
    const clean = normalizeWord(word.text);
    const cls = emphasis.has(clean) || index === group.words.length - 1 ? "current" : "past";
    return `<span class="${cls}">${esc(word.text)}</span>`;
  }).join(" ");
  return `      <div id="${group.id}" class="clip caption" data-start="${num(group.start)}" data-duration="${num(Math.max(0.08, group.end - group.start))}" data-track-index="50" data-layout-allow-caption-zone>${words}</div>`;
}

function sfxClips(sourceAssets) {
  const available = new Set((sourceAssets.sfx || []).filter((item) => item.available).map((item) => item.name));
  const cues = [];
  if (available.has("pop.wav")) {
    for (const at of [34.980, 35.940, 37.460]) {
      cues.push({ at, name: "pop.wav", volume: 0.15, purpose: "payoff click" });
    }
    cues.push({ at: 41.915, name: "pop.wav", volume: 0.12, purpose: "CTA confirmation" });
  }
  if (available.has("whoosh.wav")) {
    for (const at of [11.520, 28.880, 37.960]) {
      cues.push({ at, name: "whoosh.wav", volume: 0.11, purpose: "editorial push accent" });
    }
  }
  return cues;
}

function sceneTone(scene) {
  if (scene.avatar_direction === "hidden") return "opaque";
  if (scene.avatar_direction === "fullscreen") return "clear";
  return "mixed";
}

function labels(scene) {
  return (scene.content.labels || []).filter(Boolean);
}

function headline(scene) {
  return scene.content.headline || scene.speech || "";
}

function chipList(items, cls = "chip") {
  return items.map((item, index) => `<div id="item-${index + 1}" class="${cls}">${esc(item)}</div>`).join("\n        ");
}

function blockMarkup(scene) {
  const block = scene.primary_block_id;
  const title = headline(scene);
  const list = labels(scene);
  if (block === "local:block:stat_number") {
    return `<section class="block stat-block">
        <div id="${scene.scene_id}-stat" class="stat">3</div>
        <h1>${esc(title)}</h1>
      </section>`;
  }
  if (block === "local:block:sequence_flow") {
    return `<section class="block flow-block">
        <h1>${esc(title)}</h1>
        <div class="flow-steps">${chipList(list.length ? list : ["КТО", "ЧТО", "КАК"], "flow-step")}</div>
      </section>`;
  }
  if (block === "local:block:complexity_cloud") {
    return `<section class="block cloud-block">
        <h1>${esc(title)}</h1>
        <div class="cloud">${chipList(list.concat(scene.content.emphasis_words || []).slice(0, 5), "cloud-chip")}</div>
        <div class="resolve">ОСНОВА ПРОЩЕ</div>
      </section>`;
  }
  if (block === "local:block:task_list") {
    return `<section class="block task-block">
        <h1>${esc(title)}</h1>
        <div class="tasks">${chipList(list, "task-row")}</div>
      </section>`;
  }
  if (block === "local:block:concept_nodes") {
    return `<section class="block nodes-block">
        <div class="hub">${esc(title)}</div>
        <div class="node node-a">${esc(list[0] || "КТО")}</div>
        <div class="node node-b">${esc(list[1] || "ЧТО")}</div>
        <div class="node node-c">${esc(list[2] || "КАК")}</div>
      </section>`;
  }
  if (block === "local:block:persona_card") {
    return `<section class="block persona-block">
        <h1>${esc(title)}</h1>
        <div class="person-mark">Ч</div>
        <div class="persona-list">${chipList(list, "persona-row")}</div>
      </section>`;
  }
  if (block === "local:block:value_layers") {
    return `<section class="block value-block">
        <h1>${esc(title)}</h1>
        <div class="layer muted">${esc(list[0] || "ПРОДУКТ")}</div>
        <div class="arrow">↓</div>
        <div class="layer accent">${esc(list[1] || "РЕАЛЬНАЯ ЦЕННОСТЬ")}</div>
      </section>`;
  }
  return `<section class="block anchor-block"><h1>${esc(title)}</h1></section>`;
}

function layoutChrome(scene) {
  if (scene.avatar_direction === "hidden") return `<div class="cover"></div>`;
  if (scene.avatar_direction === "editorial_bubble") {
    return `<div class="paper-left"></div><div class="bubble-frame"></div>`;
  }
  if (scene.avatar_direction === "object_overlay") {
    return `<div class="side-shade"></div>`;
  }
  if (scene.avatar_direction === "split") {
    return `<div class="split-panel"></div><div class="split-line"></div>`;
  }
  if (scene.avatar_direction === "fullscreen") {
    return `<div class="fullscreen-shade"></div>`;
  }
  return "";
}

function sceneCss(scene) {
  const tone = sceneTone(scene);
  const block = scene.primary_block_id || "avatar";
  return `
      @font-face{font-family:Unbounded;font-style:normal;font-weight:600;src:url("assets/fonts/unbounded-600-cyrillic.woff2") format("woff2");}
      @font-face{font-family:Unbounded;font-style:normal;font-weight:700;src:url("assets/fonts/unbounded-700-cyrillic.woff2") format("woff2");}
      @font-face{font-family:Unbounded;font-style:normal;font-weight:800;src:url("assets/fonts/unbounded-800-cyrillic.woff2") format("woff2");}
      @font-face{font-family:Manrope;font-style:normal;font-weight:700;src:url("assets/fonts/manrope-700-cyrillic.woff2") format("woff2");}
      #root{position:absolute;inset:0;width:${WIDTH}px;height:${HEIGHT}px;overflow:hidden;color:#fff;font-family:Manrope,Arial,sans-serif;}
      .scene-clip{position:absolute;inset:0;width:100%;height:100%;overflow:hidden;}
      .cover{position:absolute;inset:0;background:#171310;background-image:radial-gradient(760px 680px at 12% 12%,rgba(216,58,50,.28),transparent 62%),radial-gradient(760px 720px at 90% 86%,rgba(240,185,76,.14),transparent 65%);}
      .paper-left{position:absolute;left:0;top:0;width:58%;height:100%;background:#f3efe7;color:#171310;box-shadow:40px 0 80px rgba(23,19,16,.18);}
      .bubble-frame{position:absolute;right:58px;top:430px;width:520px;height:900px;border:5px solid #d83a32;border-radius:48% 48% 18% 48%/34% 34% 16% 34%;box-shadow:28px 30px 0 rgba(216,58,50,.18);background:rgba(0,0,0,0);}
      .side-shade{position:absolute;inset:0;background:linear-gradient(90deg,rgba(23,19,16,.08),rgba(23,19,16,.05) 45%,rgba(23,19,16,.82));}
      .split-panel{position:absolute;right:0;top:0;width:54%;height:100%;background:#171310;background-image:radial-gradient(600px 700px at 80% 15%,rgba(216,58,50,.22),transparent 62%);}
      .split-line{position:absolute;left:46%;top:0;width:8px;height:100%;background:#d83a32;transform-origin:50% 0;}
      .fullscreen-shade{position:absolute;inset:0;background:linear-gradient(0deg,rgba(23,19,16,.85),rgba(23,19,16,.04) 48%,rgba(23,19,16,.16));}
      .block{position:absolute;z-index:5;}
      .block h1{margin:0;font-family:Unbounded,sans-serif;font-weight:800;letter-spacing:0;line-height:1.06;text-wrap:balance;}
      .stat-block{right:56px;top:420px;width:500px;text-align:center;}
      .stat{font-family:Unbounded;font-size:360px;line-height:.92;font-weight:800;color:#FFE500;text-shadow:0 26px 80px rgba(255,229,0,.16);}
      .stat-block h1{font-size:56px;}
      .flow-block{left:${tone === "opaque" ? "86px" : scene.avatar_direction === "split" ? "545px" : "86px"};top:${scene.scene_id === "s12" ? "330px" : "330px"};width:${scene.avatar_direction === "split" ? "470px" : "910px"};text-align:${scene.scene_id === "s12" ? "center" : "left"};}
      .flow-block h1{font-size:${scene.scene_id === "s12" ? "108px" : "64px"};color:${tone === "opaque" ? "#fff" : "#f3efe7"};}
      .flow-steps{display:grid;gap:24px;margin-top:54px;}
      .flow-step{padding:32px 36px;border:3px solid #FFE500;border-radius:28px;background:rgba(255,229,0,.1);font-family:Unbounded;font-size:${scene.scene_id === "s12" ? "72px" : "48px"};font-weight:800;text-align:center;}
      .cloud-block{left:72px;top:300px;width:936px;text-align:center;}
      .cloud-block h1{font-size:72px;margin-bottom:64px;}
      .cloud{position:relative;height:720px;}
      .cloud-chip{position:relative;display:inline-block;margin:18px;padding:28px 34px;border:2px solid rgba(255,255,255,.18);border-radius:28px;background:rgba(255,255,255,.07);font-family:Unbounded;font-size:42px;font-weight:700;}
      .resolve{position:absolute;left:130px;right:130px;bottom:110px;padding:34px;border:3px solid #FFE500;border-radius:34px;background:rgba(255,229,0,.12);font-family:Unbounded;font-size:48px;font-weight:800;}
      .task-block{left:86px;top:${scene.scene_id === "s13" ? "500px" : "330px"};width:${scene.scene_id === "s13" ? "760px" : "900px"};}
      .task-block h1{font-size:${scene.scene_id === "s13" ? "70px" : "76px"};margin-bottom:52px;}
      .tasks{display:grid;gap:20px;}
      .task-row{padding:28px 34px;border-radius:28px;background:#f0b94c;color:#171310;font-family:Unbounded;font-size:42px;font-weight:800;}
      .nodes-block{position:absolute;inset:0;}
      .hub{position:absolute;left:250px;top:680px;width:580px;height:330px;display:flex;align-items:center;justify-content:center;padding:42px;border:4px solid #FFE500;border-radius:50%;background:rgba(255,229,0,.12);font-family:Unbounded;font-size:48px;font-weight:800;line-height:1.08;text-align:center;}
      .node{position:absolute;width:330px;min-height:170px;display:flex;align-items:center;justify-content:center;padding:28px;border:2px solid rgba(255,255,255,.22);border-radius:32px;background:#f3efe7;color:#171310;font-family:Unbounded;font-size:42px;font-weight:800;text-align:center;}
      .node-a{left:375px;top:320px}.node-b{left:80px;top:1210px}.node-c{right:80px;top:1210px}
      .persona-block{right:50px;top:300px;width:500px;padding:42px;border:3px solid #FFE500;border-radius:42px;background:rgba(23,19,16,.72);}
      .persona-block h1{font-size:50px;text-align:center;}
      .person-mark{width:120px;height:120px;margin:34px auto;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#FFE500;color:#171310;font-family:Unbounded;font-size:64px;font-weight:800;}
      .persona-list{display:grid;gap:14px}.persona-row{padding:20px;border-radius:22px;background:rgba(255,255,255,.1);font-size:28px;font-weight:800;}
      .value-block{left:84px;top:300px;width:912px;text-align:center}.value-block h1{font-size:74px;margin-bottom:60px;}
      .layer{padding:48px;border:2px solid rgba(255,255,255,.2);border-radius:36px;background:rgba(255,255,255,.08);font-family:Unbounded;font-size:58px;font-weight:800}.layer.accent{border-color:#FFE500;background:rgba(255,229,0,.12);color:#FFE500}.arrow{font-size:72px;color:#FFE500;margin:22px 0;}
      .anchor-block{left:70px;right:70px;bottom:${scene.scene_id === "s11" ? "500px" : "220px"};text-align:left}.anchor-block h1{font-size:${scene.scene_id === "s13" ? "78px" : "86px"};text-shadow:0 16px 50px rgba(0,0,0,.75);}
      .scene-meta{position:absolute;left:54px;top:54px;padding:10px 14px;border-radius:999px;background:rgba(23,19,16,.82);color:#FFE500;font-size:22px;font-weight:800;letter-spacing:5px;}
      .handle{position:absolute;right:54px;bottom:54px;padding:14px 20px;border-radius:999px;background:rgba(23,19,16,.78);font-size:28px;font-weight:800;color:#FFE500;}
    `;
}

function sceneScript(scene) {
  const d = Math.max(0.6, scene.duration);
  const itemTweenBlocks = new Set([
    "local:block:sequence_flow",
    "local:block:complexity_cloud",
    "local:block:task_list",
    "local:block:concept_nodes",
    "local:block:persona_card",
    "local:block:value_layers",
  ]);
  const optionalTweens = [];
  if (itemTweenBlocks.has(scene.primary_block_id)) {
    optionalTweens.push(`tl.fromTo(".flow-step,.task-row,.cloud-chip,.persona-row,.node,.layer",{opacity:0,y:44,scale:.9},{opacity:1,y:0,scale:1,duration:.42,stagger:.12,ease:"back.out(1.3)"},0.42);`);
  }
  if (scene.primary_block_id === "local:block:stat_number") {
    optionalTweens.push(`tl.fromTo(".stat",{innerText:0,scale:.72,opacity:0},{innerText:3,snap:{innerText:1},scale:1,opacity:1,duration:1.18,ease:"power2.out"},0.28);`);
  }
  if (scene.avatar_direction === "split") {
    optionalTweens.push(`tl.fromTo(".split-line",{scaleY:0},{scaleY:1,duration:.42},0.18);`);
  }
  return `
      window.__timelines=window.__timelines||{};
      const tl=gsap.timeline({paused:true,defaults:{ease:"power3.out"}});
      tl.fromTo(".block",{opacity:0,y:64,scale:.96},{opacity:1,y:0,scale:1,duration:${Math.min(0.62, d * 0.24).toFixed(3)}},0.12);
      ${optionalTweens.join("\n      ")}
      tl.to(".block",{scale:1.018,duration:${Math.max(0.6, d - 0.9).toFixed(3)},ease:"sine.inOut"},0.8);
      window.__timelines["${scene.scene_id}"]=tl;
    `;
}

function sceneHtml(scene) {
  const chrome = layoutChrome(scene);
  const block = scene.primary_block_id ? blockMarkup(scene) : `<section class="block anchor-block"><h1>${esc(headline(scene))}</h1></section>`;
  const handle = scene.scene_id === "s13" ? `<div class="handle">@julia.agents</div>` : "";
  return `<!doctype html>
<html lang="ru">
  <head><meta charset="UTF-8"><meta name="viewport" content="width=${WIDTH}, height=${HEIGHT}"></head>
  <body>
    <template>
      <style>${sceneCss(scene)}</style>
      <div id="root" data-composition-id="${scene.scene_id}" data-width="${WIDTH}" data-height="${HEIGHT}" data-duration="${num(scene.duration)}">
        <section id="${scene.scene_id}-canvas" class="clip scene-clip" data-start="0" data-duration="${num(scene.duration)}" data-track-index="0">
          ${chrome}
          <div class="scene-meta">${esc(scene.scene_id.toUpperCase())} / ${esc(scene.avatar_direction)}</div>
          ${block}
          ${handle}
        </section>
        <script>${sceneScript(scene)}</script>
      </div>
    </template>
  </body>
</html>
`;
}

function indexHtml(plan, words, sourceAssets) {
  const captions = plan.scenes.flatMap((scene) => captionGroups(scene, words.words).map((group) => captionHtml(scene, group))).join("\n");
  const sceneSlots = plan.scenes.map((scene) => `      <div id="slot-${scene.scene_id}" class="clip scene-slot" data-composition-id="${scene.scene_id}" data-composition-src="compositions/${scene.scene_id}.html" data-start="${num(scene.start)}" data-duration="${num(scene.duration)}" data-track-index="10" data-width="${WIDTH}" data-height="${HEIGHT}"></div>`).join("\n");
  const transitionClips = plan.scenes
    .filter((scene) => scene.start > 0 && scene.transition_in_id !== "approved:transition:hard_cut")
    .map((scene) => {
      const cls = scene.transition_in_id.includes("white_flash") ? "white-flash" : "push-accent";
      const duration = cls === "white-flash" ? 0.12 : 0.28;
      return `      <div id="transition-${scene.scene_id}" class="clip transition ${cls}" data-start="${num(scene.start)}" data-duration="${duration}" data-track-index="60"></div>`;
    }).join("\n");
  const sfx = sfxClips(sourceAssets).map((cue, index) => {
    const cueDuration = cue.name === "pop.wav" ? 0.12 : 0.35;
    return `      <audio id="sfx-${index + 1}" src="assets/media/sfx/${cue.name}" data-start="${cue.at.toFixed(3)}" data-duration="${cueDuration}" data-track-index="${80 + index}" data-volume="${cue.volume}"></audio>`;
  }).join("\n");
  return `<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=${WIDTH}, height=${HEIGHT}">
    <title>sales-three-questions-draft</title>
    <script src="assets/vendor/gsap.min.js"></script>
    <style>
      @font-face{font-family:Unbounded;font-style:normal;font-weight:600;src:url("assets/fonts/unbounded-600-cyrillic.woff2") format("woff2");}
      @font-face{font-family:Unbounded;font-style:normal;font-weight:700;src:url("assets/fonts/unbounded-700-cyrillic.woff2") format("woff2");}
      @font-face{font-family:Unbounded;font-style:normal;font-weight:800;src:url("assets/fonts/unbounded-800-cyrillic.woff2") format("woff2");}
      html,body{margin:0;width:${WIDTH}px;height:${HEIGHT}px;overflow:hidden;background:#171310;color:#fff;font-family:Unbounded,sans-serif;}
      #root{position:relative;width:${WIDTH}px;height:${HEIGHT}px;overflow:hidden;background:#171310;}
      .base-video{position:absolute;inset:0;width:${WIDTH}px;height:${HEIGHT}px;object-fit:cover;object-position:50% 48%;z-index:0;}
      .scene-slot{position:absolute;inset:0;z-index:20;}
      .caption{position:absolute;z-index:70;left:60px;right:60px;bottom:150px;min-height:78px;padding:22px 28px;border-radius:26px;background:rgba(23,19,16,.86);box-shadow:0 18px 50px rgba(0,0,0,.28);font-family:Unbounded;font-size:36px;font-weight:700;line-height:1.22;text-align:center;text-wrap:balance;}
      .caption .past{color:#fff}.caption .current{color:#FFE500;}
      .watermark{position:absolute;z-index:75;right:38px;top:44px;padding:12px 18px;border-radius:999px;background:rgba(23,19,16,.62);color:#FFE500;font-family:Unbounded;font-size:25px;font-weight:800;}
      .transition{position:absolute;inset:0;z-index:90;pointer-events:none;}
      .white-flash{background:#fffdf5;}
      .push-accent{background:linear-gradient(90deg,rgba(216,58,50,.0),rgba(216,58,50,.86),rgba(240,185,76,.0));transform:skewX(-12deg);}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="sales-three-questions-draft" data-start="0" data-width="${WIDTH}" data-height="${HEIGHT}" data-duration="${DURATION}" data-fps="${FPS}">
      <video id="avatar-base-video" class="clip base-video" src="assets/media/avatar-base-silent.mp4" data-start="0" data-duration="${DURATION}" data-track-index="0" muted playsinline></video>
${sceneSlots}
      <div id="watermark" class="clip watermark" data-start="2" data-duration="${DURATION - 2}" data-track-index="55">@julia.agents</div>
${captions}
${transitionClips}
${sfx}
      <audio id="master-voice" src="assets/media/voice_master.wav" data-start="0" data-duration="${DURATION}" data-track-index="100" data-volume="1"></audio>
    </div>
    <script>
      window.__timelines=window.__timelines||{};
      const tl=gsap.timeline({paused:true});
      tl.fromTo(".white-flash",{opacity:1},{opacity:0,duration:.12,ease:"power2.out"},34.44);
      tl.fromTo(".push-accent",{x:-1080,opacity:.9},{x:1080,opacity:0,duration:.28,ease:"power3.inOut"},11.52);
      tl.fromTo(".push-accent",{x:-1080,opacity:.9},{x:1080,opacity:0,duration:.28,ease:"power3.inOut"},28.88);
      tl.fromTo(".push-accent",{x:-1080,opacity:.9},{x:1080,opacity:0,duration:.28,ease:"power3.inOut"},37.96);
      window.__timelines["sales-three-questions-draft"]=tl;
    </script>
  </body>
</html>
`;
}

function packageJson() {
  return `${JSON.stringify({
    name: "sales-three-questions-stage-03-render",
    private: true,
    type: "module",
    scripts: {
      lint: "npx --yes hyperframes@0.7.88 lint --json",
      check: "npx --yes hyperframes@0.7.88 check --json",
      snapshot: "npx --yes hyperframes@0.7.88 snapshot",
      render: "npx --yes hyperframes@0.7.88 render --quality draft --fps 30 --output ../renders/sales-three-questions-draft.mp4",
    },
    dependencies: {},
  }, null, 2)}\n`;
}

function hyperframesJson() {
  return `${JSON.stringify({
    $schema: "https://hyperframes.heygen.com/schema/hyperframes.json",
    registry: "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
    skill: "general-video",
    paths: { blocks: "compositions", components: "compositions/components", assets: "assets" },
    media: { autoProxy: true },
  }, null, 2)}\n`;
}

function reportFor(plan, items, sourceAssets) {
  return {
    generated_at: new Date().toISOString(),
    project: {
      width: WIDTH,
      height: HEIGHT,
      fps: FPS,
      duration: DURATION,
      root: projectDir,
      hyperframes_pin: "0.7.88",
      hyperframes_upgrade: "0.7.87 -> 0.7.88",
    },
    source_implementations: {
      approved_layout_adapter: layoutAdapterSource,
      local_blocks: localBlockSource,
    },
    scenes: plan.scenes.map((scene) => {
      const layout = inventoryLookup(items, scene.layout_id);
      const block = scene.primary_block_id ? inventoryLookup(items, scene.primary_block_id) : null;
      return {
        scene_id: scene.scene_id,
        start: scene.start,
        end: scene.end,
        duration: scene.duration,
        requested: {
          layout_id: scene.layout_id,
          primary_block_id: scene.primary_block_id,
          technique_ids: scene.technique_ids,
          adaptation_requests: scene.adaptation_requests,
        },
        resolved: {
          layout_source_ref: layout.source_ref,
          layout_evidence_refs: layout.evidence_refs,
          block_source_ref: block?.source_ref ?? null,
          block_evidence_refs: block?.evidence_refs ?? null,
          actual_source_implementation: scene.primary_block_id ? localBlockSource[scene.primary_block_id] : layoutAdapterSource,
          fallback: scene.adaptation_requests?.map((request) => ({
            catalog_id: request.catalog_id,
            fallback_catalog_id: request.fallback_catalog_id,
            used: true,
          })) ?? [],
        },
        variables: {
          headline: scene.content.headline,
          labels: scene.content.labels,
          emphasis_words: scene.content.emphasis_words,
          avatar_direction: scene.avatar_direction,
          captions: scene.captions,
        },
        composition_path: resolve(compositionDir, `${scene.scene_id}.html`),
      };
    }),
    sfx: sfxClips(sourceAssets),
  };
}

async function writeDocs(plan) {
  const sceneLines = plan.scenes.map((scene) => `## Frame ${scene.scene_id}
status: build
src: project/compositions/${scene.scene_id}.html
time: ${scene.start.toFixed(3)}-${scene.end.toFixed(3)}
layout: ${scene.layout_id}
block: ${scene.primary_block_id || "avatar only"}
beat: ${scene.speech}
`).join("\n");
  await writeFile(resolve(stageDir, "README.md"), `# Stage 03 Render

Deterministic HyperFrames draft render for sales-three-questions-poc.

Run order:

1. node scripts/prepare-assets.mjs
2. node scripts/compile-edit-plan.mjs
3. node scripts/verify-render.mjs
`, "utf8");
  await writeFile(resolve(stageDir, "BRIEF.md"), `---
workflow: general-video
flow: automation
storyboard: no
project: sales-three-questions-poc
duration: 42.32
language: ru
---

Build one local draft MP4 from the approved Stage 02 edit_plan. Do not change scene timing, order, text, master audio, or creative choices.
`, "utf8");
  await writeFile(resolve(stageDir, "STORYBOARD.md"), `# Storyboard

${sceneLines}`, "utf8");
}

async function main() {
  await mkdir(compositionDir, { recursive: true });
  await mkdir(reportsDir, { recursive: true });

  const plan = await readJson(resolve(stageDir, "input", "edit_plan.timed.json"));
  const words = await readJson(resolve(stageDir, "input", "word-timings.json"));
  const sourceAssets = await readJson(resolve(stageDir, "input", "source-assets.json"));
  const items = await readJson(resolve(repoRoot, "experiments", "hyperframes-workflow-poc", "stage-01-catalog", "inventory", "items.json"));
  assertTimeline(plan);

  for (const scene of plan.scenes) {
    await writeFile(resolve(compositionDir, `${scene.scene_id}.html`), sceneHtml(scene), "utf8");
  }
  await writeFile(resolve(projectDir, "index.html"), indexHtml(plan, words, sourceAssets), "utf8");
  await writeFile(resolve(projectDir, "package.json"), packageJson(), "utf8");
  await writeFile(resolve(projectDir, "hyperframes.json"), hyperframesJson(), "utf8");
  await writeDocs(plan);

  const report = reportFor(plan, items, sourceAssets);
  await writeFile(resolve(reportsDir, "compiler-report.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ status: "PASS", scenes: plan.scenes.length, project: projectDir }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || String(error));
  process.exit(1);
});
