import fs from "node:fs";
import path from "node:path";

const ROOT = process.cwd();
const STAGE = path.join(ROOT, "experiments/hyperframes-workflow-poc/stage-01-catalog");
const GALLERY = path.join(STAGE, "gallery");

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function write(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text.endsWith("\n") ? text : `${text}\n`, "utf8");
}

function writeJson(file, data) {
  write(file, JSON.stringify(data, null, 2));
}

function escapeScriptJson(data) {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}

function main() {
  const catalog = readJson(path.join(STAGE, "gallery/data/catalog.json"));
  writeJson(path.join(GALLERY, "data/catalog.json"), catalog);
  write(path.join(GALLERY, "index.html"), html(catalog));
  write(path.join(GALLERY, "assets/gallery.css"), css());
  write(path.join(GALLERY, "assets/gallery.js"), js());
  console.log(`gallery built: ${catalog.items.length} cards`);
}

function html(catalog) {
  return `<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Stage 01 HyperFrames catalog</title>
    <link rel="stylesheet" href="assets/gallery.css" />
  </head>
  <body>
    <header class="topbar">
      <div>
        <h1>Stage 01 HyperFrames catalog</h1>
        <p>161 карточка: upstream blocks/components, локальные Reels Factory blocks и approved montage patterns.</p>
      </div>
      <div class="actions">
        <button id="exportReview" type="button">Export review JSON</button>
        <button id="resetReview" type="button" class="secondary">Reset review</button>
      </div>
    </header>

    <main>
      <section id="summary" class="summary"></section>

      <section class="filters" aria-label="Фильтры каталога">
        <label>Поиск <input id="search" type="search" placeholder="name, title, description, tags" /></label>
        <label>Source <select id="sourceFilter"></select></label>
        <label>Kind <select id="kindFilter"></select></label>
        <label>Role <select id="roleFilter"></select></label>
        <label>Orientation <select id="orientationFilter"></select></label>
        <label>Status <select id="statusFilter"></select></label>
        <label>Technique <select id="techniqueFilter"></select></label>
        <label>Sort <select id="sortMode">
          <option value="score">score</option>
          <option value="title">title</option>
          <option value="kind">kind</option>
        </select></label>
        <label class="check"><input id="shortlistOnly" type="checkbox" /> только auto-shortlist</label>
      </section>

      <section class="resultLine"><span id="visibleCount"></span></section>
      <section id="cards" class="cards"></section>
    </main>

    <script id="catalog-data" type="application/json">${escapeScriptJson(catalog)}</script>
    <script src="assets/gallery.js"></script>
  </body>
</html>`;
}

