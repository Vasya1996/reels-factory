/**
 * Компилятор: project-skills/edit_plan.json + word-timings → HyperFrames-композиция.
 *
 * Что делает:
 *  1) читает план (9 сцен) и пословные тайминги (локальный whisper-alignment);
 *  2) сопоставляет сцены golden-блокам (mapping ниже);
 *  3) генерирует standalone-композицию по контракту HyperFrames:
 *     root[data-composition-id] + клипы .clip[data-start/duration/track] +
 *     ОДИН paused GSAP timeline в window.__timelines;
 *  4) декларативные data-anim/data-at из шаблонов превращает в tweens
 *     с абсолютными временами (детерминированно, seek-safe);
 *  5) подставляет реальное видео аватара (assets/avatar.mp4, немое) в
 *     avatar-слоты блоков и мастер-аудио (assets/voice.mp3) на весь ролик.
 *
 * Два выходных файла (одна и та же разметка сцен, разный playback-слой):
 *  - build/index.html — для build/preview.html (лёгкий локальный скраббер:
 *    play/пауза/перемотка без CLI). Плейбеком управляет наш JS
 *    (window.__setMediaTime) — это НЕ совместимо с реальным HyperFrames
 *    рендерером (лимит imperative_media_control), но удобно для мгновенной
 *    итерации без Chrome/ffmpeg.
 *  - build/render.html — для `npx hyperframes lint/check/render`: та же
 *    разметка, но БЕЗ единой imperative-строчки над <video>/<audio> —
 *    playback полностью декларативный (data-start/data-duration/
 *    data-media-start на самих media-тегах), как требует контракт
 *    hyperframes-core (variables-and-media.md).
 *
 * build/ самодостаточен: assets/, fonts/, tokens.css копируются внутрь при
 * каждой компиляции — и локальный http.server, и `hyperframes render build`
 * резолвят пути одинаково (root-relative, без "../").
 *
 * Рендерер HyperFrames НЕ модифицируется: мы производим его вход.
 * Запуск: node compiler/compile.mjs
 */
import { readFileSync, writeFileSync, mkdirSync, cpSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as B from './blocks.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');                    // golden-catalog/
// Параметризовано (NEXT-SESSION.md шаг 4): по умолчанию project-skills/ (старый
// "ai-skills-poc"), для нового ролика передать имя папки первым аргументом,
// напр. `node compiler/compile.mjs project-avatar-bot`.
const projectDir = join(root, process.argv[2] || 'project-skills');
const buildDir = join(root, 'build');
const renderDir = join(root, 'render-project');    // самодостаточный project root для `npx hyperframes`

const plan = JSON.parse(readFileSync(join(projectDir, 'edit_plan.json'), 'utf8'));
const timings = JSON.parse(readFileSync(join(projectDir, 'word-timings.json'), 'utf8'));
const words = timings.words;

/* Сцена → шаблон golden-блока: раньше был захардкожен построчно под 9 сцен
 * "ai-skills-poc" (баг компилятора — новый план с другим числом/набором
 * сцен ломался, scene.block из плана игнорировался). Теперь берём функцию
 * блока прямо по имени из edit_plan.json (тому самому `scene.block`, который
 * уже проверяет validate-plan.mjs через BLOCK_PASSPORTS). */
const SCENE_MAP = Object.fromEntries(
  plan.scenes.map(s => [s.scene_id, scene => B[scene.block](scene, ctx(scene))]),
);

/* Верхние tech-лейблы ОТКЛЮЧЕНЫ по фидбеку Юлии 2026-08-03:
 * абстрактные мета-слова («ПЕРСОНАЛИЗАЦИЯ», «МАСШТАБ») в кадре = кринж.
 * tech() в blocks.mjs не рендерится при пустой строке — лейбл всегда ''. */
function ctx(scene) {
  return {
    sid: scene.scene_id,
    label: '',
    words: words.filter(w => w.index >= scene.word_start && w.index <= scene.word_end),
  };
}

/* ---------- копируем ассеты внутрь build/ и render-project/, чтобы пути
   были root-relative (и локальный http.server, и `npx hyperframes`
   резолвят "assets/..." против ЭТОЙ папки, без "../") ---------- */
