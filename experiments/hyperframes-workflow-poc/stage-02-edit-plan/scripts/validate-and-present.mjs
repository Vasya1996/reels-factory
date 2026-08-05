import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const stageDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const plan = JSON.parse(fs.readFileSync(path.join(stageDir, "edit_plan.draft.json"), "utf8"));
const timing = JSON.parse(fs.readFileSync(path.join(stageDir, "inputs", "word-timings.json"), "utf8"));
const catalogDoc = JSON.parse(fs.readFileSync(
  path.join(stageDir, "inputs", "catalog-shortlist.compact.json"), "utf8"));
const constraints = JSON.parse(fs.readFileSync(
  path.join(stageDir, "inputs", "project-constraints.json"), "utf8"));

const errors = [];
const warnings = [];
const catalog = new Map(catalogDoc.items.map((item) => [item.id, item]));
const readyIds = new Set(catalogDoc.items
  .filter((item) => item.execution_mode === "render_ready").map((item) => item.id));
const adaptIds = new Set(catalogDoc.items
  .filter((item) => item.execution_mode === "adapt_required").map((item) => item.id));
const techniqueIds = new Set(catalogDoc.items.flatMap((item) =>
  item.techniques.map((technique) => technique.id)));

function check(condition, message) {
  if (!condition) errors.push(message);
}

function label(id) {
  return id ? (catalog.get(id)?.title || id) : "—";
}

function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  return `${minutes}:${rest.toFixed(2).padStart(5, "0")}`;
}

function escapeCell(value) {
  return String(value ?? "—").replaceAll("|", "\\|").replaceAll("\n", " ");
}

function presenter(scene) {
  return {
    fullscreen: "Ведущая крупно",
    split: "Ведущая + контент (split)",
    editorial_bubble: "Ведущая в editorial bubble",
    object_overlay: "Ведущая + предметный overlay",
    hidden: "Ведущей нет",
  }[scene.avatar_direction] || scene.avatar_direction;
}

check(plan.plan_version === "hf-edit-plan-poc-1", "wrong plan_version");
check(plan.status === "draft", "status must be draft");
check(plan.duration_seconds === timing.duration_seconds, "duration differs from alignment");
check(Array.isArray(plan.scenes) && plan.scenes.length >= 8 && plan.scenes.length <= 18,
  "scene count must be 8..18");

const seenSceneIds = new Set();
let expectedWord = 0;
let hiddenRun = 0;
let maxHiddenRun = 0;
let primaryTransitionUses = 0;
const timedScenes = [];

for (let index = 0; index < (plan.scenes || []).length; index += 1) {
  const scene = plan.scenes[index];
  check(!seenSceneIds.has(scene.scene_id), `duplicate scene_id ${scene.scene_id}`);
  seenSceneIds.add(scene.scene_id);
  check(scene.word_start === expectedWord,
    `${scene.scene_id}: expected word_start ${expectedWord}, got ${scene.word_start}`);
  check(Number.isInteger(scene.word_end) && scene.word_end >= scene.word_start,
    `${scene.scene_id}: invalid word_end`);
  check(scene.word_end < timing.words.length, `${scene.scene_id}: word_end out of range`);
  expectedWord = scene.word_end + 1;

  check(readyIds.has(scene.layout_id), `${scene.scene_id}: layout is not render-ready`);
  check(catalog.get(scene.layout_id)?.kind === "layout", `${scene.scene_id}: layout_id is not a layout`);
  if (scene.primary_block_id !== null) {
    check(readyIds.has(scene.primary_block_id), `${scene.scene_id}: primary block is not render-ready`);
    check(catalog.get(scene.primary_block_id)?.kind === "block", `${scene.scene_id}: primary_block_id is not a block`);
  }
  for (const id of scene.component_ids || []) {
    check(readyIds.has(id), `${scene.scene_id}: component ${id} is not render-ready`);
    check(catalog.get(id)?.kind === "component", `${scene.scene_id}: ${id} is not a component`);
  }
  for (const id of scene.technique_ids || []) {
    check(techniqueIds.has(id), `${scene.scene_id}: unknown technique ${id}`);
  }
  check(readyIds.has(scene.transition_in_id), `${scene.scene_id}: transition is not render-ready`);
  check(catalog.get(scene.transition_in_id)?.kind === "transition",
    `${scene.scene_id}: transition_in_id is not a transition`);
  for (const request of scene.adaptation_requests || []) {
    check(adaptIds.has(request.catalog_id),
      `${scene.scene_id}: adaptation target ${request.catalog_id} is not adapt_required`);
    check(readyIds.has(request.fallback_catalog_id),
      `${scene.scene_id}: fallback ${request.fallback_catalog_id} is not render-ready`);
  }

  const startWord = timing.words[scene.word_start];
  const endWord = timing.words[scene.word_end];
  if (!startWord || !endWord) continue;
  const next = plan.scenes[index + 1];
  const start = index === 0 ? 0 : startWord.start;
  const end = next ? timing.words[next.word_start].start : timing.duration_seconds;
  const speech = timing.blocks.map((block) => block.text).join("\n")
    .slice(startWord.char_start, endWord.char_end + 1);
  const duration = Number((end - start).toFixed(3));

  if (scene.avatar_direction === "hidden") {
    hiddenRun += duration;
    maxHiddenRun = Math.max(maxHiddenRun, hiddenRun);
  } else {
    hiddenRun = 0;
  }
  if (scene.transition_in_id === plan.creative_direction.primary_transition_id && index > 0) {
    primaryTransitionUses += 1;
  }

  const visualParts = [
    label(scene.layout_id),
    scene.primary_block_id ? `блок: ${label(scene.primary_block_id)}` : null,
    ...(scene.component_ids || []).map((id) => `overlay: ${label(id)}`),
    scene.content?.headline ? `текст: «${scene.content.headline}»` : null,
    scene.content?.labels?.length ? `метки: ${scene.content.labels.join(" / ")}` : null,
    ...(scene.adaptation_requests || []).map((request) =>
      `кандидат на адаптацию: ${label(request.catalog_id)}; fallback: ${label(request.fallback_catalog_id)}`),
  ].filter(Boolean);
  const sfx = (scene.media_intents || [])
    .filter((intent) => intent.type === "sfx")
    .map((intent) => intent.query);

  timedScenes.push({ ...scene, start, end, duration, speech, visualParts, sfx });
}

