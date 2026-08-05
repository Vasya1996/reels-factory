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

const cleanWord = s => String(s ?? '').toLowerCase().replace(/[^a-zа-яё0-9]/gi, '');

/** Слова речи сцены → спаны caption с пословным появлением.
 *  emphasis_words (ровно 1 слово из речи сцены) получает mint-хайлайт —
 *  единственное надёжное место для этого: заголовок есть не у всех блоков
 *  (complexityCloud/phoneCase/statNumber иногда null), а субтитры есть всегда. */
function captionWords(scene, ctx, { size = 44, bottom = 120 } = {}) {
  if (scene.captions === 'hidden') return '';
  const emphSet = new Set((scene.content.emphasis_words || []).map(cleanWord));
  const spans = ctx.words.map(w => {
    const isEmph = emphSet.has(cleanWord(w.text));
    const style = isEmph
      ? ' style="background:var(--mint);padding:2px 8px;border-radius:6px;margin:0 2px"' : '';
    return `<span data-anim="cword" data-at="${w.start.toFixed(3)}"${style}>${esc(w.text)}</span>`;
  }).join(' ');
  return `<div class="hf-cap" style="position:absolute;left:50%;bottom:${bottom}px;transform:translateX(-50%);
    max-width:900px;text-align:center;font-family:MontserratX,sans-serif;font-weight:900;font-size:${size}px;
    text-transform:uppercase;color:var(--ink);background:var(--card);border:5px solid var(--ink);
    padding:18px 34px;box-shadow:6px 8px 0 rgba(27,27,24,.16);border-radius:20px;line-height:1.35">${spans}</div>`;
}

/** Видео-тег аватара, совместимый с реальным HyperFrames-рендерером.
 *
 *  ВАЖНО (lint: video_nested_in_timed_element): <video> не может быть
 *  вложен ни в один элемент с data-start (в т.ч. в саму секцию сцены) —
 *  "framework cannot manage playback of nested media, video будет
 *  FROZEN в рендере". Поэтому видео НЕ встраивается внутрь HTML сцены —
 *  compile.mjs собирает его в отдельный массив и кладёт ПРЯМЫМ потомком
 *  #root (рядом с секциями .clip), с абсолютным позиционированием
 *  1080×1920, вычисленным заранее под каждый слот (см. вызовы ниже).
 *  По той же причине здесь нет data-anim/fade-появления — .clip
 *  видимостью управляет только фреймворк (determinism-rules.md).
 *
 *  class="clip" + data-start/data-duration/data-media-start/data-track-index
 *  (playback владеет фреймворк, никакого play()/pause()/currentTime из JS).
 *  Один и тот же непрерывный дубль — глобальное время сцены === смещение
 *  в исходнике, поэтому data-media-start = data-start.
 *  Трек 2 зарезервирован под все avatar-video (сцены не пересекаются по
 *  времени, поэтому им можно безопасно делить один трек). */
function avatarVideoTag(scene, { style, objectPosition = '50% 50%' }) {
  const dur = (scene.end - scene.start).toFixed(3);
  return `<video id="av-${scene.scene_id}" class="clip avatar-video" data-start="${scene.start.toFixed(3)}" data-duration="${dur}"
      data-media-start="${scene.start.toFixed(3)}" data-track-index="2"
      muted playsinline preload="auto" src="assets/avatar.mp4"
      style="position:absolute;${style};object-fit:cover;object-position:${objectPosition};display:block"></video>`;
}

const CANVAS_W = 1080, CANVAS_H = 1920;

/** Мини-PiP аватара (по образцу G17 pip_screencast) — используется в блоках,
 *  где основной слот занят другим контентом (телефон, было/стало), чтобы
 *  лицо не пропадало из кадра дольше 4с (правило avatar-first).
 *  ВАЖНО: рендерер позиционирует video по left/top — right/bottom он не
 *  учитывает (проверено на снапшотах, видео уезжало в left:0;top:0), поэтому
 *  right/bottom из параметров пересчитываются в left/top здесь. */
