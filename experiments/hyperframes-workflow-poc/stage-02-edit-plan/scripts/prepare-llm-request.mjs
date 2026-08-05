import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import path from "node:path";

const stageDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const catalogDir = path.resolve(stageDir, "..", "stage-01-catalog");
const inputDir = path.join(stageDir, "inputs");
const audioDir = path.join(inputDir, "audio");

const paths = {
  scenario: path.join(audioDir, "scenario.json"),
  alignment: path.join(audioDir, "alignment.json"),
  provider: path.join(audioDir, "provider.json"),
  constraints: path.join(inputDir, "project-constraints.json"),
  shortlist: path.join(catalogDir, "shortlist", "auto-shortlist.json"),
  inventory: path.join(catalogDir, "inventory", "items.json"),
  techniques: path.join(catalogDir, "inventory", "techniques.json"),
  prompt: path.join(stageDir, "prompt", "system.md"),
  wordsOut: path.join(inputDir, "word-timings.json"),
  catalogOut: path.join(inputDir, "catalog-shortlist.compact.json"),
  schemaOut: path.join(stageDir, "schemas", "edit-plan.schema.json"),
  requestOut: path.join(stageDir, "llm-request.json"),
  auditOut: path.join(stageDir, "reports", "input-audit.md"),
};

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function sha256(text) {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const body = JSON.stringify(value, null, 2) + "\n";
  if (!fs.existsSync(file) || fs.readFileSync(file, "utf8") !== body) {
    fs.writeFileSync(file, body, "utf8");
  }
}