function css() {
  return `:root {
  color-scheme: light;
  --ink: #191714;
  --muted: #6b6259;
  --paper: #f7f3ed;
  --panel: #ffffff;
  --line: #ddd5ca;
  --red: #b42318;
  --amber: #b7791f;
  --green: #26734d;
  --blue: #285f8f;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  color: var(--ink);
  background: var(--paper);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 24px;
  background: rgba(247, 243, 237, 0.94);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(12px);
}

h1 { margin: 0 0 4px; font-size: 24px; line-height: 1.15; }
p { margin: 0; color: var(--muted); }

button, select, input, textarea {
  font: inherit;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}

button {
  padding: 10px 14px;
  color: #fff;
  background: var(--ink);
  cursor: pointer;
}

button.secondary {
  color: var(--ink);
  background: #fff;
}

main { padding: 20px 24px 44px; }

.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.metric {
  padding: 12px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.metric strong { display: block; font-size: 22px; }
.metric span { color: var(--muted); font-size: 13px; }

.filters {
  display: grid;
  grid-template-columns: minmax(220px, 2fr) repeat(6, minmax(130px, 1fr)) minmax(110px, 0.8fr) minmax(170px, 1fr);
  gap: 10px;
  align-items: end;
  padding: 14px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
}

.filters label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.filters input, .filters select {
  width: 100%;
  min-height: 38px;
  padding: 8px 10px;
  color: var(--ink);
}

.filters .check {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  color: var(--ink);
}

.filters .check input { width: auto; min-height: auto; }

.resultLine {
  margin: 14px 0;
  color: var(--muted);
  font-size: 14px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
}

.card {
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.card.forbidden {
  border-color: var(--red);
  box-shadow: inset 0 0 0 2px rgba(180, 35, 24, 0.1);
}

.poster {
  position: relative;
  aspect-ratio: 9 / 12;
  max-height: 360px;
  background: #151515;
  overflow: hidden;
}

.poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.badge {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 8px;
  border-radius: 999px;
  background: #ece5da;
  color: var(--ink);
  font-size: 12px;
  line-height: 1;
}

.badge.status-ready { background: #dff3e8; color: var(--green); }
.badge.status-adapt { background: #fff0d6; color: var(--amber); }
.badge.status-reference_only { background: #e5eff8; color: var(--blue); }
.badge.status-forbidden { background: #ffe0de; color: var(--red); }

.body { padding: 14px; }
.titleRow { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
h2 { margin: 0; font-size: 18px; line-height: 1.2; }
.id { margin-top: 5px; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; overflow-wrap: anywhere; }
.desc { margin-top: 10px; color: #423b34; font-size: 14px; line-height: 1.38; }

.forbiddenBanner {
  margin: 10px 0;
  padding: 9px 10px;
  color: var(--red);
  background: #fff0ef;
  border: 1px solid #ffc6c0;
  border-radius: 6px;
  font-weight: 700;
}

.meta, .tags, .techniques {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

details {
  margin-top: 10px;
  padding: 9px 10px;
  background: #fbfaf8;
  border: 1px solid #eee7dc;
  border-radius: 6px;
}

summary { cursor: pointer; font-weight: 700; }
ul { margin: 8px 0 0; padding-left: 18px; }
li { margin: 4px 0; }

.review {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.review textarea {
  min-height: 68px;
  padding: 9px;
  resize: vertical;
}

.previewLink {
  position: absolute;
  right: 10px;
  bottom: 10px;
  padding: 7px 10px;
  color: #fff;
  background: rgba(0, 0, 0, 0.75);
  border-radius: 6px;
  text-decoration: none;
  font-size: 13px;
}

@media (max-width: 1100px) {
  .filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .topbar { align-items: flex-start; flex-direction: column; }
}

@media (max-width: 640px) {
  main, .topbar { padding-left: 14px; padding-right: 14px; }
  .filters { grid-template-columns: 1fr; }
  .cards { grid-template-columns: 1fr; }
}`;
}

