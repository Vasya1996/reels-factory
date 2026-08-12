/**
 * Компилятор: edit_plan.timed.json + word-timings → HyperFrames-композиция.
 *
 * Что делает:
 *  1) читает план (13 сцен) и пословные тайминги ElevenLabs;
 *  2) сопоставляет сцены golden-блокам (mapping ниже: старые catalog-id плана
 *     → принятые Юлией блоки «Скетчбука»; отклонённые свайпом id заменены);
 *  3) генерирует standalone-композицию по контракту HyperFrames:
 *     root[data-composition-id] + клипы .clip[data-start/duration/track] +
 *     ОДИН paused GSAP timeline в window.__timelines;
 *  4) декларативные data-anim/data-at из шаблонов превращает в tweens
 *     с абсолютными временами (детерминированно, seek-safe).
 *
 * Рендерер HyperFrames НЕ модифицируется: мы производим его вход.
 * Запуск: node compiler/compile.mjs
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as B from './blocks.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');                    // golden-catalog/
const stage02 = join(root, '..', 'stage-02-edit-plan');

const plan = JSON.parse(readFileSync(join(stage02, 'edit_plan.timed.json'), 'utf8'));
const timings = JSON.parse(readFileSync(join(stage02, 'inputs', 'word-timings.json'), 'utf8'));
const words = timings.words;

/* Сцена → шаблон golden-блока.
 * Отклонённые свайпом id плана заменены на принятые эквиваленты:
 *  concept_nodes → progressive/ghost, persona_card → chapterGhost,
 *  value_layers → beforeAfter, avatar_broll_split → chapterGhost,
 *  social_outro → ctaPillWord. */
const SCENE_MAP = {
  s01: s => B.statNumber(s, ctx(s)),
  s02: s => B.avatarBubble(s, ctx(s)),
  s03: s => B.complexityCloud(s, ctx(s)),
  s04: s => B.checklistStrike(s, ctx(s)),
  s05: s => B.sequenceFlow(s, ctx(s)),
  s06: s => B.chapterGhost(s, ctx(s), { num: 1 }),
  s07: s => B.beforeAfter(s, ctx(s)),
  s08: s => B.chapterGhost(s, ctx(s), { num: 3 }),
  s09: s => B.avatarBubble(s, ctx(s)),
  s10: s => B.progressiveText(s, ctx(s), { lines: ['ОСТАЛЬНОЕ', 'НАДСТРОЙКА', 'НАД ТРЕМЯ'] }),
  s11: s => B.avatarFullscreen(s, ctx(s)),
  s12: s => B.sequenceFlow(s, ctx(s)),
  s13: s => B.ctaPillWord(s, ctx(s)),
};

function ctx(scene) {
  return {
    sid: scene.scene_id,
    words: words.filter(w => w.index >= scene.word_start && w.index <= scene.word_end),
  };
}

/* ---------- сборка клипов ---------- */
let clips = '';
for (const scene of plan.scenes) {
  const html = SCENE_MAP[scene.scene_id](scene);
  const dur = (scene.end - scene.start).toFixed(3);
  clips += `
  <section id="${scene.scene_id}" class="clip" data-start="${scene.start.toFixed(3)}" data-duration="${dur}" data-track-index="1">
    ${html.replace(/class="skb-scene"/, `class="skb-scene" data-scene="${scene.scene_id}"`)}
  </section>`;
}

/* ---------- уникальные id для анимируемых элементов ---------- */
let uid = 0;
clips = clips.replace(/data-anim="/g, () => `id="an${(uid++).toString(36).padStart(3, '0')}" data-anim="`);

/* ---------- композиция ---------- */
const composition = `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=1080, height=1920">
<title>${plan.project_id} · golden compile</title>
<script src="vendor/gsap.min.js"></script>
<link rel="stylesheet" href="../tokens.css">
<style>
  body{background:#000;display:block}
  #root{position:relative;width:1080px;height:1920px;overflow:hidden;background:var(--paper)}
  .clip{position:absolute;inset:0}
  .skb-scene{position:absolute;inset:0;display:flex;flex-direction:column;padding:118px 84px 104px;
    background-color:var(--paper);
    background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);
    background-size:67px 67px}
  .skb-scene .pill{opacity:1;transform:rotate(var(--rot,0deg))}
  .skb-scene .w,.skb-scene .tech{opacity:1;transform:none}
  .hl i{transform-origin:left center}
  .strike u{transform-origin:left center}
</style>
</head>
<body>
<div id="root" data-composition-id="reel-golden" data-start="0" data-width="1080" data-height="1920" data-duration="${plan.duration_seconds}">
${clips}
</div>
<script>
window.__timelines = window.__timelines || {};
const tl = gsap.timeline({ paused: true });
const POP = 'back.out(1.6)', OUT = 'power3.out';
document.querySelectorAll('[data-anim]').forEach(el => {
  const at = parseFloat(el.dataset.at), kind = el.dataset.anim, id = '#' + el.id;
  if (kind === 'word') {
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
    tl.from(id, { scale: 0.4, rotation: -20, autoAlpha: 0, duration: 0.3, ease: POP }, at);
  } else if (kind === 'fade') {
    tl.from(id, { autoAlpha: 0, y: 12, duration: 0.34, ease: OUT }, at);
  }
});
window.__timelines['reel-golden'] = tl;
</script>
</body>
</html>`;

mkdirSync(join(root, 'build'), { recursive: true });
writeFileSync(join(root, 'build', 'index.html'), composition);

/* ---------- превью-обёртка (аниматик с контролами) ---------- */
const preview = `<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><title>Превью · аниматик 42s</title>
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
  win.__timelines['reel-golden'].time(time,false);
  win.document.querySelectorAll('.clip').forEach(c=>{
    const s=+c.dataset.start,d=+c.dataset.duration;
    c.style.display=(time>=s&&time<s+d)?'block':'none';
  });
  seek.value=time; tEl.textContent=time.toFixed(2)+' / '+DUR;
}
function tick(now){
  if(!playing) return;
  const t=Math.min(base+(now-t0)/1000,DUR);
  apply(t);
  if(t>=DUR){playing=false;btn.textContent='▶ Сначала';base=0;return}
  raf=requestAnimationFrame(tick);
}
btn.onclick=()=>{
  if(playing){playing=false;btn.textContent='▶ Играть';base=+seek.value;return}
  playing=true;btn.textContent='⏸ Пауза';
  base=+seek.value>=DUR?0:+seek.value;
  t0=performance.now();requestAnimationFrame(tick);
};
seek.oninput=()=>{playing=false;btn.textContent='▶ Играть';apply(+seek.value);base=+seek.value};
f.onload=()=>setTimeout(()=>apply(0),300);
</script>
</body></html>`;
writeFileSync(join(root, 'build', 'preview.html'), preview);

console.log('OK: build/index.html (' + Math.round(composition.length / 1024) + ' KB), ' +
  plan.scenes.length + ' scenes, ' + uid + ' animated elements, ' +
  words.length + ' word timings, duration ' + plan.duration_seconds + 's');