mkdirSync(buildDir, { recursive: true });
mkdirSync(renderDir, { recursive: true });
for (const dir of [buildDir, renderDir]) {
  cpSync(join(root, 'assets'), join(dir, 'assets'), { recursive: true });
  cpSync(join(root, 'fonts'), join(dir, 'fonts'), { recursive: true });
  cpSync(join(root, 'tokens.css'), join(dir, 'tokens.css'));
}
mkdirSync(join(renderDir, 'vendor'), { recursive: true });
cpSync(join(buildDir, 'vendor', 'gsap.min.js'), join(renderDir, 'vendor', 'gsap.min.js'));

/* ---------- сборка клипов (общая для index.html и render.html) ----------
 * <video> НЕ кладём внутрь <section class="clip"> сцены — HyperFrames не
 * умеет управлять playback вложенных в другой timed-элемент media (lint:
 * video_nested_in_timed_element, "video будет FROZEN в рендере"). Поэтому
 * блоки возвращают { html, video }: html уходит в секцию сцены, video —
 * отдельным ПРЯМЫМ потомком #root (см. mediaVideos ниже), с абсолютным
 * позиционированием и своим собственным data-start/data-duration. */
let clips = '';
let mediaVideos = '';
for (const scene of plan.scenes) {
  const { html, video } = SCENE_MAP[scene.scene_id](scene);
  const dur = (scene.end - scene.start).toFixed(3);
  clips += `
  <section id="${scene.scene_id}" class="clip" data-start="${scene.start.toFixed(3)}" data-duration="${dur}" data-track-index="1">
    ${html.replace(/class="skb-scene"/, `class="skb-scene" data-scene="${scene.scene_id}"`)}
  </section>`;
  if (video) mediaVideos += `\n${video}`;
}

