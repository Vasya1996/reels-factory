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
import re
from pathlib import Path

from reels_factory.config import FACTORY_DIR
from reels_factory.llm import LLMRunner

ROLES_4 = ["hook", "development", "payoff", "cta"]  # предпочтительный вариант (без context)
ROLES_5 = ["hook", "context", "development", "payoff", "cta"]

HOOK_TYPES = "fail_first, clutch_save, number_shock, question_hook, before_after, insight_reveal"

# эмоц-теги ElevenLabs в квадратных скобках ([смех], [вздыхает]...) — не слова
_TAG_RE = re.compile(r"\[[^\]\n]*\]")

WORD_LIMIT_HARD = 70   # валидатор: жёсткий предел (иначе ролик не влезет)
WORD_LIMIT_SOFT = 60   # промпт: целевой предел

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


def build_prompt(hypothesis: dict) -> str:
    theme = hypothesis.get("theme", "")
    theme_spoken = hypothesis.get("theme_spoken") or theme
    hook_type = hypothesis.get("hook_type", "")
    case = hypothesis.get("case")
    insight = hypothesis.get("insight")
    facts = hypothesis.get("facts")
    legend = hypothesis.get("legend") or ""
    cta_phrase = hypothesis.get("cta_phrase") or ""

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

        "СКЕЛЕТ РОЛИКА (суммарная длительность 15-35 секунд). ПРЕДПОЧИТАЙ "
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
        "после ударной гласной). В speech допустимы эмоц-теги ElevenLabs в "
        "квадратных скобках, например [смех], [вздыхает] — они не считаются "
        "словами при подсчёте лимита речи.\n"
        f"ЛИМИТ РЕЧИ (критично, иначе ролик не влезет): суммарно по всем speech — "
        f"НЕ БОЛЕЕ {WORD_LIMIT_SOFT} слов; одна реплика — не более 14 слов. "
        "Коротко и хлёстко.",

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
        '{"role": "hook", "start": 0.0, "end": 3.0, "speech": "...", "pause_after": 0.5}, '
        '{"role": "development", "start": 3.5, "end": 15.0, "speech": "..."}, '
        '{"role": "payoff", "start": 15.0, "end": 22.0, "speech": "..."}, '
        '{"role": "cta", "start": 22.0, "end": 25.0, "speech": "..."}'
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
        raise ScenarioError("bad json: no JSON object found in reply")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ScenarioError(f"bad json: {e}") from e


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

    n_words = sum(_wordcount(b.get("speech", "")) for b in blocks)
    if n_words > WORD_LIMIT_HARD:
        errs.append(
            f"речь слишком длинная: {n_words} слов (максимум {WORD_LIMIT_HARD})"
        )

    total = blocks[-1].get("end") if isinstance(blocks[-1].get("end"), (int, float)) else None
    if total is not None and not (14 <= total <= 40):
        errs.append(f"общая длительность {total}с вне 14-40с")

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
# роли позиционные, тайминги — черновая оценка по счёту слов.

WORDS_PER_SEC = 2.5

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


def scenario_from_text(workdir: Path, text: str) -> dict:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    sc = {"mode": "verbatim", "blocks": split_verbatim(text)}
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

def run_generated_path(workdir, idea: dict, skill_runner, language: str) -> dict:
    """Путь «из сырья»: скилл-генерация -> полировка+судья -> scenario.json."""
    from reels_factory.humanize import refine_loop

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    task = {"language": language,
            "idea": idea.get("idea"),
            "length_s": idea.get("length_s"),
            "quotes": idea.get("quotes") or [],
            "persona": idea.get("persona")}
    payload = workdir / "idea.json"
    payload.write_text(json.dumps(task, ensure_ascii=False, indent=1),
                       encoding="utf-8")

    reply = skill_runner.run_skill("writing-scenario", payload)
    draft = _extract_json(reply)
    errs = validate_integrity(draft)
    if errs:
        raise ScenarioError(f"черновик генерации: {errs}")

    final, verdict = refine_loop(skill_runner, workdir, draft,
                                 {k: task[k] for k in ("idea", "length_s", "quotes")},
                                 language)
    errs = validate_integrity(final)
    if errs:
        raise ScenarioError(f"целостность после полировки: {errs}")
    (workdir / "scenario.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "scenario": final, "verdict": verdict}
