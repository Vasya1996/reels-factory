#!/usr/bin/env node
/**
 * Визуальный критик (слой 4) — TZ-CRITIC.md.
 *
 * Детерминированная обвязка вокруг ОДНОГО vision-вызова (сам вызов делает
 * внешний агент/модель — этот скрипт только готовит вход и применяет выход):
 *
 *   node compiler/critic.mjs snapshot <projectDir> <round>
 *     — 2 кадра на сцену (start+0.4с и середина) через `hyperframes snapshot`
 *       на render-project/, + пакет для слепого vision-ревью
 *       (<projectDir>/critic-request-round<N>.md, БЕЗ ожидаемых находок).
 *
 *   node compiler/critic.mjs apply <projectDir> <findingsJsonPath> <round>
 *     — автокурирование (правило v5 №14): каждый fix_op (кроме report_only)
 *       пробуется на КОПИИ плана и коммитится, только если результат
 *       проходит `validate-plan.mjs` (0 FAIL — WARN не блокирует); иначе
 *       откатывается и уходит в report_only с причиной отказа валидатора.
 *       Ручное курирование не требуется. Бэкапит план до правок. Сама
 *       compile.mjs не запускает — это отдельный следующий шаг.
 *
 * Код блоков/компилятора не трогает (TZ-CRITIC.md: "код блоков/компилятора
 * в этом ТЗ не менять").
 */
import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const golden = join(here, '..');

const FIXED_CHECKLIST = `Фиксированный чек-лист (NEXT-SESSION.md, правила v3-v5). По КАЖДОЙ сцене
ответь да/нет на каждый пункт, разбирая переданные кадры (начало и середина):

1. Пустая композиция: раскладка отжала место под контент, а самого контента
   там нет. Проверяй КАЖДУЮ сцену без исключения, даже если она не выглядит
   "сломанной" на первый взгляд: мысленно оцени, какая доля кадра (на глаз,
   в процентах) не занята ни аватаром, ни текстом, ни графикой. Если пустует
   заметная часть кадра (примерно треть и больше) — это находка, даже если
   формально в раскладке "что-то есть" (например, только заголовок наверху,
   а весь остальной отведённый под контент блок — пустое поле/бумага).
   ОБЯЗАТЕЛЬНО (правило v6 №16): для этой находки fix_op обязан быть
   add_label(text, trigger_word_index), где text — ДОСЛОВНО слово/фраза из
   "Речь сцены" ниже; report_only для находки этого класса допустим ТОЛЬКО
   вместе с объяснением в поле evidence, почему ни одно слово речи сцены не
   подходит для label.
2. Текст в кадре без функции: для КАЖДОГО отдельного текстового элемента
   (заголовок, метка, тег — не субтитры) отдельно спроси: если стереть
   именно этот элемент прямо сейчас, зритель что-то теряет? Особый случай —
   одиночное слово-название в углу кадра, которое лишь называет то же самое,
   что через мгновение и так проговорят субтитры внизу: это находка, даже
   если по формальным правилам (длина, отсутствие цитаты) элемент "разрешён".
3. Мета-слова/абстрактные категории в кадре (не конкретная нумерация глав).
4. Заголовок дублирует субтитры/речь сцены (>60% слов).
5. Приём (визуальная метафора блока) противоречит смыслу речи сцены.
6. Мёртвый простой в начале сцены: на кадре "начало" (t=scene.start+0.4)
   уже видно готовое событие, но между стартом сцены и первым событием
   слишком большой воздух.
7. Fullscreen-аватар: минимум 2 сцены должны быть TRUE fullscreen (видео на
   весь кадр, без рамки/капсулы/бумаги вокруг), хук обязан быть таким.
8. Текст обрезан/вылезает за кадр/перекрыт другим элементом; субтитры легли
   на важный контент.
9. Хук (первая сцена): заголовок — суть первой фразы (или его вообще нет),
    не абстракция типа "ЗНАКОМО?".

Правило v6 №17: «графика опережает слово» НЕ проверяется — это
машинно-гарантировано компилятором (тайминги строятся из word.start,
опережение физически невозможно; 3 ложных срабатывания за 3 круга на
прошлом проекте). Чек-лист — только невычислимое: пустота кадра, функция
текста, семантика приёма, читаемость.

ВАЖНО, постоянное уточнение правила 2/4 (не путать приём с багом): если
текст label/пилюли/облака-стикера — это слово или фраза, взятая ДОСЛОВНО из
речи именно этой сцены, то появление того же слова чуть позже в субтитрах —
НЕ дубль-баг, а задуманное подтверждение сказанного (стикер стемпится, когда
слово прозвучало, субтитры донабирают его следом — это одна и та же
механика, не два независимых текста). Находка "дубль" — ТОЛЬКО когда
элемент декоративный и не несёт НИКАКОЙ второй функции (например, одиночный
заголовок-этикетка в углу, который просто называет то же самое и ничего не
добавляет). Не предлагай remove_label только потому, что слово label потом
встречается в субтитрах — это нормально для label, взятых из речи.

Выведи СТРОГИЙ JSON (без markdown, без пояснений вне JSON) — массив находок:
[{"scene_id":"sNN","rule":"<номер правила из списка выше>","evidence":"что именно видно на кадре(ах)","fix_op":"<ровно одна строка из меню>"}]

Меню fix_op (используй ТОЛЬКО эти формы, ничего своего не изобретай):
- set_block(name)
- set_headline(null|text)
- add_label(text, trigger_word_index) — текст ТОЛЬКО дословно из слов речи ИМЕННО этой сцены (см. блок "Речь сцены" ниже), trigger_word_index — индекс слова из этой же речи, откуда взят текст
- remove_label(idx)
- set_label_trigger(idx, word_index)
- move_boundary(scene, ±sec)
- set_captions(hidden|bottom)
- set_transition(name)
- report_only

Если находку нельзя починить ни одним из этих fix_op — используй "report_only".
Если находок нет вообще — верни пустой массив [].`;