function avatarPip(scene, { top, bottom, right = 64, size = 220 } = {}) {
  const left = CANVAS_W - right - size;
  const topPx = top != null ? top : CANVAS_H - bottom - size;
  return avatarVideoTag(scene, {
    style: `left:${left}px;top:${topPx}px;width:${size}px;height:${size}px;border-radius:50%;
      border:6px solid var(--ink);box-shadow:var(--shadow-card);transform:rotate(-1.2deg);z-index:5`,
    objectPosition: '50% 20%',
  });
}

/** Правило v3 №4: графика подтверждает сказанное слово, появляется ПОСЛЕ
 *  него (допуск 0…+0.4с). trigger_word_index — глобальный индекс слова
 *  (тот же, что в word-timings.json); offset держим в начале допуска. */
function triggerAt(ctx, triggerWordIndex, offset = 0) {
  const w = ctx.words.find(x => x.index === triggerWordIndex);
  if (!w) throw new Error(`triggerAt: word index ${triggerWordIndex} not found in scene words`);
  return w.start + offset;
}

function tech(label, at) {
  if (!label) return '';
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
  const item = scene.content.labels?.[0];
  const rawLabel = (typeof item === 'object' ? item?.text : item) ?? '';
  const label = esc(rawLabel);
  const at = (typeof item === 'object' && item.trigger_word_index != null)
    ? triggerAt(ctx, item.trigger_word_index) : t + 0.35;
  // Ширина холста — 1080px, доступно под текст стикера ~900px. При 220px
  // 9-буквенное "БЕСПЛАТНО" вылезало за оба края (проверено на снапшоте:
  // видно только "ЕСПЛАТН") — 220px держит лишь ≤4 символа ("0 ₽").
  // Дальше — деление по длине под реальную ширину буквы Montserrat-900.
  const len = rawLabel.length;
  const fontSize = len <= 1 ? 460 : len <= 4 ? 220 : len <= 6 ? 150 : len <= 9 ? 108 : 84;
  const padding = len <= 1 ? '10px 80px' : len <= 4 ? '30px 70px' : '26px 40px';
  const html = `
  <div class="skb-scene" style="align-items:center;text-align:center;justify-content:center">
    ${tech(ctx.label, t)}
    <div class="bignum" data-anim="stamp" data-at="${at.toFixed(3)}"
      style="margin-top:40px;background:var(--yellow);border:8px solid var(--ink);white-space:nowrap;
      border-radius:38px 240px 34px 225px / 225px 34px 240px 38px;padding:${padding};
      font-family:MontserratX,sans-serif;font-weight:900;font-size:${fontSize}px;line-height:1;color:var(--ink);
      box-shadow:14px 16px 0 var(--ink);transform:rotate(-2deg)">${label}</div>
    ${headline(scene, ctx, { size: 74, at: t + 0.9 })}
    ${captionWords(scene, ctx)}
  </div>`;
  return { html, video: null };
}

/** G01 avatar_editorial_bubble — аватар в рамке + пункты.
 *  Текстовая колонка — фиксированной ширины (526px, не flex:1): справа от
 *  неё поверх сцены отдельно накладывается видео 340×860 (см. video ниже),
 *  раньше стоявшее рядом во flex-ряду как flex:none сосед. */
export function avatarBubble(scene, ctx, { sticker } = {}) {
  const t = scene.start;
  const pts = (scene.content.labels || []).map((l, i) => `
    <div class="pill r${(i % 3) + 1}" style="--rot:${i % 2 ? '.5deg' : '-.6deg'}"
      data-anim="card" data-at="${triggerAt(ctx, l.trigger_word_index).toFixed(3)}">
      <span class="idx">0${i + 1}</span><span class="txt">${esc(l.text.toLowerCase())}</span></div>`).join('');
  const html = `
  <div class="skb-scene">
    ${tech(ctx.label, t)}
    ${sticker ? `<div class="sticker" data-anim="stamp" data-at="${(t + 0.3).toFixed(3)}" style="font-size:110px">${esc(sticker)}</div>` : ''}
    <div style="margin-top:30px;width:526px">
      ${headline(scene, ctx, { size: 86, at: t + 0.45 })}
      <div style="display:flex;flex-direction:column;gap:30px;margin-top:56px">${pts}</div>
    </div>
    ${captionWords(scene, ctx)}
  </div>`;
  // right:84 → left = 1080-84-340 = 656 (рендерер учитывает только left/top).
  const video = avatarVideoTag(scene, {
    style: 'left:656px;top:236px;width:340px;height:860px;border-radius:170px 34px 170px 38px / 38px 170px 34px 170px;border:6px solid var(--ink);box-shadow:var(--shadow-card);z-index:1',
    objectPosition: '50% 20%',
  });
  return { html, video };
}

