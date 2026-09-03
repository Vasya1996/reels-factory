"""Генератор сценария рилса: ведущий раскрывает кейс по теме пользователя.

Промпт = фиксированный скелет по ролям + легенда продукта + гипотеза (тема,
тип хука, кейс; опционально insight — неочевидный факт, и facts — role->описание
видимого в видеоряде, для граундинга реплик) + стиль из factory/style-guide.md
(если есть); ответ строго JSON, валидатор проверяет роли/тайминги/обязательные
поля; при нарушениях — ретрай с описанием отклонения.

Скелет: hook / development / payoff / cta (context опционален). Хук цепляет
зрителя (не обязательно вопрос), без приветствий/экспозиции и без обращений к
ассистентам/брендам; тема звучит в первых фразах. CTA содержит ДОСЛОВНУЮ фразу
призыва из конфига (product.cta_phrase).
"""
import json
import math
import re
from pathlib import Path

from reels_factory.config import FACTORY_DIR
from reels_factory.llm import LLMRunner

ROLES_4 = ["hook", "development", "payoff", "cta"]  # предпочтительный вариант (без context)
ROLES_5 = ["hook", "context", "development", "payoff", "cta"]

HOOK_TYPES = "fail_first, clutch_save, number_shock, question_hook, before_after, insight_reveal"

# Legacy-сценарии могли содержать служебные пометки в квадратных скобках;
# при оценке длины они не считаются словами.
_TAG_RE = re.compile(r"\[[^\]\n]*\]")

WORD_LIMIT_HARD = 70   # валидатор: жёсткий предел (иначе ролик не влезет)
WORD_LIMIT_SOFT = 60   # промпт: целевой предел

# Темп речи для любой оценки длительности ДО озвучки: сколько слов писать под
# заданную длину (words_soft/words_hard ниже), сколько секунд займёт путь
# «дословно» (split_verbatim, run_verbatim_path) и перевод (bot.py step_translate).
# Раньше здесь стояли две копии одного числа (2.5) — по имени WORDS_PER_SECOND_TARGET
# и WORDS_PER_SEC, взятого из «natural speaking pace» в справке HyperFrames
# (skills/hyperframes-creative/references/narration.md:7), а не из замера ElevenLabs.
#
# Замер по 8 прод-заданиям reels-factory на 134.209.80.75 (2026-09-03; метод:
# слова/знаки сценария против длительности по последнему слову
# audio/tts/alignment.words.json, сверено с ffprobe voice_master.wav; скрипт и
# полная таблица — scratchpad/measure_tempo.py и tempo-measure.md той сессии):
#   ru (n=7): words/s p25=2.28, медиана=2.41, p75=2.59, диапазон 2.11-2.89
#   kk (n=1): 2.38 words/s — одно наблюдение, отдельную константу не заводим
# 2.5 оказалось не серединой, а верхней границей: черновой план по нему выходил
# короче факта — job e00b740b (154 слова): scenario.json (split_verbatim по
# 2.5) даёт план 59.6с, реальная озвучка (alignment) 72.8с, +22%. Цепочка
# fullscreen-окон без лица вылетала за MAX_FACE_ABSENCE_S уже после оплаты
# (editplan.py:_enforce_face_absence_chain).
#
# Берём 25-й процентиль (не медиану): оценка "слова -> секунды" должна не
# выходить короче факта чаще, чем сейчас, а не совпадать с ним в среднем —
# 25-й процентиль слева от большинства реальных темпов, поэтому estimated >=
# real в основном (5 из 7 ru-заданий; ≥75 % только вместе с kk), медиана
# давала бы промах в половине случаев. 2.28 округлено вниз до 2.2 для запаса
# и потому что 2.2 слов/с — то же число, которым HyperFrames меряет TTS-паузы
# в PR-роликах
# (skills/pr-to-video/references/story-design.md:175) — независимое
# подтверждение порядка величины на другом корпусе текстов.
#
# Открытый вопрос: язык здесь не различаем (ru и kk смешаны, en не встречался
# в выборке). Отдельная константа на kk/en не заводится — данных мало (1
# kk-задание), а плодить числа без нужды хуже, чем взять чуть неточное общее.
# Разойдётся заметно на большей выборке — тогда разводить по языку.
WORDS_PER_SEC = 2.2
MAX_SUPPORTED_DURATION_S = 90
# Верхняя граница ролика, когда target_duration_s не задан. Бот берёт её как
# длину ещё не написанного сценария: до генерации считать больше не из чего.
DEFAULT_MAX_DURATION_S = 40.0

