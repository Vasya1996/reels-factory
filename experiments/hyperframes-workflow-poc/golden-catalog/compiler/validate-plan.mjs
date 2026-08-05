#!/usr/bin/env node
/**
 * Валидатор edit_plan.json — правила из NEXT-SESSION.md / TZ-STAGE-A.md +
 * "Правила вкуса v3" (фидбек Юлии по ai-skills-poc.mp4, итерация 2).
 *
 * Запуск: node compiler/validate-plan.mjs [путь/к/edit_plan.json]
 * По умолчанию: project-skills/edit_plan.json (word-timings.json ищется
 * в той же папке).
 *
 * Правила (старые, NEXT-SESSION.md / TZ-STAGE-A.md):
 *  1. avatar-first: лицо ≥50% хронометража; непрерывные отрезки БЕЗ лица
 *     (avatar_direction === "hidden", соседние такие сцены суммируются)
 *     — каждый отрезок ≤4с.
 *  2. Разнообразие блоков: один block ≤2 раза за ролик; соседние сцены —
 *     разные block.
 *  3. Дубль headline vs субтитры сцены: >60% слов headline встречаются в
 *     speech сцены — FAIL. Пул из 0-1 слова — исключение. (Область сузили
 *     до headline в этой итерации — labels теперь ОБЯЗАНЫ содержать слова
 *     речи по правилу v3 №5, дальше см. why в rule-5-source ниже.)
 *  4. emphasis_words: ровно 1 слово на сцену, встречается в речи сцены.
 *  5. content-fit: по паспорту блока (BLOCK_PASSPORTS ниже).
 *  6. Переходы: transition_in есть у каждой сцены; primary ≥60% смен;
 *     акценты суммарно ≤2 за ролик.
 *
 * Правила v3 (новые, этот файл — реализация):
 *  v3-1. Хук-заголовок не абстракция — эвристикой не проверяется (это
 *        творческая оценка), но headline хука (первой сцены) обязан либо
 *        отсутствовать, либо не входить в META_WORDS (см. v3-3).
 *  v3-2. Хук — строго avatarFullscreen (не bubble/frame). Плюс WARN, если
 *        суммарный fullscreen-avatar сильно уходит от ориентира ~20%.
 *  v3-3. Никаких мета-слов в headline: чёрный список категорийных слов
 *        (ПЕРСОНАЛИЗАЦИЯ, МАСШТАБ, РЕШЕНИЕ, ...) — FAIL. Реальная нумерация
 *        глав («ВОПРОС 01», «ШАГ 2») разрешена явно.
 *  v3-4. trigger_word_index у каждого label (кроме EXEMPT_BLOCKS) — есть,
 *        целое число, входит в диапазон слов сцены. Тайминг data-at
 *        компилятор строит именно от него (см. blocks.mjs triggerAt) —
 *        валидатор проверяет план ДО компиляции, поэтому проверяет только
 *        структурную корректность trigger_word_index, а не сам итоговый
 *        data-at (тот гарантированно ≥ времени слова по построению).
 *  v3-5. Источник: у каждого label (кроме EXEMPT_BLOCKS) хотя бы одно
 *        содержательное (не стоп-)слово текста буквально встречается в
 *        речи ИМЕННО ЭТОЙ сцены — или является числом-эквивалентом
 *        произнесённого числительного (один→1, и т.д.).
 *
 * Правила v4 (новые, фидбек Юлии 2026-08-03, итерация 2):
 *  v4-1. Сцена не простаивает: первое крупное событие сцены (первый
 *        trigger_word_index среди labels, не-EXEMPT блоки) должно наступать
 *        не позже чем через 1.2с после scene.start. Субтитры (captionWords)
 *        событием не считаются. Сцены без labels с trigger_word_index (только
 *        headline или EXEMPT_BLOCKS) не проверяются — там нет "ожидания".
 *  v4-2. TRUE fullscreen: блоки avatarFullscreen/avatarFullscreenCta теперь
 *        рендерят видео на весь кадр 1080×1920 без бумаги/рамки/капсулы
 *        (см. blocks.mjs). Минимум 2 такие сцены за ролик, хук — обязательно
 *        одна из них (проверка хука — см. v3-2 выше, она уже требует
 *        avatarFullscreen на s01). Ориентир по суммарному времени (~20%)
 *        остаётся WARN, как в v3-2.
 *
 * EXEMPT_BLOCKS (phoneCase, avatarFullscreenCta) — labels там не пересказ
 * речи по жанру (вымышленный кейс-диалог / @handle из брифа), поэтому v3-4
 * и v3-5 к ним не применяются; labels остаются обычными строками, а не
 * {text, trigger_word_index}.
 */
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const planPath = resolve(process.argv[2] || join(here, '..', 'project-skills', 'edit_plan.json'));
const timingsPath = join(dirname(planPath), 'word-timings.json');