/** G13 complexity_cloud — слова-стикеры вокруг аватара (аватар в кадре). */
export function complexityCloud(scene, ctx) {
  const t = scene.start;
  const defaultWords = [
    { text: 'воронки', trigger_word_index: null }, { text: 'приёмы', trigger_word_index: null },
    { text: 'скрипты', trigger_word_index: null }, { text: 'триггеры', trigger_word_index: null },
    { text: 'прогревы', trigger_word_index: null }, { text: 'фразы', trigger_word_index: null },
  ];
  const cloudWords = (scene.content.labels && scene.content.labels.length ? scene.content.labels : defaultWords).slice(0, 6);
  const pos = [
    'left:20px;top:16%;--rot:-3deg','right:30px;top:22%;--rot:2deg',
    'left:40px;top:44%;--rot:1.5deg','right:20px;top:50%;--rot:-2deg',
    'left:30px;top:72%;--rot:2.5deg','right:50px;top:76%;--rot:-1.5deg'];
  const cls = ['','y','m','','y','m'];
  const clouds = cloudWords.map((l, i) => {
    const at = l.trigger_word_index != null ? triggerAt(ctx, l.trigger_word_index) : t + 0.9 + i * 0.45;
    return `
    <div class="cloudw ${cls[i]}" data-anim="pop" data-at="${at.toFixed(3)}"
      style="position:absolute;${pos[i]};background:var(${cls[i]==='y'?'--yellow':cls[i]==='m'?'--mint':'--card'});
      border:5px solid var(--ink);padding:20px 32px;font-size:40px;font-weight:600;color:var(--ink);
      box-shadow:6px 8px 0 rgba(27,27,24,.15);white-space:nowrap;transform:rotate(var(--rot))">${esc(l.text)}</div>`;
  }).join('');
  const html = `
  <div class="skb-scene" style="padding:118px 60px 104px">
    ${tech(ctx.label, t)}
    ${headline(scene, ctx, { size: 84, at: t + 0.3 })}
    <div style="position:relative;flex:1;margin-top:30px">
      ${clouds}
    </div>
    ${captionWords(scene, ctx)}
  </div>`;
  const video = avatarVideoTag(scene, {
    style: 'left:310px;top:564px;width:460px;height:680px;border-radius:230px 230px 180px 180px / 300px 300px 140px 140px;border:6px solid var(--ink);box-shadow:var(--shadow-card);z-index:1',
    objectPosition: '50% 15%',
  });
  return { html, video };
}

/** G11 checklist_strike — пункты зачёркиваются. */
export function checklistStrike(scene, ctx) {
  const t = scene.start;
  const items = scene.content.labels || [];
  const rows = items.map((l, i) => `
    <div class="pill r${(i % 3) + 1} strike" style="--rot:${i % 2 ? '.6deg' : '-.7deg'}"
      data-anim="card" data-at="${(t + 0.7 + i * 1.0).toFixed(3)}" data-strike-at="${(t + 1.35 + i * 1.0).toFixed(3)}">
      <u></u><span class="idx">0${i + 1}</span><span class="txt">${esc(l.toLowerCase())}</span></div>`).join('');
  const html = `
  <div class="skb-scene">
    ${tech(ctx.label, t)}
    ${headline(scene, ctx, { size: 92, at: t + 0.2 })}
    <div style="display:flex;flex-direction:column;gap:40px;margin-top:90px">${rows}</div>
    ${captionWords(scene, ctx)}
  </div>`;
  return { html, video: null };
}

