import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const stageDir = resolve(here, "..");
const repoRoot = resolve(stageDir, "..", "..", "..");
const mediaDir = resolve(stageDir, "project", "assets", "media");
const sfxDir = resolve(mediaDir, "sfx");
const fontsDir = resolve(stageDir, "project", "assets", "fonts");
const vendorDir = resolve(stageDir, "project", "assets", "vendor");
const inputDir = resolve(stageDir, "input");
const reportsDir = resolve(stageDir, "reports");

const ffmpeg = process.env.FFMPEG_PATH ||
  resolve(repoRoot, "..", "revideo_test", "node_modules", "@ffmpeg-installer", "win32-x64", "ffmpeg.exe");
const ffprobe = process.env.FFPROBE_PATH ||
  resolve(repoRoot, "..", "revideo_test", "node_modules", "@ffprobe-installer", "win32-x64", "ffprobe.exe");

const avatarSources = [
  {
    order: 1,
    source: "C:\\Users\\Asus\\Downloads\\Продажи\\1.mp4",
    adopted: "avatar-island-01.mp4",
    expectedDuration: 11.720,
    expectedSha256: "7BCEEE4F0DA73792FF7AFD70AF9BF4A8D5E4C5D24FD81476615E8A40A86D57E9",
  },
  {
    order: 2,
    source: "C:\\Users\\Asus\\Downloads\\Продажи\\2.mp4",
    adopted: "avatar-island-02.mp4",
    expectedDuration: 10.920,
    expectedSha256: "A61D9B531F9F0BC40F752CA5B5D176CC3E4009EFF1558BF6702172DA246316FE",
  },
  {
    order: 3,
    source: "C:\\Users\\Asus\\Downloads\\Продажи\\3.mp4",
    adopted: "avatar-island-03.mp4",
    expectedDuration: 11.480,
    expectedSha256: "C2683128DC6CFE16698D6D70B43BE544C5B5DC7B3C5E38D9F16A2078AAE98EAB",
  },
  {
    order: 4,
    source: "C:\\Users\\Asus\\Downloads\\Продажи\\4.mp4",
    adopted: "avatar-island-04.mp4",
    expectedDuration: 6.888,
    expectedSha256: "769B0624E46415778759BE44BD46D098E34F67279B8B200B7C5F72D3EDA4A220",
  },
];

const masterAudioSource = "C:\\Users\\Asus\\Documents\\personal_ai\\projects\\content_factory\\work\\diagnostics\\ivc-v3-scenario-20260726T182834Z\\eleven\\voice_master.wav";
const sfxSources = [
  ["whoosh.wav", "C:\\Users\\Asus\\Documents\\personal_ai\\projects\\content_factory\\work\\archives\\reels-factory-e2e-20260727-d2aa4090\\job\\revideo\\public\\whoosh.wav"],
  ["type.wav", "C:\\Users\\Asus\\Documents\\personal_ai\\projects\\content_factory\\work\\archives\\reels-factory-e2e-20260727-d2aa4090\\job\\revideo\\public\\type.wav"],
  ["pop.wav", "C:\\Users\\Asus\\Documents\\personal_ai\\projects\\content_factory\\work\\archives\\reels-factory-e2e-20260727-d2aa4090\\job\\revideo\\public\\pop.wav"],
  ["ding.wav", "C:\\Users\\Asus\\Documents\\personal_ai\\projects\\content_factory\\work\\archives\\reels-factory-e2e-20260727-d2aa4090\\job\\revideo\\public\\ding.wav"],
];

function run(command, args, options = {}) {
  return new Promise((resolveRun, reject) => {
    const child = spawn(command, args, { windowsHide: true, ...options });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => { stdout += chunk; });
    child.stderr?.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolveRun({ stdout, stderr });
      else reject(new Error(`Command failed (${code}): ${command} ${args.join(" ")}\n${stderr || stdout}`));
    });
  });
}

async function sha256(path) {
  return new Promise((resolveHash, reject) => {
    const hash = createHash("sha256");
    createReadStream(path)
      .on("data", (chunk) => hash.update(chunk))
      .on("error", reject)
      .on("end", () => resolveHash(hash.digest("hex").toUpperCase()));
  });
}

async function probe(path) {
  const { stdout } = await run(ffprobe, [
    "-v", "error",
    "-print_format", "json",
    "-show_format",
    "-show_streams",
    path,
  ]);
  return JSON.parse(stdout);
}

function streamSummary(probeJson) {
  return probeJson.streams.map((stream) => ({
    index: stream.index,
    codec_type: stream.codec_type,
    codec_name: stream.codec_name,
    width: stream.width ?? null,
    height: stream.height ?? null,
    pix_fmt: stream.pix_fmt ?? null,
    sample_rate: stream.sample_rate ?? null,
    channels: stream.channels ?? null,
    r_frame_rate: stream.r_frame_rate ?? null,
    avg_frame_rate: stream.avg_frame_rate ?? null,
    duration: stream.duration ? Number(stream.duration) : null,
  }));
}

function durationOf(probeJson) {
  return Number(probeJson.format?.duration ?? 0);
}

function assertNear(label, actual, expected, tolerance = 0.035) {
  if (Math.abs(actual - expected) > tolerance) {
    throw new Error(`${label}: duration mismatch, expected ${expected}, got ${actual}`);
  }
}

async function copyIfExists(source, target) {
  if (!existsSync(source)) return null;
  await copyFile(source, target);
  return target;
}