const DIRECTION_FOR_BLOCK = {
  avatarFullscreen: 'fullscreen',
  avatarFullscreenCta: 'fullscreen',
  avatarBubble: 'editorial_bubble',
  complexityCloud: 'fullscreen',
  phoneCase: 'object_overlay',
  beforeAfter: 'object_overlay',
  statNumber: 'hidden',
  checklistStrike: 'hidden',
  chapterGhost: 'hidden',
  sequenceFlow: 'hidden',
  progressiveText: 'hidden',
  taskList: 'object_overlay',
};

/** Зеркало EXEMPT_BLOCKS из validate-plan.mjs: labels там — обычные строки
 *  без trigger_word_index (жанр не пересказывает речь). Нужно для
 *  add_label — знать, в каком формате пушить новый элемент. */
const EXEMPT_BLOCKS = new Set(['phoneCase', 'avatarFullscreenCta']);

function loadProject(projectDir) {
  const plan = JSON.parse(readFileSync(join(projectDir, 'edit_plan.json'), 'utf8'));
  const timings = JSON.parse(readFileSync(join(projectDir, 'word-timings.json'), 'utf8'));
  return { plan, timings, words: timings.words };
}

function sceneSpeech(scene, words) {
  return words.filter(w => w.index >= scene.word_start && w.index <= scene.word_end).map(w => w.text).join(' ');
}