/** G15 big_ghost_number + пункты (главы 1/2/3). */
export function chapterGhost(scene, ctx, { num }) {
  const t = scene.start;
  const pts = (scene.content.labels || []).map((l, i) => `
    <div class="pill r${(i % 3) + 1}" style="--rot:${i % 2 ? '.5deg' : '-.6deg'}"
      data-anim="card" data-at="${(t + 1.1 + i * 0.9).toFixed(3)}">
      <span class="idx">0${i + 1}</span><span class="txt">${esc(l.toLowerCase())}</span></div>`).join('');
  const html = `
  <div class="skb-scene">
    <div data-anim="stamp" data-at="${(t + 0.4).toFixed(3)}" style="position:absolute;right:-40px;top:44%;
      font-family:MontserratX,sans-serif;font-weight:900;font-size:820px;line-height:1;color:transparent;
      -webkit-text-stroke:8px rgba(27,27,24,.2);transform:translateY(-50%)">${num}</div>
    ${tech(ctx.label, t)}
    ${headline(scene, ctx, { size: 100, at: t + 0.3 })}
    <div style="display:flex;flex-direction:column;gap:36px;margin-top:90px;position:relative">${pts}</div>
    ${captionWords(scene, ctx)}
  </div>`;
  return { html, video: null };
}

/** G12 before_after — было/стало. Мини-PiP аватара сверху справа: заголовок
 *  здесь обычно null (карточка сама показывает контраст), поэтому верхний
 *  правый угол свободен и не конфликтует с текстом. */
export function beforeAfter(scene, ctx) {
  const t = scene.start;
  const [before, after] = scene.content.labels;
  // Реплики-бэйджи «КАЖЕТСЯ»/«НА САМОМ ДЕЛЕ» и хвостик-«✗» — декоративная
  // обвязка, не сами факты; держатся коротким смещением от карточки, а не
  // от отдельного триггер-слова. Сами карточки (before/after) стартуют от
  // trigger_word_index своего label (правило v3 №4).
  // Слово-триггер «after» может по случайности звучать РАНЬШЕ слова-триггера
  // «before» в самой фразе (как в s07: «настроил» сказано раньше, чем «...не
  // объясняешь», хотя визуально after должен появиться ПОСЛЕ before) —
  // подстраховка, а не полагаться на порядок слов в конкретном сценарии.
  // Зазор небольшой (0.5с, не classic 1.2с): если trigger-слово попадает
  // ближе к концу сцены, на полную раскадровку before→after может не
  // остаться времени — сцена всё равно обрежется по data-duration.
  const beforeAt = triggerAt(ctx, before.trigger_word_index);
  const afterAt = Math.max(triggerAt(ctx, after.trigger_word_index), beforeAt + 0.5);
  const html = `
  <div class="skb-scene">
    ${tech(ctx.label, t)}
    ${headline(scene, ctx, { size: 92, at: t + 0.2 })}
    <div data-anim="fade" data-at="${(beforeAt - 0.2).toFixed(3)}" style="align-self:flex-start;background:var(--ink);color:var(--card);
      font-family:JBMonoX,monospace;font-weight:700;font-size:28px;letter-spacing:.16em;padding:10px 24px;
      transform:rotate(-1deg);margin-top:70px">КАЖЕТСЯ</div>
    <div class="strike-card" data-anim="card" data-at="${beforeAt.toFixed(3)}" style="position:relative;background:var(--card);
      border:6px solid var(--ink);padding:52px 56px;margin-top:22px;box-shadow:var(--shadow-card);transform:rotate(-.6deg)">
      <div style="font-family:MontserratX,sans-serif;font-weight:900;font-size:84px;color:var(--ink);text-transform:uppercase">${esc(before.text)}</div>
      <div class="xmark" data-anim="tick" data-at="${(beforeAt + 0.35).toFixed(3)}" style="position:absolute;right:30px;top:-52px;
        font-family:CaveatX,cursive;font-size:170px;color:var(--red);transform:rotate(-8deg)">✗</div>
    </div>
    <div data-anim="fade" data-at="${(afterAt - 0.2).toFixed(3)}" style="align-self:flex-start;background:var(--red);color:var(--card);
      font-family:JBMonoX,monospace;font-weight:700;font-size:28px;letter-spacing:.16em;padding:10px 24px;
      transform:rotate(-1deg);margin-top:60px">НА САМОМ ДЕЛЕ</div>
    <div data-anim="stamp" data-at="${afterAt.toFixed(3)}" style="background:var(--mint);border:6px solid var(--ink);
      border-radius:38px 240px 34px 225px / 225px 34px 240px 38px;padding:60px 56px;margin-top:22px;
      box-shadow:var(--shadow-cta);transform:rotate(.9deg)">
      <div style="font-family:MontserratX,sans-serif;font-weight:900;font-size:96px;color:var(--ink);text-transform:uppercase">${esc(after.text)}</div>
    </div>
    ${captionWords(scene, ctx)}
  </div>`;
  const video = avatarPip(scene, { top: 118, right: 84, size: 210 });
  return { html, video };
}

