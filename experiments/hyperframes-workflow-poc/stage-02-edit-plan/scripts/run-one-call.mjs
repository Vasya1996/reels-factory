import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const stageDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const requestPath = path.join(stageDir, "llm-request.json");
const rawPath = path.join(stageDir, "llm-response.raw.json");
const planPath = path.join(stageDir, "edit_plan.draft.json");
const callReportPath = path.join(stageDir, "reports", "llm-call.json");

if (fs.existsSync(rawPath) || fs.existsSync(planPath)) {
  throw new Error(
    "LLM output already exists. Refusing a second call; archive/remove it explicitly first.",
  );
}

const request = JSON.parse(fs.readFileSync(requestPath, "utf8"));
if (request.call_budget !== 1 || request.messages.length !== 2) {
  throw new Error("llm-request.json does not declare exactly one call and two messages");
}

const system = request.messages.find((message) => message.role === "system")?.content;
const user = request.messages.find((message) => message.role === "user")?.content;
const schema = request.response_format?.json_schema?.schema;
if (!system || !user || !schema) throw new Error("LLM request is incomplete");

const env = { ...process.env, CLAUDE_CODE_DISABLE_AUTO_MEMORY: "1" };
delete env.ANTHROPIC_API_KEY;
delete env.ANTHROPIC_AUTH_TOKEN;

const args = [
  "-p",
  "--output-format", "json",
  "--model", "sonnet",
  "--effort", "high",
  "--max-budget-usd", "1.00",
  "--no-session-persistence",
  "--setting-sources", "",
  "--strict-mcp-config",
  "--disable-slash-commands",
  "--tools", "",
  "--system-prompt", system,
  "--json-schema", JSON.stringify(schema),
];

const startedAt = new Date().toISOString();
const result = spawnSync("claude", args, {
  cwd: stageDir,
  input: user,
  encoding: "utf8",
  env,
  timeout: 600_000,
  maxBuffer: 20 * 1024 * 1024,
  windowsHide: true,
});

if (result.error) throw result.error;
if (result.status !== 0) {
  throw new Error(
    `claude call failed (${result.status}): ${(result.stderr || result.stdout || "").slice(0, 1200)}`,
  );
}

let outer;
try {
  outer = JSON.parse(result.stdout.trim());
} catch (error) {
  throw new Error(`claude returned invalid outer JSON: ${error.message}`);
}
if (outer.is_error) {
  throw new Error(`claude returned an error: ${String(outer.result || "unknown").slice(0, 1200)}`);
}

let plan = outer.structured_output;
if (!plan && typeof outer.result === "string") {
  try {
    plan = JSON.parse(outer.result);
  } catch {
    // The CLI should return structured_output when --json-schema is used.
  }
}
if (!plan || typeof plan !== "object" || Array.isArray(plan)) {
  throw new Error("claude response has no structured edit plan");
}

fs.mkdirSync(path.dirname(callReportPath), { recursive: true });
fs.writeFileSync(rawPath, JSON.stringify(outer, null, 2) + "\n", "utf8");
fs.writeFileSync(planPath, JSON.stringify(plan, null, 2) + "\n", "utf8");
fs.writeFileSync(callReportPath, JSON.stringify({
  status: "complete",
  calls: 1,
  model_requested: "sonnet",
  effort: "high",
  started_at: startedAt,
  finished_at: new Date().toISOString(),
  total_cost_usd: outer.total_cost_usd ?? null,
  duration_ms: outer.duration_ms ?? null,
  duration_api_ms: outer.duration_api_ms ?? null,
  num_turns: outer.num_turns ?? null,
  usage: outer.usage ?? null,
}, null, 2) + "\n", "utf8");

console.log(JSON.stringify({
  status: "complete",
  calls: 1,
  plan: path.relative(stageDir, planPath).replaceAll("\\", "/"),
  cost_usd: outer.total_cost_usd ?? null,
  scenes: Array.isArray(plan.scenes) ? plan.scenes.length : null,
}, null, 2));