function writeText(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const body = value.endsWith("\n") ? value : value + "\n";
  if (!fs.existsSync(file) || fs.readFileSync(file, "utf8") !== body) {
    fs.writeFileSync(file, body, "utf8");
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function buildWords(alignmentDoc, scenario) {
  const source = alignmentDoc.normalized_alignment || alignmentDoc.alignment;
  const chars = source.characters;
  const starts = source.character_start_times_seconds;
  const ends = source.character_end_times_seconds;
  assert(Array.isArray(chars) && chars.length > 0, "alignment characters missing");
  assert(chars.length === starts.length && chars.length === ends.length,
    "alignment arrays have different lengths");

  const exactText = scenario.blocks.map((block) => block.speech).join("\n");
  assert(chars.join("") === exactText,
    "scenario text does not exactly match normalized alignment characters");

  const blockRanges = [];
  let cursor = 0;
  for (const block of scenario.blocks) {
    const startChar = cursor;
    const endChar = cursor + block.speech.length - 1;
    blockRanges.push({
      id: block.id,
      role: block.role,
      text: block.speech,
      char_start: startChar,
      char_end: endChar,
    });
    cursor = endChar + 2;
  }

  const words = [];
  let tokenStart = null;
  const flush = (exclusiveEnd) => {
    if (tokenStart === null) return;
    const tokenEnd = exclusiveEnd - 1;
    const raw = chars.slice(tokenStart, exclusiveEnd).join("");
    const text = raw
      .replace(/^[^\p{L}\p{N}]+/gu, "")
      .replace(/[^\p{L}\p{N}]+$/gu, "");
    if (text && /[\p{L}\p{N}]/u.test(text)) {
      const block = blockRanges.find((candidate) =>
        tokenStart >= candidate.char_start && tokenEnd <= candidate.char_end);
      assert(block, `word at characters ${tokenStart}-${tokenEnd} has no scenario block`);
      const index = words.length;
      words.push({
        id: `w${String(index).padStart(3, "0")}`,
        index,
        text,
        start: Number(starts[tokenStart].toFixed(3)),
        end: Number(ends[tokenEnd].toFixed(3)),
        block_id: block.id,
        role: block.role,
        char_start: tokenStart,
        char_end: tokenEnd,
      });
    }
    tokenStart = null;
  };

  for (let index = 0; index < chars.length; index += 1) {
    if (/\s/u.test(chars[index])) flush(index);
    else if (tokenStart === null) tokenStart = index;
  }
  flush(chars.length);

  for (const block of blockRanges) {
    const contained = words.filter((word) => word.block_id === block.id);
    assert(contained.length > 0, `block ${block.id} has no words`);
    block.word_start = contained[0].index;
    block.word_end = contained.at(-1).index;
    block.start = contained[0].start;
    block.end = contained.at(-1).end;
  }

  return { exactText, words, blocks: blockRanges };
}

function compactCatalog(inventory, shortlist, techniquesDoc) {
  const wanted = new Set(shortlist.items.map((entry) => entry.id));
  const selected = inventory.filter((item) => wanted.has(item.id));
  const found = new Set(selected.map((item) => item.id));
  const missing = [...wanted].filter((id) => !found.has(id));
  assert(missing.length === 0, `shortlist IDs missing from inventory: ${missing.join(", ")}`);
  assert(selected.length === 49, `expected 49 shortlisted items, got ${selected.length}`);

  const techniqueById = new Map(
    techniquesDoc.techniques.map((technique) => [technique.id, technique]),
  );
  const techniqueIdsByItem = new Map(
    techniquesDoc.item_to_techniques.map((entry) => [entry.item_id, entry.technique_ids]),
  );

  const compact = selected.map((item) => {
    const parameterLevel = item.parameterization?.level || "unknown";
    const readyLevels = new Set([
      "declarative", "generated_python", "approved_js_contract",
    ]);
    const renderReady = item.assessment?.review_status === "ready"
      && item.assessment?.runtime_allowed === true
      && readyLevels.has(parameterLevel);
    return {
      id: item.id,
      title: item.title,
      kind: item.kind,
      source: item.source,
      description: item.description,
      tags: item.tags || [],
      techniques: (techniqueIdsByItem.get(item.id) || []).map((techniqueId) => {
        const technique = techniqueById.get(techniqueId);
        assert(technique, `technique ${techniqueId} for ${item.id} is missing`);
        return {
          id: technique.id,
          name_ru: technique.name_ru,
          description_ru: technique.description_ru,
          category: technique.category,
          use_when_ru: technique.use_when_ru || [],
          avoid_when_ru: technique.avoid_when_ru || [],
        };
      }),
      capabilities: {
        roles: item.capabilities?.roles || [],
        placement: item.capabilities?.placement || [],
        supports_overlay: Boolean(item.capabilities?.supports_overlay),
        supports_text_content: Boolean(item.capabilities?.supports_text_content),
        supports_media_content: Boolean(item.capabilities?.supports_media_content),
      },
      parameter_contract: {
        level: parameterLevel,
        fields: [
          ...(item.parameterization?.contract_fields || []),
          ...(item.parameterization?.declared_variables || []),
          ...(item.parameterization?.manifest_params || []),
        ].filter((value, index, all) => value && all.indexOf(value) === index),
      },
      execution_mode: renderReady ? "render_ready" : "adapt_required",
      score: item.assessment?.score,
      selection_reason: item.assessment?.reason,
      adaptation_needed: item.assessment?.adaptation_needed || [],
      risks: item.assessment?.risks || [],
    };
  });

  compact.sort((a, b) => a.id.localeCompare(b.id));
  return compact;
}

function nullableEnum(values) {
  return { anyOf: [{ type: "string", enum: values }, { type: "null" }] };
}

function buildSchema({ duration, words, catalog }) {
  const ready = catalog.filter((item) => item.execution_mode === "render_ready");
  const adapt = catalog.filter((item) => item.execution_mode === "adapt_required");
  const layouts = ready.filter((item) => item.kind === "layout").map((item) => item.id);
  const transitions = ready.filter((item) => item.kind === "transition").map((item) => item.id);
  const blocks = ready.filter((item) => item.kind === "block").map((item) => item.id);
  const components = ready.filter((item) => item.kind === "component").map((item) => item.id);
  const readyIds = ready.map((item) => item.id);
  const adaptIds = adapt.map((item) => item.id);
  const techniqueIds = [...new Set(catalog.flatMap((item) =>
    item.techniques.map((technique) => technique.id)))].sort();

  const mediaIntent = {
    type: "object",
    additionalProperties: false,
    required: ["type", "query", "purpose", "required"],
    properties: {
      type: { type: "string", enum: ["broll", "image", "icon", "sfx"] },
      query: { type: "string", minLength: 3, maxLength: 120 },
      purpose: { type: "string", minLength: 3, maxLength: 160 },
      required: { type: "boolean" },
    },
  };

  const adaptationRequest = {
    type: "object",
    additionalProperties: false,
    required: ["catalog_id", "fallback_catalog_id", "reason", "desired_parameters"],
    properties: {
      catalog_id: { type: "string", enum: adaptIds },
      fallback_catalog_id: { type: "string", enum: readyIds },
      reason: { type: "string", minLength: 5, maxLength: 220 },
      desired_parameters: {
        type: "array",
        maxItems: 10,
        items: {
          type: "object",
          additionalProperties: false,
          required: ["name", "value"],
          properties: {
            name: { type: "string", minLength: 1, maxLength: 60 },
            value: { type: "string", maxLength: 160 },
          },
        },
      },
    },
  };

  const scene = {
    type: "object",
    additionalProperties: false,
    required: [
      "scene_id", "word_start", "word_end", "purpose", "coverage",
      "layout_id", "primary_block_id", "component_ids", "technique_ids",
      "transition_in_id", "content", "captions", "avatar_direction",
      "media_intents", "adaptation_requests", "rationale",
    ],
    properties: {
      scene_id: { type: "string", pattern: "^s[0-9]{2}$" },
      word_start: { type: "integer", minimum: 0, maximum: words.length - 1 },
      word_end: { type: "integer", minimum: 0, maximum: words.length - 1 },
      purpose: {
        type: "string",
        enum: ["hook", "build", "explain", "contrast", "payoff", "cta"],
      },
      coverage: {
        type: "string",
        enum: ["avatar", "mixed", "hyperframes", "broll"],
      },
      layout_id: { type: "string", enum: layouts },
      primary_block_id: nullableEnum(blocks),
      component_ids: components.length > 0 ? {
        type: "array",
        uniqueItems: true,
        maxItems: 2,
        items: { type: "string", enum: components },
      } : {
        type: "array",
        maxItems: 0,
        items: { type: "string" },
      },
      technique_ids: {
        type: "array",
        uniqueItems: true,
        maxItems: 4,
        items: { type: "string", enum: techniqueIds },
      },
      transition_in_id: { type: "string", enum: transitions },
      content: {
        type: "object",
        additionalProperties: false,
        required: ["headline", "labels", "emphasis_words"],
        properties: {
          headline: { type: ["string", "null"], maxLength: 80 },
          labels: {
            type: "array",
            maxItems: 5,
            items: { type: "string", minLength: 1, maxLength: 40 },
          },
          emphasis_words: {
            type: "array",
            uniqueItems: true,
            maxItems: 3,
            items: { type: "string", minLength: 1, maxLength: 30 },
          },
        },
      },
      captions: { type: "string", enum: ["bottom", "top", "hidden"] },
      avatar_direction: {
        type: "string",
        enum: ["fullscreen", "split", "editorial_bubble", "object_overlay", "hidden"],
      },
      media_intents: { type: "array", maxItems: 3, items: mediaIntent },
      adaptation_requests: {
        type: "array",
        maxItems: 2,
        items: adaptationRequest,
      },
      rationale: { type: "string", minLength: 5, maxLength: 260 },
    },
  };

  return {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    title: "HyperFrames one-call edit plan draft",
    type: "object",
    additionalProperties: false,
    required: [
      "plan_version", "status", "project_id", "duration_seconds",
      "creative_direction", "scenes", "global_notes",
    ],
    properties: {
      plan_version: { const: "hf-edit-plan-poc-1" },
      status: { const: "draft" },
      project_id: { const: "sales-three-questions-poc" },
      duration_seconds: { const: duration },
      creative_direction: {
        type: "object",
        additionalProperties: false,
        required: ["concept", "mood", "rhythm", "primary_transition_id", "accent_transition_ids"],
        properties: {
          concept: { type: "string", minLength: 10, maxLength: 400 },
          mood: { type: "string", minLength: 5, maxLength: 160 },
          rhythm: { type: "string", minLength: 5, maxLength: 220 },
          primary_transition_id: { type: "string", enum: transitions },
          accent_transition_ids: {
            type: "array",
            uniqueItems: true,
            maxItems: 2,
            items: { type: "string", enum: transitions },
          },
        },
      },
      scenes: { type: "array", minItems: 8, maxItems: 18, items: scene },
      global_notes: {
        type: "array",
        maxItems: 8,
        items: { type: "string", minLength: 3, maxLength: 220 },
      },
    },
  };
}

function main() {
  const scenario = readJson(paths.scenario);
  const alignment = readJson(paths.alignment);
  const provider = readJson(paths.provider);
  const constraints = readJson(paths.constraints);
  const shortlist = readJson(paths.shortlist);
  const inventory = readJson(paths.inventory);
  const techniques = readJson(paths.techniques);
  const systemPrompt = fs.readFileSync(paths.prompt, "utf8").trim();

  assert(Array.isArray(scenario.blocks) && scenario.blocks.length > 0,
    "scenario blocks missing");
  assert(alignment.validation_status === "pass_exact_canonical_text",
    `alignment validation failed: ${alignment.validation_status}`);
  assert(provider.alignment_validation === "pass_exact_canonical_text",
    `provider alignment validation failed: ${provider.alignment_validation}`);

  const wordData = buildWords(alignment, scenario);
  const textHash = sha256(wordData.exactText);
  assert(textHash === alignment.text_sha256,
    "scenario sha256 does not match alignment.text_sha256");
  assert(textHash === provider.input_sha256,
    "scenario sha256 does not match provider.input_sha256");
  assert(Number(provider.master_duration_seconds) === Number(provider.alignment_end_seconds),
    "provider audio duration differs from alignment end");

  const catalog = compactCatalog(inventory, shortlist, techniques);
  const duration = Number(provider.master_duration_seconds);
  const schema = buildSchema({ duration, words: wordData.words, catalog });
  const ready = catalog.filter((item) => item.execution_mode === "render_ready");
  const adapt = catalog.filter((item) => item.execution_mode === "adapt_required");

  const wordOutput = {
    format_version: 1,
    source_text_sha256: textHash,
    duration_seconds: duration,
    word_count: wordData.words.length,
    blocks: wordData.blocks,
    words: wordData.words,
  };
  const catalogOutput = {
    catalog_version: shortlist.catalog_version,
    shortlist_source: "stage-01-catalog/shortlist/auto-shortlist.json",
    item_count: catalog.length,
    render_ready_count: ready.length,
    adapt_required_count: adapt.length,
    items: catalog,
  };

  const payload = {
    task: "Create exactly one draft edit plan for human review.",
    project: {
      id: constraints.project_id,
      title: scenario.title,
      deliverable: constraints.deliverable,
      duration_seconds: duration,
      canvas: constraints.canvas,
      brand: constraints.brand,
    },
    narration: {
      locked: true,
      language: scenario.language,
      exact_text: wordData.exactText,
      blocks: wordData.blocks,
      words: wordData.words.map(({ char_start, char_end, ...word }) => word),
    },
    constraints,
    catalog: catalogOutput,
  };

  const request = {
    request_version: 1,
    call_budget: 1,
    provider_agnostic: true,
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: JSON.stringify(payload) },
    ],
    response_format: {
      type: "json_schema",
      json_schema: {
        name: "hyperframes_edit_plan_draft",
        strict: true,
        schema,
      },
    },
  };

  writeJson(paths.wordsOut, wordOutput);
  writeJson(paths.catalogOut, catalogOutput);
  writeJson(paths.schemaOut, schema);
  writeJson(paths.requestOut, request);

  const requestBytes = Buffer.byteLength(JSON.stringify(request), "utf8");
  const groups = (items, key) => Object.fromEntries(
    [...new Set(items.map((item) => item[key]))]
      .sort()
      .map((value) => [value, items.filter((item) => item[key] === value).length]),
  );
  const audit = `# Stage 02 input audit\n\n`
    + `Status: **PASS**\n\n`
    + `- Scenario: ${scenario.title}\n`
    + `- Exact text SHA-256: \`${textHash}\`\n`
    + `- Alignment validation: \`${alignment.validation_status}\`\n`
    + `- Duration: ${duration.toFixed(2)} seconds\n`
    + `- Words: ${wordData.words.length}\n`
    + `- Scenario blocks: ${wordData.blocks.length}\n`
    + `- Shortlist items: ${catalog.length}\n`
    + `- Render-ready items: ${ready.length}\n`
    + `- Adapt-required items: ${adapt.length}\n`
    + `- Kinds: ${JSON.stringify(groups(catalog, "kind"))}\n`
    + `- Request size: ${requestBytes} bytes (~${Math.ceil(requestBytes / 4)} rough tokens)\n`
    + `- LLM calls made: 0\n`
    + `- Provider calls made: 0\n\n`
    + `The request contains one system message, one compact JSON payload and a strict response schema.\n`;
  writeText(paths.auditOut, audit);

  console.log(JSON.stringify({
    status: "PASS",
    duration_seconds: duration,
    words: wordData.words.length,
    catalog_items: catalog.length,
    render_ready: ready.length,
    adapt_required: adapt.length,
    request_bytes: requestBytes,
    outputs: Object.fromEntries(Object.entries(paths)
      .filter(([key]) => key.endsWith("Out"))
      .map(([key, value]) => [key, path.relative(stageDir, value).replaceAll("\\", "/")])),
  }, null, 2));
}

main();
