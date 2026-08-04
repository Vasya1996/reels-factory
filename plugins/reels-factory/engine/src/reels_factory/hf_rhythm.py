"""Ритм готового ролика: сколько раз меняется картинка и где она стоит.

Числа сняты покадрово с трёх эталонных рилсов приёмки
(`docs/goal-hyperframes.md`), во фреймворке их нет: `hyperframes check` судит
вёрстку кадра, а не монтаж, и формула плотности из `talking-head-recut`
отвечает только за число карточек. Поэтому смены считаем по самому файлу —
детектором сцен ffmpeg, тем же, чем ролик судили на приёмке.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from reels_factory.config import FFMPEG, FFPROBE

#: Порог детектора сцен. 0,06 — то значение, на котором принятый ролик
#: 03.08.2026 дал 23 смены при 41,6 с; ниже начинает считать дрейф зума за
#: склейку, выше перестаёт видеть замену вставки.
SCENE_THRESHOLD = 0.06

#: Планка эталонов: смена картинки не реже раза в две секунды и ни одного
#: неподвижного куска длиннее восьми.
MAX_SECONDS_PER_CHANGE = 2.0
MAX_STATIC_SPAN = 8.0

#: Наименьший зазор между соседними карточками. Карточка даёт две смены —
#: приход сцены и её уход, — но только если между сценами есть кадр без них:
#: впритык поставленные блоки детектор видит как одну склейку. Планку меряет
#: D21 по плану, до рендера: узнать об этом на готовом mp4 стоило бы четыре
#: минуты рендера и целую сессию агента.
MIN_CARD_GAP = 0.8

_PTS = re.compile(r"pts_time:([0-9.]+)")


def _duration(mp4: Path) -> float:
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(mp4)],
        capture_output=True, text=True, check=True)
    return float((result.stdout or "0").strip())


def scene_changes(mp4) -> list[float]:
    """Моменты заметной смены картинки, в секундах."""
    mp4 = Path(mp4)
    result = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(mp4), "-vf",
         f"select='gt(scene,{SCENE_THRESHOLD})',metadata=print:file=-",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [float(value) for value in _PTS.findall(result.stdout or "")]


def measure(mp4) -> dict:
    """Замер ритма: смены, требуемый минимум и самый длинный статичный кусок."""
    mp4 = Path(mp4)
    duration = _duration(mp4)
    cuts = scene_changes(mp4)
    edges = [0.0, *cuts, duration]
    spans = [(edges[i + 1] - edges[i], edges[i], edges[i + 1])
             for i in range(len(edges) - 1)]
    longest = max(spans, default=(duration, 0.0, duration))
    return {
        "duration": round(duration, 2),
        "changes": len(cuts),
        "changes_required": int(duration / MAX_SECONDS_PER_CHANGE),
        "longest_static": round(longest[0], 2),
        "longest_static_at": [round(longest[1], 2), round(longest[2], 2)],
        "longest_static_limit": MAX_STATIC_SPAN,
    }


def rhythm_gates(mp4) -> dict[str, str]:
    """PASS/FAIL по планке эталонов. Мерится на готовом файле, а не на плане."""
    report = measure(mp4)
    gates = {}
    if report["changes"] >= report["changes_required"]:
        gates["D18_change_rate"] = (
            f'PASS: {report["changes"]} смен при минимуме '
            f'{report["changes_required"]}')
    else:
        gates["D18_change_rate"] = (
            f'FAIL: картинка меняется {report["changes"]} раз за '
            f'{report["duration"]:g} с, эталон требует не меньше '
            f'{report["changes_required"]}')
    if report["longest_static"] <= MAX_STATIC_SPAN:
        gates["D19_static_span"] = (
            f'PASS: самый длинный кусок без смены {report["longest_static"]:g} с')
    else:
        start, end = report["longest_static_at"]
        gates["D19_static_span"] = (
            f'FAIL: {report["longest_static"]:g} с без смены картинки '
            f"({start:g}–{end:g} с), предел {MAX_STATIC_SPAN:g}")
    return gates