/** G10 phone_case_overlay — переписка в мессенджере (кейс).
 *  content.labels — реплики по очереди: чётные (0,2,...) слева "клиент",
 *  нечётные (1,3,...) справа "агент/ты". Мини-PiP аватара внизу справа под
 *  телефоном — держит лицо в кадре (правило avatar-first), не перекрывает
 *  ни экран телефона, ни зону субтитров. */
export function phoneCase(scene, ctx) {
  const t = scene.start;
  const msgs = scene.content.labels || [];
  const bubbles = msgs.map((m, i) => {
    const isRight = i % 2 === 1;
    return `
    <div class="msg ${isRight ? 'in-r' : 'in-l'}" data-anim="card" data-at="${(t + 0.9 + i * 0.85).toFixed(3)}"
      style="max-width:82%;padding:24px 30px;font-size:32px;font-weight:600;line-height:1.32;color:var(--ink);
      border:5px solid var(--ink);align-self:${isRight ? 'flex-end' : 'flex-start'};
      background:${isRight ? 'var(--mint)' : 'var(--card)'};
      border-radius:${isRight ? '34px 8px 40px 34px' : '8px 34px 34px 40px'};
      box-shadow:5px 6px 0 rgba(27,27,24,.14)">${esc(m)}</div>`;
  }).join('');
  const html = `
  <div class="skb-scene">
    ${tech(ctx.label, t)}
    ${headline(scene, ctx, { size: 84, at: t + 0.2 })}
    <div data-anim="fade" data-at="${(t + 0.5).toFixed(3)}" style="width:640px;margin:36px auto 0;background:var(--card);
      border:8px solid var(--ink);border-radius:60px;padding:34px 28px;box-shadow:12px 14px 0 rgba(27,27,24,.16);
      transform:rotate(-.6deg);display:flex;flex-direction:column;gap:22px">
      <div style="width:190px;height:10px;border-radius:8px;background:var(--ink);opacity:.85;margin:0 auto 6px"></div>
      ${bubbles}
    </div>
    ${captionWords(scene, ctx)}
  </div>`;
  const video = avatarPip(scene, { bottom: 340, right: 80, size: 210 });
  return { html, video };
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
  const html = `
  <div class="skb-scene" style="justify-content:center">
    ${tech(ctx.label, t)}
    <div style="display:flex;flex-direction:column;gap:36px;margin-top:60px">${rows}</div>
    ${captionWords(scene, ctx)}
  </div>`;
  return { html, video: null };
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
  const html = `
  <div class="skb-scene">
    ${tech(ctx.label, t)}
    ${headline(scene, ctx, { size: 88, at: t + 0.15 })}
    <div style="display:flex;flex-direction:column;gap:14px;margin-top:70px">${rows}</div>
    ${captionWords(scene, ctx)}
  </div>`;
  return { html, video: null };
}

/** Скрим-градиент для TRUE fullscreen-сцен: без него tech-лейбл/заголовок
 *  (тёмный --ink) рискуют потерять контраст на светлых кадрах реального
 *  видео — раньше их держал на себе паперный фон капсулы, которого больше
 *  нет (правило v4 №7, TRUE fullscreen без бумаги/рамки). Затемнение только
 *  сверху, в зоне текста; субтитры снизу уже несут свой непрозрачный чип. */
