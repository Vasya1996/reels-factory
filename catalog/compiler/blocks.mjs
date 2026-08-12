/**
 * Шаблоны golden-блоков для компилятора.
 * Каждый шаблон: (scene, ctx) => html-строка сцены (содержимое клипа).
 *
 * Анимации объявляются декларативно атрибутами:
 *   data-anim="word|pop|stamp|card|strike|tick|hl|fade"
 *   data-at="<секунды от начала КОМПОЗИЦИИ>"
 * Тайминг-строитель (в assemble.mjs) превращает их в tweens одного
 * paused GSAP timeline. Никакого JS внутри шаблонов.
 *
 * ctx: { sid, t(wordIndexOrOffset), words(scene), esc, hl(text, emph) }
 */

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/** Слова речи сцены → спаны caption с пословным появлением. */
function captionWords(scene, ctx, { size = 44, bottom = 120 } = {}) {
  if (scene.captions === 'hidden') return '';
  const spans = ctx.words.map(w =>
    `<span class="w" data-anim="word" data-at="${w.start.toFixed(3)}">${esc(w.text)}</span>`
  ).join(' ');
  return `<div class="hf-cap" style="position:absolute;left:50%;bottom:${bottom}px;transform:translateX(-50%);
    max-width:900px;text-align:center;font-family:MontserratX,sans-serif;font-weight:900;font-size:${size}px;
    text-transform:uppercase;color:var(--ink);background:var(--card);border:5px solid var(--ink);
    padding:18px 34px;box-shadow:6px 8px 0 rgba(27,27,24,.16);border-radius:20px;line-height:1.35">${spans}</div>`;
}

function tech(label, at) {
  return `<div class="tech" data-anim="fade" data-at="${at.toFixed(3)}"><span class="dash"></span><span class="lbl">${esc(label)}</span></div>`;
}

function headline(scene, ctx, { size = 96, at, split } = {}) {
  const t0 = at ?? scene.start + 0.25;
  const emph = new Set((scene.content.emphasis_words || []).map(w => w.toUpperCase().replace(/[^А-ЯA-ZЁ0-9]/g,'')));
  const parts = (split || [scene.content.headline]).filter(Boolean);
  let i = 0;
  const lines = parts.map(line => {
    const ws = line.split(/\s+/).map(word => {
      const clean = word.toUpperCase().replace(/[^А-ЯA-ZЁ0-9]/g,'');
      const at_i = (t0 + i * 0.22).toFixed(3); i++;
      if (emph.has(clean)) {
        return `<span class="w hl" data-anim="word" data-at="${at_i}" data-hl-at="${(+at_i + 0.24).toFixed(3)}"><i></i>${esc(word)}</span>`;
      }
      return `<span class="w" data-anim="word" data-at="${at_i}">${esc(word)}</span>`;
    }).join(' ');
    return ws;
  });
  return `<h1 style="font-size:${size}px">${lines.join('<br>')}</h1>`;
}

/* ---------- шаблоны блоков ---------- */

/** G07 stat_number — гигантская цифра-стикер + подпись. */
export function statNumber(scene, ctx) {
  const t = scene.start;
  const label = esc(scene.content.labels?.[0] ?? '');
  return `
  <div class="skb-scene" style="align-items:center;text-align:center;justify-content:center">
    ${tech('Хук', t)}
    <div class="bignum" data-anim="stamp" data-at="${(t + 0.35).toFixed(3)}"
      style="margin-top:40px;background:var(--yellow);border:8px solid var(--ink);
      border-radius:38px 240px 34px 225px / 225px 34px 240px 38px;padding:10px 80px;
      font-family:MontserratX,sans-serif;font-weight:900;font-size:460px;line-height:1;color:var(--ink);
      box-shadow:14px 16px 0 var(--ink);transform:rotate(-2deg)">${label}</div>
    ${headline(scene, ctx, { size: 74, at: t + 0.9 })}
    ${captionWords(scene, ctx)}
  </div>`;
}