const plan = JSON.parse(readFileSync(planPath, 'utf8'));
const timings = JSON.parse(readFileSync(timingsPath, 'utf8'));
const words = timings.words;

const clean = s => String(s ?? '').toLowerCase().replace(/[^a-zа-яё0-9]/gi, '');
const splitWords = s => String(s ?? '').split(/\s+/).map(clean).filter(Boolean);

const STOPWORDS = new Set([
  'и','в','на','с','со','по','из','для','что','как','а','но','или','это',
  'то','же','ли','бы','не','к','у','о','об','от','до','при','за','над',
  'под','через','такие','этого','эта','эти','этот',
]);

const NUMBER_WORDS = {
  ноль: '0', один: '1', одна: '1', одно: '1', два: '2', две: '2', три: '3',
  четыре: '4', пять: '5', шесть: '6', семь: '7', восемь: '8', девять: '9',
  десять: '10',
};

/** Правило v3 №3: категорийные мета-слова, описывающие СЦЕНУ, а не
 *  говорящие со зрителем. Тест из NEXT-SESSION.md: «сказала бы ведущая это
 *  слово зрителю в лицо?» / «понятно ли оно без контекста сцены?». */
const META_WORDS = new Set([
  'персонализация', 'масштаб', 'решение', 'примеры', 'кейс', 'итог',
  'ответ', 'ответы', 'объяснение', 'демонстрация', 'вывод', 'заключение',
]);
/** Исключение v3 №3: реальная нумерация глав разрешена явно. */
const CHAPTER_NUMBERING_RE = /^(вопрос|шаг|глава|часть|этап)\s*\d+/iu;

/** Блоки, чьи labels — не пересказ речи по жанру (см. шапку файла). */
const EXEMPT_BLOCKS = new Set(['phoneCase', 'avatarFullscreenCta']);

/** Паспорта блоков — что и сколько можно класть в labels (используются
 *  здесь и должны быть зеркалом prompts/visual-director.md). */
export const BLOCK_PASSPORTS = {
  statNumber: { maxLabels: 1, maxLabelLen: 12, note: 'labels[0] — цифра или короткое слово из речи (гигантский стикер), ≤12 символов' },
  avatarFullscreen: { maxLabels: 0, note: 'нет labels, только headline (хук — часто и без headline тоже)' },
  avatarFullscreenCta: { maxLabels: 1, maxLabelLen: 24, labelRule: 'handle', note: 'labels[0] — @handle (обычная строка, не {text,trigger})' },
  avatarBubble: { maxLabels: 3, maxLabelLen: 28, note: 'короткие пункты-пилюли рядом с ведущей' },
  complexityCloud: { maxLabels: 6, maxLabelLen: 16, note: 'облако слов-стикеров вокруг лица, каждое слово — одно короткое понятие из речи' },
  phoneCase: { minLabels: 2, maxLabels: 4, maxLabelLen: 60, labelRule: 'chat-lines', note: 'реплики переписки по очереди слева/справа, придуманный кейс — обычные строки, не {text,trigger}' },
  beforeAfter: { minLabels: 2, maxLabels: 2, maxLabelLen: 28, note: 'ровно 2 labels: [было, стало]' },
  checklistStrike: { maxLabels: 3, maxLabelLen: 28, note: 'пункты, которые зачёркиваются по очереди' },
  chapterGhost: { maxLabels: 3, maxLabelLen: 28, note: 'пункты главы под гигантской полупрозрачной цифрой' },
  sequenceFlow: { maxLabels: 3, maxLabelLen: 28, note: 'шаги стрелкой вниз' },
  progressiveText: { maxLabels: 3, maxLabelLen: 28, note: 'крупные строки друг под другом' },
  ctaPillWord: { maxLabels: 4, maxLabelLen: 28, note: 'мини-пилюли шагов + @handle одной из labels' },
  taskList: { maxLabels: 6, maxLabelLen: 28, note: 'пункты-чеклист с галочкой ✓ — для позитивных перечислений/«уже сделано», не для боли/перегруза (см. complexityCloud)' },
};

