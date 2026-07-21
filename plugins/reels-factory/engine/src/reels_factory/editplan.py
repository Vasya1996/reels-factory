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

`validate_plan` — гейты плана: ловят провал ритма ДО рендера, чтобы не
смотреть глазами на готовый ролик и не гонять ffmpeg впустую.
"""
import re
import subprocess

from reels_factory.config import FFMPEG

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
