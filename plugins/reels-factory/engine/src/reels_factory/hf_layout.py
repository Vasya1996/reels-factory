"""Геометрия вертикального кадра 1080x1920.

Прямоугольники раскладок продублированы из справочных файлов скила
talking-head-recut (таблица composition layouts, колонка portrait). Скил
обновляется отдельно от нас, поэтому значения зафиксированы здесь.

Безопасных зон движок не знает вовсе — это наше знание.
"""
from __future__ import annotations

from reels_factory.config import FPS, OUT_H, OUT_W

#: Окно ведущей. Числа — их таблица раскладок, колонка portrait, строка
#: «9:16 source video» (references/layouts/{overlay,stack,split,pip}.html).
#: Прежнее значение `pip` было взято из строки «16:9 source» (360x203) — под
#: наши вертикальные клипы оно не годится: клип 1080x1920 в таком окне
#: обрезается до полоски глаз.
VIDEO_RECTS = {
    "full": {"left": 0, "top": 0, "width": 1080, "height": 1920},
    "overlay": {"left": 0, "top": 0, "width": 1080, "height": 1920},
    "stack": {"left": 0, "top": 0, "width": 1080, "height": 844},
    "split": {"left": 0, "top": 960, "width": 1080, "height": 960},
    "pip": {"left": 738, "top": 28, "width": 312, "height": 555},
    "pip-tr": {"left": 738, "top": 28, "width": 312, "height": 555},
    "pip-tl": {"left": 30, "top": 28, "width": 312, "height": 555},
    "pip-br": {"left": 738, "top": 1337, "width": 312, "height": 555},
    "pip-bl": {"left": 30, "top": 1337, "width": 312, "height": 555},
    # Наезд на ведущую: то же окно, увеличенное на 16% и сдвинутое так, чтобы
    # голова осталась в верхней трети. Кадр закрывает целиком — окно больше
    # кадра, лишнее срезает `overflow:hidden` обёртки. В эталонных рилсах такой
    # «поп»-наезд стоит в каждой паузе между сценами; у нас пауза шла одним
    # неподвижным планом, и детектор сцен не видел там ни одной смены.
    "punch": {"left": -87, "top": -170, "width": 1254, "height": 2229},
}

#: Куда садится карточка при каждой из пяти зон скила. Числа — его же таблица
#: (talking-head-recut/SKILL.md:181-187), доли пересчитаны на 1080x1920.
ZONE_RECTS = {
    "fullscreen": {"left": 0, "top": 0, "width": 1080, "height": 1920},
    "video-overlay": {"left": 0, "top": 0, "width": 1080, "height": 1920},
    "whiteboard-area": {"left": 40, "top": 528, "width": 1000, "height": 864},
    "lower-third": {"left": 0, "top": 1344, "width": 1080, "height": 576},
    "side-panel": {"left": 0, "top": 1152, "width": 1080, "height": 768},
}

# Все пять зон скила (talking-head-recut/SKILL.md:180-188) разрешены: своих
# ограничений поверх его геометрии мы не вводим — они однажды уже зажали
# карточку в центр кадра. Пиксели зоны выводит сам скил, поэтому дублировать
# его таблицу у себя незачем.
ALLOWED_ZONES = {"video-overlay", "fullscreen", "lower-third",
                 "side-panel", "whiteboard-area"}

# Зоны, закрывающие кадр целиком непрозрачной подложкой: ими и закрывается
# интервал, где аватара нет. `video-overlay` тоже во весь кадр, но по контракту
# прозрачен (SKILL.md:625-648), поэтому чёрный кадр под собой не прячет.
FULL_FRAME_ZONES = {"fullscreen"}

# зоны, где ведущей в кадре нет: проверять их на лицо бессмысленно
FACELESS_ZONES = FULL_FRAME_ZONES

# запас вокруг центра лица: 0.6 высоты головы в каждую сторону
FACE_MARGIN = 0.6


def quantize(seconds: float) -> float:
    """Округлить время к сетке кадров: движок иначе добавляет до 1/30 секунды."""
    return round(round(float(seconds) * FPS) / FPS, 3)


def avatar_gaps(clips: list[dict], duration: float) -> list[tuple[float, float]]:
    """Интервалы, где клипа с ведущей нет — под ними чёрный кадр.

    Ведущую заказывают кусками, там где она нужна по смыслу. Считаем от клипов,
    а не от плана монтажа: клипы это факт, план — чужое мнение. Задание агенту и
    гейт закрытия интервалов берут пропуски отсюда, иначе гейт проверял бы не
    то, о чём просили.
    """
    covered = sorted((float(c["start"]), float(c["start"]) + float(c["duration"]))
                     for c in clips or [])
    gaps, cursor = [], 0.0
    for start, end in covered:
        if start - cursor > 1.0 / FPS:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor > 1.0 / FPS:
        gaps.append((cursor, duration))
    return gaps


def face_box(face: dict | None) -> dict | None:
    if not face:
        return None
    cx, cy, h = float(face["cx"]), float(face["cy"]), float(face["h"])
    margin = h * FACE_MARGIN
    return {"left": cx - margin, "top": cy - margin,
            "width": 2 * margin, "height": 2 * margin}


def moved_face(face: dict | None, video_rect: dict | None) -> dict | None:
    """Лицо в координатах кадра, когда раскладка подвинула окно с видео.

    Видео вписывается в своё окно с сохранением пропорций (object-fit: cover),
    поэтому центр лица и высота головы масштабируются одним коэффициентом.
    """
    if not face or not video_rect:
        return face
    rw, rh = float(video_rect["width"]), float(video_rect["height"])
    # object-fit: cover — вписываем по БОЛЬШЕЙ стороне и обрезаем по краям,
    # поэтому кадр смещён центрирующим отступом, иногда отрицательным
    scale = max(rw / OUT_W, rh / OUT_H)
    offset_x = float(video_rect["left"]) + (rw - OUT_W * scale) / 2
    offset_y = float(video_rect["top"]) + (rh - OUT_H * scale) / 2
    return {"cx": offset_x + float(face["cx"]) * scale,
            "cy": offset_y + float(face["cy"]) * scale,
            "h": float(face["h"]) * scale}


def _intersects(a: dict, b: dict) -> bool:
    return not (
        a["left"] + a["width"] <= b["left"]
        or b["left"] + b["width"] <= a["left"]
        or a["top"] + a["height"] <= b["top"]
        or b["top"] + b["height"] <= a["top"]
    )


def violations(content_rect: dict, face: dict | None) -> list[str]:
    """Нарушения прямоугольника ВИДИМОГО СОДЕРЖИМОГО. Пусто — всё чисто.

    Правило одно: не перекрывать лицо. Всё остальное — дело скила.
    """
    box = face_box(face)
    if box is not None and _intersects(content_rect, box):
        return ["перекрывает лицо ведущей"]
    return []