/* ---------- уникальные id для анимируемых элементов ---------- */
let uid = 0;
clips = clips.replace(/data-anim="/g, () => `id="an${(uid++).toString(36).padStart(3, '0')}" data-anim="`);

const masterAudioTag = `<audio id="masterAudio" class="clip" data-start="0" data-duration="${plan.duration_seconds}" data-track-index="3" src="assets/voice.mp3" preload="auto"></audio>`;

const gsapTimelineScript = `
window.__timelines = window.__timelines || {};
const tl = gsap.timeline({ paused: true });
const POP = 'back.out(1.6)', OUT = 'power3.out';
document.querySelectorAll('[data-anim]').forEach(el => {
  const at = parseFloat(el.dataset.at), kind = el.dataset.anim, id = '#' + el.id;
  if (kind === 'cword') {
    tl.from(id, { autoAlpha: 0, duration: 0.18 }, at);
  } else if (kind === 'word') {
    tl.from(id, { y: 14, autoAlpha: 0, duration: 0.22, ease: OUT }, at);
    const hlAt = el.dataset.hlAt, i = el.querySelector('i');
    if (hlAt && i) tl.fromTo(i, { scaleX: 0 }, { scaleX: 1, duration: 0.3, ease: OUT }, parseFloat(hlAt));
  } else if (kind === 'pop') {
    tl.from(id, { scale: 0.6, autoAlpha: 0, duration: 0.3, ease: POP }, at);
  } else if (kind === 'stamp') {
    tl.from(id, { scale: 1.3, autoAlpha: 0, duration: 0.38, ease: POP }, at);
  } else if (kind === 'card') {
    tl.from(id, { y: 30, autoAlpha: 0, duration: 0.4, ease: OUT }, at);
    const sAt = el.dataset.strikeAt, u = el.querySelector('u');
    if (sAt && u) {
      tl.fromTo(u, { scaleX: 0 }, { scaleX: 1, duration: 0.26, ease: OUT }, parseFloat(sAt));
      tl.to(id + ' .txt', { color: 'rgba(27,27,24,.4)', duration: 0.2 }, parseFloat(sAt) + 0.1);
    }
  } else if (kind === 'tick') {
    // .from() не годится здесь (баг найден на taskList/beforeAfter,
    // 2026-08-03): GSAP резолвит "to" для scale/rotation в текущее
    // computed-значение элемента, а для свежего [data-anim] элемента это
    // те же исходные scale(.4)/rotate(-20deg) из класса .tick — тween
    // получается 0→0, no-op. fromTo с явным "to" однозначен.
    tl.fromTo(id, { scale: 0.4, rotation: -20, autoAlpha: 0 },
      { scale: 1, rotation: 0, autoAlpha: 1, duration: 0.3, ease: POP }, at);
  } else if (kind === 'fade') {
    tl.from(id, { autoAlpha: 0, y: 12, duration: 0.34, ease: OUT }, at);
  }
});
window.__timelines['reel-skills'] = tl;`;

/* Синхронизация мастер-аудио и avatar-видео с внешним таймлайном превью.
   ТОЛЬКО для build/preview.html (наш лёгкий скраббер) — реальный
   HyperFrames-рендерер запрещает imperative play()/pause()/currentTime на
   managed media (lint: imperative_media_control), поэтому этот блок
   попадает исключительно в index.html, НЕ в render.html. */
const mediaSyncScript = `
window.__setMediaTime = function (t, playing) {
  // Пока playing=true, видео/аудио сами продвигают currentTime в реальном
  // времени — форсировать seek каждый тик нельзя (H.264 не имеет кадра на
  // каждую миллисекунду, повторный seek на не-keyframe запускает decode с
  // предыдущего keyframe и не успевает закончиться за 16мс: получается
  // "seek-шторм" и видео визуально замирает). Поэтому: жёсткий seek только
  // при смене сцены или большом дрейфе (>0.35с), иначе даём плееру играть.
  const audio = document.getElementById('masterAudio');
  if (audio) {
    if (!playing) {
      audio.pause();
      if (Math.abs(audio.currentTime - t) > 0.02) audio.currentTime = t;
    } else {
      if (audio.dataset.synced !== '1' || Math.abs(audio.currentTime - t) > 0.35) {
        audio.currentTime = t;
        audio.dataset.synced = '1';
      }
      if (audio.paused) audio.play().catch(() => {});
    }
  }
  document.querySelectorAll('.avatar-video').forEach(v => {
    // Видео — ПРЯМОЙ потомок #root (не вложено в секцию сцены, см.
    // compile.mjs), с собственными data-start/data-duration — тот же цикл
    // preview.html, что переключает .clip секций, переключает и его
    // display. Видимость проверяем у самого элемента, не у родителя.
    const visible = v.style.display !== 'none';
    if (!visible) {
      if (!v.paused) v.pause();
      v.dataset.synced = '';
      return;
    }
    if (!playing) {
      v.pause();
      if (Math.abs(v.currentTime - t) > 0.02) v.currentTime = t;
      return;
    }
    if (v.dataset.synced !== v.id || Math.abs(v.currentTime - t) > 0.35) {
      v.currentTime = t;
      v.dataset.synced = v.id;
    }
    if (v.paused) v.play().catch(() => {});
  });
};`;

function buildDocument({ title, includeMediaSync }) {
  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=1080, height=1920">
<title>${title}</title>
<script src="vendor/gsap.min.js"></script>
<link rel="stylesheet" href="tokens.css">
<style>
  body{background:#000;display:block}
  #root{position:relative;width:1080px;height:1920px;overflow:hidden;background:var(--paper)}
  /* z-index:2 — сцены (.clip секции) стоят выше "холстовых" avatar-video
     (z-index:1 инлайн, см. blocks.mjs) и ниже PiP-видео (z-index:5 инлайн).
     Инлайн-стиль всегда переопределяет это класс-правило для самих <video>. */
  .clip{position:absolute;inset:0;z-index:2}
  /* Фон-бумага теперь ОДИН общий слой на #root (см. #bg ниже), не на
     каждой .skb-scene: скрин сцены сидит на z-index:2, а avatar-video —
     на z-index:1. Если бы .skb-scene сама красила непрозрачный фон, она
     закрашивала бы видео ПОД собой (оно перестало быть DOM-ребёнком сцены
     — video_nested_in_timed_element запрещает вложенность, см. blocks.mjs). */
  .skb-scene{position:absolute;inset:0;display:flex;flex-direction:column;padding:118px 84px 400px;background:transparent}
  .skb-scene .pill{opacity:1;transform:rotate(var(--rot,0deg))}
  .skb-scene .w,.skb-scene .tech{opacity:1;transform:none}
  .hl i{transform-origin:left center}
  .strike u{transform-origin:left center}
</style>
</head>
<body>
<div id="root" data-composition-id="reel-skills" data-start="0" data-width="1080" data-height="1920" data-duration="${plan.duration_seconds}">
<div id="bg" style="position:absolute;inset:0;z-index:0;background-color:var(--paper);
  background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);
  background-size:67px 67px"></div>
${clips}
${mediaVideos}
${masterAudioTag}
</div>
<script>${gsapTimelineScript}${includeMediaSync ? mediaSyncScript : ''}
</script>
</body>
</html>`;
}