function js() {
  return `(() => {
  const catalog = JSON.parse(document.getElementById("catalog-data").textContent);
  const autoShortlist = new Set(catalog.items
    .filter((item) => item.assessment.review_status !== "forbidden")
    .filter((item) => item.assessment.review_status === "ready" || (item.assessment.review_status === "adapt" && item.assessment.score >= 3))
    .map((item) => item.id));
  const storageKey = "hf-stage-01-review";
  let review = loadReview();

  const el = (id) => document.getElementById(id);
  const controls = {
    search: el("search"),
    source: el("sourceFilter"),
    kind: el("kindFilter"),
    role: el("roleFilter"),
    orientation: el("orientationFilter"),
    status: el("statusFilter"),
    technique: el("techniqueFilter"),
    sort: el("sortMode"),
    shortlist: el("shortlistOnly"),
  };

  function loadReview() {
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey) || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  function saveReview() {
    localStorage.setItem(storageKey, JSON.stringify(review));
  }

  function optionList(select, values, labelAll = "Все") {
    select.innerHTML = "";
    select.append(new Option(labelAll, ""));
    for (const value of values) select.append(new Option(value, value));
  }

  function uniq(values) {
    return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  }

  function setup() {
    optionList(controls.source, uniq(catalog.items.map((i) => i.source)));
    optionList(controls.kind, uniq(catalog.items.map((i) => i.kind)));
    optionList(controls.role, uniq(catalog.items.flatMap((i) => i.capabilities.roles)));
    optionList(controls.orientation, uniq(catalog.items.map((i) => i.dimensions.orientation)));
    optionList(controls.status, uniq(catalog.items.map((i) => i.assessment.review_status)));
    controls.technique.innerHTML = "";
    controls.technique.append(new Option("Все", ""));
    for (const technique of catalog.techniques) {
      controls.technique.append(new Option(technique.name_ru, technique.id));
    }
    for (const input of Object.values(controls)) input.addEventListener("input", render);
    el("exportReview").addEventListener("click", exportReview);
    el("resetReview").addEventListener("click", resetReview);
    renderSummary();
    render();
  }

  function renderSummary() {
    const blocks = [
      ["total", catalog.counts.total],
      ...Object.entries(catalog.counts.sources).map(([k, v]) => [\`source: \${k}\`, v]),
      ...Object.entries(catalog.counts.kinds).map(([k, v]) => [\`kind: \${k}\`, v]),
      ...Object.entries(catalog.counts.statuses).map(([k, v]) => [\`status: \${k}\`, v]),
      ...Object.entries(catalog.counts.orientations).map(([k, v]) => [\`orientation: \${k}\`, v]),
    ];
    el("summary").innerHTML = blocks.map(([label, value]) => \`<div class="metric"><strong>\${value}</strong><span>\${escapeHtml(label)}</span></div>\`).join("");
  }

  function filteredItems() {
    const q = controls.search.value.trim().toLowerCase();
    let items = catalog.items.filter((item) => {
      const text = [item.id, item.name, item.title, item.description, ...(item.tags || []), ...item.techniques.map((t) => t.name_ru)].join(" ").toLowerCase();
      return (!q || text.includes(q))
        && (!controls.source.value || item.source === controls.source.value)
        && (!controls.kind.value || item.kind === controls.kind.value)
        && (!controls.role.value || item.capabilities.roles.includes(controls.role.value))
        && (!controls.orientation.value || item.dimensions.orientation === controls.orientation.value)
        && (!controls.status.value || item.assessment.review_status === controls.status.value)
        && (!controls.technique.value || item.techniques.some((t) => t.id === controls.technique.value))
        && (!controls.shortlist.checked || autoShortlist.has(item.id));
    });
    if (controls.sort.value === "score") items.sort((a, b) => b.assessment.score - a.assessment.score || a.title.localeCompare(b.title));
    if (controls.sort.value === "title") items.sort((a, b) => a.title.localeCompare(b.title));
    if (controls.sort.value === "kind") items.sort((a, b) => a.kind.localeCompare(b.kind) || a.title.localeCompare(b.title));
    return items;
  }

  function render() {
    const items = filteredItems();
    el("visibleCount").textContent = \`Показано \${items.length} из \${catalog.items.length}\`;
    el("cards").innerHTML = items.map(cardHtml).join("");
    for (const card of el("cards").querySelectorAll("[data-card-id]")) {
      const id = card.dataset.cardId;
      card.querySelector("select").addEventListener("change", (event) => {
        review[id] = { ...(review[id] || {}), decision: event.target.value, notes: card.querySelector("textarea").value || "" };
        saveReview();
      });
      card.querySelector("textarea").addEventListener("input", (event) => {
        review[id] = { ...(review[id] || { decision: "undecided" }), notes: event.target.value };
        saveReview();
      });
    }
  }

  function cardHtml(item) {
    const saved = review[item.id] || item.human_review || { decision: "undecided", notes: "" };
    const status = item.assessment.review_status;
    const poster = item.preview.poster_local || "assets/placeholder.svg";
    const details = item.techniques.map((t) => \`<li><strong>\${escapeHtml(t.name_ru)}</strong>: \${escapeHtml(t.description_ru)}</li>\`).join("");
    return \`<article class="card \${status === "forbidden" ? "forbidden" : ""}" data-card-id="\${escapeAttr(item.id)}">
      <div class="poster">
        <img src="\${escapeAttr(poster)}" alt="" loading="lazy" />
        \${item.preview.video_remote ? \`<a class="previewLink" href="\${escapeAttr(item.preview.video_remote)}" target="_blank" rel="noreferrer">Preview motion</a>\` : ""}
      </div>
      <div class="body">
        <div class="titleRow">
          <div>
            <h2>\${escapeHtml(item.title)}</h2>
            <div class="id">\${escapeHtml(item.id)}</div>
          </div>
          <span class="badge status-\${escapeAttr(status)}">\${escapeHtml(status)} · \${item.assessment.score}</span>
        </div>
        \${status === "forbidden" ? \`<div class="forbiddenBanner">Запрещено для runtime: \${escapeHtml(item.assessment.reason)}</div>\` : ""}
        <p class="desc">\${escapeHtml(item.description || item.assessment.reason)}</p>
        <div class="meta">
          <span class="badge">\${escapeHtml(item.source)}</span>
          <span class="badge">\${escapeHtml(item.kind)}</span>
          <span class="badge">\${escapeHtml(item.dimensions.orientation)}</span>
          <span class="badge">\${item.dimensions.width || "?"}×\${item.dimensions.height || "?"}</span>
          <span class="badge">\${item.duration_seconds ?? "duration ?"}s</span>
          <span class="badge">\${escapeHtml(item.parameterization.level)}</span>
        </div>
        <div class="tags">\${item.tags.map((tag) => \`<span class="badge">\${escapeHtml(tag)}</span>\`).join("")}</div>
        <div class="techniques">\${item.techniques.map((t) => \`<span class="badge">\${escapeHtml(t.name_ru)}</span>\`).join("")}</div>
        <details><summary>Приёмы</summary><ul>\${details}</ul></details>
        <details><summary>Capabilities / placement</summary><ul>
          <li>roles: \${item.capabilities.roles.map(escapeHtml).join(", ")}</li>
          <li>placement: \${item.capabilities.placement.map(escapeHtml).join(", ")}</li>
          <li>text: \${item.capabilities.supports_text_content}; media: \${item.capabilities.supports_media_content}; overlay: \${item.capabilities.supports_overlay}</li>
        </ul></details>
        <details><summary>Assessment</summary><ul>
          <li>\${escapeHtml(item.assessment.reason)}</li>
          <li>breakdown: \${item.assessment.score_breakdown.map(escapeHtml).join("; ")}</li>
          <li>adaptation: \${item.assessment.adaptation_needed.map(escapeHtml).join("; ") || "none"}</li>
          <li>risks: \${item.assessment.risks.map(escapeHtml).join("; ") || "none"}</li>
        </ul></details>
        <details><summary>Source ref</summary><ul>
          <li>manifest: \${escapeHtml(item.source_ref.manifest)}</li>
          <li>implementation: \${(item.source_ref.implementation || []).map(escapeHtml).join("; ")}</li>
        </ul></details>
        <div class="review">
          <select aria-label="Human decision">
            \${["undecided", "approve", "adapt", "reject", "reference"].map((v) => \`<option value="\${v}" \${saved.decision === v ? "selected" : ""}>\${v}</option>\`).join("")}
          </select>
          <textarea placeholder="notes">\${escapeHtml(saved.notes || "")}</textarea>
        </div>
      </div>
    </article>\`;
  }

  function exportReview() {
    const decisions = catalog.items.map((item) => {
      const saved = review[item.id] || {};
      return { id: item.id, decision: saved.decision || "undecided", notes: saved.notes || "" };
    });
    const blob = new Blob([JSON.stringify({ catalog_version: 1, decisions }, null, 2) + "\\n"], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "human-review.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  function resetReview() {
    if (!confirm("Сбросить все решения и notes в этой галерее?")) return;
    review = {};
    saveReview();
    render();
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/\\n/g, " ");
  }

  setup();
})();`;
}

main();
