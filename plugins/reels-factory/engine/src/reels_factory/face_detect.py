"""Координаты лица ведущей и свободные полосы кадра.

Детектор уже есть в движке (zoom.detect_face_anchor) и возвращает доли кадра.
Здесь они переводятся в пиксели и кладутся в face.json, чтобы задание агенту
и гейты читали одно и то же число.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from reels_factory.config import OUT_H, OUT_W

# высота головы как доля высоты кадра для говорящей головы в вертикали
FACE_HEIGHT_RATIO = 0.14
# минимальная полезная высота свободной полосы
MIN_BAND_H = 180


def face_box_for(video, out_json, *, width: int = OUT_W, height: int = OUT_H,
                 detect=None) -> dict:
    """Найти лицо и записать face.json в пикселях."""
    from reels_factory.zoom import detect_face_anchor

    fx, fy = detect_face_anchor(video, detect=detect)
    face = {"cx": round(float(fx) * width),
            "cy": round(float(fy) * height),
            "h": round(height * FACE_HEIGHT_RATIO)}
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(face, ensure_ascii=False), encoding="utf-8")
    return face


def load_face(rdir) -> dict | None:
    path = Path(rdir) / "face.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def free_bands(face: dict | None, *, width: int = OUT_W,
               height: int = OUT_H) -> list[dict]:
    """Полосы кадра, свободные от лица: над головой и под ней.

    Подсказка для агента, а не ограничение: она нужна только тем карточкам,
    которые ставятся поверх ведущей. Полноэкранным она безразлична.
    """
    from reels_factory.hf_layout import face_box

    box = face_box(face)
    if box is None:
        return [{"left": 0, "top": 0, "width": width, "height": height}]

    bands = []
    above = box["top"]
    if above >= MIN_BAND_H:
        bands.append({"left": 0, "top": 0,
                      "width": width, "height": int(above)})
    # округляем ВВЕРХ: int() отрезал бы дробную часть и полоса залезла бы
    # на лицо на доли пикселя — гейт это поймает, а причина будет неочевидна
    below_top = math.ceil(box["top"] + box["height"])
    below = height - below_top
    if below >= MIN_BAND_H:
        bands.append({"left": 0, "top": below_top,
                      "width": width, "height": int(below)})
    return bands