check(expectedWord === timing.words.length,
  `word coverage ends at ${expectedWord - 1}, expected ${timing.words.length - 1}`);
check(plan.scenes?.[0]?.transition_in_id === "approved:transition:hard_cut",
  "first scene must start with hard cut");
check(plan.scenes?.[0]?.avatar_direction !== "hidden", "hook must show presenter");
check(plan.scenes?.at(-1)?.avatar_direction !== "hidden", "CTA must show presenter");
check(maxHiddenRun <= constraints.pacing.max_fullscreen_without_avatar_seconds,
  `presenter hidden for ${maxHiddenRun.toFixed(2)}s, limit is ${constraints.pacing.max_fullscreen_without_avatar_seconds}s`);

const changes = Math.max(1, (plan.scenes?.length || 1) - 1);
const primaryShare = primaryTransitionUses / changes;
if (primaryShare < constraints.transition_direction.primary_share_min - 0.15
  || primaryShare > constraints.transition_direction.primary_share_max + 0.15) {
  warnings.push(`primary transition share is ${(primaryShare * 100).toFixed(0)}%`);
}

const validation = {
  status: errors.length ? "FAIL" : "PASS",
  errors,
  warnings,
  scene_count: plan.scenes?.length || 0,
  covered_words: expectedWord,
  total_words: timing.words.length,
  max_presenter_hidden_seconds: Number(maxHiddenRun.toFixed(3)),
  primary_transition_share: Number(primaryShare.toFixed(3)),
};

const timedPlan = {
  ...plan,
  validation,
  scenes: timedScenes.map(({ visualParts, sfx, ...scene }) => scene),
};

fs.writeFileSync(path.join(stageDir, "edit_plan.timed.json"),
  JSON.stringify(timedPlan, null, 2) + "\n", "utf8");
fs.writeFileSync(path.join(stageDir, "reports", "plan-validation.json"),
  JSON.stringify(validation, null, 2) + "\n", "utf8");

const adaptationLines = timedScenes.flatMap((scene) =>
  (scene.adaptation_requests || []).map((request) =>
    `- **${scene.scene_id}, ${formatTime(scene.start)}–${formatTime(scene.end)}:** `
      + `${label(request.catalog_id)} — ${request.reason}. `
      + `Без адаптации: ${label(request.fallback_catalog_id)}.`));

let report = `# Монтажный план — «${escapeCell(plan.project_id)}»\n\n`;
report += `Validation: **${validation.status}** · сцен: ${validation.scene_count} · `
  + `слов: ${validation.covered_words}/${validation.total_words} · `
  + `максимум без ведущей: ${validation.max_presenter_hidden_seconds.toFixed(2)} c\n\n`;
report += `## Общая режиссура\n\n`;
report += `- **Концепция:** ${plan.creative_direction.concept}\n`;
report += `- **Настроение:** ${plan.creative_direction.mood}\n`;
report += `- **Ритм:** ${plan.creative_direction.rhythm}\n`;
report += `- **Основной переход:** ${label(plan.creative_direction.primary_transition_id)}\n`;
report += `- **Акцентные переходы:** ${(plan.creative_direction.accent_transition_ids || []).map(label).join(", ") || "нет"}\n\n`;
report += `## Таймлайн для проверки\n\n`;
report += `| Время | Фраза | Ведущая | Overlay / визуал | Переход | SFX | Субтитры |\n`;
report += `|---|---|---|---|---|---|---|\n`;
for (const scene of timedScenes) {
  report += `| ${formatTime(scene.start)}–${formatTime(scene.end)} `
    + `| ${escapeCell(scene.speech)} `
    + `| ${escapeCell(presenter(scene))} `
    + `| ${escapeCell(scene.visualParts.join("; "))} `
    + `| ${escapeCell(label(scene.transition_in_id))} `
    + `| ${escapeCell(scene.sfx.join(", ") || "нет")} `
    + `| ${escapeCell(scene.captions)} |\n`;
}
report += `\n## Что требует адаптации\n\n`;
report += adaptationLines.length ? adaptationLines.join("\n") + "\n" : "Ничего.\n";
if (warnings.length) report += `\n## Предупреждения\n\n${warnings.map((item) => `- ${item}`).join("\n")}\n`;
if (errors.length) report += `\n## Ошибки\n\n${errors.map((item) => `- ${item}`).join("\n")}\n`;
fs.writeFileSync(path.join(stageDir, "reports", "human-review.md"), report, "utf8");

console.log(JSON.stringify(validation, null, 2));
if (errors.length) process.exitCode = 1;