/* ---------- snapshot ---------- */
function cmdSnapshot(projectDir, round) {
  const { plan, words } = loadProject(projectDir);
  const shots = []; // {scene_id, kind, at}
  for (const s of plan.scenes) {
    const startAt = Math.min(s.start + 0.4, s.end - 0.05);
    const midAt = (s.start + s.end) / 2;
    shots.push({ scene_id: s.scene_id, kind: 'start', at: Math.round(startAt * 100) / 100 });
    shots.push({ scene_id: s.scene_id, kind: 'mid', at: Math.round(midAt * 100) / 100 });
  }
  const atList = shots.map(s => s.at).join(',');
  const outDir = join(projectDir, `snapshots-round${round}`);
  mkdirSync(outDir, { recursive: true });

  console.log(`Снимаю ${shots.length} кадров (${shots.length / 2} сцен × 2) в ${outDir} ...`);
  // Windows: npx — .cmd-шим, CreateProcess не запускает его напрямую даже с
  // явным расширением (нужен cmd.exe) — отсюда shell:true. Аргументы все
  // внутренние (детерминированные числа/пути), инъекции не смысла нет.
  execFileSync('npx', ['--no-install', 'hyperframes', 'snapshot', '.', '--at', atList, '--no-end',
    '-o', resolve(outDir), '--describe', 'false'], {
    cwd: join(golden, 'render-project'),
    stdio: 'inherit',
    shell: true,
  });

  // hyperframes называет файлы frame-NN-at-<sec>s.png в порядке возрастания
  // времени: сопоставляем по отсортированному списку таймстампов.
  const files = readdirSync(outDir).filter(f => /^frame-\d+-at-.+\.png$/.test(f)).sort();
  const sortedShots = [...shots].sort((a, b) => a.at - b.at);
  if (files.length !== sortedShots.length) {
    throw new Error(`snapshot count mismatch: ${files.length} files vs ${sortedShots.length} requested timestamps`);
  }
  const manifest = sortedShots.map((s, i) => ({ ...s, file: files[i] }));
  writeFileSync(join(projectDir, `critic-manifest-round${round}.json`), JSON.stringify(manifest, null, 2) + '\n', 'utf8');

  // Пакет для слепого vision-ревью: чек-лист + план + речь по сценам +
  // список кадров. БЕЗ ожидаемых находок, без намёков.
  const sceneTable = plan.scenes.map(s => {
    const shotsForScene = manifest.filter(m => m.scene_id === s.scene_id)
      .map(m => `${m.kind}@${m.at}s → snapshots-round${round}/${m.file}`).join('; ');
    return [
      `### ${s.scene_id} (purpose: ${s.purpose}, block: ${s.block}, avatar_direction: ${s.avatar_direction}, captions: ${s.captions}, transition_in: ${s.transition_in})`,
      `- Диапазон: ${s.start.toFixed(2)}s–${s.end.toFixed(2)}s (слова ${s.word_start}-${s.word_end})`,
      `- Речь сцены: "${sceneSpeech(s, words)}"`,
      `- headline: ${JSON.stringify(s.content.headline)}`,
      `- labels: ${JSON.stringify(s.content.labels)}`,
      `- emphasis_words: ${JSON.stringify(s.content.emphasis_words)}`,
      `- Кадры: ${shotsForScene}`,
    ].join('\n');
  }).join('\n\n');

  const request = `# Визуальный критик — круг ${round} (${projectDir})

Ты смотришь на кадры смонтированного вертикального ролика (1080×1920) и
проверяешь монтаж по фиксированному чек-листу. У тебя нет доступа к прошлым
обсуждениям этого проекта — суди только по тому, что видишь на кадрах, и по
тексту речи/плана ниже.

## Чек-лист

${FIXED_CHECKLIST}

## Сцены

${sceneTable}

## Кадры

Открой файлы snapshots-round${round}/*.png (перечислены выше при каждой сцене)
через Read и посмотри на них лично, прежде чем отвечать.
`;
  writeFileSync(join(projectDir, `critic-request-round${round}.md`), request, 'utf8');
  console.log(`Пакет для vision-ревью: ${join(projectDir, `critic-request-round${round}.md`)}`);
  console.log(`Манифест кадров: ${join(projectDir, `critic-manifest-round${round}.json`)}`);
}

/* ---------- apply ---------- */
const ALLOWED_OPS = new Set([
  'set_block', 'set_headline', 'add_label', 'remove_label', 'set_label_trigger',
  'move_boundary', 'set_captions', 'set_transition', 'report_only',
]);

function parseOp(fixOp) {
  const m = /^(\w+)\((.*)\)$/.exec(String(fixOp).trim());
  if (!m) {
    if (fixOp === 'report_only') return { op: 'report_only', args: [] };
    throw new Error(`fix_op не распознан (не в форме name(args)): ${fixOp}`);
  }
  const [, op, argsStr] = m;
  if (!ALLOWED_OPS.has(op)) throw new Error(`fix_op вне меню: ${op}`);
  const args = argsStr.trim().length
    ? argsStr.split(',').map(a => a.trim())
    : [];
  return { op, args };
}

function findWordNearestTime(words, targetTime) {
  let best = words[0];
  let bestDelta = Infinity;
  for (const w of words) {
    const d = Math.abs(w.start - targetTime);
    if (d < bestDelta) { bestDelta = d; best = w; }
  }
  return best;
}