/** G01 avatar_editorial_bubble — аватар в рамке + пункты. */
export function avatarBubble(scene, ctx, { sticker } = {}) {
  const t = scene.start;
  const pts = (scene.content.labels || []).map((l, i) => `
    <div class="pill r${(i % 3) + 1}" style="--rot:${i % 2 ? '.5deg' : '-.6deg'}"
      data-anim="card" data-at="${(t + 1.0 + i * 0.55).toFixed(3)}">
      <span class="idx">0${i + 1}</span><span class="txt">${esc(l.toLowerCase())}</span></div>`).join('');
  return `
  <div class="skb-scene">
    ${tech(scene.purpose === 'hook' ? 'Хук' : 'Глава', t)}
    ${sticker ? `<div class="sticker" data-anim="stamp" data-at="${(t + 0.3).toFixed(3)}" style="font-size:110px">${esc(sticker)}</div>` : ''}
    <div style="display:flex;gap:46px;margin-top:30px;align-items:flex-start">
      <div style="flex:1">
        ${headline(scene, ctx, { size: 86, at: t + 0.45 })}
        <div style="display:flex;flex-direction:column;gap:30px;margin-top:56px">${pts}</div>
      </div>
      <div class="av-ph" data-anim="fade" data-at="${(t + 0.7).toFixed(3)}"
        style="width:340px;height:860px;flex:none;border:6px dashed rgba(27,27,24,.4);
        border-radius:170px 34px 170px 38px / 38px 170px 34px 170px;background:rgba(252,251,246,.5);
        display:flex;align-items:center;justify-content:center">
        <span style="font-family:JBMonoX,monospace;font-size:20px;letter-spacing:.1em;color:rgba(27,27,24,.5);text-transform:uppercase;text-align:center">аватар</span>
      </div>
    </div>
    ${captionWords(scene, ctx)}
  </div>`;
}

/** G13 complexity_cloud — слова-стикеры вокруг аватара. */
export function complexityCloud(scene, ctx) {
  const t = scene.start;
  const cloudWords = ['воронки','приёмы','скрипты','триггеры','прогревы','фразы'];
  const pos = [
    'left:20px;top:16%;--rot:-3deg','right:30px;top:22%;--rot:2deg',
    'left:40px;top:44%;--rot:1.5deg','right:20px;top:50%;--rot:-2deg',
    'left:30px;top:72%;--rot:2.5deg','right:50px;top:76%;--rot:-1.5deg'];
  const cls = ['','y','m','','y','m'];
  const clouds = cloudWords.map((w, i) => `
    <div class="cloudw ${cls[i]}" data-anim="pop" data-at="${(t + 0.9 + i * 0.45).toFixed(3)}"
      style="position:absolute;${pos[i]};background:var(${cls[i]==='y'?'--yellow':cls[i]==='m'?'--mint':'--card'});
      border:5px solid var(--ink);padding:20px 32px;font-size:40px;font-weight:600;color:var(--ink);
      box-shadow:6px 8px 0 rgba(27,27,24,.15);white-space:nowrap;transform:rotate(var(--rot))">${esc(w)}</div>`).join('');
  return `
  <div class="skb-scene" style="padding:118px 60px 104px">
    ${tech('Перечисление', t)}
    ${headline(scene, ctx, { size: 84, at: t + 0.3 })}
    <div style="position:relative;flex:1;margin-top:30px">
      <div data-anim="fade" data-at="${t.toFixed(3)}" style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
        width:460px;height:680px;border:6px dashed rgba(27,27,24,.35);
        border-radius:230px 230px 180px 180px / 300px 300px 140px 140px;display:flex;align-items:center;justify-content:center">
        <span style="font-family:JBMonoX,monospace;font-size:22px;color:rgba(27,27,24,.45);text-transform:uppercase;text-align:center">fullscreen<br>аватар</span>
      </div>
      ${clouds}
    </div>
    ${captionWords(scene, ctx)}
  </div>`;
}

/** G11 checklist_strike — пункты зачёркиваются. */
export function checklistStrike(scene, ctx) {
  const t = scene.start;
  const items = scene.content.labels || [];
  const rows = items.map((l, i) => `
    <div class="pill r${(i % 3) + 1} strike" style="--rot:${i % 2 ? '.6deg' : '-.7deg'}"
      data-anim="card" data-at="${(t + 0.7 + i * 1.0).toFixed(3)}" data-strike-at="${(t + 1.35 + i * 1.0).toFixed(3)}">
      <u></u><span class="idx">0${i + 1}</span><span class="txt">${esc(l.toLowerCase())}</span></div>`).join('');
  return `
  <div class="skb-scene">
    ${tech('Разбор', t)}
    ${headline(scene, ctx, { size: 92, at: t + 0.2 })}
    <div style="display:flex;flex-direction:column;gap:40px;margin-top:90px">${rows}</div>
    ${captionWords(scene, ctx)}
  </div>`;
}