writeFileSync(join(buildDir, 'index.html'), buildDocument({
  title: `${plan.project_id} · golden compile (preview, imperative playback)`,
  includeMediaSync: true,
}));
writeFileSync(join(renderDir, 'index.html'), buildDocument({
  title: `${plan.project_id} · golden compile (render, declarative playback)`,
  includeMediaSync: false,
}));

/* ---------- превью-обёртка (аниматик с контролами, грузит index.html) ---------- */
const preview = `<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><title>Превью · аниматик ${plan.duration_seconds}s</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#1a1916;height:100vh;display:flex;flex-direction:column;align-items:center;font-family:system-ui}
  #wrap{flex:1;display:flex;align-items:center;justify-content:center;width:100%;overflow:hidden}
  iframe{border:0;transform-origin:center center}
  #bar{width:100%;padding:14px 20px;display:flex;gap:14px;align-items:center;background:#111;color:#eee}
  button{font:700 14px system-ui;padding:9px 20px;border:0;border-radius:8px;background:#FFD84D;cursor:pointer}
  input[type=range]{flex:1}
  #t{font-variant-numeric:tabular-nums;font-size:14px;width:110px}
</style></head>
<body>
<div id="wrap"><iframe id="f" src="index.html" width="1080" height="1920" scrolling="no"></iframe></div>
<div id="bar">
  <button id="play">▶ Играть</button>
  <input type="range" id="seek" min="0" max="${plan.duration_seconds}" step="0.01" value="0">
  <div id="t">0.00 / ${plan.duration_seconds}</div>
</div>
<script>
const DUR=${plan.duration_seconds};
const f=document.getElementById('f'), seek=document.getElementById('seek'),
      tEl=document.getElementById('t'), btn=document.getElementById('play');
let playing=false, t0=0, base=0, raf;
function fit(){const w=innerWidth*.96,h=(innerHeight-70)*.98;
  f.style.transform='scale('+Math.min(w/1080,h/1920)+')';}
addEventListener('resize',fit);fit();
function apply(time){
  const win=f.contentWindow; if(!win||!win.__timelines) return;
  win.__timelines['reel-skills'].time(time,false);
  win.document.querySelectorAll('.clip').forEach(c=>{
    const s=+c.dataset.start,d=+c.dataset.duration;
    c.style.display=(time>=s&&time<s+d)?'block':'none';
  });
  if (win.__setMediaTime) win.__setMediaTime(time, playing);
  seek.value=time; tEl.textContent=time.toFixed(2)+' / '+DUR;
}
function tick(now){
  if(!playing) return;
  const t=Math.min(base+(now-t0)/1000,DUR);
  apply(t);
  if(t>=DUR){playing=false;btn.textContent='▶ Сначала';base=0;apply(0);return}
  raf=requestAnimationFrame(tick);
}
btn.onclick=()=>{
  if(playing){playing=false;btn.textContent='▶ Играть';base=+seek.value;apply(base);return}
  playing=true;btn.textContent='⏸ Пауза';
  base=+seek.value>=DUR?0:+seek.value;
  /* apply() здесь вызывается СИНХРОННО внутри обработчика клика (не через
     requestAnimationFrame кадром позже) — иначе play() у аудио/видео внутри
     iframe теряет user-activation клика и браузер молча блокирует autoplay
     со звуком (это и было причиной "нет звука"). */
  apply(base);
  t0=performance.now();requestAnimationFrame(tick);
};
seek.oninput=()=>{playing=false;btn.textContent='▶ Играть';apply(+seek.value);base=+seek.value};
f.onload=()=>setTimeout(()=>apply(0),300);
</script>
</body></html>`;
writeFileSync(join(buildDir, 'preview.html'), preview);

console.log('OK: build/index.html (preview) + render-project/index.html (CLI render), ' +
  plan.scenes.length + ' scenes, ' + uid + ' animated elements, ' +
  words.length + ' word timings, duration ' + plan.duration_seconds + 's');