/** Правило v5 №10 (NEXT-SESSION.md): лимит "блок ≤2 раза" — только для
 *  графических блоков. TRUE-fullscreen аватар — базовое состояние ролика,
 *  может повторяться сколько угодно. */
const DIVERSITY_UNLIMITED_BLOCKS = new Set(['avatarFullscreen', 'avatarFullscreenCta']);

/** Правило v5 №13: простой ≤1.2с действует и ВНУТРИ блока — для сцен, где
 *  первое видимое событие не привязано к trigger_word_index (EXEMPT_BLOCKS
 *  или блок без labels), а зашито в blocks.mjs фиксированным офсетом от
 *  scene.start. Держать синхронно с реальными data-at в blocks.mjs.
 *  null — у блока нет собственного гарантированного события (только
 *  headline/аватар/субтитры, ни один не в счёт правила 6). */
const BLOCK_BASE_OFFSET_SEC = {
  avatarFullscreenCta: 0.9, // handle-стемп (headline, если есть, ещё раньше — 0.45)
  phoneCase: 0.5,           // рамка телефона (headline, если есть, — 0.2)
  avatarFullscreen: null,
  avatarBubble: null,
  complexityCloud: null,
  statNumber: null,
  beforeAfter: null,
  taskList: null,
};

const findings = [];
const fail = (sid, rule, msg) => findings.push({ sid, rule, level: 'FAIL', msg });
const warn = (sid, rule, msg) => findings.push({ sid, rule, level: 'WARN', msg });

function sceneWords(scene) {
  return words.filter(w => w.index >= scene.word_start && w.index <= scene.word_end);
}

/** Текст label независимо от формы: {text,...} (обычные блоки) или
 *  голая строка (EXEMPT_BLOCKS, handle). */
const labelText = l => (typeof l === 'object' && l !== null ? l.text : l) ?? '';

/* ---------- 1. avatar-first ---------- */
{
  const total = plan.duration_seconds;
  let visibleTime = 0;
  let hiddenRun = 0;
  let prevHidden = false;
  for (const s of plan.scenes) {
    const dur = s.end - s.start;
    const hidden = s.avatar_direction === 'hidden';
    if (!hidden) visibleTime += dur;
    if (hidden) {
      hiddenRun = prevHidden ? hiddenRun + dur : dur;
      if (hiddenRun > 4.0001) {
        fail(s.scene_id, 'avatar-first',
          `непрерывный отрезок без лица ${hiddenRun.toFixed(2)}с (>4с)` +
          (prevHidden ? ' — продолжает предыдущую сцену без лица (подряд)' : ''));
      }
    }
    prevHidden = hidden;
  }
  const share = visibleTime / total;
  if (share < 0.5) {
    fail('*', 'avatar-first', `лицо в кадре ${(share * 100).toFixed(1)}% хронометража (<50%)`);
  }
}

/* ---------- 2. разнообразие блоков ---------- */
{
  const counts = {};
  for (const s of plan.scenes) counts[s.block] = (counts[s.block] || 0) + 1;
  for (const [block, n] of Object.entries(counts)) {
    if (n > 2 && !DIVERSITY_UNLIMITED_BLOCKS.has(block)) {
      fail('*', 'diversity', `блок "${block}" использован ${n} раз (>2 за ролик)`);
    }
  }
  for (let i = 1; i < plan.scenes.length; i++) {
    const a = plan.scenes[i - 1], b = plan.scenes[i];
    if (a.block === b.block) {
      fail(b.scene_id, 'diversity', `соседняя сцена ${a.scene_id} использует тот же блок "${a.block}"`);
    }
  }
}