/** G15 big_ghost_number + пункты (главы 1/2/3). */
export function chapterGhost(scene, ctx, { num }) {
  const t = scene.start;
  const pts = (scene.content.labels || []).map((l, i) => `
    <div class="pill r${(i % 3) + 1}" style="--rot:${i % 2 ? '.5deg' : '-.6deg'}"
      data-anim="card" data-at="${(t + 1.1 + i * 0.9).toFixed(3)}">
      <span class="idx">0${i + 1}</span><span class="txt">${esc(l.toLowerCase())}</span></div>`).join('');
  return `
  <div class="skb-scene">
    <div data-anim="stamp" data-at="${(t + 0.4).toFixed(3)}" style="position:absolute;right:-40px;top:44%;
      font-family:MontserratX,sans-serif;font-weight:900;font-size:820px;line-height:1;color:transparent;
      -webkit-text-stroke:8px rgba(27,27,24,.2);transform:translateY(-50%)">${num}</div>
    ${tech('Вопрос ' + num, t)}
    ${headline(scene, ctx, { size: 100, at: t + 0.3 })}
    <div style="display:flex;flex-direction:column;gap:36px;margin-top:90px;position:relative">${pts}</div>
    ${captionWords(scene, ctx)}
  </div>`;
}

/** G12 before_after — было/стало. */
export function beforeAfter(scene, ctx) {
  const t = scene.start;
  const [before, after] = scene.content.labels;
  return `
  <div class="skb-scene">
    ${tech('Подмена', t)}
    ${headline(scene, ctx, { size: 92, at: t + 0.2 })}
    <div data-anim="fade" data-at="${(t + 0.9).toFixed(3)}" style="align-self:flex-start;background:var(--ink);color:var(--card);
      font-family:JBMonoX,monospace;font-weight:700;font-size:28px;letter-spacing:.16em;padding:10px 24px;
      transform:rotate(-1deg);margin-top:70px">КАЖЕТСЯ</div>
    <div class="strike-card" data-anim="card" data-at="${(t + 1.1).toFixed(3)}" style="position:relative;background:var(--card);
      border:6px solid var(--ink);padding:52px 56px;margin-top:22px;box-shadow:var(--shadow-card);transform:rotate(-.6deg)">
      <div style="font-family:MontserratX,sans-serif;font-weight:900;font-size:84px;color:var(--ink);text-transform:uppercase">${esc(before)}</div>
      <div class="xmark" data-anim="tick" data-at="${(t + 1.9).toFixed(3)}" style="position:absolute;right:30px;top:-52px;
        font-family:CaveatX,cursive;font-size:170px;color:var(--red);transform:rotate(-8deg)">✗</div>
    </div>
    <div data-anim="fade" data-at="${(t + 2.3).toFixed(3)}" style="align-self:flex-start;background:var(--red);color:var(--card);
      font-family:JBMonoX,monospace;font-weight:700;font-size:28px;letter-spacing:.16em;padding:10px 24px;
      transform:rotate(-1deg);margin-top:60px">НА САМОМ ДЕЛЕ</div>
    <div data-anim="stamp" data-at="${(t + 2.55).toFixed(3)}" style="background:var(--mint);border:6px solid var(--ink);
      border-radius:38px 240px 34px 225px / 225px 34px 240px 38px;padding:60px 56px;margin-top:22px;
      box-shadow:var(--shadow-cta);transform:rotate(.9deg)">
      <div style="font-family:MontserratX,sans-serif;font-weight:900;font-size:96px;color:var(--ink);text-transform:uppercase">${esc(after)}</div>
    </div>
    ${captionWords(scene, ctx)}
  </div>`;
}

/** G05 progressive_text — крупные строки. */
export function progressiveText(scene, ctx, { lines }) {
  const t = scene.start;
  const bgs = ['', 'var(--yellow)', 'var(--mint)'];
  const rows = (lines || scene.content.labels || []).map((l, i) => `
    <div data-anim="card" data-at="${(t + 0.5 + i * 0.75).toFixed(3)}"
      style="font-family:MontserratX,sans-serif;font-weight:900;font-size:128px;line-height:1.04;
      letter-spacing:-.03em;text-transform:uppercase;color:var(--ink)">
      ${bgs[i % 3] ? `<span style="background:${bgs[i % 3]};padding:0 22px">${esc(l)}</span>` : esc(l)}</div>`).join('');
  return `
  <div class="skb-scene" style="justify-content:center">
    ${tech('Суть', t)}
    <div style="display:flex;flex-direction:column;gap:36px;margin-top:60px">${rows}</div>
    ${captionWords(scene, ctx)}
  </div>`;
}

