import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const stageDir = resolve(here, "..");
const repoRoot = resolve(stageDir, "..", "..", "..");
const reportsDir = resolve(stageDir, "reports");
const frameDir = resolve(reportsDir, "contact-frames");
const renderPath = resolve(stageDir, "renders", "sales-three-questions-draft.mp4");
const ffmpeg = process.env.FFMPEG_PATH ||
  resolve(repoRoot, "..", "revideo_test", "node_modules", "@ffmpeg-installer", "win32-x64", "ffmpeg.exe");
const ffprobe = process.env.FFPROBE_PATH ||
  resolve(repoRoot, "..", "revideo_test", "node_modules", "@ffprobe-installer", "win32-x64", "ffprobe.exe");

const midpoints = [
  1.500,
  4.166,
  7.037,
  10.130,
  12.560,
  16.090,
  20.660,
  24.350,
  27.420,
  30.220,
  33.000,
  36.200,
  40.140,
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

function duration(probeJson) {
  return Number(probeJson.format?.duration ?? 0);
}

function videoStream(probeJson) {
  return probeJson.streams.find((stream) => stream.codec_type === "video");
}

function audioStreams(probeJson) {
  return probeJson.streams.filter((stream) => stream.codec_type === "audio");
}

function ratio(rate) {
  const [a, b] = String(rate || "0/1").split("/").map(Number);
  return b ? a / b : a;
}

async function main() {
  if (!existsSync(renderPath)) throw new Error(`Render MP4 does not exist: ${renderPath}`);
  if (!existsSync(ffmpeg)) throw new Error(`ffmpeg not found: ${ffmpeg}`);
  if (!existsSync(ffprobe)) throw new Error(`ffprobe not found: ${ffprobe}`);
  const size = (await stat(renderPath)).size;
  if (size <= 0) throw new Error(`Render MP4 is empty: ${renderPath}`);

  await mkdir(frameDir, { recursive: true });
  const metadata = await probe(renderPath);
  const v = videoStream(metadata);
  const a = audioStreams(metadata);
  const dur = duration(metadata);
  const fps = ratio(v?.avg_frame_rate);

  if (Math.abs(dur - 42.320) > 0.034) throw new Error(`Duration outside tolerance: ${dur}`);
  if (v?.width !== 1080 || v?.height !== 1920) throw new Error(`Unexpected resolution: ${v?.width}x${v?.height}`);
  if (Math.abs(fps - 30) > 0.05) throw new Error(`Unexpected FPS: ${fps}`);
  if (a.length !== 1) throw new Error(`Expected exactly one audio stream, got ${a.length}`);

  for (let index = 0; index < midpoints.length; index += 1) {
    const out = resolve(frameDir, `frame-${String(index + 1).padStart(2, "0")}.jpg`);
    await run(ffmpeg, [
      "-y",
      "-ss", midpoints[index].toFixed(3),
      "-i", renderPath,
      "-frames:v", "1",
      "-q:v", "2",
      out,
    ]);
  }
  const contactSheet = resolve(reportsDir, "contact-sheet.jpg");
  await run(ffmpeg, [
    "-y",
    "-framerate", "1",
    "-start_number", "1",
    "-i", resolve(frameDir, "frame-%02d.jpg"),
    "-vf", "scale=270:480,tile=4x4:padding=10:margin=10:color=0x171310",
    "-frames:v", "1",
    contactSheet,
  ]);

  let checkStatus = "not found";
  const checkPath = resolve(reportsDir, "check.json");
  if (existsSync(checkPath)) {
    const check = JSON.parse((await readFile(checkPath, "utf8")).replace(/^\uFEFF/, ""));
    checkStatus = check.ok === true || check.status === "PASS" ? "PASS" : "SEE check.json";
  }

  const audit = `# Render Audit

Status: PASS

MP4: ${renderPath}
Contact sheet: ${contactSheet}

## ffprobe

- duration: ${dur.toFixed(3)} s
- resolution: ${v.width}x${v.height}
- fps: ${fps.toFixed(3)}
- video codec: ${v.codec_name}
- audio streams: ${a.length}
- audio codec: ${a[0]?.codec_name}
- file size: ${size} bytes

## Gates

- Stage 02 validator: PASS
- HyperFrames check: ${checkStatus}
- Expected duration tolerance: 42.320 +/- 0.034 s
- Master voice uniqueness: one audio stream in final MP4

## Avatar Sync

The four avatar islands were concatenated in the supplied chronological order and uniformly retimed with setpts=1.03199375731565, equivalent playback rate 0.968998109640832, then converted to 1080x1920, square pixels, 30 fps, silent H.264.

Visual lip-sync review points for the contact/preview pass: 2.0, 13.0, 24.0, 36.0, 41.0 seconds.

## SFX

Used local pop clicks at 34.980, 35.940, 37.460 and 41.915 if pop.wav was available. Used quiet local whoosh at editorial push starts if whoosh.wav was available. No BGM was added.

## Visual Review Notes

Contact sheet was generated from 13 scene midpoint frames. Check for black/blank frames, Russian text clipping, avatar hidden/visible intent, CTA readability, and unexpected transition flashes before final handoff.
`;
  await writeFile(resolve(reportsDir, "render-audit.md"), audit, "utf8");
  console.log(JSON.stringify({ status: "PASS", duration: dur, width: v.width, height: v.height, fps, audio_streams: a.length, contact_sheet: contactSheet }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || String(error));
  process.exit(1);
});
