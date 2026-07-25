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
import re
import subprocess
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

# HeyGen рекомендует короткий prompt: одно видимое движение + выражение лица,
# максимум две короткие части. Ролевые defaults намеренно консервативны:
# ``high`` не используется автоматически, чтобы не провоцировать переигрывание.
PERFORMANCE_BY_ROLE = {
    "hook": {
        "expressiveness": "medium",
        "motion_prompt": (
            "Looks at the camera and leans in slightly, confident and engaged."
        ),
    },
    "context": {
        "expressiveness": "low",
        "motion_prompt": (
            "Looks at the camera with a calm expression and subtle natural gestures."
        ),
    },
    "development": {
        "expressiveness": "medium",
        "motion_prompt": (
            "Looks at the camera and gestures lightly with one hand, confident and clear."
        ),
    },
    "payoff": {
        "expressiveness": "low",
        "motion_prompt": (
            "Looks at the camera and nods gently, sincere and confident."
        ),
    },
    "cta": {
        "expressiveness": "medium",
        "motion_prompt": (
            "Looks at the camera and makes one inviting open-hand gesture, warm and direct."
        ),
    },
}
DEFAULT_PERFORMANCE = PERFORMANCE_BY_ROLE["development"]

_QUERY_STOP = set((
    "и в на что как это то он она они мы вы бы же ли за по из у о а но да не нет "
    "для от до со во об про при или чтобы если когда уже ещё вот там тут так"
).split())
_NUM_RE = re.compile(r"(?<![\d.,])(\d{1,4})(?![\d.,])")
_BEFORE_MARK = re.compile(r"\b(был[оаи]?|раньше|прежде|обычно)\b", re.IGNORECASE)
_AFTER_MARK = re.compile(r"\b(ста(?:л[оаи]?|нет|ло)|теперь|сейчас)\b", re.IGNORECASE)
_CMD_VERBS = ("напиш", "спрос", "попрос")
_FORBIDDEN_MOTION = re.compile(
    r"\b(zoom|pan|dolly|lighting|background|walk|walking|"
    r"seconds?|kitchen|outside|pick(?:s|ing)? up|phone|coffee|prop)\b",
    re.IGNORECASE,
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _norm_word(value: str) -> str:
    return re.sub(r"[^a-zа-яё]", "", value.lower())


def broll_query(text: str, hint: str = "") -> str:
    """Короткий семантический запрос к локальному CLIP-индексу."""
    tokens = [
        token.strip(",.!?…:;«»\"'()-").lower()
        for token in str(text or "").split()
    ]
    kept = [token for token in tokens if len(token) > 2 and token not in _QUERY_STOP]
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


def before_after_from_text(text: str) -> dict | None:
    before, after = _BEFORE_MARK.search(text), _AFTER_MARK.search(text)
    if not (before and after and before.start() < after.start()):
        return None
    before_value = " ".join(
        text[before.end():after.start()].strip(" ,.:;-—").split()[:5]
    )
    after_value = " ".join(text[after.end():].strip(" ,.:;-—").split()[:5])
    if not before_value or not after_value:
        return None
    return {"before_value": before_value, "after_value": after_value}


def _phrase_spans(speech: str) -> list[tuple[int, int]]:
    """Стабильная draft-нарезка без audio timing.

    Фразы заканчиваются по сильной пунктуации либо каждые шесть слов. Возвращаем
    точные offsets исходной строки, поэтому LLM/edit/render могут ссылаться на
    один и тот же текст без fuzzy matching.
    """
    tokens = list(re.finditer(r"\S+", speech))
    if not tokens:
        return []
    spans: list[tuple[int, int]] = []
    start_index = 0
    for index, token in enumerate(tokens):
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
        spans = _phrase_spans(speech)
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
            "query": item.get("query") or broll_query(block.get("speech") or ""),
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


def _chart_variables(text: str, start: float, end: float) -> dict | None:
    parts = [
        part.strip(" .,")
        for part in re.split(r"[,;]| и ", text)
        if 0 < len(part.strip(" .,").split()) <= 3
        and len(part.strip(" .,")) > 2
    ]
    if len(parts) < 3 or text.count(",") < 3:
        return None
    items = parts[:5]
    span = max(0.1, end - start)
    return {
        "title": "ЧТО МОЖНО ЗАКРЫТЬ",
        "items": [
            {
                "t": round(start + span * index / len(items), 2),
                "label": label.capitalize()[:22],
                "v": [0.7, 0.55, 0.85, 0.75, 1.0][index % 5],
            }
            for index, label in enumerate(items)
        ],
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
    window["asset"] = None
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
    allow_full_cover = str(config.get("format") or "split") == "avatar"
    explicit_full_cover = (
        _legacy_full_cover(scenario, legacy_broll_plan)
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
        query = broll_query(block.get("speech") or "")
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
        "bubble": False,
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
                               or "ПОДПИСАТЬСЯ"),
                },
                camera="ken_burns",
            )
            continue

        combined = " ".join(item["text"] for item in block_phrases)
        before_after = (
            before_after_from_text(combined)
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
            )
            continue

        chart = (
            _chart_variables(
                combined,
                block_phrases[0]["estimated_timing"]["start"],
                block_phrases[-1]["estimated_timing"]["end"],
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
            )
            continue

        local_index = 0
        while local_index < len(block_phrases):
            phrase = block_phrases[local_index]
            text = phrase["text"]
            low = f" {text.lower()} "

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
                    )
                    local_index += len(selected)
                    continue

            if (
                role == "payoff"
                and not used_effects["bubble"]
                and re.search(r"настро|один раз|больше не|готов", low)
            ):
                query = broll_query(text, "крупный план, атмосфера")
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
                    used_effects["bubble"] = True
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
                and re.search(r"автоматизир|везде|многое", low)
            ):
                broll_rule = "automation_broll"
                hint = "технологии, абстрактный фон"
            elif (
                not used_effects["instruction_broll"]
                and re.search(r"инструкц|набор|блокнот|список|заметк|шаг", low)
            ):
                broll_rule = "instruction_broll"
                hint = "рабочий стол, заметки"
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
                query = broll_query(" ".join(item["text"] for item in selected), hint)
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
            phrase["coverage"] == "full_broll"
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
    for window in windows:
        timing = window.get(timing_key) or window.get("estimated_timing") or {}
        duration = max(0.0, float(timing.get("end", 0)) - float(timing.get("start", 0)))
        if window.get("coverage") == "full_broll":
            full_broll_seconds += duration
        if window.get("coverage") in {"avatar", "mixed"}:
            avatar_visible_seconds += duration
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
    window["asset"] = None
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
        if window.get("safe_to_skip_avatar") and (
            coverage != "full_broll"
            or (window.get("effect") or {}).get("type") != "broll"
        ):
            errors.append(
                f"{window.get('id')}: HeyGen skip разрешён не для full B-roll"
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

        asset = window.get("asset") or {}
        if coverage in {"full_broll", "mixed"} and (window.get("effect") or {}).get(
            "type"
        ) == "broll":
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
                window.get("coverage") != "full_broll"
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


def covered_block_indexes(plan: dict) -> set[int]:
    return {
        int(block["index"])
        for block in plan.get("blocks") or []
        if not block.get("avatar_required", True)
    }


def performance_analysis_prompt(plan: dict) -> str:
    """Prompt отдельного LLM-анализа после approval и до TTS/HeyGen."""
    payload = [
        {
            "phrase_id": phrase["id"],
            "role": phrase.get("role"),
            "text": phrase["text"],
        }
        for phrase in plan.get("phrases") or []
    ]
    return (
        "You are directing a realistic HeyGen Photo Avatar IV performance for a "
        "short vertical video. For every phrase, recommend expressiveness and one "
        "short motion prompt. expressiveness must be low, medium, or high. The "
        "motion_prompt must be plain English, describe one visible face/body/hand "
        "action plus an optional emotion, contain at most two short clauses, and "
        "must not specify timing, camera motion, scene/location, props, walking, "
        "background, or lighting. Prefer subtle stable motion; use high only when "
        "the phrase clearly needs it. Return JSON only: "
        "{\"phrases\":[{\"phrase_id\":\"phrase-000\",\"expressiveness\":\"medium\","
        "\"motion_prompt\":\"Looks at the camera and nods gently, confident and "
        "clear.\",\"rationale\":\"...\"}]}.\n\nPHRASES:\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def _extract_json_object(value: str) -> dict:
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM performance reply не содержит JSON object")
    return json.loads(value[start:end + 1])


def apply_performance_recommendations(
    plan: dict,
    recommendations: dict | list,
    *,
    source: str = "llm",
) -> dict:
    result = copy.deepcopy(plan)
    items = (
        recommendations.get("phrases")
        if isinstance(recommendations, dict)
        else recommendations
    )
    if not isinstance(items, list):
        raise ValueError("performance recommendations.phrases должен быть списком")
    by_id = {item.get("phrase_id"): item for item in items if isinstance(item, dict)}
    expected = {phrase["id"] for phrase in result.get("phrases") or []}
    if len(by_id) != len(items) or set(by_id) != expected:
        missing = sorted(expected - set(by_id))
        extra = sorted(set(by_id) - expected)
        raise ValueError(
            "performance phrase IDs не совпадают или дублируются; "
            f"missing={missing}, extra={extra}"
        )
    for phrase in result["phrases"]:
        current = phrase.get("avatar_performance") or {}
        if current.get("source") == "config":
            continue
        item = by_id[phrase["id"]]
        expressiveness = str(item.get("expressiveness") or "").lower()
        prompt = str(item.get("motion_prompt") or "").strip()
        if expressiveness not in EXPRESSIVENESS_VALUES:
            raise ValueError(
                f"{phrase['id']}: expressiveness должен быть low|medium|high"
            )
        prompt_error = _motion_prompt_error(prompt)
        if prompt_error:
            raise ValueError(f"{phrase['id']}: {prompt_error}")
        phrase["avatar_performance"] = {
            "expressiveness": expressiveness,
            "motion_prompt": prompt,
            "prompt_language": "en",
            "source": source,
            "rationale": str(item.get("rationale") or "").strip(),
            "engine_scope": "photo_avatar_iv",
        }
    return result


def enrich_performance_with_llm(plan: dict, runner) -> dict:
    """Вызвать injected LLM runner. Тесты используют FakeRunner; сеть не нужна."""
    reply = runner.run(performance_analysis_prompt(plan))
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
