"""План монтажа: единственное место, где решается «что и когда происходит».

Правила ритма собраны из практики короткого видео (см. README):
  * визуальное изменение каждые 1.5-3 с — склейка, зум, вставка, титр;
  * ориентир 5-7 изменений на 10 с: меньше 4 читается как вялость,
    больше 8 — как шум;
  * статичный кадр дольше 4 с — зона оттока;
  * первые 3 с (хук) — плотнее всего, но вставками не закрываются: зритель
    должен видеть лицо;
  * паттерн-прерывание не реже раза в 15 с.

Разделение обязанностей жёсткое: здесь только арифметика по таймингам —
паузы, длительности, сетка ритма. Смысловые решения (какая вставка подходит
к этой фразе, какое слово акцентное) принимает LLM выше по конвейеру и кладёт
в тот же план. Поэтому план — обычный dict, его одинаково легко собрать
правилами, дополнить моделью и проверить гейтами до рендера.

`build_edit_plan` создаёт versioned ``edit_plan.json`` до платных стадий.
`finalize_edit_plan` добавляет точные timing после master alignment, не
перепридумывая монтаж. Revideo только проецирует этот документ в ``tz.json``.

`validate_plan` — старые гейты арифметического rhythm-плана. Новый
`validate_edit_plan` проверяет канонический план, assets и HeyGen performance.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

from reels_factory import broll_library as broll_lib
from reels_factory.config import FFMPEG
from reels_factory.master_audio import build_canonical_script

# Ритм
MIN_GAP_S = 1.5          # чаще — уже мельтешение
MAX_GAP_S = 3.0          # реже — темп проседает (потолок для гейта)
# Целевой шаг добивки. Ровно MAX_GAP_S давал бы 3.3 изменения на 10 с — ниже
# нижней границы плотности (4). 2.0 с даёт ~5 на 10 с, середину коридора 5-7.
TARGET_GAP_S = 2.0
STATIC_LIMIT_S = 4.0     # дольше без изменений — зона оттока
PATTERN_BREAK_S = 15.0   # паттерн-прерывание не реже

# Хук: первые секунды держим плотно и не закрываем вставками
HOOK_S = 3.0
HOOK_GAP_S = 0.8

PUNCH_DUR_S = 0.6        # длительность наезда
SILENCE_DB = -30         # порог тишины для разбора речи
MIN_SILENCE_S = 0.25

_SILENCE_START_RE = re.compile(r"silence_start:\s*([\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([\d.]+)")


def detect_silences(src, *, noise_db: int = SILENCE_DB,
                    min_dur_s: float = MIN_SILENCE_S, run=None) -> list:
    """Паузы в звуке как [(start, end), ...] — через ffmpeg silencedetect."""
    cmd = [FFMPEG, "-i", str(src), "-af",
           f"silencedetect=noise={noise_db}dB:d={min_dur_s}", "-f", "null", "-"]
    out = (run or _run_capture)(cmd)
    starts = [float(x) for x in _SILENCE_START_RE.findall(out)]
    ends = [float(x) for x in _SILENCE_END_RE.findall(out)]
    return [(s, e) for s, e in zip(starts, ends)]


def speech_segments(duration: float, silences: list) -> list:
    """Куски речи между паузами — на их серединах ставить наезд бессмысленно,
    зато их границы (после вдоха, на первом слове фразы) — естественные акценты."""
    segs, cur = [], 0.0
    for s, e in silences:
        if s > cur:
            segs.append((cur, min(s, duration)))
        cur = max(cur, e)
    if cur < duration:
        segs.append((cur, duration))
    return [(s, e) for s, e in segs if e - s > 0.2]


def plan_edit(duration: float, silences: list | None = None,
              accents: list | None = None) -> dict:
    """Собрать план монтажа. accents — времена смысловых акцентов от LLM
    (необязательно): если заданы, наезды идут на них, а правила лишь добивают
    ритм там, где образовались дыры.

    Возвращает {"duration", "punch": [(start, dur), ...], "whoosh": [t, ...]}.
    """
    silences = silences or []
    segs = speech_segments(duration, silences)

    events = sorted(float(a) for a in (accents or []) if 0 < float(a) < duration)

    # начала фраз после пауз — «бесплатные» акценты: там уже есть вдох и смена
    # интонации, наезд читается как задуманный, а не как случайный
    phrase_starts = [s for s, _ in segs if s > 0.3]
    for t in phrase_starts:
        if all(abs(t - e) >= MIN_GAP_S for e in events):
            events.append(t)
    events.sort()

    # добиваем дыры: пока где-то тишина дольше MAX_GAP_S — ставим событие в неё
    events = _fill_gaps(events, duration)

    punch = [(round(t, 3), PUNCH_DUR_S) for t in events
             if t + PUNCH_DUR_S <= duration]
    # свуш — на каждый наезд: ухо цепляется раньше глаза, и переход перестаёт
    # читаться как склейка
    whoosh = [t for t, _ in punch]
    return {"duration": round(float(duration), 3), "punch": punch, "whoosh": whoosh}


def _fill_gaps(events: list, duration: float) -> list:
    out = list(events)
    cur = 0.0
    guard = 0
    while guard < 500:
        guard += 1
        nxt = next((e for e in sorted(out) if e > cur), None)
        limit = HOOK_GAP_S if cur < HOOK_S else TARGET_GAP_S
        if nxt is None:
            if duration - cur > limit:
                t = round(cur + limit, 3)
                if t + PUNCH_DUR_S > duration:
                    break
                out.append(t)
                cur = t
                continue
            break
        if nxt - cur > limit:
            out.append(round(cur + limit, 3))
        cur = nxt
    return sorted(out)


def fill_static_gaps(covered: list, duration: float, *, max_gap: float = 3.0,
                     punch_dur: float = PUNCH_DUR_S) -> list:
    """Панч-окна там, где дольше max_gap ничего не происходит.

    covered — интервалы [(start, end), ...], где движение уже есть: зумы по
    фразам, окна вставок, вспышки переходов, готовые панчи. Всё, что между ними
    длиннее max_gap, — статика (зона оттока), туда добиваются короткие панчи с
    шагом max_gap. Возвращает ТОЛЬКО добавленные окна [(t, punch_dur), ...] —
    вызывающий сам сливает их с существующими.
    """
    ivs = sorted((max(0.0, float(s)), min(duration, float(e)))
                 for s, e in covered if float(e) > float(s))
    merged = []
    for s, e in ivs:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    punches = []
    edges = [(0.0, 0.0)] + merged + [(duration, duration)]
    for (_, a), (b, _) in zip(edges, edges[1:]):
        t = a + max_gap
        while t + punch_dur <= min(b, duration):
            punches.append((round(t, 3), punch_dur))
            t += max_gap + punch_dur
    return punches


def validate_plan(plan: dict, *, insert_windows: list | None = None) -> dict:
    """Гейты плана — до рендера. Возвращает {"all_pass", "gates": {...}}."""
    duration = float(plan.get("duration") or 0)
    changes = sorted(float(t) for t, _ in plan.get("punch") or [])
    gates = {}

    gaps = _gaps(changes, duration)
    gates["rhythm_no_static"] = {
        "pass": all(g <= STATIC_LIMIT_S for g in gaps),
        "max_gap": round(max(gaps), 2) if gaps else 0,
        "limit": STATIC_LIMIT_S,
    }

    per_10s = (len(changes) / duration * 10) if duration else 0
    gates["rhythm_density"] = {
        "pass": 4 <= per_10s <= 8 if duration >= 10 else True,
        "per_10s": round(per_10s, 1),
    }

    gates["pattern_break"] = {
        "pass": all(g <= PATTERN_BREAK_S for g in gaps),
        "limit": PATTERN_BREAK_S,
    }

    # вставка на хуке — грубая ошибка: первые секунды зритель знакомится с лицом
    hook_covered = [w for w in (insert_windows or []) if float(w[0]) < HOOK_S]
    gates["hook_uncovered"] = {"pass": not hook_covered}

    inserts = insert_windows or []
    gates["inserts_count"] = {"pass": len(inserts) <= 3, "count": len(inserts)}

    return {"all_pass": all(g["pass"] for g in gates.values()), "gates": gates}


def _gaps(changes: list, duration: float) -> list:
    if duration <= 0:
        return []
    points = [0.0] + list(changes) + [duration]
    return [b - a for a, b in zip(points, points[1:])]


def _run_capture(cmd: list) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    # silencedetect пишет в stderr, а сам ffmpeg завершается с ошибкой на -f null
    return (p.stderr or "") + (p.stdout or "")


# ---------------------------------------------------------------------------
# Canonical edit_plan.json
# ---------------------------------------------------------------------------

EDIT_PLAN_FORMAT_VERSION = 1
EDIT_PLAN_FILENAME = "edit_plan.json"
EDIT_PLAN_COVERAGE = {"avatar", "full_broll", "hyperframes", "mixed"}
EDIT_PLAN_STATUSES = {"draft", "final"}
EXPRESSIVENESS_VALUES = {"low", "medium", "high"}

# Fullscreen без лица дольше этого окна читается как потеря ведущего. Это
# детерминированный quality-gate, а не совет рендереру.
MAX_FACE_ABSENCE_S = 10.0
MIN_FULLSCREEN_S = 3.0
FULL_COVER_THRESHOLD = 0.20
PHRASE_BROLL_THRESHOLD = 0.18
ASSET_DURATION_SAFETY = 1.25
FULL_COVER_ROLES = {"context", "development"}

# Avatar bubble — это не замена смысловому визуалу, а присутствие ведущего
# поверх полноэкранного B-roll/HyperFrames. Окно короче 3с мелькает, длиннее
# 6с снова начинает читаться как затянутая «голова в углу».
BUBBLE_DEFAULTS = {
    "enabled": True,
    "min_seconds": 3.0,
    "max_seconds": 6.0,
    "max_per_45_seconds": 1,
    "shape": "circle",
    "position": "bottom_left",
}
BUBBLE_SHAPES = {"circle", "square"}
BUBBLE_POSITIONS = {"bottom_left", "bottom_right", "top_left", "top_right"}
VISUAL_DIRECTOR_DEFAULTS = {
    "enabled": True,
    "min_seconds": 3.0,
    "max_seconds": 9.5,
    "max_per_30_seconds": 4,
    "max_llm_windows": 3,
    # Если в оставшемся avatar-only участке нет подходящего B-roll и ни одно
    # более сильное semantic rule/LLM решение не сработало, planner обязан
    # разбить такой участок локальной HyperFrames-иллюстрацией.
    "assetless_fallback_after_seconds": 6.0,
}
VISUAL_DIRECTOR_BLOCKS = {
    "complexity_cloud",
    "persona_card",
    "value_layers",
    "concept_nodes",
    "sequence_flow",
}
VISUAL_DIRECTOR_REQUIRED_VARIABLES = {
    "complexity_cloud": {"title", "items", "resolution"},
    "persona_card": {"title", "items"},
    "value_layers": {"title", "offer", "actual"},
    "concept_nodes": {"title", "items"},
    "sequence_flow": {"title", "items"},
}
_LANGUAGE_COPY = {
    "ru": {
        "cta_subscribe": "ПОДПИСАТЬСЯ",
        "chart_title": "ЧТО МОЖНО ЗАКРЫТЬ",
        "key_step": "КЛЮЧЕВОЙ ШАГ",
        "complexity_title": "МЫ УСЛОЖНЯЕМ ПРОДАЖИ",
        "complexity_methods": "ХИТРЫЕ ПРИЁМЫ",
        "complexity_scripts": "СКРИПТЫ",
        "complexity_phrases": "ВОЛШЕБНЫЕ ФРАЗЫ",
        "complexity_resolution": "В ОСНОВЕ — 3 ВОПРОСА",
        "value_offer": "ЧТО ПРОДАЁМ",
        "foundation_title": "ОСНОВА ПРОДАЖ",
        "foundation_items": ["КОМУ", "ЧТО", "КАК"],
        "sequence_title": "ВАЖЕН ПОРЯДОК",
        "sequence_items": ["КТО", "ЧТО", "КАК"],
        "comparison_title": "СРАВНЕНИЕ",
        "explanation_title": "КЛЮЧЕВАЯ МЫСЛЬ",
        "payoff_hint": "крупный план, атмосфера",
        "automation_hint": "технологии, абстрактный фон",
        "instruction_hint": "рабочий стол, заметки",
    },
    "kk": {
        "cta_subscribe": "ЖАЗЫЛУ",
        "chart_title": "НЕГІЗГІ ТАРМАҚТАР",
        "key_step": "НЕГІЗГІ ҚАДАМ",
        "complexity_title": "БІЗ САТУДЫ КҮРДЕЛЕНДІРЕМІЗ",
        "complexity_methods": "КҮРДЕЛІ ТӘСІЛДЕР",
        "complexity_scripts": "СКРИПТТЕР",
        "complexity_phrases": "СИҚЫРЛЫ СӨЗДЕР",
        "complexity_resolution": "НЕГІЗІНДЕ — 3 СҰРАҚ",
        "value_offer": "НЕ САТАМЫЗ",
        "foundation_title": "САТУДЫҢ НЕГІЗІ",
        "foundation_items": ["КІМГЕ", "НЕ", "ҚАЛАЙ"],
        "sequence_title": "РЕТІ МАҢЫЗДЫ",
        "sequence_items": ["КІМ", "НЕ", "ҚАЛАЙ"],
        "comparison_title": "САЛЫСТЫРУ",
        "explanation_title": "НЕГІЗГІ ОЙ",
        "payoff_hint": "ірі план, атмосфера",
        "automation_hint": "технологиялар, абстрактілі фон",
        "instruction_hint": "жұмыс үстелі, жазбалар",
    },
}

_LANGUAGE_RULES = {
    "ru": {
        "sequence_head": re.compile(
            r"\b(перв\w*|втор\w*|трет\w*|четвер\w*|пят\w*|"
            r"first|second|third|fourth|fifth)\s*:",
            re.IGNORECASE,
        ),
        "ordinals": {
            "перв": "1", "втор": "2", "трет": "3", "четвер": "4",
            "пят": "5", "first": "1", "second": "2", "third": "3",
            "fourth": "4", "fifth": "5",
        },
        "complexity": re.compile(
            r"усложн|хитр\w*\s+при[её]м|скрипт|волшебн\w*\s+фраз",
            re.IGNORECASE,
        ),
        "foundation": re.compile(
            r"в\s+основе|надстройк|три\w*\s+(?:больш\w*\s+)?вопрос",
            re.IGNORECASE,
        ),
        "order": re.compile(
            r"\bсначала\b.*\bпото(?:́)?м\b.*\bпото(?:́)?м\b",
            re.IGNORECASE | re.DOTALL,
        ),
        "before": re.compile(
            r"\b(был[оаи]?|раньше|прежде|обычно)\b", re.IGNORECASE
        ),
        "after": re.compile(
            r"\b(ста(?:л[оаи]?|нет|ло)|теперь|сейчас)\b", re.IGNORECASE
        ),
        "command_verbs": ("напиш", "спрос", "попрос"),
        "payoff": re.compile(r"настро|один раз|больше не|готов", re.IGNORECASE),
        "automation": re.compile(
            r"автоматизир|везде|многое", re.IGNORECASE
        ),
        "instruction": re.compile(
            r"инструкц|набор|блокнот|список|заметк|шаг", re.IGNORECASE
        ),
        "persona": re.compile(
            r"\bкому\b|\bкто\b|человек|боль", re.IGNORECASE
        ),
        "value": re.compile(r"\bчто\b.*прода|покупа", re.IGNORECASE),
        "foundation_start": re.compile(
            r"вс[её]\s+остальн|надстройк", re.IGNORECASE
        ),
        "foundation_three": re.compile(r"трем|тр[её]м|тремя", re.IGNORECASE),
        "sequence_start": re.compile(r"порядок|сначала", re.IGNORECASE),
        "method_item": re.compile(r"при[её]м", re.IGNORECASE),
        "script_item": re.compile(r"скрипт", re.IGNORECASE),
        "phrase_item": re.compile(r"фраз", re.IGNORECASE),
        "list_split": re.compile(r"[,;]|\s+и\s+", re.IGNORECASE),
        "comparison": re.compile(
            r"\b(?:вдвое|втрое|быстрее|медленнее|больше|меньше|"
            r"процент\w*|лет|года?|разниц\w*|против)\b",
            re.IGNORECASE,
        ),
    },
    "kk": {
        "sequence_head": re.compile(
            r"\b(бірінш\w*|екінш\w*|үшінш\w*|төртінш\w*|бесінш\w*)\s*:",
            re.IGNORECASE,
        ),
        "ordinals": {
            "бірінш": "1", "екінш": "2", "үшінш": "3",
            "төртінш": "4", "бесінш": "5",
        },
        "complexity": re.compile(
            r"күрделен|айлакер\w*\s+тәсіл|скрипт|"
            r"сиқырлы\w*\s+(?:сөз|тіркес)",
            re.IGNORECASE,
        ),
        "foundation": re.compile(
            r"негізінде|негізі|үстеме|"
            r"үш\w*\s+(?:үлкен\w*\s+)?сұрақ",
            re.IGNORECASE,
        ),
        "order": re.compile(
            r"\b(?:алдымен|бірінші)\b.*\b(?:кейін|содан\s+кейін)\b.*"
            r"\b(?:соңында|кейін|содан\s+кейін)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        "before": re.compile(
            r"\b(бұрын|бастапқыда|алдында|әдетте)\b", re.IGNORECASE
        ),
        "after": re.compile(
            r"\b(қазір|енді|кейін|нәтижесінде)\b", re.IGNORECASE
        ),
        "command_verbs": ("жаз", "сұра", "өтін"),
        "payoff": re.compile(
            r"бапта|бір рет|енді.{0,20}емес|дайын", re.IGNORECASE
        ),
        "automation": re.compile(
            r"автоматтандыр|барлығын|көп нәрсе", re.IGNORECASE
        ),
        "instruction": re.compile(
            r"нұсқаулық|жинақ|дәптер|тізім|жазба|қадам", re.IGNORECASE
        ),
        "persona": re.compile(
            r"\bкімге\b|\bкім\b|адам|мәселе|қиындық", re.IGNORECASE
        ),
        "value": re.compile(r"\bне\b.*сат|сатып\s+ал", re.IGNORECASE),
        "foundation_start": re.compile(
            r"барлық\s+қалған|қалғанының\s+бәрі|үстеме", re.IGNORECASE
        ),
        "foundation_three": re.compile(r"\bүш\w*\b", re.IGNORECASE),
        "sequence_start": re.compile(r"рет|алдымен", re.IGNORECASE),
        "method_item": re.compile(r"тәсіл", re.IGNORECASE),
        "script_item": re.compile(r"скрипт", re.IGNORECASE),
        "phrase_item": re.compile(r"сөз|тіркес", re.IGNORECASE),
        "list_split": re.compile(r"[,;]|\s+(?:және|мен)\s+", re.IGNORECASE),
        "comparison": re.compile(
            r"\b(?:екі\s+есе|үш\s+есе|жылдам|баяу|көбірек|азырақ|"
            r"пайыз\w*|жыл|айырмашылық\w*|қарсы)\b",
            re.IGNORECASE,
        ),
    },
}

# Закрытый словарь жестов. Модель выбирает ключ, английскую строку для HeyGen
# подставляет наш код: сочинённые моделью жесты («Raises four fingers») HeyGen
# не умеет, и ведущая говорила «четвёртое», показывая три пальца.
#
# Каждое английское слово взято из документированного словаря HeyGen
# (help.heygen.com/en/articles/12805098): руки — wave, point, thumbs up, hand on
# heart, peace sign, crossed arms, OK sign, namaste, open arms, fist pump,
# salute, clapping, shrug; мимика — calm, enthusiastic, serious, warm,
# confident, sincere, sad, intense; поза — lean in, grounded, warm and open,
# composed; взгляд — look at camera, look away, look off-camera; покой — no hand
# gestures, hands still, barely move. Форма строки — их канон
# «[body part] + [action] + [emotion]», не больше двух коротких частей, поэтому
# в строке ровно одна запятая (её же считает ``_motion_prompt_error``).
GESTURE_VOCABULARY = {
    "look_at_camera_calm": {
        "motion_prompt": "Looks at the camera, calm and composed.",
        "definition": (
            "Нейтральный кадр: взгляд в камеру, руки не работают. "
            "Годится для пояснений, где жест только отвлекает."
        ),
    },
    "lean_in_confident": {
        "motion_prompt": "Leans in toward the camera, confident and engaged.",
        "definition": (
            "Корпус подаётся вперёд — сокращает дистанцию. "
            "Для захода и для места, где нужно поймать внимание."
        ),
    },
    "nod_gentle": {
        "motion_prompt": "Nods gently, sincere and confident.",
        "definition": (
            "Короткий кивок без рук — подтверждение сказанного. "
            "Для вывода и согласия, не для нового тезиса."
        ),
    },
    "open_arms_invite": {
        "motion_prompt": "Open arms toward the camera, warm and sincere.",
        "definition": (
            "Обе руки раскрываются к зрителю — приглашение. "
            "Для призыва к действию и приветственных фраз."
        ),
    },
    "point_forward": {
        "motion_prompt": "Right hand points forward, confident and clear.",
        "definition": (
            "Одна рука указывает вперёд — выделяет один тезис. "
            "Для акцента на конкретном утверждении, не для перечисления."
        ),
    },
    "hand_on_heart": {
        "motion_prompt": "Right hand rests on the heart, sincere and warm.",
        "definition": (
            "Ладонь на груди — личное признание, честность. "
            "Для фраз про себя и про доверие."
        ),
    },
    "thumbs_up": {
        "motion_prompt": "Right hand gives a thumbs up, enthusiastic and warm.",
        "definition": (
            "Большой палец вверх — явное одобрение. "
            "Для хорошего результата, не для нейтрального факта."
        ),
    },
    "wave_hello": {
        "motion_prompt": "Right arm raises in a wave, enthusiastic and warm.",
        "definition": (
            "Приветственный взмах рукой. "
            "Только для первой фразы обращения, дальше выглядит навязчиво."
        ),
    },
    "shrug_light": {
        "motion_prompt": "Shoulders lift in a light shrug, calm and sincere.",
        "definition": (
            "Пожатие плечами — «очевидно» или «а что тут поделать». "
            "Для риторического вопроса и мягкого возражения."
        ),
    },
    "crossed_arms_serious": {
        "motion_prompt": "Arms cross at the chest, serious and composed.",
        "definition": (
            "Скрещённые руки — закрытая, весомая поза. "
            "Для жёсткого утверждения и предупреждения."
        ),
    },
    "look_away_thoughtful": {
        "motion_prompt": "Looks away from the camera, calm and serious.",
        "definition": (
            "Взгляд уходит в сторону — размышление, пауза. "
            "Для оговорки и для перехода к следующей мысли."
        ),
    },
    "hands_still": {
        "motion_prompt": "No hand gestures, grounded and composed.",
        "definition": (
            "Выход «жест не нужен»: руки стоят, работает только лицо. "
            "Для плотного текста, цифр и перечислений."
        ),
    },
}

#: Ключи словаря — источник enum-а в схеме ответа и в промпте.
GESTURE_KEYS = tuple(GESTURE_VOCABULARY)

# Ролевые defaults намеренно консервативны: ``high`` не назначается
# автоматически, чтобы не провоцировать переигрывание. Прежние три формулировки
# («subtle natural gestures», «gestures lightly with one hand», «inviting
# open-hand gesture») HeyGen не документирует — заменены словарными ключами.
PERFORMANCE_BY_ROLE = {
    "hook": {"expressiveness": "medium", "gesture": "lean_in_confident"},
    "context": {"expressiveness": "low", "gesture": "hands_still"},
    "development": {"expressiveness": "medium", "gesture": "point_forward"},
    "payoff": {"expressiveness": "low", "gesture": "nod_gentle"},
    "cta": {"expressiveness": "medium", "gesture": "open_arms_invite"},
}
for _role_profile in PERFORMANCE_BY_ROLE.values():
    _role_profile["motion_prompt"] = (
        GESTURE_VOCABULARY[_role_profile["gesture"]]["motion_prompt"]
    )
del _role_profile
DEFAULT_PERFORMANCE = PERFORMANCE_BY_ROLE["development"]

_QUERY_STOP = {
    "ru": set((
        "и в на что как это то он она они мы вы бы же ли за по из у о а но да "
        "не нет для от до со во об про при или чтобы если когда уже ещё вот "
        "там тут так"
    ).split()),
    "kk": set((
        "және мен да де та те бұл сол ол олар біз сіз сен үшін туралы арқылы "
        "дейін кейін бірақ немесе егер кезде қазір енді ғана емес бар жоқ осы "
        "ана мына өте тағы"
    ).split()),
}
_NUM_RE = re.compile(r"(?<![\d.,])(\d{1,4})(?![\d.,])")
# Страховка на строки, которые отправляем мы сами: словарь может протухнуть,
# и тогда в HeyGen уедет то, чем Avatar IV не управляет. Модель сюда больше не
# пишет — она выбирает ключ. `seconds?` убран: регулярка ловила порядковое
# «second» и роняла сборку на честной фразе.
_FORBIDDEN_MOTION = re.compile(
    r"\b(zoom|pan|dolly|lighting|background|walk|walking|"
    r"kitchen|outside|pick(?:s|ing)? up|phone|coffee|prop)\b",
    re.IGNORECASE,
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _language_code(value: str | None) -> str:
    return "kk" if str(value or "").strip().lower() == "kk" else "ru"


def _language_rules(language: str | None) -> dict:
    return _LANGUAGE_RULES[_language_code(language)]


def _language_copy(language: str | None) -> dict:
    return _LANGUAGE_COPY[_language_code(language)]


def _norm_word(value: str) -> str:
    return "".join(char for char in str(value).casefold() if char.isalnum())


def broll_query(text: str, hint: str = "", *, language: str = "ru") -> str:
    """Короткий семантический запрос к локальному CLIP-индексу."""
    tokens = [
        token.strip(",.!?…:;«»\"'()-").lower()
        for token in str(text or "").split()
    ]
    stop_words = _QUERY_STOP[_language_code(language)]
    kept = [token for token in tokens if len(token) > 2 and token not in stop_words]
    query = " ".join(kept[:8]) or str(text or "").strip().lower()
    return f"{query}, {hint}".strip(", ") if hint else query


def stat_from_phrase(text: str) -> dict | None:
    match = _NUM_RE.search(text)
    if not match:
        return None
    value = int(match.group(1))
    before, after = text[:match.start()], text[match.end():]
    suffix = "%" if after.lstrip()[:1] == "%" else ""
    prefix = "×" if ("×" in before[-2:] or before.strip()[-1:].lower() == "x") else ""
    return {
        "value": value,
        "prefix": prefix,
        "suffix": suffix,
        "label_top": " ".join(before.split()[-2:]),
        "label_bottom": " ".join(after.strip(" %").split()[:4]),
    }


def before_after_from_text(text: str, *, language: str = "ru") -> dict | None:
    rules = _language_rules(language)
    before = rules["before"].search(text)
    after = rules["after"].search(text)
    if not (before and after and before.start() < after.start()):
        return None
    before_value = " ".join(
        text[before.end():after.start()].strip(" ,.:;-—").split()[:5]
    )
    after_value = " ".join(text[after.end():].strip(" ,.:;-—").split()[:5])
    if not before_value or not after_value:
        return None
    return {"before_value": before_value, "after_value": after_value}


def _phrase_spans(speech: str, *, language: str = "ru") -> list[tuple[int, int]]:
    """Стабильная draft-нарезка без audio timing.

    Фразы заканчиваются по сильной пунктуации либо каждые шесть слов. Возвращаем
    точные offsets исходной строки, поэтому LLM/edit/render могут ссылаться на
    один и тот же текст без fuzzy matching.
    """
    tokens = list(re.finditer(r"\S+", speech))
    if not tokens:
        return []
    spans: list[tuple[int, int]] = []
    sequence_head = _language_rules(language)["sequence_head"]
    start_index = 0
    for index, token in enumerate(tokens):
        # Нумерованный смысловой шаг должен начинать новую canonical phrase.
        # Иначе короткий хвост предыдущего предложения («покупает.») может
        # склеиться с «Третий: ...» и исказить visual timing/bubble window.
        starts_numbered_step = bool(sequence_head.match(token.group(0)))
        if starts_numbered_step and index > start_index:
            spans.append((tokens[start_index].start(), tokens[index - 1].end()))
            start_index = index
        count = index - start_index + 1
        ends_punctuation = bool(re.search(r"[,;.!?…]$", token.group(0)))
        if count >= 6 or (ends_punctuation and count >= 3):
            spans.append((tokens[start_index].start(), token.end()))
            start_index = index + 1
    if start_index < len(tokens):
        spans.append((tokens[start_index].start(), tokens[-1].end()))
    return spans


def _timing(start: float, end: float) -> dict:
    return {"start": round(float(start), 3), "end": round(float(end), 3)}


def _draft_phrases(canonical: dict, scenario: dict, config: dict) -> list[dict]:
    phrases: list[dict] = []
    avatar_cfg = (config or {}).get("avatar") or {}
    explicit_prompt = str(avatar_cfg.get("motion_prompt") or "").strip()
    explicit_expressiveness = str(avatar_cfg.get("expressiveness") or "").strip().lower()
    if explicit_expressiveness and explicit_expressiveness not in EXPRESSIVENESS_VALUES:
        raise ValueError(
            "avatar.expressiveness должен быть одним из low|medium|high"
        )

    for block, canonical_block in zip(
        scenario.get("blocks") or [], canonical["blocks"]
    ):
        speech = canonical_block["speech"]
        spans = _phrase_spans(speech, language=canonical.get("language", "ru"))
        if not spans:
            raise ValueError(f"блок {canonical_block['id']}: нет произносимой фразы")
        block_start = float(block["start"])
        block_end = float(block["end"])
        weights = [max(1, end - start) for start, end in spans]
        total_weight = sum(weights)
        cursor = block_start

        for local_index, ((local_start, local_end), weight) in enumerate(
            zip(spans, weights)
        ):
            phrase_index = len(phrases)
            if local_index == len(spans) - 1:
                phrase_end = block_end
            else:
                phrase_end = cursor + (block_end - block_start) * weight / total_weight
                total_weight -= weight
                block_start = phrase_end
            role = canonical_block.get("role")
            default = PERFORMANCE_BY_ROLE.get(role, DEFAULT_PERFORMANCE)
            performance = {
                "expressiveness": explicit_expressiveness
                or default["expressiveness"],
                # Свой prompt из конфига жестом словаря не является — тогда
                # ключа нет, и по нему видно, что строка пришла снаружи.
                "gesture": None if explicit_prompt else default["gesture"],
                "motion_prompt": explicit_prompt or default["motion_prompt"],
                "prompt_language": "en",
                "source": "config" if explicit_prompt or explicit_expressiveness
                else "role_default",
                "rationale": (
                    "Явная настройка avatar config."
                    if explicit_prompt or explicit_expressiveness
                    else f"Безопасный ролевой default для {role or 'unknown'}."
                ),
                "engine_scope": "photo_avatar_iv",
            }
            phrases.append({
                "id": f"phrase-{phrase_index:03d}",
                "index": phrase_index,
                "block_id": canonical_block["id"],
                "block_index": canonical_block["index"],
                "role": role,
                "text": speech[local_start:local_end],
                "character_start": canonical_block["character_start"] + local_start,
                "character_end": canonical_block["character_start"] + local_end,
                "estimated_timing": _timing(cursor, phrase_end),
                "final_timing": None,
                "visual_intent": "Показать ведущего без смысловой подмены.",
                "coverage": "avatar",
                "asset": None,
                "fallback": {
                    "coverage": "avatar",
                    "reason": "Ведущий — безопасный fallback при недоступности visual asset.",
                },
                "decision_reason": "Базовый безопасный вариант.",
                "window_id": None,
                "avatar_performance": performance,
            })
            cursor = phrase_end
    return phrases


def _asset_path(name: str, library_dir: Path | str | None, meta: dict) -> Path:
    explicit = meta.get("path")
    if explicit:
        return Path(explicit)
    return Path(library_dir or broll_lib.LIBRARY_DIR) / name


def _available_index(
    index: dict,
    library_dir: Path | str | None,
    *,
    require_asset_files: bool,
) -> dict:
    if not require_asset_files:
        return dict(index)
    available = {}
    for name, meta in index.items():
        path = _asset_path(name, library_dir, meta)
        if path.is_file():
            available[name] = {**meta, "path": str(path)}
    return available


def _pick_asset(
    query: str,
    required_seconds: float,
    index: dict,
    used: set[str],
    *,
    threshold: float,
    duration_safety: float,
    embed_fn,
) -> dict | None:
    if not index:
        return None
    embedding = embed_fn(query)
    ranked: list[tuple[str, dict, float]] = []
    for name, meta in index.items():
        if name in used:
            continue
        duration = float(meta.get("duration") or 0.0)
        if duration and duration + 0.3 < required_seconds * duration_safety:
            continue
        score = broll_lib.cosine(embedding, meta.get("embedding") or [])
        ranked.append((name, meta, score))
    ranked.sort(key=lambda item: item[2], reverse=True)
    if not ranked or ranked[0][2] < threshold:
        return None
    name, meta, score = ranked[0]
    used.add(name)
    return {
        "kind": "broll",
        "source": "library",
        "src": name,
        "path": str(meta.get("path") or ""),
        "query": query,
        "confidence": round(float(score), 4),
        "duration_seconds": round(float(meta.get("duration") or 0.0), 3),
        "required_seconds": round(float(required_seconds), 3),
        "locked": True,
    }


def _legacy_full_cover(
    scenario: dict,
    legacy_broll_plan: dict | None,
    *,
    language: str = "ru",
) -> dict[int, dict]:
    by_role = {
        item.get("role"): item
        for item in ((legacy_broll_plan or {}).get("segments") or [])
        if item.get("insert")
    }
    result = {}
    for block_index, block in enumerate(scenario.get("blocks") or []):
        item = by_role.get(block.get("role"))
        if not item:
            continue
        clip = item.get("clip") or "broll.mp4"
        result[block_index] = {
            "kind": "broll",
            "source": "library" if item.get("clip") else "external",
            "src": clip,
            "path": str(item.get("path") or ""),
            "query": item.get("query") or broll_query(
                block.get("speech") or "", language=language
            ),
            "confidence": round(float(item.get("score") or 1.0), 4),
            "duration_seconds": float(item.get("duration") or 0.0),
            "required_seconds": round(
                float(block["end"]) - float(block["start"]), 3
            ),
            "locked": bool(item.get("clip")),
            "offset": float(item.get("offset") or 0.0),
        }
    return result


def _external_broll_asset(
    legacy_broll_plan: dict | None,
    role: str | None,
    query: str,
    required_seconds: float,
) -> dict | None:
    segments = (legacy_broll_plan or {}).get("segments") or []
    if not segments:
        return None
    by_role = next(
        (item for item in segments if item.get("role") == role), {}
    )
    return {
        "kind": "broll",
        "source": "external",
        "src": "broll.mp4",
        "query": query,
        "confidence": 1.0,
        "duration_seconds": 0.0,
        "required_seconds": round(float(required_seconds), 3),
        "locked": False,
        "offset": float(by_role.get("offset") or 0.0),
    }


def _chart_variables(
    text: str,
    start: float,
    end: float,
    *,
    language: str = "ru",
    title: str | None = None,
) -> dict | None:
    rules = _language_rules(language)
    parts = [
        part.strip(" .,")
        for part in rules["list_split"].split(text)
        if 0 < len(part.strip(" .,").split()) <= 3
        and len(part.strip(" .,")) > 2
    ]
    if len(parts) < 3 or text.count(",") < 3:
        return None
    items = parts[:5]
    span = max(0.1, end - start)
    return {
        "title": title or _language_copy(language)["chart_title"],
        "items": [
            {
                "t": round(start + span * index / len(items), 2),
                "label": label.capitalize()[:22],
                "v": [0.7, 0.55, 0.85, 0.75, 1.0][index % 5],
            }
            for index, label in enumerate(items)
        ],
    }


def _bubble_settings(config: dict, duration: float) -> dict:
    raw = ((config.get("edit_plan") or {}).get("bubble") or {})
    settings = dict(BUBBLE_DEFAULTS)
    settings.update(raw)
    enabled = settings.get("enabled")
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in {"1", "true", "yes", "on"}
    settings["enabled"] = bool(enabled)
    try:
        settings["min_seconds"] = float(settings["min_seconds"])
        settings["max_seconds"] = float(settings["max_seconds"])
        settings["max_per_45_seconds"] = int(settings["max_per_45_seconds"])
    except (TypeError, ValueError) as exc:
        raise ValueError("edit_plan.bubble содержит нечисловой лимит") from exc
    if not 1.2 <= settings["min_seconds"] <= settings["max_seconds"] <= 10.0:
        raise ValueError(
            "edit_plan.bubble требует 1.2 <= min_seconds <= max_seconds <= 10"
        )
    if settings["max_per_45_seconds"] < 0:
        raise ValueError("edit_plan.bubble.max_per_45_seconds должен быть >= 0")
    settings["shape"] = str(settings["shape"]).strip().lower()
    settings["position"] = str(settings["position"]).strip().lower()
    if settings["shape"] not in BUBBLE_SHAPES:
        raise ValueError("edit_plan.bubble.shape должен быть circle|square")
    if settings["position"] not in BUBBLE_POSITIONS:
        raise ValueError(
            "edit_plan.bubble.position должен быть одним из четырёх углов"
        )
    periods = max(1, math.ceil(max(0.0, float(duration)) / 45.0 - 1e-9))
    settings["max_count"] = (
        settings["max_per_45_seconds"] * periods if settings["enabled"] else 0
    )
    return settings


def _visual_director_settings(config: dict, duration: float) -> dict:
    raw = ((config.get("edit_plan") or {}).get("visual_director") or {})
    settings = dict(VISUAL_DIRECTOR_DEFAULTS)
    settings.update({key: value for key, value in raw.items() if key != "llm"})
    enabled = settings.get("enabled")
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in {"1", "true", "yes", "on"}
    settings["enabled"] = bool(enabled)
    try:
        settings["min_seconds"] = float(settings["min_seconds"])
        settings["max_seconds"] = float(settings["max_seconds"])
        settings["max_per_30_seconds"] = int(settings["max_per_30_seconds"])
        settings["max_llm_windows"] = int(settings["max_llm_windows"])
        settings["assetless_fallback_after_seconds"] = float(
            settings["assetless_fallback_after_seconds"]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("edit_plan.visual_director содержит нечисловой лимит") from exc
    if not (
        MIN_FULLSCREEN_S
        <= settings["min_seconds"]
        <= settings["max_seconds"]
        <= MAX_FACE_ABSENCE_S
    ):
        raise ValueError(
            "edit_plan.visual_director требует "
            f"{MIN_FULLSCREEN_S:.1f} <= min_seconds <= max_seconds "
            f"<= {MAX_FACE_ABSENCE_S:.1f}"
        )
    if settings["max_per_30_seconds"] < 0 or settings["max_llm_windows"] < 0:
        raise ValueError(
            "edit_plan.visual_director frequency limits должны быть >= 0"
        )
    if settings["assetless_fallback_after_seconds"] < settings["min_seconds"]:
        raise ValueError(
            "edit_plan.visual_director.assetless_fallback_after_seconds "
            "должен быть не меньше min_seconds"
        )
    periods = max(1, math.ceil(max(0.0, float(duration)) / 30.0 - 1e-9))
    settings["max_count"] = (
        settings["max_per_30_seconds"] * periods if settings["enabled"] else 0
    )
    settings["blocks"] = sorted(VISUAL_DIRECTOR_BLOCKS)
    return settings


def _visual_duration(selected: list[dict]) -> float:
    if not selected:
        return 0.0
    return (
        float(selected[-1]["estimated_timing"]["end"])
        - float(selected[0]["estimated_timing"]["start"])
    )


def _visual_label(value: str, *, words: int = 7, chars: int = 48) -> str:
    clean = " ".join(
        str(value or "").strip(" ,.!?…:;—-").split()[:words]
    )
    return clean[:chars]


def _visual_items(value: str, *, limit: int = 4) -> list[str]:
    parts = [
        _visual_label(part, words=6, chars=42)
        for part in re.split(r"[,;]", str(value or ""))
    ]
    return [part for part in parts if part][:limit]


def _visual_director_effect(
    block: str,
    variables: dict,
    *,
    source: str = "rules",
) -> dict:
    if block not in VISUAL_DIRECTOR_BLOCKS:
        raise ValueError(f"неизвестный Visual Director block: {block}")
    frozen = copy.deepcopy(variables)
    return {
        "type": block,
        **frozen,
        "hyperframes": {
            "block": block,
            "variables": copy.deepcopy(frozen),
        },
        "visual_director": {
            "template": block,
            "source": source,
        },
    }


def _bubble_title(text: str, match: re.Match, *, language: str = "ru") -> str:
    ordinal = match.group(1).lower()
    number = next(
        (
            value
            for prefix, value in _language_rules(language)["ordinals"].items()
            if ordinal.startswith(prefix)
        ),
        "",
    )
    topic = text[match.end():].strip(" .!?…:;—-")
    topic = " ".join(topic.split()[:4]).upper()
    return (
        f"{number} · {topic}".strip(" ·")[:30]
        or _language_copy(language)["key_step"]
    )


def _bubble_item_label(text: str) -> str:
    clean = " ".join(str(text or "").strip(" ,.!?…:;—-").split()[:5])
    return clean[:32]


def _bubble_task_list_candidate(
    block_phrases: list[dict],
    start_index: int,
    settings: dict,
    *,
    language: str = "ru",
) -> dict | None:
    """Найти короткий нумерованный шаг с тремя поясняющими пунктами.

    Это детерминированный offline fallback для конструкций вида
    «Третий: как продаём? Где..., какими..., в каком...». Более свободные
    семантические случаи позже может рекомендовать visual LLM, но renderer
    получает тот же canonical effect contract.
    """
    if not settings["enabled"] or start_index >= len(block_phrases):
        return None
    sequence_head = _language_rules(language)["sequence_head"]
    head = block_phrases[start_index]
    match = sequence_head.search(head["text"])
    if not match:
        return None
    supporting: list[dict] = []
    items: list[str] = []
    for phrase in block_phrases[start_index + 1:start_index + 4]:
        if sequence_head.search(phrase["text"]):
            break
        label = _bubble_item_label(phrase["text"])
        if not label:
            break
        supporting.append(phrase)
        items.append(label)
    if len(items) != 3:
        return None
    start = float(supporting[0]["estimated_timing"]["start"])
    end = float(supporting[-1]["estimated_timing"]["end"])
    duration = end - start
    if not settings["min_seconds"] <= duration <= settings["max_seconds"]:
        return None
    title = _bubble_title(head["text"], match, language=language)
    span = max(0.1, duration)
    chart_items = [
        {
            "t": round(start + span * index / len(items), 2),
            "label": label,
            "v": [0.72, 0.86, 1.0][index],
        }
        for index, label in enumerate(items)
    ]
    return {
        "lead": [head],
        "selected": supporting,
        "title": title,
        "items": items,
        "effect": {
            "type": "chart_bars",
            "title": title,
            "items": chart_items,
            "hyperframes": {
                "block": "task_list",
                "variables": {"title": title, "items": items},
            },
            "bubble": {
                "shape": settings["shape"],
                "position": settings["position"],
            },
        },
    }


def _complexity_cloud_candidate(
    block_phrases: list[dict],
    start_index: int,
    settings: dict,
    *,
    language: str = "ru",
) -> dict | None:
    if not settings["enabled"] or start_index >= len(block_phrases):
        return None
    rules = _language_rules(language)
    copy_text = _language_copy(language)
    if not rules["complexity"].search(block_phrases[start_index]["text"]):
        return None
    selected: list[dict] = []
    for phrase in block_phrases[start_index:]:
        if selected and rules["sequence_head"].search(phrase["text"]):
            break
        selected.append(phrase)
    combined = " ".join(phrase["text"] for phrase in selected)
    duration = _visual_duration(selected)
    if (
        not rules["foundation"].search(combined)
        or not settings["min_seconds"] <= duration <= settings["max_seconds"]
    ):
        return None
    items = []
    low = combined.lower()
    if rules["method_item"].search(low):
        items.append(copy_text["complexity_methods"])
    if rules["script_item"].search(low):
        items.append(copy_text["complexity_scripts"])
    if rules["phrase_item"].search(low):
        items.append(copy_text["complexity_phrases"])
    if len(items) < 3:
        items.extend(
            item.upper()
            for item in _visual_items(combined, limit=3)
            if item.upper() not in items
        )
    variables = {
        "title": copy_text["complexity_title"],
        "items": items[:4],
        "resolution": copy_text["complexity_resolution"],
    }
    return {
        "lead": [],
        "selected": selected,
        "coverage": "hyperframes",
        "effect": _visual_director_effect("complexity_cloud", variables),
        "visual_intent": (
            "Показать визуальный шум из приёмов, скриптов и фраз, затем "
            "схлопнуть его до трёх базовых вопросов."
        ),
        "reason": (
            "В речи есть явная дуга «усложняем → в основе простая система»."
        ),
    }


def _ordinal_visual_candidate(
    block_phrases: list[dict],
    start_index: int,
    settings: dict,
    *,
    language: str = "ru",
) -> dict | None:
    if not settings["enabled"] or start_index >= len(block_phrases):
        return None
    rules = _language_rules(language)
    copy_text = _language_copy(language)
    head = block_phrases[start_index]
    match = rules["sequence_head"].search(head["text"])
    if not match:
        return None
    topic = head["text"][match.end():].lower()
    following: list[dict] = []
    for phrase in block_phrases[start_index + 1:]:
        if rules["sequence_head"].search(phrase["text"]):
            break
        following.append(phrase)
    if not following:
        return None
    title = _bubble_title(head["text"], match, language=language)
    combined = " ".join(phrase["text"] for phrase in following)

    if rules["persona"].search(topic):
        selected = following
        if not (
            settings["min_seconds"]
            <= _visual_duration(selected)
            <= settings["max_seconds"]
        ):
            return None
        items = _visual_items(combined, limit=4)
        if len(items) < 2:
            return None
        return {
            "lead": [head],
            "selected": selected,
            "coverage": "hyperframes",
            "effect": _visual_director_effect(
                "persona_card",
                {"title": title, "items": items},
            ),
            "visual_intent": (
                "Разложить аудиторию на человека, контекст жизни и боль."
            ),
            "reason": "Нумерованный вопрос описывает целевого человека.",
        }

    if rules["value"].search(topic + " " + combined.lower()):
        selected = [head, *following]
        if not (
            settings["min_seconds"]
            <= _visual_duration(selected)
            <= settings["max_seconds"]
        ):
            return None
        variables = {
            "title": title,
            "offer": _visual_label(topic, words=5, chars=36).upper()
            or copy_text["value_offer"],
            "actual": _visual_label(combined, words=8, chars=58),
        }
        return {
            "lead": [],
            "selected": selected,
            "coverage": "hyperframes",
            "effect": _visual_director_effect("value_layers", variables),
            "visual_intent": (
                "Сопоставить формальное предложение и реальную покупку клиента."
            ),
            "reason": (
                "Фраза явно противопоставляет «что продаём» и "
                "«что человек покупает»."
            ),
        }
    return None


def _foundation_nodes_candidate(
    block_phrases: list[dict],
    start_index: int,
    settings: dict,
    *,
    language: str = "ru",
) -> dict | None:
    if not settings["enabled"] or start_index >= len(block_phrases):
        return None
    rules = _language_rules(language)
    copy_text = _language_copy(language)
    # Не заглатывать предшествующий нумерованный шаг только потому, что
    # «надстройка» встретилась в одной из следующих фраз: bubble для «как»
    # и concept_nodes для итогового тезиса должны остаться разными окнами.
    if not rules["foundation_start"].search(block_phrases[start_index]["text"]):
        return None
    selected = block_phrases[start_index:]
    combined = " ".join(phrase["text"] for phrase in selected)
    duration = _visual_duration(selected)
    if (
        not rules["foundation_start"].search(combined)
        or not rules["foundation_three"].search(combined)
        or not settings["min_seconds"] <= duration <= settings["max_seconds"]
    ):
        return None
    variables = {
        "title": copy_text["foundation_title"],
        "items": copy_text["foundation_items"],
    }
    return {
        "lead": [],
        "selected": selected,
        "coverage": "hyperframes",
        "effect": _visual_director_effect("concept_nodes", variables),
        "visual_intent": "Собрать три вопроса в единую основу системы продаж.",
        "reason": "Текст называет всё остальное надстройкой над тремя вопросами.",
    }


def _sequence_flow_candidate(
    block_phrases: list[dict],
    start_index: int,
    settings: dict,
    *,
    language: str = "ru",
) -> dict | None:
    if not settings["enabled"] or start_index >= len(block_phrases):
        return None
    rules = _language_rules(language)
    copy_text = _language_copy(language)
    remaining = block_phrases[start_index:]
    combined = " ".join(phrase["text"] for phrase in remaining)
    if not rules["order"].search(combined):
        return None
    first_flow = next(
        (
            index
            for index, phrase in enumerate(remaining)
            if rules["sequence_start"].search(phrase["text"])
        ),
        0,
    )
    lead = remaining[:first_flow]
    selected = remaining[first_flow:]
    duration = _visual_duration(selected)
    if not settings["min_seconds"] <= duration <= settings["max_seconds"]:
        return None
    variables = {
        "title": copy_text["sequence_title"],
        "items": copy_text["sequence_items"],
    }
    return {
        "lead": lead,
        "selected": selected,
        "coverage": "hyperframes",
        "effect": _visual_director_effect("sequence_flow", variables),
        "visual_intent": "Показать обязательный порядок: кто → что → как.",
        "reason": "В payoff явно сформулирована последовательность шагов.",
    }


def _window_effect(
    coverage: str,
    *,
    effect: dict | None = None,
    asset: dict | None = None,
) -> dict:
    if effect is not None:
        return copy.deepcopy(effect)
    if coverage == "full_broll" and asset:
        result = {
            "type": "broll",
            "style": "fullscreen",
            "broll_query": asset["query"],
            "src": asset["src"],
            "offset": float(asset.get("offset") or 0.0),
        }
        if asset.get("locked"):
            result["src_locked"] = True
        return result
    return {"type": "none"}


# Подсказка по зоне из смысла окна: где ведущий несёт смысл — карточка поверх
# видео, где важнее показать — кадр отдаётся показу. Это именно подсказка:
# окончательный выбор из пяти зон скила делает агент.
_FACELESS_COVERAGE = {"full_broll", "hyperframes"}


def _zone_for(coverage: str) -> str:
    return "fullscreen" if coverage in _FACELESS_COVERAGE else "video-overlay"


def _is_faceless(window: dict) -> bool:
    """Окно, в котором ведущей нет в кадре: полноэкранная видеовставка или
    полноэкранная графика. Только им разрешено не заказывать аватар."""
    effect = window.get("effect") or {}
    if window.get("coverage") == "full_broll" and effect.get("type") == "broll":
        return True
    return (window.get("coverage") == "hyperframes"
            and window.get("zone") == "fullscreen")


# Домен в речи: «elevenlabs точка ай о», «сайт example точка ру».
# Зона верхнего уровня в расшифровке приходит словами, поэтому переводим её.
_SPOKEN_TLD = {"ай о": "io", "ру": "ru", "кз": "kz", "ком": "com",
               "нет": "net", "орг": "org", "ай": "ai"}
_SITE_RE = re.compile(
    r"([a-z0-9-]{3,})\s*(?:точка|\.)\s*([a-z]{2,6}|" +
    "|".join(_SPOKEN_TLD) + ")", re.IGNORECASE)


def _domain(match) -> str:
    tld = match.group(2).lower()
    return f"https://{match.group(1)}.{_SPOKEN_TLD.get(tld, tld)}"
# маркеры последовательности действий на экране
_ROUTE_MARKERS = ("открыва", "вводишь", "нажима", "выбира", "листа", "прокручива")


def material_for_phrase(text: str) -> dict | None:
    """Что подготовить для этой фразы: снимок сайта, запись маршрута или ничего.

    Приём выбирается из того, что сказано, а не из того, что мы умеем:
    нет предмета — ничего не готовим.
    """
    low = str(text or "").lower()
    site = _SITE_RE.search(low)
    # то, что человек диктует после «вводишь» или «запрос» — это и есть запрос
    query_match = re.search(r"(?:вводишь|запрос)\s+([\w\s-]{3,40}?)(?:\s+(?:и|выбира|нажима|листа|прокручива)|$)", low)
    query = query_match.group(1).strip(" .,") if query_match else None
    if site and sum(marker in low for marker in _ROUTE_MARKERS) < 2:
        return {"kind": "site", "url": _domain(site)}
    if sum(marker in low for marker in _ROUTE_MARKERS) >= 2:
        # Ввод в поиск умеем только на Google: селектор поля и результата
        # у каждого сайта свой, гадать нельзя. Если назван другой домен —
        # просто открываем его и листаем.
        on_google = site is None
        steps = [{"type": "goto",
                  "url": "https://www.google.com" if on_google else _domain(site)}]
        if on_google and ("вводишь" in low or "запрос" in low):
            steps.append({"type": "type", "selector": "textarea[name=q]",
                          "text": query or "открытый проект"})
            if "выбира" in low or "ссылк" in low:
                steps.append({"type": "click", "selector": "h3"})
        steps.append({"type": "scroll", "pixels": 1200})
        return {"kind": "route", "steps": steps}
    return None


def _assign_window(
    windows: list[dict],
    phrases: list[dict],
    selected: list[dict],
    *,
    coverage: str,
    visual_intent: str,
    reason: str,
    effect: dict | None = None,
    asset: dict | None = None,
    camera: str = "hold",
    transition: str = "none",
    caption: str = "bottom",
    safe_to_skip_avatar: bool = False,
) -> dict:
    window_id = f"window-{len(windows):03d}"
    estimated = _timing(
        selected[0]["estimated_timing"]["start"],
        selected[-1]["estimated_timing"]["end"],
    )
    window = {
        "id": window_id,
        "phrase_ids": [phrase["id"] for phrase in selected],
        "block_id": selected[0]["block_id"],
        "block_index": selected[0]["block_index"],
        "role": selected[0].get("role"),
        "visual_intent": visual_intent,
        "coverage": coverage,
        "asset": copy.deepcopy(asset),
        "fallback": {
            "coverage": "avatar",
            "effect": {"type": "none"},
            "reason": "Если primary asset недоступен, сохранить ведущего.",
        },
        "decision_reason": reason,
        "estimated_timing": estimated,
        "final_timing": None,
        "camera": {"type": camera},
        "zone": _zone_for(coverage),
        # материал нужен только там, где ведущая может уйти из кадра:
        # в хуке и призыве валидатор её прятать запрещает (editplan.py:2478-2482)
        "material": (material_for_phrase(
            " ".join(p.get("text", "") for p in selected))
            if coverage in _FACELESS_COVERAGE else None),
        "transition_in": transition,
        "caption": caption,
        "effect": _window_effect(coverage, effect=effect, asset=asset),
        "safe_to_skip_avatar": bool(safe_to_skip_avatar),
    }
    windows.append(window)
    for phrase in selected:
        phrase["visual_intent"] = visual_intent
        phrase["coverage"] = coverage
        phrase["asset"] = copy.deepcopy(asset)
        phrase["decision_reason"] = reason
        phrase["window_id"] = window_id
    return window


def _extend_phrase_window(
    phrases: list[dict], start_index: int, minimum_seconds: float
) -> int:
    block_index = phrases[start_index]["block_index"]
    end_index = start_index
    while (
        phrases[end_index]["estimated_timing"]["end"]
        - phrases[start_index]["estimated_timing"]["start"]
        < minimum_seconds
        and end_index + 1 < len(phrases)
        and phrases[end_index + 1]["block_index"] == block_index
    ):
        end_index += 1
    return end_index


def _downgrade_draft_window(
    window: dict,
    phrases: list[dict],
    *,
    reason: str,
    log: list[str],
) -> None:
    """Сделать draft-окно avatar fallback до оплаты и exact timing."""
    window["coverage"] = "avatar"
    window["zone"] = _zone_for("avatar")
    window["asset"] = None
    window["material"] = None
    window["effect"] = {"type": "none"}
    window["camera"] = {
        "type": "hold" if window.get("role") == "payoff" else "ken_burns"
    }
    window["transition_in"] = "none"
    window["caption"] = "bottom"
    window["safe_to_skip_avatar"] = False
    window["decision_reason"] = f"Preflight fallback: {reason}"
    own_ids = set(window.get("phrase_ids") or [])
    for phrase in phrases:
        if phrase["id"] in own_ids:
            phrase["coverage"] = "avatar"
            phrase["asset"] = None
            phrase["decision_reason"] = window["decision_reason"]
    log.append(f"{window.get('role')}: {reason}; сохранён avatar.")


def _plan_visual_windows(
    phrases: list[dict],
    scenario: dict,
    config: dict,
    index: dict,
    *,
    embed_fn,
    legacy_broll_plan: dict | None,
    log: list[str],
) -> list[dict]:
    windows: list[dict] = []
    used_assets: set[str] = set()
    language = _language_code(config.get("language"))
    language_rules = _language_rules(language)
    copy_text = _language_copy(language)
    total_duration = float((scenario.get("blocks") or [{}])[-1].get("end") or 0)
    bubble_settings = _bubble_settings(config, total_duration)
    visual_settings = _visual_director_settings(config, total_duration)
    allow_full_cover = str(config.get("format") or "split") == "avatar"
    explicit_full_cover = (
        _legacy_full_cover(
            scenario, legacy_broll_plan, language=language
        )
        if allow_full_cover else {}
    )
    for block_index in list(explicit_full_cover):
        block = scenario["blocks"][block_index]
        duration = float(block["end"]) - float(block["start"])
        if duration < MIN_FULLSCREEN_S or duration > MAX_FACE_ABSENCE_S:
            log.append(
                f"{block.get('role')}: legacy full cover отклонён — "
                f"длительность {duration:.1f}с вне безопасного окна "
                f"{MIN_FULLSCREEN_S:.0f}–{MAX_FACE_ABSENCE_S:.0f}с."
            )
            explicit_full_cover.pop(block_index)
    full_cover: dict[int, dict] = dict(explicit_full_cover)

    candidates = [
        (index_value, block)
        for index_value, block in enumerate(scenario.get("blocks") or [])
        if allow_full_cover
        and block.get("role") in FULL_COVER_ROLES
        and index_value not in explicit_full_cover
    ]
    candidates.sort(
        key=lambda item: float(item[1]["end"]) - float(item[1]["start"]),
        reverse=True,
    )
    chosen_indexes = set(explicit_full_cover)
    used_assets.update(
        asset["src"]
        for asset in explicit_full_cover.values()
        if asset.get("source") == "library"
    )
    for block_index, block in candidates:
        if (block_index - 1) in chosen_indexes or (block_index + 1) in chosen_indexes:
            log.append(
                f"{block.get('role')}: не закрыт — соседнее fullscreen-окно "
                "вернуло бы лицо слишком редко."
            )
            continue
        duration = float(block["end"]) - float(block["start"])
        if duration > MAX_FACE_ABSENCE_S:
            log.append(
                f"{block.get('role')}: не закрыт — {duration:.1f}с без лица "
                f"дольше лимита {MAX_FACE_ABSENCE_S:.0f}с."
            )
            continue
        query = broll_query(
            block.get("speech") or "", language=language
        )
        try:
            asset = _pick_asset(
                query,
                duration,
                index,
                used_assets,
                threshold=FULL_COVER_THRESHOLD,
                duration_safety=ASSET_DURATION_SAFETY,
                embed_fn=embed_fn,
            )
        except Exception as exc:
            log.append(f"CLIP недоступен ({str(exc)[:120]}) — без full cover.")
            asset = None
        if asset:
            full_cover[block_index] = asset
            chosen_indexes.add(block_index)
            log.append(
                f"{block.get('role')}: full_broll {asset['src']} "
                f"(confidence={asset['confidence']:.3f})."
            )

    by_block: dict[int, list[dict]] = {}
    for phrase in phrases:
        by_block.setdefault(phrase["block_index"], []).append(phrase)

    used_effects = {
        "before_after": False,
        "stat": False,
        "chart": False,
        "bubble": 0,
        "visual_director": 0,
        "automation_broll": False,
        "instruction_broll": False,
    }

    for block_index, block in enumerate(scenario.get("blocks") or []):
        block_phrases = by_block[block_index]
        role = block.get("role")
        block_duration = float(block["end"]) - float(block["start"])

        if block_index in full_cover:
            asset = full_cover[block_index]
            _assign_window(
                windows,
                phrases,
                block_phrases,
                coverage="full_broll",
                visual_intent=asset["query"],
                reason=(
                    "Уверенный существующий B-roll перекрывает весь блок; "
                    "HeyGen для блока безопасно пропустить."
                ),
                asset=asset,
                safe_to_skip_avatar=True,
            )
            continue

        if role == "cta":
            _assign_window(
                windows,
                phrases,
                block_phrases,
                coverage="mixed",
                visual_intent="Живой ведущий и CTA endcard.",
                reason="CTA сохраняет лицо и явный призыв.",
                effect={
                    "type": "cta_endcard",
                    "button": ((config.get("product") or {}).get("cta_button")
                               or copy_text["cta_subscribe"]),
                },
                camera="ken_burns",
            )
            continue

        combined = " ".join(item["text"] for item in block_phrases)
        before_after = (
            before_after_from_text(combined, language=language)
            if not used_effects["before_after"]
            and role in {"context", "development", "payoff"}
            else None
        )
        if before_after and MIN_FULLSCREEN_S <= block_duration <= MAX_FACE_ABSENCE_S:
            used_effects["before_after"] = True
            _assign_window(
                windows,
                phrases,
                block_phrases,
                coverage="hyperframes",
                visual_intent="Визуально сравнить состояние до и после.",
                reason="Явные маркеры before/after в тексте.",
                effect={
                    "type": "none",
                    "hyperframes": {
                        "block": "before_after",
                        "variables": before_after,
                    },
                },
                safe_to_skip_avatar=True,
            )
            continue

        chart = (
            _chart_variables(
                combined,
                block_phrases[0]["estimated_timing"]["start"],
                block_phrases[-1]["estimated_timing"]["end"],
                language=language,
                title=(config.get("product") or {}).get("chart_title"),
            )
            if not used_effects["chart"]
            and role in {"development", "payoff"}
            else None
        )
        if chart and MIN_FULLSCREEN_S <= block_duration <= MAX_FACE_ABSENCE_S:
            used_effects["chart"] = True
            _assign_window(
                windows,
                phrases,
                block_phrases,
                coverage="hyperframes",
                visual_intent="Показать перечисление как анимированный список.",
                reason="В речи найден короткий список из трёх и более пунктов.",
                effect={
                    "type": "chart_bars",
                    "title": chart["title"],
                    "items": chart["items"],
                    "hyperframes": {
                        "block": "task_list",
                        "variables": {
                            "title": chart["title"],
                            "items": [item["label"] for item in chart["items"]],
                        },
                    },
                },
                caption="hidden",
                safe_to_skip_avatar=True,
            )
            continue

        local_index = 0
        while local_index < len(block_phrases):
            phrase = block_phrases[local_index]
            text = phrase["text"]
            low = f" {text.lower()} "

            director_candidate = None
            if (
                role in {"context", "development", "payoff"}
                and used_effects["visual_director"] < visual_settings["max_count"]
            ):
                for finder in (
                    _complexity_cloud_candidate,
                    _ordinal_visual_candidate,
                    _foundation_nodes_candidate,
                    _sequence_flow_candidate,
                ):
                    director_candidate = finder(
                        block_phrases,
                        local_index,
                        visual_settings,
                        language=language,
                    )
                    if director_candidate:
                        break
            if director_candidate:
                lead = director_candidate["lead"]
                selected = director_candidate["selected"]
                if lead:
                    _assign_window(
                        windows,
                        phrases,
                        lead,
                        coverage="avatar",
                        visual_intent=(
                            "Сформулировать смысловой переход лицом в кадре "
                            "перед встроенной инфографикой."
                        ),
                        reason=(
                            "Eye contact разделяет соседние fullscreen visuals "
                            "и удерживает непрерывность ведущего."
                        ),
                        camera="punch_in",
                        caption="highlight",
                    )
                _assign_window(
                    windows,
                    phrases,
                    selected,
                    coverage=director_candidate["coverage"],
                    visual_intent=director_candidate["visual_intent"],
                    reason=director_candidate["reason"],
                    effect=director_candidate["effect"],
                    camera="hold",
                    transition="zoom_blur",
                    caption="hidden",
                )
                used_effects["visual_director"] += 1
                local_index += len(lead) + len(selected)
                continue

            bubble_sequence = (
                _bubble_task_list_candidate(
                    block_phrases,
                    local_index,
                    bubble_settings,
                    language=language,
                )
                if role in {"context", "development", "payoff"}
                and used_effects["bubble"] < bubble_settings["max_count"]
                else None
            )
            if bubble_sequence:
                lead = bubble_sequence["lead"]
                selected = bubble_sequence["selected"]
                _assign_window(
                    windows,
                    phrases,
                    lead,
                    coverage="avatar",
                    visual_intent=(
                        "Сформулировать нумерованный вопрос лицом в кадре "
                        "перед раскрытием списка."
                    ),
                    reason=(
                        "Короткая постановка вопроса сохраняет eye contact; "
                        "смысловой visual раскрывается на следующих пунктах."
                    ),
                    camera="punch_in",
                    caption="highlight",
                )
                _assign_window(
                    windows,
                    phrases,
                    selected,
                    coverage="mixed",
                    visual_intent=(
                        "Показать смысловую последовательность на весь экран, "
                        "сохранив ведущего в avatar bubble."
                    ),
                    reason=(
                        "Нумерованный шаг раскрывается тремя короткими "
                        "пунктами; task-list получает приоритет, лицо остаётся "
                        "в поддерживающем bubble."
                    ),
                    effect=bubble_sequence["effect"],
                    camera="hold",
                    caption="hidden",
                )
                used_effects["bubble"] += 1
                local_index += len(lead) + len(selected)
                continue

            stat = (
                stat_from_phrase(text)
                if not used_effects["stat"]
                and role in {"context", "development", "payoff"}
                else None
            )
            if stat:
                global_index = phrases.index(phrase)
                global_end = _extend_phrase_window(phrases, global_index, 4.0)
                selected = phrases[global_index:global_end + 1]
                duration = (
                    selected[-1]["estimated_timing"]["end"]
                    - selected[0]["estimated_timing"]["start"]
                )
                if duration <= MAX_FACE_ABSENCE_S:
                    used_effects["stat"] = True
                    _assign_window(
                        windows,
                        phrases,
                        selected,
                        coverage="hyperframes",
                        visual_intent="Вывести ключевое число крупной графикой.",
                        reason="Во фразе найдено явное числовое утверждение.",
                        effect={
                            "type": "none",
                            "hyperframes": {
                                "block": "stat_number",
                                "variables": stat,
                            },
                        },
                        safe_to_skip_avatar=True,
                    )
                    local_index += len(selected)
                    continue

            if (
                role == "payoff"
                and used_effects["bubble"] < bubble_settings["max_count"]
                and bubble_settings["min_seconds"]
                <= block_duration
                <= bubble_settings["max_seconds"]
                and language_rules["payoff"].search(low)
            ):
                query = broll_query(
                    text,
                    copy_text["payoff_hint"],
                    language=language,
                )
                try:
                    asset = _pick_asset(
                        query,
                        block_duration,
                        index,
                        used_assets,
                        threshold=PHRASE_BROLL_THRESHOLD,
                        duration_safety=1.0,
                        embed_fn=embed_fn,
                    )
                except Exception:
                    asset = None
                asset = asset or _external_broll_asset(
                    legacy_broll_plan,
                    role,
                    query,
                    block_duration,
                )
                if asset:
                    used_effects["bubble"] += 1
                    effect = _window_effect("full_broll", asset=asset)
                    effect["bubble"] = {
                        "shape": "circle",
                        "position": "bottom_left",
                    }
                    _assign_window(
                        windows,
                        phrases,
                        block_phrases,
                        coverage="mixed",
                        visual_intent=query,
                        reason="Payoff остаётся личным: B-roll плюс лицо в bubble.",
                        effect=effect,
                        asset=asset,
                    )
                    local_index = len(block_phrases)
                    continue

            broll_rule = None
            hint = ""
            if (
                not used_effects["automation_broll"]
                and language_rules["automation"].search(low)
            ):
                broll_rule = "automation_broll"
                hint = copy_text["automation_hint"]
            elif (
                not used_effects["instruction_broll"]
                and language_rules["instruction"].search(low)
            ):
                broll_rule = "instruction_broll"
                hint = copy_text["instruction_hint"]
            if broll_rule:
                global_index = phrases.index(phrase)
                global_end = _extend_phrase_window(
                    phrases, global_index, MIN_FULLSCREEN_S
                )
                selected = phrases[global_index:global_end + 1]
                duration = (
                    selected[-1]["estimated_timing"]["end"]
                    - selected[0]["estimated_timing"]["start"]
                )
                query = broll_query(
                    " ".join(item["text"] for item in selected),
                    hint,
                    language=language,
                )
                try:
                    asset = _pick_asset(
                        query,
                        duration,
                        index,
                        used_assets,
                        threshold=PHRASE_BROLL_THRESHOLD,
                        duration_safety=1.0,
                        embed_fn=embed_fn,
                    )
                except Exception:
                    asset = None
                asset = asset or _external_broll_asset(
                    legacy_broll_plan,
                    role,
                    query,
                    duration,
                )
                if (
                    asset
                    and MIN_FULLSCREEN_S <= duration <= MAX_FACE_ABSENCE_S
                ):
                    used_effects[broll_rule] = True
                    _assign_window(
                        windows,
                        phrases,
                        selected,
                        coverage="full_broll",
                        visual_intent=query,
                        reason="Смысловая фразовая перебивка с проверенным asset.",
                        asset=asset,
                        transition="whip",
                    )
                    local_index += len(selected)
                    continue

            _assign_window(
                windows,
                phrases,
                [phrase],
                coverage="avatar",
                visual_intent="Показать ведущего и сохранить личный контакт.",
                reason="Нет более сильного проверенного fullscreen-решения.",
                effect={"type": "none"},
                camera="hold" if role == "payoff" else "ken_burns",
            )
            local_index += 1

    windows.sort(key=lambda item: item["estimated_timing"]["start"])
    # Даже если каждое fullscreen-окно само по себе короче лимита, два
    # соседних окна могли бы скрыть лицо суммарно дольше MAX_FACE_ABSENCE_S.
    # Второе решение деградирует явно; это не позднее перепланирование.
    face_absence_start = None
    for window in windows:
        timing = window["estimated_timing"]
        if window.get("coverage") in {"full_broll", "hyperframes"}:
            if face_absence_start is None:
                face_absence_start = float(timing["start"])
            if float(timing["end"]) - face_absence_start > MAX_FACE_ABSENCE_S:
                _downgrade_draft_window(
                    window,
                    phrases,
                    reason=(
                        "соседние fullscreen-окна скрыли бы лицо дольше "
                        f"{MAX_FACE_ABSENCE_S:.0f}с"
                    ),
                    log=log,
                )
                face_absence_start = None
        else:
            face_absence_start = None
    for index, window in enumerate(windows):
        window["id"] = f"window-{index:03d}"
        for phrase_id in window["phrase_ids"]:
            next(
                phrase for phrase in phrases if phrase["id"] == phrase_id
            )["window_id"] = window["id"]
    return windows


def _refresh_blocks_and_summary(plan: dict) -> None:
    phrases = plan.get("phrases") or []
    windows = plan.get("windows") or []
    window_by_id = {window["id"]: window for window in windows}
    blocks = []
    for block in plan.get("blocks") or []:
        own = [
            phrase for phrase in phrases
            if phrase["block_index"] == block["index"]
        ]
        own_windows = {
            phrase["window_id"] for phrase in own if phrase.get("window_id")
        }
        safe = bool(own) and all(
            _is_faceless(window_by_id[phrase["window_id"]])
            and window_by_id[phrase["window_id"]].get("safe_to_skip_avatar")
            for phrase in own
        )
        next_block = copy.deepcopy(block)
        next_block["phrase_ids"] = [phrase["id"] for phrase in own]
        next_block["window_ids"] = sorted(own_windows)
        next_block["avatar_required"] = not safe
        blocks.append(next_block)
    plan["blocks"] = blocks

    timing_key = "final_timing" if plan.get("status") == "final" else "estimated_timing"
    full_broll_seconds = 0.0
    avatar_visible_seconds = 0.0
    bubble_seconds = 0.0
    bubble_windows = 0
    built_in_visual_seconds = 0.0
    built_in_visual_windows = 0
    for window in windows:
        timing = window.get(timing_key) or window.get("estimated_timing") or {}
        duration = max(0.0, float(timing.get("end", 0)) - float(timing.get("start", 0)))
        if window.get("coverage") == "full_broll":
            full_broll_seconds += duration
        if window.get("coverage") in {"avatar", "mixed"}:
            avatar_visible_seconds += duration
        if (window.get("effect") or {}).get("bubble"):
            bubble_seconds += duration
            bubble_windows += 1
        if (window.get("effect") or {}).get("visual_director"):
            built_in_visual_seconds += duration
            built_in_visual_windows += 1
    block_avatar_seconds = 0.0
    for block in blocks:
        timing = block.get(timing_key) or block.get("estimated_timing") or {}
        if block.get("avatar_required"):
            block_avatar_seconds += max(
                0.0,
                float(timing.get("end", 0)) - float(timing.get("start", 0)),
            )
    plan["summary"] = {
        "phrases": len(phrases),
        "windows": len(windows),
        "full_broll_seconds": round(full_broll_seconds, 3),
        "avatar_visible_seconds": round(avatar_visible_seconds, 3),
        "bubble_seconds": round(bubble_seconds, 3),
        "bubble_windows": bubble_windows,
        "built_in_visual_seconds": round(built_in_visual_seconds, 3),
        "built_in_visual_windows": built_in_visual_windows,
        "transitional_heygen_block_seconds": round(block_avatar_seconds, 3),
        "covered_block_indexes": [
            block["index"] for block in blocks if not block["avatar_required"]
        ],
    }


def build_edit_plan(
    scenario: dict,
    config: dict,
    *,
    index: dict | None = None,
    library_dir: Path | str | None = None,
    embed_fn=None,
    legacy_broll_plan: dict | None = None,
    visual_recommendations: dict | list | None = None,
    performance_recommendations: dict | list | None = None,
    require_asset_files: bool = True,
) -> dict:
    """Создать draft единственного монтажного плана до TTS/HeyGen."""
    canonical = build_canonical_script(scenario, config)
    log: list[str] = []
    if index is None:
        try:
            index = broll_lib.load_index(library_dir)
        except Exception as exc:
            index = {}
            log.append(f"B-roll index недоступен ({str(exc)[:120]}).")
    usable_index = _available_index(
        index or {}, library_dir, require_asset_files=require_asset_files
    )
    if not index:
        log.append("B-roll index пуст — безопасный avatar/HyperFrames plan.")
    if index and not usable_index:
        log.append("В B-roll index нет существующих media assets.")
    phrases = _draft_phrases(canonical, scenario, config)
    windows = _plan_visual_windows(
        phrases,
        scenario,
        config,
        usable_index,
        embed_fn=embed_fn or broll_lib.embed_text,
        legacy_broll_plan=legacy_broll_plan,
        log=log,
    )
    blocks = []
    for canonical_block, source_block in zip(canonical["blocks"], scenario["blocks"]):
        blocks.append({
            "id": canonical_block["id"],
            "index": canonical_block["index"],
            "role": canonical_block.get("role"),
            "character_start": canonical_block["character_start"],
            "character_end": canonical_block["character_end"],
            "estimated_timing": _timing(source_block["start"], source_block["end"]),
            "final_timing": None,
        })
    total = float(scenario["blocks"][-1]["end"])
    bubble_constraints = _bubble_settings(config, total)
    visual_constraints = _visual_director_settings(config, total)
    plan = {
        "format_version": EDIT_PLAN_FORMAT_VERSION,
        "status": "draft",
        "generated_by": "reels_factory.editplan",
        "script": {
            "language": canonical["language"],
            "text": canonical["text"],
            "text_sha256": canonical["text_sha256"],
            "character_count": len(canonical["text"]),
        },
        "timeline": {
            "estimated_duration_seconds": round(total, 3),
            "final_duration_seconds": None,
        },
        "constraints": {
            "coverage_values": sorted(EDIT_PLAN_COVERAGE),
            "full_cover_confidence_min": FULL_COVER_THRESHOLD,
            "phrase_broll_confidence_min": PHRASE_BROLL_THRESHOLD,
            "max_face_absence_seconds": MAX_FACE_ABSENCE_S,
            "min_fullscreen_seconds": MIN_FULLSCREEN_S,
            "bubble": bubble_constraints,
            "visual_director": visual_constraints,
        },
        "blocks": blocks,
        "phrases": phrases,
        "windows": windows,
        "events": {
            "punch": copy.deepcopy(
                (legacy_broll_plan or {}).get("punch") or []
            ),
        },
        "revisions": [],
        "log": log,
    }
    if visual_recommendations:
        plan = apply_visual_recommendations(
            plan, visual_recommendations, source="provided"
        )
    if performance_recommendations:
        plan = apply_performance_recommendations(
            plan, performance_recommendations, source="provided"
        )
    _refresh_blocks_and_summary(plan)
    report = validate_edit_plan(
        plan,
        library_dir=library_dir,
        require_asset_files=require_asset_files,
    )
    plan["validation"] = report
    if not report["all_pass"]:
        raise ValueError("edit plan draft invalid: " + "; ".join(report["errors"][:5]))
    return plan


def _words_for_phrase(
    phrase: dict,
    block_words: list[dict],
    phrase_index: int,
    block_phrases: list[dict],
) -> list[dict]:
    ranged = [
        word for word in block_words
        if word.get("character_start") is not None
        and word.get("character_end") is not None
        and int(word["character_end"]) > int(phrase["character_start"])
        and int(word["character_start"]) < int(phrase["character_end"])
    ]
    if ranged:
        return ranged

    # Legacy Whisper не содержит character ranges. Делим слова блока в том же
    # порядке пропорционально количеству слов draft-фраз, без fuzzy text match.
    weights = [max(1, len(item["text"].split())) for item in block_phrases]
    total_weight = sum(weights)
    boundaries = [0]
    consumed = 0
    for index, weight in enumerate(weights[:-1]):
        consumed += weight
        raw = round(len(block_words) * consumed / total_weight)
        minimum = boundaries[-1] + 1
        maximum = len(block_words) - (len(block_phrases) - index - 1)
        boundaries.append(max(minimum, min(raw, maximum)))
    boundaries.append(len(block_words))
    return block_words[boundaries[phrase_index]:boundaries[phrase_index + 1]]


def _downgrade_window(plan: dict, window: dict, reason: str) -> None:
    window["coverage"] = "avatar"
    window["zone"] = _zone_for("avatar")
    window["asset"] = None
    window["material"] = None
    window["effect"] = {"type": "none"}
    window["camera"] = {
        "type": "hold" if window.get("role") == "payoff" else "ken_burns"
    }
    window["transition_in"] = "none"
    window["caption"] = "bottom"
    window["safe_to_skip_avatar"] = False
    window["decision_reason"] = f"Fallback после exact timing: {reason}"
    phrase_ids = set(window["phrase_ids"])
    for phrase in plan["phrases"]:
        if phrase["id"] in phrase_ids:
            phrase["coverage"] = "avatar"
            phrase["asset"] = None
            phrase["decision_reason"] = window["decision_reason"]
    plan.setdefault("revisions", []).append({
        "window_id": window["id"],
        "from": "primary_visual",
        "to": "avatar",
        "reason": reason,
    })


def finalize_edit_plan(
    plan: dict,
    timed_scenario: dict,
    words: list[dict],
    *,
    require_asset_files: bool = True,
) -> dict:
    """Добавить exact timing; visual decisions сохраняются либо явно fallback."""
    result = copy.deepcopy(plan)
    if result.get("status") not in EDIT_PLAN_STATUSES:
        raise ValueError("неизвестный status edit plan")
    timed_blocks = timed_scenario.get("blocks") or []
    if len(timed_blocks) != len(result.get("blocks") or []):
        raise ValueError("timed_scenario blocks не совпадает с edit plan")

    phrases_by_block: dict[int, list[dict]] = {}
    for phrase in result["phrases"]:
        phrases_by_block.setdefault(phrase["block_index"], []).append(phrase)

    for block_index, timed_block in enumerate(timed_blocks):
        block_phrases = phrases_by_block[block_index]
        block_words = [
            word for word in words
            if (
                word.get("block_index") == block_index
                or (
                    word.get("block_index") is None
                    and float(timed_block["start"]) <= float(word["start"])
                    < float(timed_block["end"])
                )
            )
        ]
        if not block_words:
            raise ValueError(f"alignment не содержит слов блока {block_index}")
        spoken: list[tuple[float, float]] = []
        for phrase_index, phrase in enumerate(block_phrases):
            own = _words_for_phrase(
                phrase, block_words, phrase_index, block_phrases
            )
            if not own:
                raise ValueError(
                    f"alignment не содержит слов фразы {phrase['id']}"
                )
            spoken.append((float(own[0]["start"]), float(own[-1]["end"])))

        cuts = [float(timed_block["start"])]
        for left, right in zip(spoken, spoken[1:]):
            if right[0] + 1e-6 < left[1]:
                raise ValueError(
                    f"speech timing фраз блока {block_index} пересекается"
                )
            cuts.append((left[1] + right[0]) / 2.0)
        cuts.append(float(timed_block["end"]))
        for phrase_index, phrase in enumerate(block_phrases):
            phrase["final_timing"] = _timing(
                cuts[phrase_index], cuts[phrase_index + 1]
            )
            phrase["speech_timing"] = _timing(*spoken[phrase_index])

        block = result["blocks"][block_index]
        block["final_timing"] = _timing(
            timed_block["start"], timed_block["end"]
        )

    phrase_by_id = {phrase["id"]: phrase for phrase in result["phrases"]}
    for window in result["windows"]:
        selected = [phrase_by_id[item] for item in window["phrase_ids"]]
        window["final_timing"] = _timing(
            selected[0]["final_timing"]["start"],
            selected[-1]["final_timing"]["end"],
        )
        duration = (
            window["final_timing"]["end"] - window["final_timing"]["start"]
        )
        asset = window.get("asset") or {}
        if asset:
            asset["required_seconds"] = round(duration, 3)
            available = float(asset.get("duration_seconds") or 0.0)
            if (
                asset.get("source") == "library"
                and available
                and available + 0.3 < duration
            ):
                _downgrade_window(
                    result,
                    window,
                    f"asset {asset.get('src')} короче exact window "
                    f"({available:.2f}с < {duration:.2f}с)",
                )
                continue
        bubble = (window.get("effect") or {}).get("bubble")
        bubble_constraints = (result.get("constraints") or {}).get("bubble") or {}
        bubble_min = float(
            bubble_constraints.get("min_seconds", BUBBLE_DEFAULTS["min_seconds"])
        )
        bubble_max = float(
            bubble_constraints.get("max_seconds", BUBBLE_DEFAULTS["max_seconds"])
        )
        if bubble and not (
            bubble_min <= duration <= bubble_max
        ):
            _downgrade_window(
                result,
                window,
                f"bubble exact window {duration:.2f}с вне разрешённого "
                f"{bubble_min:.1f}–{bubble_max:.1f}с",
            )
            continue
        visual_director = (window.get("effect") or {}).get("visual_director")
        visual_constraints = (
            (result.get("constraints") or {}).get("visual_director") or {}
        )
        visual_min = float(
            visual_constraints.get(
                "min_seconds", VISUAL_DIRECTOR_DEFAULTS["min_seconds"]
            )
        )
        visual_max = float(
            visual_constraints.get(
                "max_seconds", VISUAL_DIRECTOR_DEFAULTS["max_seconds"]
            )
        )
        if visual_director and not visual_min <= duration <= visual_max:
            _downgrade_window(
                result,
                window,
                f"built-in visual exact window {duration:.2f}с вне разрешённого "
                f"{visual_min:.1f}–{visual_max:.1f}с",
            )
            continue
        if (
            window.get("coverage") in {"full_broll", "hyperframes"}
            and duration > MAX_FACE_ABSENCE_S
        ):
            _downgrade_window(
                result,
                window,
                f"exact window {duration:.2f}с превышает лимит отсутствия лица",
            )
        elif (
            window.get("coverage") in {"full_broll", "hyperframes"}
            and duration < MIN_FULLSCREEN_S
        ):
            _downgrade_window(
                result,
                window,
                f"exact window {duration:.2f}с короче стабильного fullscreen",
            )

    result["status"] = "final"
    result["timeline"]["final_duration_seconds"] = round(
        float(timed_scenario.get("total") or timed_blocks[-1]["end"]), 3
    )
    from reels_factory.visual_grounding import enforce_visual_grounding

    result = enforce_visual_grounding(result)
    _refresh_blocks_and_summary(result)
    report = validate_edit_plan(
        result,
        require_final=True,
        require_asset_files=require_asset_files,
    )
    result["validation"] = report
    if not report["all_pass"]:
        raise ValueError("edit plan final invalid: " + "; ".join(report["errors"][:5]))
    return result


def _motion_prompt_error(prompt: str) -> str | None:
    if not prompt:
        return "motion_prompt пуст"
    if len(prompt) > 220:
        return "motion_prompt длиннее 220 символов"
    if any(ord(character) > 127 for character in prompt):
        return "motion_prompt должен быть короткой инструкцией на английском"
    if prompt.count(",") + prompt.count(";") > 1:
        return "motion_prompt перегружен: максимум две короткие части"
    forbidden = _FORBIDDEN_MOTION.search(prompt)
    if forbidden:
        return f"motion_prompt управляет неподдерживаемым объектом: {forbidden.group(0)}"
    return None


def _visual_director_effect_error(effect: dict) -> str | None:
    director = effect.get("visual_director")
    if not director:
        return None
    if not isinstance(director, dict):
        return "visual_director metadata должен быть object"
    template = str(director.get("template") or "")
    if template not in VISUAL_DIRECTOR_BLOCKS:
        return f"неизвестный visual template: {template or '-'}"
    if effect.get("type") != template:
        return "effect.type не совпадает с visual_director.template"
    hyperframes = effect.get("hyperframes") or {}
    if hyperframes.get("block") != template:
        return "HyperFrames block не совпадает с visual template"
    variables = hyperframes.get("variables")
    if not isinstance(variables, dict):
        return "visual template variables должны быть object"
    missing = VISUAL_DIRECTOR_REQUIRED_VARIABLES[template] - set(variables)
    if missing:
        return f"visual template не содержит variables: {sorted(missing)}"
    for key in VISUAL_DIRECTOR_REQUIRED_VARIABLES[template]:
        if effect.get(key) != variables.get(key):
            return (
                f"visual runtime variable {key} не совпадает "
                "с HyperFrames variables"
            )
    title = str(variables.get("title") or "").strip()
    if not title or len(title) > 60:
        return "visual title пуст или длиннее 60 символов"
    if "items" in VISUAL_DIRECTOR_REQUIRED_VARIABLES[template]:
        items = variables.get("items")
        if (
            not isinstance(items, list)
            or not 2 <= len(items) <= 5
            or any(
                not str(item).strip() or len(str(item).strip()) > 58
                for item in items
            )
        ):
            return "visual items требуют 2–5 непустых строк до 58 символов"
    for key in ("resolution", "offer", "actual"):
        if key in VISUAL_DIRECTOR_REQUIRED_VARIABLES[template]:
            value = str(variables.get(key) or "").strip()
            if not value or len(value) > 80:
                return f"visual variable {key} пуст или длиннее 80 символов"
    return None


def validate_edit_plan(
    plan: dict,
    *,
    library_dir: Path | str | None = None,
    require_final: bool = False,
    require_asset_files: bool = True,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if plan.get("format_version") != EDIT_PLAN_FORMAT_VERSION:
        errors.append("неподдерживаемая format_version")
    if plan.get("status") not in EDIT_PLAN_STATUSES:
        errors.append("status должен быть draft|final")
    if require_final and plan.get("status") != "final":
        errors.append("ожидался final edit plan")

    script = plan.get("script") or {}
    text = str(script.get("text") or "")
    if _sha256_text(text) != script.get("text_sha256"):
        errors.append("script.text_sha256 не совпадает с canonical text")

    phrases = plan.get("phrases") or []
    ids = [phrase.get("id") for phrase in phrases]
    if not phrases or len(ids) != len(set(ids)):
        errors.append("phrase IDs пусты или не уникальны")
    previous_end = -1
    for phrase in phrases:
        start = int(phrase.get("character_start", -1))
        end = int(phrase.get("character_end", -1))
        if start < previous_end or end <= start or end > len(text):
            errors.append(f"{phrase.get('id')}: некорректный character range")
        elif text[start:end] != phrase.get("text"):
            errors.append(f"{phrase.get('id')}: text не совпадает с character range")
        previous_end = end
        if phrase.get("coverage") not in EDIT_PLAN_COVERAGE:
            errors.append(f"{phrase.get('id')}: неизвестный coverage")
        performance = phrase.get("avatar_performance") or {}
        if performance.get("expressiveness") not in EXPRESSIVENESS_VALUES:
            errors.append(f"{phrase.get('id')}: expressiveness не low|medium|high")
        prompt_error = _motion_prompt_error(
            str(performance.get("motion_prompt") or "")
        )
        if prompt_error:
            errors.append(f"{phrase.get('id')}: {prompt_error}")
        if require_final and not phrase.get("final_timing"):
            errors.append(f"{phrase.get('id')}: нет final timing")

    phrase_ids = set(ids)
    assigned: list[str] = []
    windows = plan.get("windows") or []
    window_ids = [window.get("id") for window in windows]
    if not windows or len(window_ids) != len(set(window_ids)):
        errors.append("window IDs пусты или не уникальны")
    previous_window_end = 0.0
    timing_key = "final_timing" if plan.get("status") == "final" else "estimated_timing"
    face_absence_start = None
    bubble_count = 0
    bubble_constraints = (plan.get("constraints") or {}).get("bubble") or {}
    bubble_min = float(
        bubble_constraints.get("min_seconds", BUBBLE_DEFAULTS["min_seconds"])
    )
    bubble_max = float(
        bubble_constraints.get("max_seconds", BUBBLE_DEFAULTS["max_seconds"])
    )
    visual_count = 0
    visual_constraints = (
        (plan.get("constraints") or {}).get("visual_director") or {}
    )
    visual_min = float(
        visual_constraints.get(
            "min_seconds", VISUAL_DIRECTOR_DEFAULTS["min_seconds"]
        )
    )
    visual_max = float(
        visual_constraints.get(
            "max_seconds", VISUAL_DIRECTOR_DEFAULTS["max_seconds"]
        )
    )
    for window in windows:
        own_ids = window.get("phrase_ids") or []
        assigned.extend(own_ids)
        if not own_ids or any(item not in phrase_ids for item in own_ids):
            errors.append(f"{window.get('id')}: неизвестные phrase IDs")
        own_phrases = [
            phrase for phrase in phrases if phrase.get("id") in set(own_ids)
        ]
        if any(phrase.get("window_id") != window.get("id") for phrase in own_phrases):
            errors.append(f"{window.get('id')}: phrase.window_id не совпадает")
        if any(phrase.get("coverage") != window.get("coverage") for phrase in own_phrases):
            errors.append(f"{window.get('id')}: phrase coverage не совпадает")
        if window.get("coverage") not in EDIT_PLAN_COVERAGE:
            errors.append(f"{window.get('id')}: неизвестный coverage")
        timing = window.get(timing_key) or {}
        start = float(timing.get("start", -1))
        end = float(timing.get("end", -1))
        if start + 0.002 < previous_window_end or end <= start:
            errors.append(f"{window.get('id')}: timing пересекается/неположительный")
        previous_window_end = max(previous_window_end, end)
        duration = end - start

        coverage = window.get("coverage")
        if window.get("safe_to_skip_avatar") and not _is_faceless(window):
            errors.append(
                f'{window["id"]}: HeyGen skip разрешён только там, где ведущей '
                "нет в кадре"
            )
        if coverage in {"full_broll", "hyperframes"}:
            if duration < MIN_FULLSCREEN_S:
                errors.append(
                    f"{window.get('id')}: fullscreen короче {MIN_FULLSCREEN_S}с"
                )
            if face_absence_start is None:
                face_absence_start = start
            if end - face_absence_start > MAX_FACE_ABSENCE_S + 0.001:
                errors.append(
                    f"{window.get('id')}: лицо отсутствует дольше "
                    f"{MAX_FACE_ABSENCE_S}с"
                )
        else:
            face_absence_start = None

        role = window.get("role")
        if role == "hook" and coverage not in {"avatar", "mixed"}:
            errors.append(f"{window.get('id')}: hook нельзя полностью скрывать")
        if role == "cta" and coverage not in {"avatar", "mixed"}:
            errors.append(f"{window.get('id')}: CTA нельзя полностью скрывать")

        effect = window.get("effect") or {}
        visual_error = _visual_director_effect_error(effect)
        if visual_error:
            errors.append(f"{window.get('id')}: {visual_error}")
        if effect.get("visual_director"):
            visual_count += 1
            if coverage != "hyperframes" or window.get("safe_to_skip_avatar"):
                errors.append(
                    f"{window.get('id')}: built-in visual требует "
                    "hyperframes coverage без HeyGen skip"
                )
            if role in {"hook", "cta"}:
                errors.append(
                    f"{window.get('id')}: built-in visual нельзя использовать "
                    f"в {role}"
                )
            if not visual_min <= duration <= visual_max:
                errors.append(
                    f"{window.get('id')}: built-in visual должен длиться "
                    f"{visual_min:.1f}–{visual_max:.1f}с"
                )
            if window.get("caption") != "hidden":
                errors.append(
                    f"{window.get('id')}: built-in visual требует hidden caption"
                )
        bubble = effect.get("bubble")
        if bubble:
            bubble_count += 1
            if coverage != "mixed" or window.get("safe_to_skip_avatar"):
                errors.append(
                    f"{window.get('id')}: bubble требует mixed coverage и Avatar IV"
                )
            if role in {"hook", "cta"}:
                errors.append(
                    f"{window.get('id')}: bubble нельзя использовать в {role}"
                )
            if not bubble_min <= duration <= bubble_max:
                errors.append(
                    f"{window.get('id')}: bubble должен длиться "
                    f"{bubble_min:.1f}–{bubble_max:.1f}с"
                )
            if str(bubble.get("shape") or "") not in BUBBLE_SHAPES:
                errors.append(f"{window.get('id')}: неизвестная bubble shape")
            if str(bubble.get("position") or "") not in BUBBLE_POSITIONS:
                errors.append(f"{window.get('id')}: неизвестная bubble position")
            has_supporting_visual = bool(effect.get("hyperframes")) or (
                effect.get("type") == "broll"
                and effect.get("style") == "fullscreen"
            )
            if not has_supporting_visual:
                errors.append(
                    f"{window.get('id')}: bubble требует fullscreen "
                    "B-roll или HyperFrames visual"
                )

        asset = window.get("asset") or {}
        if coverage in {"full_broll", "mixed"} and effect.get("type") == "broll":
            if not asset.get("src"):
                errors.append(f"{window.get('id')}: B-roll без asset")
            confidence = float(asset.get("confidence") or 0.0)
            threshold = (
                FULL_COVER_THRESHOLD
                if window.get("safe_to_skip_avatar")
                else PHRASE_BROLL_THRESHOLD
            )
            if asset.get("source") == "library" and confidence < threshold:
                errors.append(
                    f"{window.get('id')}: low-confidence B-roll "
                    f"{confidence:.3f}<{threshold:.2f}"
                )
            available = float(asset.get("duration_seconds") or 0.0)
            if available and available + 0.3 < duration:
                errors.append(f"{window.get('id')}: asset короче window")
            if (
                require_asset_files
                and asset.get("source") == "library"
                and asset.get("locked")
            ):
                meta = {"path": asset.get("path")} if asset.get("path") else {}
                if not _asset_path(asset["src"], library_dir, meta).is_file():
                    errors.append(
                        f"{window.get('id')}: asset не существует: {asset['src']}"
                    )
        if asset.get("source") == "external":
            warnings.append(
                f"{window.get('id')}: external B-roll проверяется после ingest"
            )

    max_bubbles = int(bubble_constraints.get("max_count", max(1, bubble_count)))
    if bubble_count > max_bubbles:
        errors.append(
            f"bubble windows превышают лимит: {bubble_count}>{max_bubbles}"
        )
    max_visuals = int(
        visual_constraints.get("max_count", max(1, visual_count))
    )
    if visual_count > max_visuals:
        errors.append(
            f"built-in visual windows превышают лимит: "
            f"{visual_count}>{max_visuals}"
        )

    if sorted(assigned) != sorted(ids):
        errors.append("windows должны назначить каждую phrase ровно один раз")

    blocks = plan.get("blocks") or []
    for block in blocks:
        if not block.get("avatar_required"):
            own = [
                window for window in windows
                if window.get("block_index") == block.get("index")
            ]
            if not own or any(
                not _is_faceless(window)
                or not window.get("safe_to_skip_avatar")
                for window in own
            ):
                errors.append(
                    f"block-{block.get('index')}: HeyGen skip без безопасного full cover"
                )
    return {
        "all_pass": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def save_edit_plan(plan: dict, workdir: Path | str) -> Path:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / EDIT_PLAN_FILENAME
    temporary = workdir / f".{EDIT_PLAN_FILENAME}.tmp"
    temporary.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)
    return path


def load_edit_plan(workdir: Path | str) -> dict:
    """Прочитать ``edit_plan.json`` из папки задания.

    Нужен пересборке: два платных LLM-прохода (визуальный директор и жесты)
    свои решения кладут только в этот документ, и повторная сборка, которая
    переиспользует уже заказанную ведущую, обязана взять их с диска, а не
    считать заново — иначе решения разойдутся с оплаченными клипами.
    """
    path = Path(workdir) / EDIT_PLAN_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


def covered_block_indexes(plan: dict) -> set[int]:
    return {
        int(block["index"])
        for block in plan.get("blocks") or []
        if not block.get("avatar_required", True)
    }


def performance_response_schema() -> dict:
    """JSON-схема ответа для `claude -p --json-schema`.

    Жест — `enum` по ключам словаря: выбор из закрытого списка принуждается на
    стороне CLI, а не проверкой постфактум. `rationale` объявлен раньше
    `gesture` — модель сначала пишет причину, потом выбирает, как в их
    классификаторе.
    """
    return {
        "type": "object",
        "properties": {
            "phrases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "phrase_id": {"type": "string"},
                        "rationale": {"type": "string"},
                        "gesture": {"type": "string", "enum": list(GESTURE_KEYS)},
                        "expressiveness": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                        },
                    },
                    "required": [
                        "phrase_id", "rationale", "gesture", "expressiveness",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["phrases"],
        "additionalProperties": False,
    }


def performance_analysis_prompt(plan: dict) -> str:
    """Prompt отдельного LLM-анализа после approval и до TTS/HeyGen.

    Написан по канону Anthropic (platform.claude.com/docs/en/build-with-claude/
    prompt-engineering/claude-prompting-best-practices): блоки размечены XML,
    вместо списка запретов дана причина ограничения и определения доступных
    жестов («Tell Claude what to do instead of what not to do»), примеры только
    положительные, `rationale` идёт перед выбором.

    Модель выбирает ключ, английскую строку для HeyGen подставляет наш код.
    """
    payload = [
        {
            "phrase_id": phrase["id"],
            "role": phrase.get("role"),
            "text": phrase["text"],
        }
        for phrase in plan.get("phrases") or []
    ]
    gestures = "\n".join(
        f'  <gesture key="{key}">{item["definition"]} '
        f'Кадр: {item["motion_prompt"]}</gesture>'
        for key, item in GESTURE_VOCABULARY.items()
    )
    return (
        "<instructions>\n"
        "Ты режиссируешь подачу ведущей в HeyGen Photo Avatar IV для короткого "
        "вертикального ролика. На каждую фразу выбери один ключ жеста из "
        "<gestures> и уровень выразительности: low, medium или high.\n"
        "\n"
        "Почему выбор такой узкий. Photo Avatar IV оживляет по звуку только "
        "лицо и руки на неподвижном портрете. Камера, план, свет, фон и всё, "
        "что попало в кадр вместе с фотографией, остаются ровно такими, какими "
        "были сняты, а момент жеста движок берёт из звуковой дорожки — задать "
        "его нам нечем. Поэтому вся режиссура сводится к двум решениям: какой "
        "из перечисленных жестов ведущая делает и насколько энергично говорит. "
        "Жесты из списка движок рисует узнаваемо; всё остальное выходит "
        "случайной формой руки, которая спорит со словами. Ключ и нужен затем, "
        "чтобы английскую строку для HeyGen подставил наш код.\n"
        "\n"
        "Сначала напиши rationale, потом выбери жест, к которому он привёл. "
        "Держись low и medium, high оставь фразе, на которой у сценария "
        "эмоциональный пик.\n"
        "</instructions>\n"
        "\n"
        "<gestures>\n" + gestures + "\n</gestures>\n"
        "\n"
        "<examples>\n"
        "<example>\n"
        "  <phrase role=\"hook\">Почему твоя реклама не окупается?</phrase>\n"
        "  <output>{\"phrase_id\":\"phrase-000\",\"rationale\":\"Заход-вопрос, "
        "нужно поймать внимание: корпус вперёд сокращает дистанцию, руки в "
        "кадре тут только отвлекут.\",\"gesture\":\"lean_in_confident\","
        "\"expressiveness\":\"medium\"}</output>\n"
        "</example>\n"
        "<example>\n"
        "  <phrase role=\"development\">Деньги теряются на одном шаге — на "
        "заявке.</phrase>\n"
        "  <output>{\"phrase_id\":\"phrase-004\",\"rationale\":\"Один "
        "конкретный тезис, который надо выделить: указующая рука ставит акцент "
        "ровно на нём.\",\"gesture\":\"point_forward\","
        "\"expressiveness\":\"medium\"}</output>\n"
        "</example>\n"
        "<example>\n"
        "  <phrase role=\"development\">Четвёртое — правильная "
        "экономика.</phrase>\n"
        "  <output>{\"phrase_id\":\"phrase-007\",\"rationale\":\"Числительное "
        "просится на счётный жест пальцами, но такого жеста в словаре нет, и "
        "движок показал бы произвольное число пальцев мимо слова. Пункт "
        "перечисления держится голосом, руки оставляем в "
        "покое.\",\"gesture\":\"hands_still\",\"expressiveness\":\"medium\"}"
        "</output>\n"
        "</example>\n"
        "<example>\n"
        "  <phrase role=\"payoff\">Именно так это и работает.</phrase>\n"
        "  <output>{\"phrase_id\":\"phrase-009\",\"rationale\":\"Вывод, "
        "который подтверждает сказанное раньше: кивок закрывает мысль, а новый "
        "жест рукой начал бы новую.\",\"gesture\":\"nod_gentle\","
        "\"expressiveness\":\"low\"}</output>\n"
        "</example>\n"
        "<example>\n"
        "  <phrase role=\"cta\">Сохрани видео и приходи за разбором.</phrase>\n"
        "  <output>{\"phrase_id\":\"phrase-011\",\"rationale\":\"Прямое "
        "обращение к зрителю: раскрытые руки читаются как приглашение и "
        "поддерживают призыв.\",\"gesture\":\"open_arms_invite\","
        "\"expressiveness\":\"medium\"}</output>\n"
        "</example>\n"
        "</examples>\n"
        "\n"
        "Ответь одним JSON-объектом, по записи на каждую фразу, в том же "
        "порядке полей: {\"phrases\":[{\"phrase_id\":\"phrase-000\","
        "\"rationale\":\"...\",\"gesture\":\"nod_gentle\","
        "\"expressiveness\":\"medium\"}]}\n"
        "\n"
        "<phrases>\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n</phrases>"
    )


def _extract_json_object(value: str) -> dict:
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM performance reply не содержит JSON object")
    return json.loads(value[start:end + 1])


def visual_analysis_prompt(plan: dict) -> str:
    """Prompt optional Visual Director pass after deterministic planning."""
    phrase_by_id = {
        phrase["id"]: phrase for phrase in plan.get("phrases") or []
    }
    candidates = []
    for window in plan.get("windows") or []:
        effect = window.get("effect") or {}
        timing = window.get("estimated_timing") or {}
        if (
            window.get("coverage") != "avatar"
            or effect.get("type") != "none"
            or window.get("role") in {"hook", "cta"}
        ):
            continue
        candidates.extend(
            {
                "phrase_id": phrase_id,
                "role": phrase_by_id[phrase_id].get("role"),
                "text": phrase_by_id[phrase_id]["text"],
                "start": timing.get("start"),
                "end": timing.get("end"),
            }
            for phrase_id in window.get("phrase_ids") or []
        )
    constraints = (plan.get("constraints") or {}).get("visual_director") or {}
    return (
        "You are the Visual Director for a short vertical talking-head video. "
        "Recommend zero or more LOCAL built-in motion-graphic windows only for "
        "the candidate phrase IDs below. Use only these templates: "
        + ", ".join(sorted(VISUAL_DIRECTOR_BLOCKS))
        + ". Every recommendation must use contiguous phrase IDs from one block, "
        "must last between "
        f"{constraints.get('min_seconds', 3.0)} and "
        f"{constraints.get('max_seconds', 9.5)} seconds, and must not touch hook "
        "or CTA. IMPORTANT: adjacent fullscreen recommendations accumulate. "
        "Across full_broll and hyperframes windows combined, the presenter may "
        "not be absent for more than "
        f"{(plan.get('constraints') or {}).get('max_face_absence_seconds', MAX_FACE_ABSENCE_S)} "
        "continuous seconds. Leave at least one avatar or mixed phrase between "
        "recommendations whenever that cumulative limit would be exceeded. "
        "Zero recommendations is better than an unsafe timeline. Prefer a visual "
        "only when it materially explains the words; otherwise omit it. Use at most "
        f"{constraints.get('max_llm_windows', 3)} windows. Variables contract: "
        "complexity_cloud={title,items[2..5],resolution}; "
        "persona_card={title,items[2..5]}; "
        "value_layers={title,offer,actual}; "
        "concept_nodes={title,items[2..5]}; "
        "sequence_flow={title,items[2..5]}. Keep title <=60 characters, item "
        "strings <=58, and other strings <=80. Return JSON only: "
        '{"visuals":[{"phrase_ids":["phrase-000"],'
        '"template":"concept_nodes","variables":{"title":"...",'
        '"items":["...","..."]},"rationale":"..."}]}.'
        "\n\nCANDIDATES:\n"
        + json.dumps(candidates, ensure_ascii=False)
    )


def _reindex_edit_windows(plan: dict) -> None:
    windows = plan.get("windows") or []
    windows.sort(key=lambda item: item["estimated_timing"]["start"])
    phrase_by_id = {
        phrase["id"]: phrase for phrase in plan.get("phrases") or []
    }
    for index, window in enumerate(windows):
        window["id"] = f"window-{index:03d}"
        for phrase_id in window.get("phrase_ids") or []:
            phrase_by_id[phrase_id]["window_id"] = window["id"]


def _apply_one_visual_recommendation(
    plan: dict,
    item: dict,
    *,
    source: str,
    used_phrase_ids: set[str],
) -> tuple[dict, dict]:
    """Apply one recommendation transactionally and validate the whole timeline."""
    result = copy.deepcopy(plan)
    if not isinstance(item, dict):
        raise ValueError("каждая visual recommendation должна быть object")
    phrase_by_id = {
        phrase["id"]: phrase for phrase in result.get("phrases") or []
    }
    phrase_order = {
        phrase["id"]: index
        for index, phrase in enumerate(result.get("phrases") or [])
    }
    phrase_ids = item.get("phrase_ids")
    if (
        not isinstance(phrase_ids, list)
        or not phrase_ids
        or any(phrase_id not in phrase_by_id for phrase_id in phrase_ids)
    ):
        raise ValueError("visual recommendation содержит неизвестные phrase IDs")
    if (
        len(set(phrase_ids)) != len(phrase_ids)
        or used_phrase_ids.intersection(phrase_ids)
    ):
        raise ValueError("visual recommendation phrase IDs дублируются")
    indexes = [phrase_order[phrase_id] for phrase_id in phrase_ids]
    if indexes != list(range(indexes[0], indexes[-1] + 1)):
        raise ValueError("visual recommendation phrase IDs должны быть смежными")
    selected = [phrase_by_id[phrase_id] for phrase_id in phrase_ids]
    if len({phrase["block_index"] for phrase in selected}) != 1:
        raise ValueError("visual recommendation не может пересекать blocks")
    if any(phrase.get("role") in {"hook", "cta"} for phrase in selected):
        raise ValueError("visual recommendation не может закрывать hook/CTA")

    constraints = (result.get("constraints") or {}).get("visual_director") or {}
    duration = _visual_duration(selected)
    visual_min = float(
        constraints.get("min_seconds", VISUAL_DIRECTOR_DEFAULTS["min_seconds"])
    )
    visual_max = float(
        constraints.get("max_seconds", VISUAL_DIRECTOR_DEFAULTS["max_seconds"])
    )
    if not visual_min <= duration <= visual_max:
        raise ValueError(
            f"visual recommendation duration {duration:.2f}с вне "
            f"{visual_min:.1f}–{visual_max:.1f}с"
        )

    window_by_id = {
        window["id"]: window for window in result.get("windows") or []
    }
    source_windows = {phrase["window_id"] for phrase in selected}
    selected_set = set(phrase_ids)
    for window_id in source_windows:
        window = window_by_id[window_id]
        effect = window.get("effect") or {}
        if (
            window.get("coverage") != "avatar"
            or effect.get("type") != "none"
            or not set(window.get("phrase_ids") or []).issubset(selected_set)
        ):
            raise ValueError(
                "visual LLM может заменять только целые avatar-only windows"
            )

    template = str(item.get("template") or "")
    variables = item.get("variables")
    if template not in VISUAL_DIRECTOR_BLOCKS or not isinstance(variables, dict):
        raise ValueError("visual recommendation template/variables invalid")
    effect = _visual_director_effect(template, variables, source=source)
    rationale = str(item.get("rationale") or "").strip()
    effect["visual_director"]["rationale"] = rationale
    visual_error = _visual_director_effect_error(effect)
    if visual_error:
        raise ValueError(f"visual recommendation invalid: {visual_error}")

    result["windows"] = [
        window
        for window in result["windows"]
        if window["id"] not in source_windows
    ]
    intent_source = (
        "Assetless HyperFrames fallback"
        if source == "assetless_fallback"
        else "LLM Visual Director"
    )
    _assign_window(
        result["windows"],
        result["phrases"],
        selected,
        coverage="hyperframes",
        visual_intent=f"{intent_source}: {template}.",
        reason=rationale or "Visual Director recommendation.",
        effect=effect,
        camera="hold",
        transition="zoom_blur",
        caption="hidden",
    )
    _reindex_edit_windows(result)
    _refresh_blocks_and_summary(result)
    report = validate_edit_plan(result, require_asset_files=False)
    result["validation"] = report
    if not report["all_pass"]:
        raise ValueError(
            "LLM visual enrichment invalid: "
            + "; ".join(report["errors"][:5])
        )
    return result, {
        "phrase_ids": list(phrase_ids),
        "template": template,
        "rationale": rationale,
    }


def apply_visual_recommendations(
    plan: dict,
    recommendations: dict | list,
    *,
    source: str = "llm",
    strict: bool = True,
    max_recommendations: int | None = None,
) -> dict:
    """Apply safe visuals; tolerant LLM mode rejects only the unsafe item.

    ``strict=True`` remains the contract for explicit/programmatic input.
    The optional LLM boundary uses ``strict=False`` so one bad recommendation
    cannot discard valid recommendations or stop the paid pipeline.
    """
    result = copy.deepcopy(plan)
    items = (
        recommendations.get("visuals")
        if isinstance(recommendations, dict)
        else recommendations
    )
    review = {
        "source": source,
        "mode": "strict" if strict else "tolerant",
        "requested": len(items) if isinstance(items, list) else 0,
        "accepted": [],
        "rejected": [],
    }
    if not isinstance(items, list):
        error = "visual recommendations.visuals должен быть списком"
        if strict:
            raise ValueError(error)
        review["rejected"].append({"index": None, "reason": error})
        result.setdefault("visual_director_reviews", []).append(review)
        result.setdefault("log", []).append(
            f"Visual Director {source}: ответ отклонён ({error})."
        )
        return result

    constraints = (result.get("constraints") or {}).get("visual_director") or {}
    max_items = (
        int(max_recommendations)
        if max_recommendations is not None
        else int(
            constraints.get(
                "max_llm_windows", VISUAL_DIRECTOR_DEFAULTS["max_llm_windows"]
            )
        )
    )
    if len(items) > max_items and strict:
        raise ValueError(
            f"visual recommendations превышают лимит: {len(items)}>{max_items}"
        )

    used_phrase_ids: set[str] = set()
    for index, item in enumerate(items):
        if index >= max_items:
            review["rejected"].append({
                "index": index,
                "phrase_ids": (
                    list(item.get("phrase_ids") or [])
                    if isinstance(item, dict)
                    else []
                ),
                "template": (
                    str(item.get("template") or "")
                    if isinstance(item, dict)
                    else ""
                ),
                "reason": f"превышен лимит рекомендаций {max_items}",
            })
            continue
        try:
            candidate, accepted = _apply_one_visual_recommendation(
                result,
                item,
                source=source,
                used_phrase_ids=used_phrase_ids,
            )
        except (KeyError, TypeError, ValueError) as exc:
            if strict:
                raise
            review["rejected"].append({
                "index": index,
                "phrase_ids": (
                    list(item.get("phrase_ids") or [])
                    if isinstance(item, dict)
                    else []
                ),
                "template": (
                    str(item.get("template") or "")
                    if isinstance(item, dict)
                    else ""
                ),
                "reason": str(exc),
            })
            continue
        result = candidate
        used_phrase_ids.update(accepted["phrase_ids"])
        review["accepted"].append({"index": index, **accepted})

    result.setdefault("visual_director_reviews", []).append(review)
    result.setdefault("log", []).append(
        f"Visual Director {source}: принято {len(review['accepted'])}, "
        f"отклонено {len(review['rejected'])}."
    )
    _refresh_blocks_and_summary(result)
    report = validate_edit_plan(result, require_asset_files=False)
    result["validation"] = report
    if not report["all_pass"]:
        raise ValueError(
            "visual enrichment internal invariant failed: "
            + "; ".join(report["errors"][:5])
        )
    return result


def _assetless_visual_item(
    phrases: list[dict],
    *,
    language: str,
) -> dict:
    copy_text = _language_copy(language)
    labels = [
        _visual_label(phrase["text"], words=7, chars=58).upper()
        for phrase in phrases
        if _visual_label(phrase["text"], words=7, chars=58)
    ]
    if len(labels) < 2:
        words = str(phrases[0]["text"] if phrases else "").split()
        split_at = max(1, len(words) // 2)
        labels = [
            _visual_label(" ".join(words[:split_at]), words=7, chars=58).upper(),
            _visual_label(" ".join(words[split_at:]), words=7, chars=58).upper(),
        ]
    labels = [label for label in dict.fromkeys(labels) if label][:5]
    if len(labels) < 2:
        labels = [copy_text["explanation_title"], "ДЕТАЛИ"]
        if _language_code(language) == "kk":
            labels[-1] = "ЕГЖЕЙ-ТЕГЖЕЙ"

    combined = " ".join(phrase["text"] for phrase in phrases)
    if _language_rules(language)["comparison"].search(combined):
        template = "value_layers"
        variables = {
            "title": copy_text["comparison_title"],
            "offer": labels[0],
            "actual": labels[-1],
        }
        rationale = (
            "B-roll отсутствует; сравнение показано локальной "
            "HyperFrames-композицией."
        )
    else:
        template = "concept_nodes"
        variables = {
            "title": copy_text["explanation_title"],
            "items": labels,
        }
        rationale = (
            "B-roll отсутствует; длинный talking-head участок разбит "
            "локальной смысловой HyperFrames-иллюстрацией."
        )
    return {
        "phrase_ids": [phrase["id"] for phrase in phrases],
        "template": template,
        "variables": variables,
        "rationale": rationale,
    }


def _assetless_visual_recommendations(plan: dict, limit: int) -> list[dict]:
    constraints = (plan.get("constraints") or {}).get("visual_director") or {}
    minimum = float(
        constraints.get("min_seconds", VISUAL_DIRECTOR_DEFAULTS["min_seconds"])
    )
    maximum = float(
        constraints.get("max_seconds", VISUAL_DIRECTOR_DEFAULTS["max_seconds"])
    )
    trigger = float(
        constraints.get(
            "assetless_fallback_after_seconds",
            VISUAL_DIRECTOR_DEFAULTS["assetless_fallback_after_seconds"],
        )
    )
    phrase_by_id = {
        phrase["id"]: phrase for phrase in plan.get("phrases") or []
    }
    groups: list[list[dict]] = []
    current: list[dict] = []
    for window in sorted(
        plan.get("windows") or [],
        key=lambda item: item["estimated_timing"]["start"],
    ):
        effect = window.get("effect") or {}
        eligible = (
            window.get("coverage") == "avatar"
            and effect.get("type") == "none"
            and window.get("role") in {"context", "development", "payoff"}
        )
        contiguous = (
            current
            and current[-1].get("block_index") == window.get("block_index")
            and abs(
                float(current[-1]["estimated_timing"]["end"])
                - float(window["estimated_timing"]["start"])
            )
            <= 0.002
        )
        if not eligible:
            if current:
                groups.append(current)
                current = []
            continue
        if current and not contiguous:
            groups.append(current)
            current = []
        current.append(window)
    if current:
        groups.append(current)

    recommendations: list[dict] = []
    language = str((plan.get("script") or {}).get("language") or "ru")
    comparison_rule = _language_rules(language)["comparison"]

    def range_duration(group: list[dict], start: int, end: int) -> float:
        return (
            float(group[end]["estimated_timing"]["end"])
            - float(group[start]["estimated_timing"]["start"])
        )

    def range_phrases(group: list[dict], start: int, end: int) -> list[dict]:
        return [
            phrase_by_id[phrase_id]
            for window in group[start:end + 1]
            for phrase_id in window.get("phrase_ids") or []
        ]

    for group in groups:
        if range_duration(group, 0, len(group) - 1) + 0.001 < trigger:
            continue

        # Сначала резервируем наиболее информативные сравнительные фрагменты,
        # а generic concept_nodes используем только в оставшихся длинных дырах.
        # Так «25% против 35%» не теряется из-за механического выбора первых
        # трёх секунд блока.
        matching = [
            bool(comparison_rule.search(
                " ".join(
                    phrase_by_id[phrase_id]["text"]
                    for phrase_id in window.get("phrase_ids") or []
                )
            ))
            for window in group
        ]
        comparison_ranges: list[tuple[int, int]] = []
        index = 0
        while index < len(group):
            if not matching[index]:
                index += 1
                continue
            start = index
            while index + 1 < len(group) and matching[index + 1]:
                index += 1
            end = index
            # Одно предыдущее окно обычно содержит первый объект сравнения:
            # «обычная гостиница — 25», затем «у бутик-отеля — 35».
            if start > 0 and range_duration(group, start - 1, end) <= maximum:
                start -= 1
            while (
                range_duration(group, start, end) + 0.001 < minimum
                and end + 1 < len(group)
                and range_duration(group, start, end + 1) <= maximum
            ):
                end += 1
            # Не заканчивать semantic block полноэкранным fallback, если
            # можно оставить последнюю фразу ведущему. Иначе visual следующего
            # semantic block окажется соседним и два окна сложатся >10 секунд.
            if (
                end == len(group) - 1
                and end > start
                and range_duration(group, start, end - 1) >= minimum
            ):
                end -= 1
            duration = range_duration(group, start, end)
            if minimum <= duration <= maximum:
                if (
                    comparison_ranges
                    and start <= comparison_ranges[-1][1] + 1
                ):
                    previous_start, previous_end = comparison_ranges[-1]
                    if range_duration(group, previous_start, end) <= maximum:
                        comparison_ranges[-1] = (previous_start, end)
                else:
                    comparison_ranges.append((start, end))
            index += 1

        def append_generic(start: int, end: int, *, force: bool = False) -> None:
            cursor = start
            while cursor <= end and len(recommendations) < limit:
                remaining = range_duration(group, cursor, end)
                if remaining + 0.001 < trigger and not (
                    force and remaining + 0.001 >= minimum
                ):
                    break
                selected_end = cursor
                while (
                    selected_end <= end
                    and range_duration(group, cursor, selected_end) < minimum
                ):
                    selected_end += 1
                if (
                    selected_end > end
                    or range_duration(group, cursor, selected_end) > maximum
                ):
                    break
                recommendations.append(
                    _assetless_visual_item(
                        range_phrases(group, cursor, selected_end),
                        language=language,
                    )
                )
                # Одно avatar-окно между assetless visuals возвращает eye
                # contact и сбрасывает cumulative face-absence interval.
                cursor = selected_end + 2

        cursor = 0
        for comparison_start, comparison_end in comparison_ranges:
            # Оставляем одно avatar-окно непосредственно перед сравнением.
            gap_to_comparison = (
                range_duration(group, cursor, comparison_start - 1)
                if cursor < comparison_start
                else 0.0
            )
            append_generic(
                cursor,
                comparison_start - 2,
                force=gap_to_comparison + 0.001 >= trigger,
            )
            if len(recommendations) >= limit:
                break
            recommendations.append(
                _assetless_visual_item(
                    range_phrases(group, comparison_start, comparison_end),
                    language=language,
                )
            )
            cursor = comparison_end + 2
        if len(recommendations) < limit:
            append_generic(cursor, len(group) - 1)
    return recommendations


def ensure_assetless_visual_coverage(plan: dict) -> dict:
    """Fill long no-B-roll talking-head gaps with safe local HyperFrames."""
    result = copy.deepcopy(plan)
    constraints = (result.get("constraints") or {}).get("visual_director") or {}
    if not constraints.get("enabled", True):
        return result
    existing = sum(
        1
        for window in result.get("windows") or []
        if (window.get("effect") or {}).get("visual_director")
    )
    available = max(0, int(constraints.get("max_count") or 0) - existing)
    if not available:
        return result
    recommendations = _assetless_visual_recommendations(result, available)
    if not recommendations:
        return result
    return apply_visual_recommendations(
        result,
        {"visuals": recommendations},
        source="assetless_fallback",
        strict=False,
        max_recommendations=available,
    )


def enrich_visuals_with_llm(plan: dict, runner) -> dict:
    """Run optional Visual Director LLM and degrade safely to HyperFrames."""
    try:
        reply = runner.run(visual_analysis_prompt(plan))
        parsed = _extract_json_object(reply)
    except Exception as exc:
        result = copy.deepcopy(plan)
        result.setdefault("visual_director_reviews", []).append({
            "source": "llm",
            "mode": "tolerant",
            "requested": 0,
            "accepted": [],
            "rejected": [{"index": None, "reason": str(exc)}],
        })
        result.setdefault("log", []).append(
            "Visual Director LLM недоступен/невалиден; "
            "использован локальный HyperFrames fallback."
        )
        return ensure_assetless_visual_coverage(result)
    enriched = apply_visual_recommendations(
        plan,
        parsed,
        source="llm",
        strict=False,
    )
    return ensure_assetless_visual_coverage(enriched)


def _performance_warn(message: str) -> None:
    print(f"[performance] {message}", file=sys.stderr)


def role_default_performance(role: str | None, rationale: str) -> dict:
    """Пластика по роли — тот же профиль, что кладёт черновик плана.

    Используется как единственный откат: брак рекомендации стоит одной ровной
    фразы, а не всей сборки.
    """
    default = PERFORMANCE_BY_ROLE.get(role, DEFAULT_PERFORMANCE)
    return {
        "expressiveness": default["expressiveness"],
        "gesture": default["gesture"],
        "motion_prompt": default["motion_prompt"],
        "prompt_language": "en",
        "source": "role_default",
        "rationale": rationale,
        "engine_scope": "photo_avatar_iv",
    }


def apply_performance_recommendations(
    plan: dict,
    recommendations: dict | list,
    *,
    source: str = "llm",
) -> dict:
    """Разложить рекомендации по фразам. Брак не роняет сборку.

    Неизвестный ключ жеста, пропущенная фраза, кривая выразительность и вовсе
    отсутствующий список — всё это откатывается на ролевой default с
    предупреждением в stderr. Фатальным остаётся только неразбираемый ответ
    (его ловит `_extract_json_object` выше по стеку).
    """
    result = copy.deepcopy(plan)
    items = (
        recommendations.get("phrases")
        if isinstance(recommendations, dict)
        else recommendations
    )
    if not isinstance(items, list):
        _performance_warn(
            "в ответе нет списка phrases — вся пластика берётся по ролям"
        )
        items = []
    by_id: dict = {}
    for item in items:
        if isinstance(item, dict):
            by_id[item.get("phrase_id")] = item
    expected = {phrase["id"] for phrase in result.get("phrases") or []}
    extra = sorted(key for key in by_id if key not in expected)
    if extra:
        _performance_warn(f"рекомендации на неизвестные фразы пропущены: {extra}")
    for phrase in result["phrases"]:
        current = phrase.get("avatar_performance") or {}
        if current.get("source") == "config":
            continue
        role = phrase.get("role")
        item = by_id.get(phrase["id"])
        if not isinstance(item, dict):
            _performance_warn(
                f"{phrase['id']}: рекомендации нет — жест по роли "
                f"{role or 'unknown'}"
            )
            phrase["avatar_performance"] = role_default_performance(
                role, "Модель не прислала рекомендацию для этой фразы."
            )
            continue
        gesture = str(item.get("gesture") or "").strip()
        entry = GESTURE_VOCABULARY.get(gesture)
        if entry is None:
            _performance_warn(
                f"{phrase['id']}: жест {gesture or '<пусто>'!r} не из словаря — "
                f"взят жест по роли {role or 'unknown'}"
            )
            phrase["avatar_performance"] = role_default_performance(
                role,
                f"Модель выбрала жест вне словаря ({gesture or '<пусто>'}); "
                "взят ролевой default.",
            )
            continue
        # Страховка на протухший словарь: строку шлём мы, и она обязана
        # проходить тот же контроль, что и любая другая.
        prompt_error = _motion_prompt_error(entry["motion_prompt"])
        if prompt_error:
            _performance_warn(
                f"{phrase['id']}: строка жеста {gesture} не проходит проверку "
                f"({prompt_error}) — взят жест по роли {role or 'unknown'}"
            )
            phrase["avatar_performance"] = role_default_performance(
                role, f"Строка словаря для {gesture} невалидна: {prompt_error}."
            )
            continue
        expressiveness = str(item.get("expressiveness") or "").strip().lower()
        if expressiveness not in EXPRESSIVENESS_VALUES:
            fallback = PERFORMANCE_BY_ROLE.get(role, DEFAULT_PERFORMANCE)
            _performance_warn(
                f"{phrase['id']}: expressiveness "
                f"{expressiveness or '<пусто>'!r} не low|medium|high — взят "
                f"уровень по роли {role or 'unknown'}"
            )
            expressiveness = fallback["expressiveness"]
        phrase["avatar_performance"] = {
            "expressiveness": expressiveness,
            "gesture": gesture,
            "motion_prompt": entry["motion_prompt"],
            "prompt_language": "en",
            "source": source,
            "rationale": str(item.get("rationale") or "").strip(),
            "engine_scope": "photo_avatar_iv",
        }
    return result


def enrich_performance_with_llm(plan: dict, runner) -> dict:
    """Вызвать injected LLM runner. Тесты используют FakeRunner; сеть не нужна."""
    try:
        reply = runner.run(performance_analysis_prompt(plan))
    except Exception as exc:  # сеть, таймаут, упавший CLI
        _performance_warn(
            f"модель не ответила ({exc}) — пластика всех фраз берётся по ролям"
        )
        reply = "{\"phrases\":[]}"
    enriched = apply_performance_recommendations(
        plan, _extract_json_object(reply), source="llm"
    )
    report = validate_edit_plan(enriched, require_asset_files=False)
    enriched["validation"] = report
    if not report["all_pass"]:
        raise ValueError(
            "LLM performance enrichment invalid: "
            + "; ".join(report["errors"][:5])
        )
    return enriched