/* ---------- v3-2. хук строго fullscreen + ориентир по времени ---------- */
{
  const hook = plan.scenes[0];
  if (hook.purpose === 'hook' || hook.scene_id === plan.scenes[0].scene_id) {
    if (hook.block !== 'avatarFullscreen') {
      fail(hook.scene_id, 'v3-hook-fullscreen',
        `хук использует блок "${hook.block}" — правило v3 №2 требует строго avatarFullscreen (не bubble/frame)`);
    }
  }
  const fsTime = plan.scenes
    .filter(s => s.block === 'avatarFullscreen' || s.block === 'avatarFullscreenCta')
    .reduce((sum, s) => sum + (s.end - s.start), 0);
  const fsShare = fsTime / plan.duration_seconds;
  if (fsShare < 0.10 || fsShare > 0.35) {
    warn('*', 'v3-hook-fullscreen',
      `fullscreen-аватар ${(fsShare * 100).toFixed(1)}% хронометража — далеко от ориентира v3 №2 (~20%)`);
  }

  // v4-2: минимум 2 TRUE-fullscreen сцены за ролик (правило v4 №7).
  const fsScenes = plan.scenes.filter(s => s.block === 'avatarFullscreen' || s.block === 'avatarFullscreenCta');
  if (fsScenes.length < 2) {
    fail('*', 'v4-fullscreen-count',
      `TRUE-fullscreen сцен всего ${fsScenes.length} (avatarFullscreen/avatarFullscreenCta) — правило v4 №7 требует ≥2 за ролик`);
  }
}

/* ---------- v4-1 / v5-13. сцена не простаивает (≤1.2с до первого события,
   в т.ч. внутри блока для EXEMPT_BLOCKS / сцен без labels) ---------- */
for (const s of plan.scenes) {
  const triggerIdxs = EXEMPT_BLOCKS.has(s.block) ? [] : (s.content.labels || [])
    .map(l => (typeof l === 'object' && l !== null ? l.trigger_word_index : null))
    .filter(Number.isInteger);

  if (triggerIdxs.length) {
    const firstIdx = Math.min(...triggerIdxs);
    const w = words.find(x => x.index === firstIdx);
    if (w) {
      const idle = w.start - s.start;
      if (idle > 1.2001) {
        fail(s.scene_id, 'v4-idle',
          `первое событие сцены (label) наступает через ${idle.toFixed(2)}с после начала (>1.2с, правило v4 №6) — ` +
          `сдвинуть границу сцены к первому trigger_word_index или отдать освободившееся время предыдущей сцене/fullscreen-аватару`);
      }
    }
    continue;
  }

  // Нет label-события (EXEMPT_BLOCKS или labels=[]) — проверяем собственный
  // офсет блока (правило v5 №13): headline не в счёт (если он есть, событие
  // ещё раньше офсета).
  const baseOffset = BLOCK_BASE_OFFSET_SEC[s.block];
  if (baseOffset != null && baseOffset > 1.2001) {
    fail(s.scene_id, 'v4-idle',
      `собственный первый элемент блока "${s.block}" зашит на +${baseOffset}с от начала сцены (>1.2с, правило v5 №13) — поправить тайминг в blocks.mjs`);
  }
}