async function main() {
  if (!existsSync(ffmpeg)) throw new Error(`ffmpeg not found: ${ffmpeg}`);
  if (!existsSync(ffprobe)) throw new Error(`ffprobe not found: ${ffprobe}`);

  await mkdir(mediaDir, { recursive: true });
  await mkdir(sfxDir, { recursive: true });
  await mkdir(fontsDir, { recursive: true });
  await mkdir(vendorDir, { recursive: true });
  await mkdir(inputDir, { recursive: true });
  await mkdir(reportsDir, { recursive: true });

  await copyFile(resolve(repoRoot, "experiments", "hyperframes-workflow-poc", "stage-02-edit-plan", "edit_plan.timed.json"), resolve(inputDir, "edit_plan.timed.json"));
  await copyFile(resolve(repoRoot, "experiments", "hyperframes-workflow-poc", "stage-02-edit-plan", "inputs", "word-timings.json"), resolve(inputDir, "word-timings.json"));

  const avatarAssets = [];
  for (const item of avatarSources) {
    if (!existsSync(item.source)) throw new Error(`Missing avatar island: ${item.source}`);
    const adoptedPath = resolve(mediaDir, item.adopted);
    await copyFile(item.source, adoptedPath);
    const hash = await sha256(adoptedPath);
    if (hash !== item.expectedSha256) {
      throw new Error(`${item.adopted}: SHA-256 mismatch, expected ${item.expectedSha256}, got ${hash}`);
    }
    const metadata = await probe(adoptedPath);
    assertNear(item.adopted, durationOf(metadata), item.expectedDuration);
    avatarAssets.push({
      order: item.order,
      source_path: item.source,
      adopted_path: adoptedPath,
      sha256: hash,
      duration: durationOf(metadata),
      streams: streamSummary(metadata),
    });
  }

  const masterAdopted = resolve(mediaDir, "voice_master.wav");
  await copyFile(masterAudioSource, masterAdopted);
  const masterProbe = await probe(masterAdopted);
  const masterHash = await sha256(masterAdopted);
  assertNear("voice_master.wav", durationOf(masterProbe), 42.320);

  const concatPath = resolve(mediaDir, "avatar-concat.txt");
  const concatBody = avatarAssets
    .map((asset) => `file '${asset.adopted_path.replaceAll("\\", "/").replaceAll("'", "'\\''")}'`)
    .join("\n");
  await writeFile(concatPath, `${concatBody}\n`, "utf8");

  const avatarBase = resolve(mediaDir, "avatar-base-silent.mp4");
  await run(ffmpeg, [
    "-y",
    "-f", "concat",
    "-safe", "0",
    "-i", concatPath,
    "-an",
    "-vf", "setpts=1.03199375731565*PTS,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration=0.12,trim=duration=42.32,setpts=PTS-STARTPTS",
    "-t", "42.32",
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-movflags", "+faststart",
    avatarBase,
  ]);
  const avatarBaseProbe = await probe(avatarBase);
  assertNear("avatar-base-silent.mp4", durationOf(avatarBaseProbe), 42.320);

  const fontSourceDir = resolve(repoRoot, "plugins", "reels-factory", "engine", "hyperframes", "_fonts");
  for (const name of [
    "unbounded-600-cyrillic.woff2",
    "unbounded-700-cyrillic.woff2",
    "unbounded-800-cyrillic.woff2",
    "manrope-500-cyrillic.woff2",
    "manrope-600-cyrillic.woff2",
    "manrope-700-cyrillic.woff2",
  ]) {
    await copyFile(resolve(fontSourceDir, name), resolve(fontsDir, name));
  }
  await copyFile(
    resolve(repoRoot, "..", "reference-audit", "hyperframes-main-20260801-complete", "hyperframes-main", "skills", "talking-head-recut", "assets", "vendor", "gsap.min.js"),
    resolve(vendorDir, "gsap.min.js"),
  );

  const sfx = [];
  for (const [name, source] of sfxSources) {
    const target = resolve(sfxDir, name);
    const adopted = await copyIfExists(source, target);
    sfx.push({
      name,
      source_path: source,
      adopted_path: adopted,
      available: Boolean(adopted),
      sha256: adopted ? await sha256(adopted) : null,
      probe: adopted ? streamSummary(await probe(adopted)) : null,
    });
  }

  const manifest = {
    generated_at: new Date().toISOString(),
    ffmpeg,
    ffprobe,
    avatar_sync: {
      source_total_duration: 41.008,
      target_duration: 42.320,
      setpts: 1.03199375731565,
      playback_rate: 0.968998109640832,
      target_island_boundaries: [
        { island: 1, start: 0.0, end: 12.094967 },
        { island: 2, start: 12.094967, end: 23.364339 },
        { island: 3, start: 23.364339, end: 35.211627 },
        { island: 4, start: 35.211627, end: 42.320000 },
      ],
      visual_lip_sync_check_points: [2.0, 13.0, 24.0, 36.0, 41.0],
    },
    avatar_islands: avatarAssets,
    master_audio: {
      source_path: masterAudioSource,
      adopted_path: masterAdopted,
      sha256: masterHash,
      duration: durationOf(masterProbe),
      streams: streamSummary(masterProbe),
    },
    derived_assets: {
      avatar_base_silent: {
        adopted_path: avatarBase,
        sha256: await sha256(avatarBase),
        duration: durationOf(avatarBaseProbe),
        streams: streamSummary(avatarBaseProbe),
      },
    },
    sfx,
  };

  await writeFile(resolve(inputDir, "source-assets.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  await writeFile(resolve(reportsDir, "input-audit.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ status: "PASS", avatar_base_duration: durationOf(avatarBaseProbe), master_audio_duration: durationOf(masterProbe) }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || String(error));
  process.exit(1);
});