/** G06 sequence_flow — КТО → ЧТО → КАК. */
export function sequenceFlow(scene, ctx) {
  const t = scene.start;
  const steps = (scene.content.labels || []).map(l => l.replace(/^\d+\.\s*/, ''));
  const rows = steps.map((s, i) => `
    ${i ? `<div class="arr" data-anim="fade" data-at="${(t + 0.5 + i * 0.85).toFixed(3)}"
      style="font-family:CaveatX,cursive;font-size:96px;line-height:.7;color:var(--red);text-align:center">↓</div>` : ''}
    <div class="pill r${(i % 3) + 1}" style="--rot:${i % 2 ? '.5deg' : '-.6deg'};justify-content:center"
      data-anim="card" data-at="${(t + 0.3 + i * 0.85).toFixed(3)}">
      <span style="font-family:MontserratX,sans-serif;font-weight:900;font-size:84px;text-transform:uppercase;color:var(--ink)">${esc(s)}</span></div>`).join('');
  return `
  <div class="skb-scene">
    ${tech('Порядок', t)}
    ${headline(scene, ctx, { size: 88, at: t + 0.15 })}
    <div style="display:flex;flex-direction:column;gap:14px;margin-top:70px">${rows}</div>
    ${captionWords(scene, ctx)}
  </div>`;
}

/** G02 avatar_fullscreen_hook — fullscreen аватар + крупный текст. */
export function avatarFullscreen(scene, ctx) {
  const t = scene.start;
  return `
  <div class="skb-scene" style="padding:0">
    <div data-anim="fade" data-at="${t.toFixed(3)}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
      <div style="width:620px;height:1100px;border:6px dashed rgba(27,27,24,.35);
        border-radius:310px 310px 230px 230px / 400px 400px 190px 190px;display:flex;align-items:flex-end;justify-content:center;padding-bottom:60px">
        <span style="font-family:JBMonoX,monospace;font-size:24px;letter-spacing:.12em;color:rgba(27,27,24,.45);text-transform:uppercase;text-align:center">fullscreen аватар</span>
      </div>
    </div>
    <div style="position:absolute;top:110px;left:64px">${tech('Крупный план', t)}</div>
    <div style="position:absolute;left:64px;right:64px;bottom:230px">
      ${headline(scene, ctx, { size: 104, at: t + 0.45 })}
    </div>
    ${captionWords(scene, ctx)}
  </div>`;
}

/** G20 cta_pill_word — финал. */
export function ctaPillWord(scene, ctx) {
  const t = scene.start;
  const steps = (scene.content.labels || []).filter(l => !l.startsWith('@'));
  const handle = (scene.content.labels || []).find(l => l.startsWith('@')) || '@julia.agents';
  const mini = steps.map((s, i) => `
    <span data-anim="pop" data-at="${(t + 0.9 + i * 0.5).toFixed(3)}" style="display:inline-block;background:var(--card);
      border:5px solid var(--ink);padding:14px 30px;border-radius:16px;font-family:MontserratX,sans-serif;
      font-weight:900;font-size:44px;color:var(--ink);margin:0 10px;transform:rotate(${i % 2 ? 1 : -1}deg)">${esc(s)}</span>`).join('');
  return `
  <div class="skb-scene" style="align-items:center;text-align:center;padding-top:240px">
    <div class="tech" data-anim="fade" data-at="${t.toFixed(3)}" style="align-self:center"><span class="dash"></span><span class="lbl">Финал</span></div>
    ${headline(scene, ctx, { size: 92, at: t + 0.25 })}
    <div style="margin-top:80px">${mini}</div>
    <div class="cta-big" data-anim="stamp" data-at="${(t + 2.6).toFixed(3)}" style="margin-top:90px;background:var(--yellow);
      border:6px solid var(--ink);border-radius:38px 240px 34px 225px / 225px 34px 240px 38px;
      padding:44px 90px;font-family:MontserratX,sans-serif;font-weight:900;font-size:96px;color:var(--ink);
      box-shadow:var(--shadow-cta);transform:rotate(-1.5deg)">СОХРАНИ</div>
    <div data-anim="fade" data-at="${(t + 3.4).toFixed(3)}" style="margin-top:90px;font-family:JBMonoX,monospace;
      font-weight:700;font-size:36px;letter-spacing:.1em;color:var(--card);background:var(--ink);
      padding:16px 34px;border-radius:16px;transform:rotate(-.8deg)">${esc(handle)}</div>
    ${captionWords(scene, ctx)}
  </div>`;
}
