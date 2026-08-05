import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";

const ROOT = process.cwd();
const CONTENT_ROOT = path.resolve(ROOT, "..");
const STAGE = path.join(ROOT, "experiments/hyperframes-workflow-poc/stage-01-catalog");
const REPORT = path.join(STAGE, "reports/validation.json");
const UPSTREAM = path.join(CONTENT_ROOT, "reference-audit/hyperframes-main-20260801-complete/hyperframes-main");
const APPROVED = path.join(CONTENT_ROOT, "plan-previews/two-reel-catalog-proxy-20260729");
const MAX = 2 * 1024 * 1024;
const CATEGORIES = new Set(["speaker_layout","composition_layout","caption_and_typography","title_and_lower_third","data_and_statistics","comparison_and_process","social_and_editorial_overlay","transition","texture_and_finishing","media_treatment","vfx_and_shader","spatial_motion","code_and_terminal","map_and_diagram","brand_and_outro","other"]);
const SCORE_ROLE_SET = new Set(["caption","lower_third","title","quote","data_visualization","stat","comparison","list","process","social_overlay","transition","layout"]);
const TRANSITION_VARIANTS = {
  "upstream:block:transitions-3d": { ids: ["transition_3d_card_flip"], labels: ["3D Card Flip"] },
  "upstream:block:transitions-blur": { ids: ["transition_blur_through","transition_directional_blur","transition_calm_blur_through"], labels: ["Blur Through","Directional Blur","Calm Blur Through"] },
  "upstream:block:transitions-cover": { ids: ["transition_staggered_blocks","transition_horizontal_blinds","transition_vertical_blinds"], labels: ["STAGGERED BLOCKS","HORIZONTAL BLINDS","VERTICAL BLINDS"] },
  "upstream:block:transitions-destruction": { ids: ["transition_page_burn"], labels: ["Page Burn"] },
  "upstream:block:transitions-dissolve": { ids: ["transition_crossfade","transition_blur_crossfade","transition_focus_pull","transition_dip_to_black"], labels: ["Crossfade","Blur Crossfade","Focus Pull","Color Dip"] },
  "upstream:block:transitions-distortion": { ids: ["transition_distortion_glitch","transition_chromatic_aberration","transition_ripple_distortion"], labels: ["Glitch","Chromatic Aberration","Ripple"] },
  "upstream:block:transitions-grid": { ids: ["transition_grid_dissolve"], labels: ["Grid Dissolve"] },
  "upstream:block:transitions-light": { ids: ["transition_light_leak","transition_overexposure_burn","transition_film_burn"], labels: ["LIGHT LEAK","OVEREXPOSURE BURN","FILM BURN"] },
  "upstream:block:transitions-mechanical": { ids: ["transition_mechanical_shutter","transition_clock_wipe"], labels: ["Shutter","Clock Wipe"] },
  "upstream:block:transitions-other": { ids: ["transition_flash_cut","transition_gravity_drop","transition_morph_circle"], labels: ["Flash Cut","Gravity Drop","Morph Circle"] },
  "upstream:block:transitions-push": { ids: ["transition_push_slide","transition_vertical_push","transition_elastic_push","transition_squeeze"], labels: ["Push Slide","Vertical Push","Elastic Push","Squeeze"] },
  "upstream:block:transitions-radial": { ids: ["transition_circle_iris","transition_diamond_iris","transition_diagonal_split"], labels: ["Circle Iris","Diamond Iris","Diagonal Split"] },
  "upstream:block:transitions-scale": { ids: ["transition_zoom_through","transition_zoom_out"], labels: ["Zoom Through","Zoom Out"] },
};
const checks = [], errors = [], warnings = [];
function readJson(file) { return JSON.parse(fs.readFileSync(file, "utf8")); }
function exists(file) { return fs.existsSync(file); }
function ok(name, pass, detail = "") { checks.push({ name, ok: Boolean(pass), detail: pass ? "" : detail }); if (!pass) errors.push(detail || name); }
function warn(s) { warnings.push(s); }
function files(dir) { const out=[]; for (const e of fs.readdirSync(dir,{withFileTypes:true})) { const f=path.join(dir,e.name); if (e.isDirectory()) out.push(...files(f)); else out.push(f); } return out; }
function trailing(file) { const b=fs.readFileSync(file); return b.length && b[b.length-1]===10; }
function count(items,p) { return items.filter(p).length; }
function sameSet(a,b) { return a.length===b.length && [...a].sort().every((v,i)=>v===[...b].sort()[i]); }
function by(items,f) { return Object.fromEntries(Object.entries(items.reduce((a,x)=>(a[f(x)]=(a[f(x)]||0)+1,a),{})).sort()); }
function sourceRoot(item) {
  if (item.source === "upstream") return UPSTREAM;
  if (item.source === "approved") return APPROVED;
  return ROOT;
}
function sourceFile(item, rel) { return path.join(sourceRoot(item), rel.replaceAll("/", path.sep).replace(/:\d+$/,"")); }
function lineCount(file) { return fs.readFileSync(file,"utf8").split(/\r?\n/).length; }
function signatureMime(file) {
  const b = fs.readFileSync(file).subarray(0,16);
  if (b[0]===0x89&&b[1]===0x50&&b[2]===0x4e&&b[3]===0x47) return "image/png";
  if (b[0]===0xff&&b[1]===0xd8&&b[2]===0xff) return "image/jpeg";
  if (b.toString("ascii",0,4)==="RIFF"&&b.toString("ascii",8,12)==="WEBP") return "image/webp";
  if (b.toString("ascii",0,3)==="GIF") return "image/gif";
  return null;
}
function validateSchema(schema, value, label, ptr = "") {
  if (schema.const !== undefined && value !== schema.const) errors.push(`${label}${ptr}: expected const ${schema.const}`);
  if (schema.type) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    const actual = Array.isArray(value) ? "array" : value === null ? "null" : typeof value;
    if (!types.includes(actual)) errors.push(`${label}${ptr}: type ${actual} not in ${types.join("|")}`);
  }
  if (schema.enum && !schema.enum.includes(value)) errors.push(`${label}${ptr}: enum mismatch ${value}`);
  if (schema.pattern && typeof value === "string" && !new RegExp(schema.pattern).test(value)) errors.push(`${label}${ptr}: pattern mismatch`);
  if (schema.minItems !== undefined && Array.isArray(value) && value.length < schema.minItems) errors.push(`${label}${ptr}: expected at least ${schema.minItems} items`);
  if (schema.required && value && typeof value === "object") for (const key of schema.required) if (!(key in value)) errors.push(`${label}${ptr}/${key}: missing required`);
  if (schema.properties && value && typeof value === "object") {
    for (const [key, sub] of Object.entries(schema.properties)) if (key in value) validateSchema(sub, value[key], label, `${ptr}/${key}`);
  }
  if (schema.items && Array.isArray(value)) value.forEach((v,i)=>validateSchema(schema.items,v,label,`${ptr}/${i}`));
}
function inferParam(item) {
  if (item.source === "local") return "generated_python";
  if (item.source === "approved") return "approved_js_contract";
  if (item.parameterization.declared_variables?.length) return "declarative";
  if (item.parameterization.manifest_params?.length) return "manifest_only";
  return "none";
}
function recomputeScore(item) {
  let score = 0;
  if (item.source === "approved" && item.name !== "avatar_cutout_overlay") score += 5;
  if (item.source === "local") score += 4;
  if ((item.capabilities.roles || []).some((r) => SCORE_ROLE_SET.has(r))) score += 3;
  if (["portrait","adaptive"].includes(item.dimensions.orientation)) score += 2;
  if (["declarative","generated_python"].includes(item.parameterization.level)) score += 2;
  if (item.parameterization.manifest_params?.length) score += 1;
  if (item.preview.poster_remote) score += 1;
  if (item.kind === "block" && item.dimensions.orientation === "landscape" && !/responsive|portrait/i.test(`${item.description} ${(item.tags||[]).join(" ")}`)) score -= 2;
  if (item.runtime.remote_dependencies?.length) score -= 2;
  if (item.runtime.uses_shader_or_webgl) score -= 2;
  if ((item.capabilities.roles || []).some((r) => ["code","map"].includes(r))) score -= 3;
  if (item.name === "avatar_cutout_overlay") score -= 100;
  return score;
}
function hasCyrillic(s) { return /[А-Яа-яЁё]/.test(String(s)); }
function languageCheck(value, label) {
  if (Array.isArray(value)) value.forEach((v,i)=>languageCheck(v,`${label}/${i}`));
  else if (typeof value === "string" && value.trim() && !hasCyrillic(value) && !/^(GSAP|WebGL|Light Leak|Apple|CSS|overlay|fullscreen|reference|runtime-ready|VFX|CTA|ID|URL|MIME|PNG|JPG|JPEG|WebP|GIF)$/i.test(value.trim())) errors.push(`${label}: нет кириллицы`);
  if (typeof value === "string" && /\b(the|with|using|that|which|screen|frame|video|transition|caption)\b.{20,}/i.test(value) && !hasCyrillic(value)) errors.push(`${label}: длинное английское предложение`);
}
function main() {
  const itemSchema = readJson(path.join(STAGE,"inventory/catalog.schema.json"));
  const techSchema = readJson(path.join(STAGE,"inventory/techniques.schema.json"));
  const items = readJson(path.join(STAGE,"inventory/items.json"));
  const techniques = readJson(path.join(STAGE,"inventory/techniques.json"));
  const gallery = readJson(path.join(STAGE,"gallery/data/catalog.json"));
  const shortlist = readJson(path.join(STAGE,"shortlist/auto-shortlist.json"));
  const human = readJson(path.join(STAGE,"shortlist/human-review.template.json"));
  const runtime = readJson(path.join(STAGE,"reports/runtime-dependencies.json"));
  const downloads = readJson(path.join(STAGE,"reports/preview-downloads.json"));
  const curation = readJson(path.join(STAGE,"scripts/technique-curation.json"));
  const audit = readJson(path.join(STAGE,"reports/technique-extraction-audit.json"));
  items.forEach((item,i)=>validateSchema(itemSchema,item,"items.json",`/${i}`));
  validateSchema(techSchema, techniques, "techniques.json");
  const ids = items.map((i)=>i.id);
  ok("total items", items.length === 161, `expected 161 items got ${items.length}`);
  ok("source/kind counts", count(items,i=>i.source==="upstream"&&i.kind==="block")===113 && count(items,i=>i.source==="upstream"&&i.kind==="component")===25 && count(items,i=>i.source==="local"&&i.kind==="block")===8 && count(items,i=>i.source==="approved"&&i.kind==="layout")===10 && count(items,i=>i.source==="approved"&&i.kind==="transition")===5, `bad counts ${JSON.stringify(by(items,i=>`${i.source}:${i.kind}`))}`);
  ok("unique sorted item IDs", new Set(ids).size===ids.length && ids.every((id,i)=>i===0||ids[i-1].localeCompare(id)<=0), "item IDs not unique/sorted");
  const techIds = techniques.techniques.map((t)=>t.id);
  ok("unique sorted technique IDs", new Set(techIds).size===techIds.length && techIds.every((id,i)=>i===0||techIds[i-1].localeCompare(id)<=0), "technique IDs not unique/sorted");
  ok("unique technique names", new Set(techniques.techniques.map((t)=>t.name_ru)).size===techniques.techniques.length, "different techniques share the same name_ru");
  const itemSet = new Set(ids), techSet = new Set(techIds);
  ok("mapping count", techniques.item_to_techniques.length === 161, "item_to_techniques count mismatch");
  ok("mapping keys unique", new Set(techniques.item_to_techniques.map(m=>m.item_id)).size===161, "mapping keys not unique");
  for (const m of techniques.item_to_techniques) {
    if (!itemSet.has(m.item_id)) errors.push(`mapping unknown item ${m.item_id}`);
    if (!m.technique_ids?.length) errors.push(`mapping ${m.item_id} has no techniques`);
    for (const id of m.technique_ids || []) if (!techSet.has(id)) errors.push(`mapping ${m.item_id} unknown technique ${id}`);
  }
  for (const t of techniques.techniques) {
    if (!CATEGORIES.has(t.category)) errors.push(`technique ${t.id}: invalid category`);
    if (!t.implementation_ids?.length) errors.push(`technique ${t.id}: no implementations`);
    for (const id of t.implementation_ids || []) if (!itemSet.has(id)) errors.push(`technique ${t.id}: unknown implementation ${id}`);
    ["name_ru","description_ru","viewer_sees_ru","use_when_ru","avoid_when_ru","variants_ru","controllable_fields_ru","placement_ru","adaptation_notes_ru","dependencies_ru","risks_ru"].forEach((k)=>languageCheck(t[k], `technique ${t.id}/${k}`));
    for (const e of t.evidence_refs || []) languageCheck(e.reason_ru, `technique ${t.id}/evidence_refs/reason_ru`);
    const copy = `${t.description_ru}\n${t.viewer_sees_ru}\n${(t.use_when_ru||[]).join("\n")}`;
    if (/Приём использует реализацию|характерную для .+ композицию|визуальная логика совпадает с фразой/i.test(copy)) errors.push(`technique ${t.id}: шаблонное описание вместо конкретной семантики`);
    if (String(t.description_ru || "").length < 35 || String(t.viewer_sees_ru || "").length < 35) errors.push(`technique ${t.id}: описание слишком короткое для проверки визуального поведения`);
  }
  for (const item of items) {
    const root = sourceRoot(item);
    if (!exists(sourceFile(item,item.source_ref.manifest))) errors.push(`${item.id}: manifest path missing ${item.source_ref.manifest}`);
    for (const impl of item.source_ref.implementation || []) {
      if (/^evidence:|function /.test(impl)) errors.push(`${item.id}: pseudo implementation path ${impl}`);
      if (!exists(path.join(root, impl.replaceAll("/", path.sep).replace(/:\d+$/,"")))) errors.push(`${item.id}: implementation path missing ${impl}`);
    }
    for (const e of item.evidence_refs || []) {
      const file = path.join(root, e.path.replaceAll("/", path.sep));
      if (!exists(file)) errors.push(`${item.id}: evidence path missing ${e.path}`);
      else if (!(e.line_start > 0 && e.line_end >= e.line_start && e.line_end <= lineCount(file))) errors.push(`${item.id}: invalid evidence range ${e.path}:${e.line_start}-${e.line_end}`);
      if (!hasCyrillic(e.reason_ru || "")) errors.push(`${item.id}: evidence reason not Russian`);
    }
    if (item.source === "upstream" && item.assessment.runtime_allowed) errors.push(`${item.id}: upstream runtime_allowed true`);
    if (item.name === "avatar_cutout_overlay" && !(item.assessment.review_status === "forbidden" && item.assessment.runtime_allowed === false)) errors.push("avatar_cutout_overlay policy broken");
    if (inferParam(item) !== item.parameterization.level) errors.push(`${item.id}: parameterization expected ${inferParam(item)} got ${item.parameterization.level}`);
    if (item.source === "approved" && item.parameterization.level === "declarative") errors.push(`${item.id}: approved item is declarative`);
    if (item.source === "local" && (!item.parameterization.contract_fields?.length || item.parameterization.level !== "generated_python")) errors.push(`${item.id}: local contract missing`);
    const score = recomputeScore(item);
    if (score !== item.assessment.score) errors.push(`${item.id}: score ${item.assessment.score} != recomputed ${score}`);
  }
  const depUrls = new Set(runtime.dependencies.map((d)=>d.url));
  for (const item of items) {
    const itemDeps = [...new Set(runtime.dependencies.filter((d)=>d.item_id===item.id).map((d)=>d.url))].sort();
    if (JSON.stringify(itemDeps) !== JSON.stringify([...(item.runtime.remote_dependencies||[])].sort())) errors.push(`${item.id}: runtime deps mismatch`);
  }
  for (const d of runtime.dependencies) {
    if (/static\.heygen\.ai\/hyperframes-oss\/docs\/images\/catalog|hyperframes\.heygen\.com\/schema|w3\.org\/(2000\/svg|1999\/xhtml)/.test(d.url)) errors.push(`forbidden runtime URL ${d.url}`);
    if (!["script_src","stylesheet_href","media_src","css_url","css_import","js_fetch","js_import","js_new_url"].includes(d.usage)) errors.push(`bad runtime usage ${d.usage}`);
    const item = items.find((i)=>i.id===d.item_id);
    if (!item) errors.push(`runtime unknown item ${d.item_id}`);
    else if (!exists(sourceFile(item,d.path))) errors.push(`runtime path missing ${d.path}`);
    if (!(d.line > 0)) errors.push(`runtime line invalid ${d.item_id}`);
  }
  ok("runtime regression URLs absent", ![...depUrls].some((u)=>/static\.heygen\.ai\/hyperframes-oss\/docs\/images\/catalog|hyperframes\.heygen\.com\/schema|w3\.org\/(2000\/svg|1999\/xhtml)/.test(u)), "metadata/preview namespace URL leaked");
  ok("downloads attempted", downloads.attempted === true, "preview-downloads attempted is not true");
  ok("download entries count", downloads.entries.length === 161, `download entries ${downloads.entries.length}`);
  for (const e of downloads.entries) {
    if (!itemSet.has(e.id)) errors.push(`download unknown item ${e.id}`);
    if (["downloaded","cached"].includes(e.status)) {
      const file = path.join(STAGE, e.local_path.replaceAll("/", path.sep));
      if (!exists(file)) errors.push(`${e.id}: downloaded/cached poster missing`);
      else {
        const mime = signatureMime(file);
        if (!mime || mime !== e.content_type) errors.push(`${e.id}: poster MIME mismatch`);
        if (fs.statSync(file).size > MAX) errors.push(`${e.id}: poster over 2MB`);
        if (!({ "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif" }[mime] === path.extname(file).toLowerCase())) errors.push(`${e.id}: extension mismatch`);
      }
    }
  }
  for (const item of items) {
    const local = item.preview.poster_local;
    if (local && !exists(path.join(STAGE,"gallery",local.replaceAll("/", path.sep)))) errors.push(`${item.id}: poster_local missing ${local}`);
    if (local === "assets/placeholder.svg") {
      const e = downloads.entries.find((x)=>x.id===item.id);
      if (!e || !["failed","not_applicable"].includes(e.status)) errors.push(`${item.id}: placeholder without failed/not_applicable report`);
    }
  }
  ok("curation entries", curation.items.length === 161 && curation.items.every((i)=>i.reviewed === true), "curation does not cover 161 reviewed items");
  ok("audit entries", audit.item_mappings?.length === 161, "technique extraction audit mismatch");
  ok("audit text source list", Array.isArray(audit.source_text_files_inspected) && !audit.source_text_files_inspected.some((file)=>/\.(wav|mp4|mov|glb|png|jpe?g|webp|gif)$/i.test(file)), "technique audit contains binary files as inspected text");
  for (const entry of curation.items) {
    for (const evidence of entry.evidence_refs || []) {
      if (/Файл реализации прочитан для анализа|Прочитанный source range подтверждает mapping/i.test(evidence.reason_ru || "")) errors.push(`${entry.item_id}: формальное evidence без объяснения приёма`);
    }
    if (entry.item_id.startsWith("upstream:") && !TRANSITION_VARIANTS[entry.item_id]) {
      const manifestEvidence = (entry.evidence_refs || []).find((e)=>/registry-item\.json$/i.test(e.path));
      if (!manifestEvidence) errors.push(`${entry.item_id}: нет manifest description evidence`);
      else {
        const item = items.find((candidate)=>candidate.id===entry.item_id);
        const file = sourceFile(item, manifestEvidence.path);
        const selected = fs.readFileSync(file,"utf8").split(/\r?\n/).slice(manifestEvidence.line_start-1,manifestEvidence.line_end).join("\n");
        if (!/"description"\s*:/.test(selected)) errors.push(`${entry.item_id}: evidence range не содержит manifest description`);
      }
    }
  }
  for (const [id, expected] of Object.entries(TRANSITION_VARIANTS)) {
    const m = curation.items.find((x)=>x.item_id===id);
    if (!m || JSON.stringify(m.technique_ids) !== JSON.stringify(expected.ids)) errors.push(`${id}: mapping ${JSON.stringify(m?.technique_ids)} не совпадает с source variants ${JSON.stringify(expected.ids)}`);
    const evidence = m?.evidence_refs?.[0];
    if (!evidence) errors.push(`${id}: нет evidence для transition variants`);
    else {
      const item = items.find((candidate)=>candidate.id===id);
      const file = sourceFile(item,evidence.path);
      const selected = fs.readFileSync(file,"utf8").split(/\r?\n/).slice(evidence.line_start-1,evidence.line_end).join("\n").toLowerCase();
      for (const label of expected.labels) if (!selected.includes(label.toLowerCase())) errors.push(`${id}: evidence range не содержит label ${label}`);
    }
  }
  ok("not one-technique-only", curation.items.some((i)=>i.technique_ids.length > 1), "no multi-technique mapping");
  const otherOnly = techniques.item_to_techniques.filter((m)=>m.technique_ids.every((id)=>techniques.techniques.find((t)=>t.id===id)?.category==="other")).length;
  ok("other only <=10%", otherOnly <= 16, `other-only items ${otherOnly}`);
  ok("role regressions", !items.find((i)=>i.id==="upstream:component:texture-mask-text")?.capabilities.roles.includes("map") && !items.find((i)=>i.id==="upstream:component:vignette")?.capabilities.roles.includes("transition") && !items.find((i)=>i.id==="upstream:component:motion-blur")?.capabilities.roles.includes("transition"), "role regression failed");
  ok("shortlist excludes forbidden", !shortlist.items.some((r)=>items.find((i)=>i.id===r.id)?.assessment.review_status==="forbidden"), "shortlist contains forbidden");
  ok("gallery IDs", sameSet(gallery.items.map((i)=>i.id), ids), "gallery IDs mismatch");
  ok("human review IDs", sameSet(human.decisions.map((d)=>d.id), ids), "human review IDs mismatch");
  const html = fs.readFileSync(path.join(STAGE,"gallery/index.html"),"utf8");
  for (const token of ["search","sourceFilter","kindFilter","roleFilter","orientationFilter","statusFilter","techniqueFilter","sortMode","Export review JSON","Reset review"]) if (!html.includes(token)) errors.push(`gallery HTML missing ${token}`);
  try { execSync("node --check experiments/hyperframes-workflow-poc/stage-01-catalog/gallery/assets/gallery.js", { cwd: ROOT, encoding: "utf8" }); } catch(e) { errors.push(`gallery JS syntax failed: ${e.message}`); }
  const badMedia = files(STAGE).filter((f)=>/\.(mp4|mov|wav)$/i.test(f));
  ok("no video/audio", badMedia.length===0, `forbidden media ${badMedia.join(", ")}`);
  const big = files(STAGE).filter((f)=>fs.statSync(f).size > MAX);
  ok("no files over 2MB", big.length===0, `files over 2MB ${big.join(", ")}`);
  for (const jf of files(STAGE).filter((f)=>/\.json$/i.test(f))) if (!trailing(jf)) errors.push(`JSON missing trailing newline ${path.relative(STAGE,jf)}`);
  if (downloads.counts.failed > 0) warn(`${downloads.counts.failed} poster downloads failed with documented errors.`);
  const result = { ok: errors.length === 0, checks, errors, warnings, counts: { total: items.length, upstream_blocks: count(items,i=>i.source==="upstream"&&i.kind==="block"), upstream_components: count(items,i=>i.source==="upstream"&&i.kind==="component"), local_blocks: count(items,i=>i.source==="local"), approved_layouts: count(items,i=>i.source==="approved"&&i.kind==="layout"), approved_transitions: count(items,i=>i.source==="approved"&&i.kind==="transition"), techniques: techniques.techniques.length, runtime_dependency_items: new Set(runtime.dependencies.map((d)=>d.item_id)).size, runtime_unique_urls: depUrls.size, scoring_verified: errors.filter((e)=>/score .*recomputed/.test(e)).length === 0 ? 161 : 0 } };
  fs.writeFileSync(REPORT, `${JSON.stringify(result,null,2)}\n`, "utf8");
  if (!result.ok) { console.error(JSON.stringify(result,null,2)); process.exit(1); }
  console.log("validation PASS");
}
main();