STYLE_GUIDE_PATH = FACTORY_DIR / "style-guide.md"


class ScenarioError(Exception):
    pass


def _wordcount(text) -> int:
    return len(_TAG_RE.sub("", str(text or "")).split())


# буквенное слово (кириллица или латиница) — числа-слова ("2", "5") сюда не попадают
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")


def _theme_root(word: str) -> str:
    """Корень слова: обрезаем падежный хвост максимум на 2 буквы, но не ниже длины 3."""
    cut = max(0, min(2, len(word) - 3))
    return word[: len(word) - cut]


def _mentions_theme(text: str, *candidates) -> bool:
    """Упоминается ли тема в тексте — пословный матч по корню.

    Слова кандидата, чьего алфавита нет в тексте, несопоставимы и
    пропускаются (латинская тема при русском тексте — не провал).
    Если сопоставимых кандидатов не осталось вообще — не валим (True).
    """
    low = (text or "").lower()
    comparable = 0
    for g in candidates:
        g = str(g or "").strip()
        if not g:
            continue
        words = _WORD_RE.findall(g)
        matchable = [
            w for w in words
            if re.search(r"[а-яё]" if re.search(r"[а-яё]", w.lower()) else r"[a-z]", low)
        ]
        if not matchable:
            continue
        comparable += 1
        longest = max(matchable, key=len).lower()
        root = _theme_root(longest)
        if len(root) >= 2 and root in low:
            return True
    return comparable == 0


def _read_style_excerpt(max_chars: int = 1500) -> str:
    if not STYLE_GUIDE_PATH.exists():
        return ""
    text = STYLE_GUIDE_PATH.read_text(encoding="utf-8")
    return text[:max_chars]


def _duration_contract(hypothesis: dict | None) -> dict:
    """Legacy CLI defaults stay compatible; an explicit target scales to 90s."""
    hyp = hypothesis or {}
    raw = hyp.get("target_duration_s", hyp.get("length_s"))
    if raw in (None, ""):
        return {
            "target": 25.0,
            "minimum": 14.0,
            "maximum": DEFAULT_MAX_DURATION_S,
            "words_soft": WORD_LIMIT_SOFT,
            "words_hard": WORD_LIMIT_HARD,
            "explicit": False,
        }
    try:
        target = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("target_duration_s должен быть числом") from exc
    if not 14 <= target <= MAX_SUPPORTED_DURATION_S:
        raise ValueError(
            f"target_duration_s должен быть в диапазоне 14-"
            f"{MAX_SUPPORTED_DURATION_S}с"
        )
    tolerance = max(3.0, target * 0.12)
    return {
        "target": target,
        "minimum": max(14.0, target - tolerance),
        "maximum": min(MAX_SUPPORTED_DURATION_S, target + tolerance),
        "words_soft": max(30, round(target * WORDS_PER_SEC)),
        "words_hard": max(
            36, math.ceil(target * WORDS_PER_SEC * 1.12)
        ),
        "explicit": True,
    }