function scrimTop(height = 420) {
  return `<div style="position:absolute;inset:0 0 auto 0;height:${height}px;
    background:linear-gradient(180deg,rgba(0,0,0,.5),rgba(0,0,0,0));pointer-events:none"></div>`;
}

/** Видео TRUE fullscreen: весь кадр 1080×1920, без border/border-radius —
 *  сам холст сцены, не "капсула на бумаге" (правило v4 №7). */
function avatarFullscreenVideo(scene) {
  return avatarVideoTag(scene, { style: 'left:0;top:0;width:1080px;height:1920px;z-index:1' });
}

/** G02 avatar_fullscreen_hook — TRUE fullscreen аватар + крупный текст.
 *  Видео покрывает весь кадр (правило v4 №7): без бумаги, без рамки/капсулы —
 *  фон сцены и есть видео; поверх только скрим + tech-лейбл/заголовок/субтитры. */
export function avatarFullscreen(scene, ctx) {
  const t = scene.start;
  const html = `
  <div class="skb-scene" style="padding:0">
    ${scrimTop()}
    <div style="position:absolute;top:110px;left:64px">${tech(ctx.label, t)}</div>
    ${scene.content.headline ? `<div style="position:absolute;left:64px;right:64px;top:210px">
      ${headline(scene, ctx, { size: 80, at: t + 0.45 })}
    </div>` : ''}
    ${captionWords(scene, ctx)}
  </div>`;
  return { html, video: avatarFullscreenVideo(scene) };
}

/** G02 avatar_fullscreen — вариант с финальным CTA-хэндлом, тоже TRUE fullscreen. */
export function avatarFullscreenCta(scene, ctx) {
  const t = scene.start;
  const handle = (scene.content.labels || [])[0] || '';
  const html = `
  <div class="skb-scene" style="padding:0">
    ${scrimTop()}
    <div style="position:absolute;top:110px;left:64px">${tech(ctx.label, t)}</div>
    <div style="position:absolute;left:64px;right:64px;top:210px">
      ${headline(scene, ctx, { size: 80, at: t + 0.45 })}
    </div>
    ${handle ? `<div data-anim="stamp" data-at="${(t + 0.9).toFixed(3)}" style="position:absolute;left:50%;bottom:400px;
      transform:translateX(-50%) rotate(-.8deg);font-family:JBMonoX,monospace;font-weight:700;font-size:36px;
      letter-spacing:.1em;color:var(--card);background:var(--ink);padding:16px 34px;border-radius:16px">${esc(handle)}</div>` : ''}
    ${captionWords(scene, ctx)}
  </div>`;
  return { html, video: avatarFullscreenVideo(scene) };
}

/** G08 task_list — позитивный чек-лист (правило вкуса №12, NEXT-SESSION.md):
 *  пункты со стикером-галочкой ✓, для перечислений «уже сделано» — не
 *  путать с complexityCloud (метафора перегруза, для боли/сложности).
 *  Мини-PiP аватара сверху справа держит лицо в кадре (avatar-first),
 *  как в phoneCase/beforeAfter — сам G08 в каталоге без аватар-слота. */
export function taskList(scene, ctx) {
  const t = scene.start;
  const pts = (scene.content.labels || []).map((l, i) => {
    const at = triggerAt(ctx, l.trigger_word_index);
    return `
    <div class="pill r${(i % 3) + 1}" style="--rot:${i % 2 ? '.5deg' : '-.6deg'}"
      data-anim="card" data-at="${at.toFixed(3)}">
      <span class="idx">0${i + 1}</span><span class="txt">${esc(l.text.toLowerCase())}</span>
      <span class="tick" data-anim="tick" data-at="${(at + 0.3).toFixed(3)}" style="color:var(--mint)">✓</span>
    </div>`;
  }).join('');
  const html = `
  <div class="skb-scene">
    ${tech(ctx.label, t)}
    ${headline(scene, ctx, { size: 88, at: t + 0.2 })}
    <div style="display:flex;flex-direction:column;gap:36px;margin-top:70px">${pts}</div>
    ${captionWords(scene, ctx)}
  </div>`;
  const video = avatarPip(scene, { top: 110, right: 64, size: 190 });
  return { html, video };
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