function applyFinding(plan, words, finding) {
  const scene = plan.scenes.find(s => s.scene_id === finding.scene_id);
  if (!scene) throw new Error(`сцена ${finding.scene_id} не найдена в плане`);
  const { op, args } = parseOp(finding.fix_op);

  switch (op) {
    case 'report_only':
      return { mutated: false };

    case 'set_block': {
      const name = args[0]?.replace(/^['"]|['"]$/g, '');
      scene.block = name;
      if (DIRECTION_FOR_BLOCK[name]) scene.avatar_direction = DIRECTION_FOR_BLOCK[name];
      return { mutated: true };
    }

    case 'set_headline': {
      const raw = args.join(',').trim();
      scene.content.headline = (raw === 'null' || raw === '') ? null : raw.replace(/^['"]|['"]$/g, '');
      return { mutated: true };
    }

    case 'add_label': {
      // Правило v5 №11: пустые композиции становятся ремонтопригодными —
      // текст только из слов речи ИМЕННО этой сцены (проверит
      // validate-plan.mjs v3-5 сам; здесь просто добавляем в нужном формате).
      if (args.length < 2) throw new Error(`add_label: нужно (text, trigger_word_index), получено: ${args.join(',')}`);
      const wordIndex = Number(args[args.length - 1]);
      const text = args.slice(0, -1).join(',').trim().replace(/^['"]|['"]$/g, '');
      if (!Number.isInteger(wordIndex)) throw new Error(`add_label: неверный trigger_word_index ${args[args.length - 1]}`);
      if (!text) throw new Error('add_label: пустой текст');
      if (!Array.isArray(scene.content.labels)) scene.content.labels = [];
      scene.content.labels.push(EXEMPT_BLOCKS.has(scene.block) ? text : { text, trigger_word_index: wordIndex });
      return { mutated: true };
    }

    case 'remove_label': {
      const idx = Number(args[0]);
      if (!Number.isInteger(idx)) throw new Error(`remove_label: неверный idx ${args[0]}`);
      scene.content.labels.splice(idx, 1);
      return { mutated: true };
    }

    case 'set_label_trigger': {
      const idx = Number(args[0]);
      const wordIndex = Number(args[1]);
      if (!Number.isInteger(idx) || !Number.isInteger(wordIndex)) {
        throw new Error(`set_label_trigger: неверные аргументы ${args.join(',')}`);
      }
      const label = scene.content.labels[idx];
      if (typeof label !== 'object' || label === null) {
        throw new Error(`set_label_trigger: labels[${idx}] не объект {text, trigger_word_index}`);
      }
      label.trigger_word_index = wordIndex;
      return { mutated: true };
    }

    case 'move_boundary': {
      // move_boundary(scene, ±sec) — двигает СТАРТ указанной сцены на ±sec,
      // конец предыдущей сцены сдвигается вместе с ней (контракт: сцены
      // партиционируют временную шкалу без зазоров/наложений). Границу
      // слов пересчитываем на ближайшее слово к новому времени, чтобы
      // word_start/word_end остались валидным партиционированием.
      const targetId = args[0]?.replace(/^['"]|['"]$/g, '') || finding.scene_id;
      const deltaSec = Number(args[1] ?? args[0]); // допускаем move_boundary(±sec) без явного id
      const idx = plan.scenes.findIndex(s => s.scene_id === targetId);
      if (idx <= 0) throw new Error(`move_boundary: не найдена сцена ${targetId} (или это первая сцена, двигать некуда)`);
      const target = plan.scenes[idx];
      const prev = plan.scenes[idx - 1];
      const newTime = target.start + (Number.isFinite(deltaSec) ? deltaSec : 0);
      const nearestWord = findWordNearestTime(words, newTime);
      prev.end = nearestWord.start;
      prev.word_end = Math.max(prev.word_start, nearestWord.index - 1);
      target.start = nearestWord.start;
      target.word_start = nearestWord.index;
      return { mutated: true };
    }

    case 'set_captions': {
      const value = args[0]?.replace(/^['"]|['"]$/g, '');
      scene.captions = value;
      return { mutated: true };
    }

    case 'set_transition': {
      const value = args[0]?.replace(/^['"]|['"]$/g, '');
      scene.transition_in = value;
      return { mutated: true };
    }

    default:
      throw new Error(`fix_op не поддержан: ${op}`);
  }
}

/** Прогоняет кандидат-план через validate-plan.mjs. Возвращает {pass, output}
 *  — pass=true, если 0 FAIL (WARN не блокирует, как и в самом validate-plan.mjs). */
function validateCandidate(candidatePath) {
  try {
    const output = execFileSync('node', [join(golden, 'compiler', 'validate-plan.mjs'), candidatePath], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
    });
    return { pass: true, output };
  } catch (e) {
    return { pass: false, output: `${e.stdout || ''}${e.stderr || ''}` };
  }
}

function failLinesOnly(output) {
  const lines = String(output).split('\n').filter(l => l.startsWith('[FAIL]'));
  return lines.length ? lines.join('\n') : output.trim().slice(-400);
}

/** Автокурирование (правило v5 №14): каждый fix_op пробуется на копии плана;
 *  коммитится, только если результат проходит validate-plan.mjs (0 FAIL).
 *  Иначе — откат, находка уходит в report_only с причиной отказа. Никакого
 *  ручного курирования — критерий истины один: валидатор. */
function cmdApply(projectDir, findingsPath, round) {
  const findings = JSON.parse(readFileSync(findingsPath, 'utf8'));
  if (!Array.isArray(findings)) throw new Error('findings должен быть JSON-массивом');

  const { words } = loadProject(projectDir);
  const planPath = join(projectDir, 'edit_plan.json');
  const candidatePath = join(projectDir, '.critic-candidate.json');
  const backupPath = join(projectDir, `edit_plan.before-round${round}.json`);
  writeFileSync(backupPath, readFileSync(planPath, 'utf8'), 'utf8');

  let plan = JSON.parse(readFileSync(planPath, 'utf8'));
  const applied = [];
  const rejected = []; // {..finding, reason}

  for (const f of findings) {
    if (parseOp(f.fix_op).op === 'report_only') {
      rejected.push({ ...f, reason: 'report_only (сам критик посчитал немеханизируемым)' });
      continue;
    }
    const trial = structuredClone(plan);
    try {
      applyFinding(trial, words, f);
    } catch (e) {
      rejected.push({ ...f, reason: `ошибка применения fix_op: ${e.message}` });
      continue;
    }
    writeFileSync(candidatePath, JSON.stringify(trial, null, 2) + '\n', 'utf8');
    const v = validateCandidate(candidatePath);
    if (v.pass) {
      plan = trial;
      applied.push(f);
    } else {
      rejected.push({ ...f, reason: `не прошло validate-plan.mjs:\n${failLinesOnly(v.output)}` });
    }
  }

  if (existsSync(candidatePath)) {
    try { rmSync(candidatePath); } catch { /* noop */ }
  }

  writeFileSync(planPath, JSON.stringify(plan, null, 2) + '\n', 'utf8');
  console.log(`Бэкап плана: ${backupPath}`);
  console.log(`Применено автокурированием: ${applied.length}`);
  applied.forEach(f => console.log(`  [applied] ${f.scene_id} · ${f.rule} · ${f.fix_op}`));
  console.log(`Отклонено/report_only: ${rejected.length}`);
  rejected.forEach(f => console.log(`  [rejected] ${f.scene_id} · ${f.rule} · ${f.fix_op} — ${f.reason.split('\n')[0]}`));

  writeFileSync(join(projectDir, `critic-apply-round${round}.json`), JSON.stringify({ applied, rejected }, null, 2) + '\n', 'utf8');
}

/* ---------- CLI ---------- */
const [, , cmd, ...rest] = process.argv;
if (cmd === 'snapshot') {
  const [projectDirArg, round] = rest;
  cmdSnapshot(resolve(golden, projectDirArg), round || '1');
} else if (cmd === 'apply') {
  const [projectDirArg, findingsPath, round] = rest;
  cmdApply(resolve(golden, projectDirArg), resolve(findingsPath), round || '1');
} else {
  console.error('Usage:\n  node compiler/critic.mjs snapshot <projectDir> <round>\n  node compiler/critic.mjs apply <projectDir> <findingsJsonPath> <round>');
  process.exit(1);
}