/* ---------- 3/4/5/v3-3/v3-4/v3-5 — по сценам ---------- */
for (const s of plan.scenes) {
  const speechWords = new Set(sceneWords(s).map(w => clean(w.text)));
  const passport = BLOCK_PASSPORTS[s.block];
  const exempt = EXEMPT_BLOCKS.has(s.block);

  if (!passport) {
    warn(s.scene_id, 'content-fit', `нет паспорта для блока "${s.block}" — пропущена проверка content-fit`);
  } else {
    const labels = s.content.labels || [];
    if (passport.maxLabels != null && labels.length > passport.maxLabels) {
      fail(s.scene_id, 'content-fit', `labels: ${labels.length} шт (> ${passport.maxLabels} по паспорту "${s.block}")`);
    }
    if (passport.minLabels != null && labels.length < passport.minLabels) {
      fail(s.scene_id, 'content-fit', `labels: ${labels.length} шт (< ${passport.minLabels} по паспорту "${s.block}")`);
    }
    if (passport.labelRule === 'handle') {
      const v = labelText(labels[0]);
      if (v && !v.startsWith('@')) fail(s.scene_id, 'content-fit', `avatarFullscreenCta labels[0]="${v}" — не похоже на @handle`);
    } else if (passport.maxLabelLen != null) {
      labels.forEach((l, i) => {
        const v = labelText(l);
        if (v.length > passport.maxLabelLen) {
          fail(s.scene_id, 'content-fit', `labels[${i}]="${v}" длиннее ${passport.maxLabelLen} символов (${v.length})`);
        }
      });
    }
  }

  // v3-4 / v3-5: trigger_word_index + источник (только не-exempt блоки)
  if (!exempt) {
    (s.content.labels || []).forEach((l, i) => {
      if (typeof l !== 'object' || l === null || typeof l.text !== 'string') {
        fail(s.scene_id, 'v3-source', `labels[${i}] не в формате {text, trigger_word_index} — блок "${s.block}" не в EXEMPT_BLOCKS`);
        return;
      }
      const idx = l.trigger_word_index;
      if (!Number.isInteger(idx)) {
        fail(s.scene_id, 'v3-trigger', `labels[${i}]="${l.text}" — нет целочисленного trigger_word_index`);
      } else if (idx < s.word_start || idx > s.word_end) {
        fail(s.scene_id, 'v3-trigger', `labels[${i}]="${l.text}" — trigger_word_index=${idx} вне диапазона слов сцены [${s.word_start}, ${s.word_end}]`);
      }
      const contentWords = splitWords(l.text).filter(w => !STOPWORDS.has(w));
      const sourced = contentWords.some(w => {
        if (speechWords.has(w)) return true;
        // цифра-label ("1") может быть числом-эквивалентом произнесённого слова
        for (const [word, digit] of Object.entries(NUMBER_WORDS)) {
          if (w === digit && speechWords.has(word)) return true;
        }
        return false;
      });
      if (contentWords.length > 0 && !sourced) {
        fail(s.scene_id, 'v3-source',
          `labels[${i}]="${l.text}" — ни одно содержательное слово не звучит в речи этой сцены (правило v3 №5, "не выдумывать")`);
      }
    });
  }

  // дубль headline vs речь сцены (область сужена до headline, см. шапку файла)
  const headlineWords = splitWords(s.content.headline);
  if (headlineWords.length > 1) {
    const matched = headlineWords.filter(w => speechWords.has(w)).length;
    const ratio = matched / headlineWords.length;
    if (ratio > 0.6) {
      fail(s.scene_id, 'duplication',
        `${(ratio * 100).toFixed(0)}% слов headline совпадают со словами речи сцены (>60%): ` +
        `[${headlineWords.filter(w => speechWords.has(w)).join(', ')}]`);
    }
  }

  // v3-3: мета-слова в headline
  if (s.content.headline && !CHAPTER_NUMBERING_RE.test(s.content.headline.trim())) {
    const bad = headlineWords.filter(w => META_WORDS.has(w));
    if (bad.length) {
      fail(s.scene_id, 'v3-meta-words', `headline="${s.content.headline}" содержит мета-слово(а): ${bad.join(', ')}`);
    }
  }

  // emphasis_words
  const emph = s.content.emphasis_words || [];
  if (emph.length !== 1) {
    fail(s.scene_id, 'emphasis', `emphasis_words: ${emph.length} слов (нужно ровно 1)`);
  } else if (!speechWords.has(clean(emph[0]))) {
    fail(s.scene_id, 'emphasis', `emphasis_words[0]="${emph[0]}" не встречается в речи этой сцены`);
  }

  if (!s.transition_in) fail(s.scene_id, 'transitions', 'нет поля transition_in');
}

/* ---------- 6. переходы ---------- */
{
  const trans = plan.scenes.map(s => s.transition_in).filter(Boolean);
  if (trans.length) {
    const counts = {};
    for (const t of trans) counts[t] = (counts[t] || 0) + 1;
    const [primary, primaryN] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    const share = primaryN / trans.length;
    if (share < 0.6) {
      fail('*', 'transitions', `primary-переход "${primary}" — ${(share * 100).toFixed(0)}% смен (<60%)`);
    }
    const accents = trans.length - primaryN;
    if (accents > 2) {
      fail('*', 'transitions', `акцентных переходов (не primary) — ${accents} шт (>2 за ролик)`);
    }
  }
}

/* ---------- отчёт ---------- */
const fails = findings.filter(f => f.level === 'FAIL');
const warns = findings.filter(f => f.level === 'WARN');
const status = fails.length === 0 ? 'PASS' : 'FAIL';

console.log(`\nВалидатор плана: ${planPath}`);
console.log(`Статус: ${status}\n`);
if (findings.length === 0) {
  console.log('Нарушений не найдено.');
} else {
  for (const f of findings) {
    console.log(`[${f.level}] ${f.sid} · ${f.rule} — ${f.msg}`);
  }
}
console.log(`\nИтого: ${fails.length} FAIL, ${warns.length} WARN.`);

if (process.argv.includes('--json')) {
  console.log(JSON.stringify({ status, findings }, null, 2));
}

process.exit(fails.length === 0 ? 0 : 1);