def build_prompt(hypothesis: dict) -> str:
    theme = hypothesis.get("theme", "")
    theme_spoken = hypothesis.get("theme_spoken") or theme
    hook_type = hypothesis.get("hook_type", "")
    case = hypothesis.get("case")
    insight = hypothesis.get("insight")
    facts = hypothesis.get("facts")
    legend = hypothesis.get("legend") or ""
    cta_phrase = hypothesis.get("cta_phrase") or ""
    duration = _duration_contract(hypothesis)
    target = duration["target"]
    hook_end = min(3.0, target * 0.10)
    cta_seconds = min(5.0, max(3.0, target * 0.08))
    payoff_seconds = max(5.0, target * 0.18)
    payoff_start = target - cta_seconds - payoff_seconds
    cta_start = target - cta_seconds

    persona = hypothesis.get("persona") or {}
    if not isinstance(persona, dict):
        persona = {}
    persona_desc = str(persona.get("description") or "").strip()
    speech_style = str(persona.get("speech_style") or "").strip()
    if persona_desc:
        persona_line = (
            f"Ведёт ролик: {persona_desc}. Реплики пиши под этого персонажа — "
            "живо, по делу, как в разговоре с подписчиком."
        )
        if speech_style:
            persona_line += f" Манера речи персонажа: {speech_style}."
    else:
        persona_line = (
            "Ведёт ролик ведущий: живо, по делу, как в разговоре с подписчиком."
        )

    parts = [
        "Ты — сценарист коротких вертикальных рилсов (Reels/Shorts/TikTok). "
        + persona_line
        + (f"\nЛЕГЕНДА ПРОДУКТА (контекст, не пересказывать в лоб): {legend}" if legend else ""),

        f"СКЕЛЕТ РОЛИКА (целевая длительность {target:g} секунд, допустимо "
        f"{duration['minimum']:g}-{duration['maximum']:g}с). ПРЕДПОЧИТАЙ "
        "4-БЛОЧНЫЙ ВАРИАНТ (без context) — блоки hook, development, payoff, cta "
        "по порядку. Блок context (5 блоков: hook, context, development, payoff, "
        "cta) допустим, только если реально нужна короткая доп. завязка. "
        "НИКАКОЙ ЭКСПОЗИЦИИ И САМОРЕКЛАМЫ («сегодня расскажу», «в этом видео» и "
        "т.п.) — ведущий сразу заходит в тему.\n"
        "- hook: 0-3с — цепляющая фраза, которая цепляет зрителя (НЕ обязательно "
        "вопрос, можно и утверждение), БЕЗ приветствий («привет», «здарова») и "
        "БЕЗ обращений к голосовым ассистентам и упоминаний бренда/продукта — "
        f"хук держит зрителя сам по себе; тема («{theme_spoken}») звучит в первых "
        "фразах — в самом хуке или в первой реплике ведущего в development; тип "
        "хука один из: " + HOOK_TYPES + ";\n"
        "- (опционально) context: короткая завязка сразу после хука;\n"
        "- development: ведущий раскрывает кейс — конкретика, механика, цифры;\n"
        "- payoff: результат/вывод, что сработало;\n"
        "- cta: последние ~3 секунды — призыв, ФИКСИРОВАННАЯ ФРАЗА ДОСЛОВНО: "
        f"«{cta_phrase}» (должна войти в реплику блока cta ровно этими словами).\n"
        "У ведущего реплика (speech) обязательна в КАЖДОМ блоке.\n"
        "ПАУЗЫ: у любого блока можно указать поле \"pause_after\" (секунды, 0-1) "
        "— драматургическая пауза-заморозка после блока; после хука почти всегда "
        "нужна пауза 0.4-0.6 (дать фразе повиснуть), в остальных местах — по "
        "смыслу или совсем без неё.\n"
        "В сложных словах можно ставить ударение акутом (символ U+0301 сразу "
        "после ударной гласной). Не добавляй в speech метакоманды и аудиотеги "
        "в квадратных скобках: модель Eleven Multilingual v2 их не поддерживает. "
        "Живую подачу создавай естественными разговорными формулировками.\n"
        f"ЛИМИТ РЕЧИ (критично, иначе ролик не влезет): цель — около "
        f"{duration['words_soft']} слов, жёсткий максимум "
        f"{duration['words_hard']} слов суммарно; каждое предложение — не более "
        "15 слов. Коротко и хлёстко.",

        f"ГИПОТЕЗА ДЛЯ ЭТОГО РОЛИКА: тема — {theme}, тип хука — {hook_type}."
        + (f" Кейс: {case}." if case else ""),
    ]

    if insight:
        parts.append(
            "ИНСАЙТ (неочевидный факт — тема ролика, раскрой через хук и "
            f"development): {insight}"
        )

    if facts:
        facts_lines = "\n".join(f"- {role}: {desc}" for role, desc in facts.items())
        parts.append(
            "ФАКТЫ О ВИДЕОРЯДЕ (единственное, что реально видно в кадре, по блокам):\n"
            + facts_lines + "\n"
            "ЖЁСТКОЕ ПРАВИЛО ГРАУНДИНГА: в репликах можно утверждать только то, "
            "что есть в этих фактах. Ничего не выдумывай про результаты, которых "
            "нет в кадре — если факта для блока нет, не утверждай ничего "
            "конкретного о результате в этом блоке."
        )

    style_excerpt = _read_style_excerpt()
    if style_excerpt:
        parts.append("СТИЛЬ (живой тон, без ИИ-канцелярита):\n" + style_excerpt)

    parts.append(
        "Ответь ТОЛЬКО JSON без пояснений и без markdown-ограждений, строго по схеме "
        "(предпочтительный 4-блочный вариант, без context):\n"
        '{"theme": "...", "hook_type": "...", "premise": "...", "title": "...", '
        '"broll_query": "...", "blocks": ['
        f'{{"role": "hook", "start": 0.0, "end": {hook_end:.1f}, '
        '"speech": "...", "pause_after": 0.5}, '
        f'{{"role": "development", "start": {hook_end:.1f}, '
        f'"end": {payoff_start:.1f}, "speech": "..."}}, '
        f'{{"role": "payoff", "start": {payoff_start:.1f}, '
        f'"end": {cta_start:.1f}, "speech": "..."}}, '
        f'{{"role": "cta", "start": {cta_start:.1f}, '
        f'"end": {target:.1f}, "speech": "..."}}'
        ']}\n'
        "Роли блоков — ровно hook, development, payoff, cta по порядку (или "
        "hook, context, development, payoff, cta, если context правда нужен). "
        "У КАЖДОГО блока обязателен непустой speech. "
        f"У cta speech обязан содержать дословную фразу «{cta_phrase}»."
    )

    return "\n\n".join(parts)


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        # Без куска ответа непонятно, что вообще пришло вместо сценария.
        raise ScenarioError(
            "bad json: no JSON object found in reply: "
            + repr(str(text or "").strip()[:300])
        )
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ScenarioError(f"bad json: {e}") from e


