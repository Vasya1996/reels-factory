"""Ритм готового ролика: сколько раз меняется картинка и где она стоит.

Числа сняты покадрово с трёх эталонных рилсов приёмки
(`docs/goal-hyperframes.md`), во фреймворке их нет: `hyperframes check` судит
вёрстку кадра, а не монтаж, и формула плотности из `talking-head-recut`
отвечает только за число карточек. Поэтому смены считаем по самому файлу —
детектором сцен ffmpeg, тем же, чем ролик судили на приёмке.

`lavfi.scene_score` — средняя яркостная разница соседних кадров: он слеп
именно там, где смена реальна, но обе стороны стыка тёмные (карточки схемы на
тёмном фоне, тёмный аватар в тёмном уголке). `rb0907-university`, стык
s-20→s-21 (65,867 с): три карточки схемы исчезают и окно ведущей прыгает по
кадру между разными углами — глазу это жёсткий срез, а `scene_score` даёт
0,0496 против порога 0,06 (`feat/vasya-d18-university`, ревью PR #94). Порог
ниже не годится: у того же ролика зум-рампа (плавный наезд без склейки, ни
одного кадра сцены не меняющий) уже на 0,02–0,04 даёт 30–40 ложных срабатываний
на файл — средняя яркостная дельта не отличает «структурный разрыв» от
«растянутого по кадрам движения», это один и тот же по природе сигнал в
разной концентрации.

`scdet` (штатный фильтр ffmpeg, `lavfi.scd.score`) считает иначе — не голую
яркостную разницу, а нормализованную частоту кадра поверх скользящего среднего
(mafd), из-за чего одиночный разрыв кадра даёт всплеск на порядок выше своего
же окружения, а растянутый по кадрам зум остаётся плоским. На том же стыке
65,867 с он даёт 1,937 при соседних кадрах 0,08/0,24 — запас почти вчетверо, и
не путает наезд со склейкой (проверено на трёх роликах `rb0907-*`, каталог
третий эталонов результата не даёт: `hyperframes` меряет вёрстку кадра, не
готовый файл, ни `check`, ни `SKILL.md` монтажных скиллов метрики склейки не
содержат). Используем его как ВТОРОЙ канал, а не замену первого: у него своя
чувствительность к движению внутри вставки (проверено — не подавляет
`scene_score` там, где тот уже ловит смену), поэтому в список идут только его
находки, которых `scene_score` не назвал сам — иначе старый калиброванный счёт
смен посыпался бы вдвое на каждом ролике и планка `MAX_SECONDS_PER_CHANGE`
перестала бы что-либо отличать.
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

#: Порог второго канала (`scdet`) — ловит структурный разрыв, который
#: `SCENE_THRESHOLD` не видит на тёмных кадрах (см. модульный докстринг).
#: Замерено сплошным проходом на трёх роликах `rb0907-*` (кадры внутри 0,5 с
#: от настоящего среза или 0,35 с от вспышки `flash` — исключены, кадры, уже
#: пойманные `scene_score`, не участвуют в потолке — их ловит первый канал
#: независимо от этого порога): потолок ложного срабатывания — 1,477
#: (`rb0907-university`, 30,8 с — наезд камеры с всплытием титра, среза нет);
#: пол самого слабого найденного разрыва — 1,937 (`rb0907-university`,
#: 65,867 с, стык s-20→s-21 — тот самый дефект, что чинит этот файл). Порог —
#: 1,707, середина между ними: запас ~13% с обеих сторон, а не ~39%, как
#: считалось раньше на неверном потолке 1,078.
#:
#: Запас не универсален: тот же класс события (всплытие титра/подписи без
#: среза) даёт на `rb0907-philosophers` 1,91, а на `rb0907-ai-employee` —
#: 2,31, выше и порога, и пола. `D18_change_rate` требует МИНИМУМ смен, а не
#: точный счёт, поэтому лишняя находка тут гейт не портит; недолов настоящего
#: среза (тот случай, который чинит этот файл) — портил бы. Побочный эффект
#: подъёма порога с 1,5 до 1,707: слабый шов вставки на `rb0907-philosophers`
#: (10,937 с, scd 1,64) перестаёт ловиться — тот же класс пробела, что уже
#: не ловят швы `rb0907-university` на 11,831 с и 59,6 с, вне заявленного
#: дефекта (стык s-20→s-21) и не регрессия этой правки.
SCD_THRESHOLD = 1.707

#: Второй канал добавляет находку, только если она дальше этого зазора от уже
#: найденной `scene`-каналом: иначе один и тот же физический срез считался бы
#: дважды и ломал калибровку `MAX_SECONDS_PER_CHANGE`.
SCD_MERGE_GAP = 0.2

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
_SCENE = re.compile(r"lavfi\.scene_score=([0-9.]+)")
_SCD = re.compile(r"lavfi\.scd\.score=([0-9.]+)")


def _duration(mp4: Path) -> float:
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(mp4)],
        capture_output=True, text=True, check=True)
    return float((result.stdout or "0").strip())


def _merge_channels(scene_hits: list[float], scd_hits: list[float],
                     gap: float) -> list[float]:
    """Склейка находок двух каналов в один список срезов.

    `scene_hits` остаются как есть — это откалиброванный счёт, который
    `MAX_SECONDS_PER_CHANGE` уже мерит. `scd_hits` добавляют находку, только
    если она дальше `gap` от любой из `scene_hits`: иначе один и тот же
    физический срез, пойманный обоими каналами разом, засчитался бы дважды.
    """
    extra = [t for t in scd_hits
             if all(abs(t - s) > gap for s in scene_hits)]
    return sorted(scene_hits + extra)


def scene_changes(mp4) -> list[float]:
    """Моменты заметной смены картинки, в секундах.

    Один проход ffmpeg считает оба канала разом (`scdet` перед `select`, чтобы
    декодировать файл один раз, а не два): `scene_score` — как раньше, `scd`
    — только чтобы добрать разрывы, которые первый канал прозевал на тёмном
    кадре (см. докстринг модуля).
    """
    mp4 = Path(mp4)
    result = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(mp4), "-vf",
         "scdet=threshold=0:sc_pass=0,select='gte(scene\\,0)',"
         "metadata=print:file=-",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = result.stdout or ""

    scene_hits: list[float] = []
    scd_hits: list[float] = []
    pts = None
    for line in output.splitlines():
        found = _PTS.search(line)
        if found:
            pts = float(found.group(1))
            continue
        if pts is None:
            continue
        found = _SCENE.search(line)
        if found and float(found.group(1)) > SCENE_THRESHOLD:
            scene_hits.append(pts)
            continue
        found = _SCD.search(line)
        if found and float(found.group(1)) > SCD_THRESHOLD:
            scd_hits.append(pts)

    return _merge_channels(scene_hits, scd_hits, SCD_MERGE_GAP)


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
