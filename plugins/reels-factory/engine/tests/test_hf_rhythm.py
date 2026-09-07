import re
import subprocess

import pytest

from reels_factory.hf_rhythm import (SCD_THRESHOLD, SCENE_THRESHOLD,
                                      _merge_channels, scene_changes)


def test_merge_срез_пойманный_обоими_каналами_считается_один_раз():
    # 5,05 с — тот же физический срез, что и 5,0 с у scene-канала (в зазоре
    # 0,2 с): scd не должен задвоить его в списке смен.
    assert _merge_channels([5.0], [5.05], gap=0.2) == [5.0]


def test_merge_находка_scdet_вне_зазора_добавляется():
    # 10,0 с дальше 0,2 с от единственной находки scene-канала — это другой
    # срез, `scene_score` его прозевал (тёмный кадр), scd обязан добавить.
    assert _merge_channels([5.0], [10.0], gap=0.2) == [5.0, 10.0]


def test_merge_граница_зазора():
    # ровно на границе (0,2 с от 0,0) — ещё не «дальше зазора», один срез.
    # (база 0,0 — чтобы вычитание не давало паразитную погрешность плавающей
    # точки на самой границе: 5.2 - 5.0 != 0.2 ровно из-за неё)
    assert _merge_channels([0.0], [0.2], gap=0.2) == [0.0]
    # чуть дальше границы — уже отдельный срез.
    assert _merge_channels([0.0], [0.201], gap=0.2) == [0.0, 0.201]

_PTS = re.compile(r"pts_time:([0-9.]+)")
_SCENE = re.compile(r"lavfi\.scene_score=([0-9.]+)")
_SCD = re.compile(r"lavfi\.scd\.score=([0-9.]+)")


def _scores(mp4) -> list[tuple[float, float, float]]:
    """(pts, scene_score, scd.score) для каждого кадра — для проверки внутри теста."""
    from reels_factory.config import FFMPEG

    result = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(mp4), "-vf",
         "scdet=threshold=0:sc_pass=0,select='gte(scene\\,0)',"
         "metadata=print:file=-",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out, rows, pts, scene, scd = result.stdout or "", [], None, None, None
    for line in out.splitlines():
        m = _PTS.search(line)
        if m:
            if pts is not None:
                rows.append((pts, scene or 0.0, scd or 0.0))
            pts, scene, scd = float(m.group(1)), None, None
            continue
        m = _SCENE.search(line)
        if m:
            scene = float(m.group(1))
            continue
        m = _SCD.search(line)
        if m:
            scd = float(m.group(1))
    if pts is not None:
        rows.append((pts, scene or 0.0, scd or 0.0))
    return rows


@pytest.mark.slow
def test_слабый_по_пикселям_срез_ловится_вторым_каналом(tmp_path):
    """rb0907-university, стык s-20→s-21 (65,867 с): три карточки схемы

    исчезают и уголок ведущей прыгает по кадру между разными углами — глазу
    жёсткий срез, а `scene_score` даёт 0,0496 при пороге 0,06 (ревью PR #94).
    Синтетика воспроизводит ровно этот профиль: тёмный фон на весь кадр не
    меняется, меняются только мелкие по площади элементы (карточки и уголок) —
    средняя яркостная дельта тонет ниже порога, а структурный разрыв остаётся.
    """
    from reels_factory.config import FFMPEG

    cut = tmp_path / "cut.mp4"
    vf = (
        "drawbox=x=40:y=100:w=80:h=40:color=0x9999aa@0.8:t=fill:"
        "enable='lt(t\\,1)',"
        "drawbox=x=180:y=100:w=80:h=40:color=0x9999aa@0.8:t=fill:"
        "enable='lt(t\\,1)',"
        "drawbox=x=320:y=100:w=80:h=40:color=0x9999aa@0.8:t=fill:"
        "enable='lt(t\\,1)',"
        "drawbox=x=380:y=770:w=60:h=60:color=0xdddddd@0.9:t=fill:"
        "enable='lt(t\\,1)',"
        "drawbox=x=30:y=770:w=60:h=60:color=0xdddddd@0.9:t=fill:"
        "enable='gte(t\\,1)'"
    )
    subprocess.run(
        [FFMPEG, "-y", "-f", "lavfi", "-i",
         "color=c=0x141414:s=480x854:d=2:r=30",
         "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cut)],
        check=True, capture_output=True)

    rows = _scores(cut)
    at_cut = min(rows, key=lambda row: abs(row[0] - 1.0))
    assert at_cut[1] <= SCENE_THRESHOLD, (
        f"тест не воспроизводит дефект: старый канал уже видит срез "
        f"({at_cut[1]} > {SCENE_THRESHOLD})")
    assert at_cut[2] > SCD_THRESHOLD, (
        f"второй канал тоже не видит срез: scd={at_cut[2]}")

    cuts = scene_changes(cut)
    assert any(abs(t - 1.0) < 0.1 for t in cuts), (
        f"срез на 1,0 с не найден среди {cuts} — ровно то, из-за чего "
        "PR #94 чинил не то (fond, а не меру)")


@pytest.mark.slow
def test_плавный_дрейф_без_среза_не_считается_сменой(tmp_path):
    """Наезд камеры и дрейф фона — непрерывное движение, не склейка.

    Маленький квадрат едет по тёмному кадру без единого скачка (аналог наезда
    камеры/дрейфа `.aurora`): у второго канала своя, отдельная от старого
    порога чувствительность, и он не имеет права принять растянутое по кадрам
    движение за структурный разрыв — иначе список смен раздулся бы на каждом
    ролике с наездом камеры или биролл-панорамой.
    """
    from reels_factory.config import FFMPEG

    drift = tmp_path / "drift.mp4"
    subprocess.run(
        [FFMPEG, "-y",
         "-f", "lavfi", "-i", "color=c=0x141414:s=480x854:d=2:r=30",
         "-f", "lavfi", "-i", "color=c=0xdddddd:s=60x60:d=2:r=30",
         "-filter_complex", "[0][1]overlay=x='40+320*t/2':y=770:eval=frame",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(drift)],
        check=True, capture_output=True)

    rows = _scores(drift)
    assert max(row[1] for row in rows) < SCENE_THRESHOLD
    assert max(row[2] for row in rows) < SCD_THRESHOLD

    assert scene_changes(drift) == [], (
        "плавное движение без склейки не должно давать ни одной смены")