def _skill_json(runner, skill: str, payload_path, workdir, retries: int = 1) -> dict:
    """Ответ скилла -> dict; сырой ответ ложится рядом с заданием.

    Файл ответа — единственный след, по которому потом видно, что пришло
    вместо JSON. Проза вместо схемы бывает случайной, поэтому один повтор.
    """
    workdir = Path(workdir)
    last = None
    for _ in range(retries + 1):
        reply = runner.run_skill(skill, payload_path)
        (workdir / f"{skill}_reply.txt").write_text(reply or "", encoding="utf-8")
        try:
            return _extract_json(reply)
        except ScenarioError as e:
            last = e
    raise last


def validate_scenario(sc: dict, hypothesis: dict | None = None) -> list[str]:
    errs = []
    blocks = sc.get("blocks")
    if not isinstance(blocks, list):
        return ["blocks: отсутствует список блоков"]

    hyp = hypothesis or {}
    theme_spoken = hyp.get("theme_spoken")
    cta_phrase = (hyp.get("cta_phrase") or "").strip()
    product_name = (hyp.get("product_name") or "").strip()

    roles = [b.get("role") if isinstance(b, dict) else None for b in blocks]
    if roles not in (ROLES_4, ROLES_5):
        errs.append(f"roles: {roles} (нужно {ROLES_4} или {ROLES_5} по порядку)")
        return errs  # дальше по индексам полагаться нельзя

    prev_end = None
    hook_speech = ""
    development_speeches = []
    for role, block in zip(roles, blocks):
        start, end = block.get("start"), block.get("end")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (start, end)):
            errs.append(f"{role}: start/end не числа")
            continue

        if role == "hook" and start != 0:
            errs.append(f"{role}: start должен быть 0")
        if prev_end is not None and start != prev_end:
            errs.append(f"{role}: start ({start}) должен равняться end предыдущего блока ({prev_end})")
        prev_end = end

        speech = block.get("speech")
        if not speech:
            errs.append(f"{role}: пустой speech")
        if role == "development":
            development_speeches.append(speech)

        pause_after = block.get("pause_after")
        if "pause_after" in block:
            if not isinstance(pause_after, (int, float)) or isinstance(pause_after, bool) \
                    or not (0 <= pause_after <= 1):
                errs.append(f"{role}: pause_after ({pause_after!r}) должен быть числом 0..1")

        if role == "hook":
            hook_speech = speech or ""
            if product_name and product_name.lower() in (speech or "").lower():
                errs.append(
                    "hook: speech не должен упоминать продукт/бренд "
                    "(хук цепляет зрителя, к продукту — позже)"
                )

        if role == "cta":
            if cta_phrase and cta_phrase not in (speech or ""):
                errs.append(
                    f"cta: speech должен содержать дословную фразу «{cta_phrase}»"
                )

    # тема должна звучать в первых фразах — в хуке ИЛИ в любой реплике development
    first_phrases = " ".join(str(t or "") for t in [hook_speech, *development_speeches])
    if not _mentions_theme(first_phrases, sc.get("theme"), theme_spoken):
        errs.append("тема не упомянута в первых фразах (хук или development)")

    duration = _duration_contract(hyp)
    n_words = sum(_wordcount(b.get("speech", "")) for b in blocks)
    if n_words > duration["words_hard"]:
        errs.append(
            f"речь слишком длинная: {n_words} слов "
            f"(максимум {duration['words_hard']})"
        )

    total = blocks[-1].get("end") if isinstance(blocks[-1].get("end"), (int, float)) else None
    if total is not None and not (
        duration["minimum"] <= total <= duration["maximum"]
    ):
        errs.append(
            f"общая длительность {total}с вне "
            f"{duration['minimum']:g}-{duration['maximum']:g}с"
        )

    return errs


def generate_scenario(workdir: Path, hypothesis: dict, runner: LLMRunner, retries: int = 2) -> dict:
    workdir = Path(workdir)
    base_prompt = build_prompt(hypothesis)
    last_errors = []

    for attempt in range(retries + 1):
        prompt = base_prompt
        if attempt > 0:
            prompt += (
                f"\n\nТвой прошлый ответ отклонён валидатором: {last_errors}. "
                "Исправь и верни только JSON."
            )

        reply = runner.run(prompt)
        try:
            sc = _extract_json(reply)
            errors = validate_scenario(sc, hypothesis)
        except ScenarioError as e:
            last_errors = [str(e)]
            continue
        except Exception as e:  # страховка: кривая форма не должна ронять retry-цикл
            last_errors = [f"внутренняя ошибка валидации: {type(e).__name__}: {e}"]
            continue

        if not errors:
            (workdir / "scenario.json").write_text(
                json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            return sc
        last_errors = errors

    raise ScenarioError(f"исчерпаны ретраи ({retries}): {last_errors}")


# ---------------------------------------------------------------------------
# Путь «дословно»: текст пользователя без правок (spec 2026-07-21).
# Блоки — только формат передачи сборке/Юле: границы по предложениям,
# роли позиционные, тайминги — черновая оценка по счёту слов (WORDS_PER_SEC
# выше, :66).

_SENT_RE = re.compile(r"(?<=[.!?…])\s+")


def split_verbatim(text: str) -> list[dict]:
    text = str(text or "").strip()
    if not text:
        raise ScenarioError("пустой текст")
    sents = [s for s in _SENT_RE.split(text) if s.strip()]
    n_blocks = min(4, len(sents))
    total_words = sum(len(s.split()) for s in sents)

    groups = []
    i = 0
    remaining_words = total_words
    for g in range(n_blocks):
        remaining_groups = n_blocks - g
        # оставить хотя бы по одному предложению каждой следующей группе
        max_take = len(sents) - i - (remaining_groups - 1)
        target = remaining_words / remaining_groups
        cur, cur_words = [], 0
        while len(cur) < max_take and (not cur or cur_words < target):
            cur.append(sents[i])
            cur_words += len(sents[i].split())
            i += 1
        groups.append(" ".join(cur))
        remaining_words -= cur_words

    blocks, t = [], 0.0
    for role, chunk in zip(ROLES_4, groups):
        dur = round(len(chunk.split()) / WORDS_PER_SEC, 1)
        blocks.append({"role": role, "start": round(t, 1),
                       "end": round(t + dur, 1), "speech": chunk})
        t += dur
    return blocks


def scenario_from_text(workdir: Path, text: str, language: str | None = None) -> dict:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    sc = {"mode": "verbatim", "blocks": split_verbatim(text)}
    if language:
        sc["language"] = str(language).strip().lower()
    (workdir / "scenario.json").write_text(
        json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
    return sc


def validate_integrity(sc: dict) -> list[str]:
    """Только механика (файл годен для сборки). Качество — судья, не код."""
    errs = []
    blocks = sc.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return ["blocks: отсутствует или пуст"]
    prev_end = None
    for i, b in enumerate(blocks):
        if not isinstance(b, dict):
            errs.append(f"блок {i}: не объект")
            continue
        if not str(b.get("speech") or "").strip():
            errs.append(f"блок {i} ({b.get('role')}): пустой speech")
        start, end = b.get("start"), b.get("end")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in (start, end)):
            errs.append(f"блок {i}: start/end не числа")
            continue
        if prev_end is not None and start != prev_end:
            errs.append(f"блок {i}: start ({start}) != end предыдущего ({prev_end})")
        prev_end = end
    return errs


def run_verbatim_path(workdir, text: str, skill_runner, language: str) -> dict:
    """Путь «дословно»: фонетика (единственная правка) -> scenario.json."""
    from reels_factory.humanize import humanize_scenario

    workdir = Path(workdir)
    draft = {"mode": "verbatim", "blocks": split_verbatim(text)}
    final = humanize_scenario(skill_runner, workdir, draft,
                              mode="phonetics", language=language)
    final["language"] = str(language).strip().lower()
    final["mode"] = "verbatim"
    errs = validate_integrity(final)
    if errs:
        raise ScenarioError(f"целостность: {errs}")
    (workdir / "scenario.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    n_words = sum(_wordcount(b["speech"]) for b in final["blocks"])
    return {"ok": True, "scenario": final,
            "info": {"words": n_words,
                     "est_seconds": round(n_words / WORDS_PER_SEC)}}


# ---------------------------------------------------------------------------
# Путь «из сырья»: задание-идея -> генерация скиллом -> хуманизация+судья.

def _n_fails(verdict: dict) -> int:
    scores = (verdict or {}).get("scores") or {}
    return sum(1 for v in scores.values() if v is False)


def _pick_variant2(attempts: list, best_scenario: dict):
    """Следующий по качеству ОТЛИЧАЮЩИЙСЯ от best сценарий (или None)."""
    ranked = sorted(enumerate(attempts),
                    key=lambda t: (_n_fails(t[1].get("verdict")), -t[0]))
    for _, a in ranked[1:]:
        if a.get("scenario", {}).get("blocks") != best_scenario.get("blocks"):
            return a["scenario"]
    return None


def run_generated_path(workdir, idea: dict, skill_runner, language: str,
                       gender: str | None = None) -> dict:
    """Путь «из сырья»: скилл-генерация -> полировка+судья -> scenario.json.

    `gender` — пол ведущего, «male» или «female». Без него модель не знает, в
    каком роде рассказчик говорит о себе, и мужчине достаётся «сделала».
    Значение идёт во все три скилла пути (генерация, полировка, судья): текст
    правит каждый из них, и знать род должен каждый.

    При браке (verdict.pass=False) вместо претензий судьи пользователю
    предлагается второй вариант реплик (scenario.variant2.json), если он
    отличается от лучшего — внутренняя кухня судей в scenario.json не
    попадает."""
    from reels_factory.humanize import refine_loop

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    task = {"language": language,
            "idea": idea.get("idea"),
            "length_s": idea.get("length_s"),
            "quotes": idea.get("quotes") or [],
            "persona": idea.get("persona")}
    if gender:
        task["gender"] = str(gender).strip().lower()
    payload = workdir / "idea.json"
    payload.write_text(json.dumps(task, ensure_ascii=False, indent=1),
                       encoding="utf-8")

    draft = _skill_json(skill_runner, "writing-scenario", payload, workdir)
    errs = validate_integrity(draft)
    if errs:
        raise ScenarioError(f"черновик генерации: {errs}")

    carried = ["idea", "length_s", "quotes"] + (["gender"] if gender else [])
    final, verdict = refine_loop(skill_runner, workdir, draft,
                                 {k: task[k] for k in carried}, language)
    final["language"] = str(language).strip().lower()
    if gender:
        final["gender"] = task["gender"]
    final.setdefault("mode", "generated")
    errs = validate_integrity(final)
    if errs:
        raise ScenarioError(f"целостность после полировки: {errs}")
    (workdir / "scenario.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")

    result = {"ok": True, "scenario": final, "verdict": verdict}
    if not verdict["pass"]:
        log_path = workdir / "judge_log.json"
        if log_path.exists():
            attempts = json.loads(log_path.read_text(encoding="utf-8")).get("attempts", [])
            variant2 = _pick_variant2(attempts, final)
            if variant2 is not None:
                variant2["language"] = str(language).strip().lower()
                variant2.setdefault("mode", "generated")
                (workdir / "scenario.variant2.json").write_text(
                    json.dumps(variant2, ensure_ascii=False, indent=1), encoding="utf-8")
                result["variants"] = 2
    return result


# ---------------------------------------------------------------------------
# Task 10: извлечение 2-3 идей рилсов из сырого транскрипта/заметок.

def run_ideas(workdir, source_text: str, skill_runner, language: str) -> dict:
    """Скилл-извлечение идей: сырьё -> ideas_task.json -> extracting-ideas -> ideas.json."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    payload = workdir / "ideas_task.json"
    payload.write_text(json.dumps({"language": language, "transcript": source_text},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    data = _skill_json(skill_runner, "extracting-ideas", payload, workdir)
    ideas = data.get("ideas")
    if not isinstance(ideas, list) or not (2 <= len(ideas) <= 3):
        raise ScenarioError(f"ожидалось 2–3 идеи, получено: {ideas!r}")
    for i, idea in enumerate(ideas):
        for key in ("idea", "draft_hook", "quotes", "length_s"):
            if not idea.get(key):
                raise ScenarioError(f"идея {i}: нет поля {key}")
    (workdir / "ideas.json").write_text(
        json.dumps({"ideas": ideas}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "ideas": ideas}
